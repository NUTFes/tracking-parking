"""
送信キューとワーカースレッド

検出ループはenqueue()を呼ぶだけでブロックしない。実際の送信は別スレッドの
_run()が行う。「応答を受け取ってから要素を消す」という不変条件を守るため、
queue.get()で取り出した要素はワーカーローカルの_inflightスロットへ保持し、
決着（成功、または最終的な失敗としてスプールへ書く）してから手放す。
どの瞬間でもイベントは「キューの中」「_inflight」「決着済み」のいずれかに
あり、shutdown()は前者2つの両方をスプールへ書く。

この不変条件を守るため、「キューから取り出す」と「_inflightへ代入する」を
_lock保護の下で1つの操作として行う（_try_process_one()）。queue.get()と
代入を別々の文として書くと、その間にshutdown()のドレインが割り込み、
イベントがキューにも_inflightにも属さない瞬間が生まれる。shutdown()側の
ドレインも同じ_lockで保護し、両者が同時に「取り出し中」の状態を見ないように
している。

スプールファイルへのアクセス（追記・読み直し・書き戻し）も同じ_lockで
保護する。replay_spool()は起動直後にワーカースレッドで実行されるが、
その最中にメインスレッドがshutdown()を呼ぶと、shutdown()もスプールへ
追記する（_spool_new経由）。replay_spool()の書き戻しをロック無しで
行うと、その追記をロック前のスナップショットで上書きして消してしまう。

ExperimentLogger（common/wandb_logger.py）はフェイルファストで例外を
握りつぶさないが、この送信スレッドは意図的に逆の方針を取る。ネットワーク
断で検知プロセスが死ぬと現場のカウントそのものが止まり、ローカルの
JSONログも途切れる。送信の失敗はスプールとログから後で回収できるが、
止まったカウントは回収できない。
"""

import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from tracking_parking.api import spool as spool_module
from tracking_parking.api.client import EventPayload, SendResult
from tracking_parking.api.failures import Disposition, is_retryable

logger = logging.getLogger(__name__)

# 1イベントにつき初回送信＋最大3回まで再送する（指数バックオフ 1秒→2秒→4秒）。
# ワーカーを長く占有しないための上限であって、送信を諦める線ではない。
# それでも決着しなければスプールへ落とし、次のイベントへ進む。長時間の
# 回線断はスプールと起動時のreplay_spool()で回収する。
RETRY_BACKOFF_SEC: tuple[float, ...] = (1.0, 2.0, 4.0)

# キューが空のときのポーリング間隔。queue.get(timeout=...)による効率的な
# 待ちではなく短いポーリングにしているのは、取り出しと_inflightへの代入を
# 同じロックの下で行う必要があり、ロックを保持したままブロッキングする
# get()は使えないため。
POLL_INTERVAL_SEC = 0.1


class EventApiClient(Protocol):
    """EventSenderが必要とするクライアントの最小インターフェース。"""

    def post_event(self, event: EventPayload) -> SendResult: ...


def _default_now() -> str:
    return datetime.now().astimezone().isoformat()


class EventSender:
    """送信キューとワーカースレッド。"""

    def __init__(
        self,
        client: EventApiClient,
        spool_path: Path,
        *,
        execution_id: str | None = None,
        max_queue: int = 10_000,
        log: Callable[[str], None] = print,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], str] = _default_now,
    ):
        self._client = client
        self._spool_path = Path(spool_path)
        self._execution_id = execution_id
        self._queue: "queue.Queue[EventPayload]" = queue.Queue(maxsize=max_queue)
        self._inflight: EventPayload | None = None
        self._sending_enabled = True
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._log = log
        self._sleep = sleep
        self._now = now
        self._lock = threading.Lock()
        self._stats = {"sent": 0, "dropped": 0, "spooled": 0, "queue_full": 0, "replayed": 0}

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="api-event-sender", daemon=True)
        self._thread.start()

    def set_sending_enabled(self, enabled: bool) -> None:
        self._sending_enabled = enabled

    def is_sending_enabled(self) -> bool:
        return self._sending_enabled

    @property
    def stats(self) -> dict:
        with self._lock:
            return dict(self._stats)

    def enqueue(self, payload: EventPayload) -> bool:
        """検出ループから呼ばれる。非ブロッキング。

        停止中（set_sending_enabled(False)）は捨てて溜めない。既にキューに
        入っているイベントは、有効だった時刻に検出された正当なものなので
        停止コマンドが届いても捨てない（このガードは新規のenqueueだけを止める）。
        """
        if not self._sending_enabled:
            return False
        try:
            self._queue.put_nowait(payload)
            return True
        except queue.Full:
            with self._lock:
                self._stats["queue_full"] += 1
            self._log("[api] 送信キューが満杯のためイベントを1件破棄しました")
            return False

    def replay_spool(self) -> int:
        """起動時にワーカーの最初の仕事として呼ぶ。スプールに残った全レコードを送り直す。

        request_idがあるので、届いていたかどうかを気にせず全件送り直せる
        （届いていればサーバーが2xxで既存イベントを返し、system_countは
        動かさない）。メインスレッドでやると、長時間の回線断の後に検出
        ループの起動が止まるため、必ずワーカースレッド上で行う。

        1件送るたびに、その時点でキューに積まれている新規イベント（検出
        ループが今まさに検知したもの）を優先して処理する。スプールが
        大量に残っている状況でこれをしないと、replay完了までワーカーが
        占有され、新規イベントがキュー満杯で（スプールにも書かれずに）
        破棄されてしまう。shutdown()が呼ばれた場合も、残りのレコードは
        送らずに打ち切る（次回起動時のreplayに委ねる）。

        書き戻しはロード時のスナップショットに基づかず、送信直後に
        ファイルを読み直してから、今回解決できた分（成功・DROP）だけを
        request_id基準で取り除く。スナップショットのまま書き戻すと、
        replay実行中にshutdown()が追記したレコード（今回runのイベント）を
        消してしまうため。
        """
        contents = spool_module.load(self._spool_path)
        if not contents.records and not contents.passthrough_lines:
            return 0

        replayed = 0
        resolved_ids: set[str] = set()
        dropped_ids: set[str] = set()
        updated: dict[str, spool_module.SpoolRecord] = {}

        for record in contents.records:
            if self._stop_event.is_set():
                break

            # 新規イベントを塞がないよう、次のreplayへ進む前にキューを吐き出す。
            while self._try_process_one():
                pass

            payload = EventPayload(
                request_id=record.request_id,
                event_type=record.event_type,
                detected_at=record.detected_at,
                vehicle_track_id=record.vehicle_track_id,
            )
            result = self._send_with_retry(payload)
            replayed += 1
            if result.disposition == Disposition.OK:
                resolved_ids.add(record.request_id)
            elif result.disposition == Disposition.DROP:
                self._log(f"[api] スプール中のイベントを破棄しました（設定の誤り）: {result.error}")
                dropped_ids.add(record.request_id)
            else:
                updated[record.request_id] = record.with_retry_result(
                    disposition=str(result.disposition), error=result.error
                )

        with self._lock:
            current = spool_module.load(self._spool_path)
            remaining_records = [
                updated.get(r.request_id, r)
                for r in current.records
                if r.request_id not in resolved_ids and r.request_id not in dropped_ids
            ]
            spool_module.rewrite(
                self._spool_path, records=remaining_records, passthrough_lines=current.passthrough_lines
            )
            self._stats["replayed"] += replayed
        return replayed

    def _run(self) -> None:
        try:
            self.replay_spool()
        except Exception:
            logger.exception("[api] 起動時のスプール再送で例外が発生しました")

        while not self._stop_event.is_set():
            if not self._try_process_one():
                self._sleep(POLL_INTERVAL_SEC)

    def _try_process_one(self) -> bool:
        """キューから1件取り出して処理する。空なら何もせずFalseを返す。

        取り出し（queue.get_nowait）と_inflightへの代入を同じ_lockの下で
        一体の操作として行う。別々の文にすると、その間にshutdown()の
        ドレインが割り込んだとき、イベントがキューにも_inflightにも
        属さない瞬間ができ、取りこぼす。
        """
        with self._lock:
            try:
                payload = self._queue.get_nowait()
                self._inflight = payload
            except queue.Empty:
                return False

        try:
            self._process(payload)
        except Exception:
            # ワーカースレッドは絶対に死なせない。未知の例外はスプールへ退避して次へ進む。
            logger.exception("[api] 送信ワーカーで未知の例外が発生しました。イベントをスプールへ退避します")
            self._spool_new(payload, disposition=Disposition.UNKNOWN, error="worker crashed")
        finally:
            with self._lock:
                self._inflight = None
        return True

    def _process(self, payload: EventPayload) -> None:
        result = self._send_with_retry(payload)
        if result.disposition == Disposition.OK:
            with self._lock:
                self._stats["sent"] += 1
            return
        if result.disposition == Disposition.DROP:
            with self._lock:
                self._stats["dropped"] += 1
            self._log(f"[api] イベントを破棄しました（設定の誤り）: {result.error}")
            return
        self._spool_new(payload, disposition=result.disposition, error=result.error)

    def _send_with_retry(self, payload: EventPayload) -> SendResult:
        """再送可否の判定はis_retryable()に委ねる（ここで独自に条件を書かない）。

        将来request_idを送るのをやめる変更が入ったとき、is_retryable()の
        docstringが警告している通りUNKNOWNをFalseへ戻す必要がある。判定を
        ここへ重複させていると、is_retryable()だけ直しても実際の再送挙動が
        変わらず、警告が意味を持たなくなる。
        """
        result = self._client.post_event(payload)
        if not is_retryable(result.disposition):
            return result
        for backoff in RETRY_BACKOFF_SEC:
            self._sleep(backoff)
            result = self._client.post_event(payload)
            if not is_retryable(result.disposition):
                return result
        return result

    def _spool_new(self, payload: EventPayload, *, disposition: Disposition, error: str | None) -> None:
        record = spool_module.new_record(
            spooled_at=self._now(),
            request_id=payload.request_id,
            event_type=payload.event_type,
            detected_at=payload.detected_at,
            vehicle_track_id=payload.vehicle_track_id,
            disposition=str(disposition),
            error=error,
            execution_id=self._execution_id,
        )
        with self._lock:
            spool_module.append_record(self._spool_path, record)
            self._stats["spooled"] += 1

    def shutdown(self, flush_timeout_sec: float) -> dict:
        """キューが空になり_inflightが無くなるのを上限つきで待ち、残りをスプールへ書く。

        待ち上限を超えて残ったもの（キューの残り＋_inflight）は「結果不明」
        としてスプールへ退避する。request_idがあるので、実際には送信済み
        だったとしても次回起動時の再送で二重計上にはならない
        （サーバーが2xxで既存イベントを返すだけ）。

        キューのドレインと_inflightの読み取りは、ワーカー側の取り出しと
        同じ_lockの下で行う。ロック無しで行うと、ワーカーが「キューから
        取り出した直後・_inflightへ代入する前」の瞬間を踏んだとき、
        キューは空・_inflightもNoneに見えてしまい、そのイベントを
        取りこぼす（_try_process_one()のdocstring参照）。
        """
        deadline = time.monotonic() + max(flush_timeout_sec, 0.0)
        while time.monotonic() < deadline:
            with self._lock:
                idle = self._queue.empty() and self._inflight is None
            if idle:
                break
            self._sleep(0.02)

        with self._lock:
            remaining: list[EventPayload] = []
            while True:
                try:
                    remaining.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            if self._inflight is not None:
                remaining.append(self._inflight)

        for payload in remaining:
            self._spool_new(payload, disposition=Disposition.UNKNOWN, error="shutdown: flush期限までに決着しなかった")

        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

        return self.stats
