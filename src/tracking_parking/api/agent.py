"""
ハートビートとコマンド処理

POST /heartbeatの応答がコマンドの唯一の配送路（呼んだ時点でpending→
deliveredへ移り、この応答にしか載らない。list_pending_for_deviceは
pending状態のコマンドしか拾わないため、一度deliveredになったコマンドは
二度と別のheartbeatへ再配送されない）。応答受信からackまでの間に
プロセスが落ちるとそのコマンドは永久に届かないため、ローカルの状態
変更を先に適用してから同じtick内でackを投げる。ackが失敗してもローカル
の変更は巻き戻さない。サーバーとの食い違いが生まれるが、それはログへ
出して人が気づくものとして扱う（この一度きりの配送という制約の下では、
コマンドの実行そのものを取り消す判断の方が危険なため）。

restartは未対応。プロセスを起動・監視する仕組みがこのリポジトリに
無いため、実行したふりをせずfailedで理由を返す。stop_counting中に
プロセスを再起動すると、停止状態がプロセスをまたいで保持されない
（起動直後は必ず送信する状態から始まる）ため「止めたはずが再起動で
勝手に再開する」という矛盾を抱えることになる、という理由もある。
"""

import logging
import threading
from typing import Callable, Protocol

from tracking_parking.api.client import SendResult
from tracking_parking.api.failures import Disposition

logger = logging.getLogger(__name__)

RESTART_UNSUPPORTED_MESSAGE = (
    "プロセスの再起動に未対応です。プロセス管理の仕組みがエッジ側リポジトリに"
    "ないため、手動で再起動してください。"
)


class HeartbeatApiClient(Protocol):
    def post_heartbeat(self, status: str = "ok") -> SendResult: ...
    def ack_command(self, command_id: int, *, status: str, result_message: str | None) -> SendResult: ...


class HeartbeatAgent:
    """ハートビート送信と、応答に載って届くコマンドの処理を行う。"""

    def __init__(
        self,
        client: HeartbeatApiClient,
        interval_sec: float,
        *,
        on_start_counting: Callable[[], None],
        on_stop_counting: Callable[[], None],
        log: Callable[[str], None] = print,
    ):
        self._client = client
        self._interval_sec = interval_sec
        self._on_start_counting = on_start_counting
        self._on_stop_counting = on_stop_counting
        self._log = log
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="api-heartbeat", daemon=True)
        self._thread.start()

    def stop(self, timeout_sec: float = 5.0) -> None:
        """interval_secの途中で呼んでも即座に抜ける（Event.waitがすぐ解ける）。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_sec)

    def _run(self) -> None:
        # 起動直後に1回tick()してから待ちに入る。次のinterval_secを待たず
        # 即座にオンライン表示させるため。
        while True:
            try:
                self.tick()
            except Exception:
                # ワーカースレッドは絶対に死なせない。
                logger.exception("[api] ハートビートで未知の例外が発生しました")
            if self._stop_event.wait(self._interval_sec):
                return

    def tick(self) -> None:
        """1回分のハートビート送信とコマンド処理。テストから直接呼べるように公開する。"""
        result = self._client.post_heartbeat()
        if result.disposition != Disposition.OK:
            self._log(f"[api] ハートビート送信に失敗しました: {result.error}")
            return
        commands = (result.body or {}).get("commands") or []
        for command in commands:
            self._handle_command(command)

    def _handle_command(self, command: dict) -> None:
        command_id = command.get("id")
        command_type = command.get("command_type")

        # ローカルの状態変更を先に適用してから、同じtick内でackする
        # （ここで例外が起きてもワーカーは死なない。_run側のtry/exceptが拾う）。
        if command_type == "start_counting":
            self._on_start_counting()
            self._ack(command_id, status="completed", result_message=None)
        elif command_type == "stop_counting":
            self._on_stop_counting()
            self._ack(command_id, status="completed", result_message=None)
        elif command_type == "restart":
            self._ack(command_id, status="failed", result_message=RESTART_UNSUPPORTED_MESSAGE)
        else:
            self._ack(command_id, status="failed", result_message=f"未対応のcommand_type: {command_type}")

    def _ack(self, command_id: int, *, status: str, result_message: str | None) -> None:
        result = self._client.ack_command(command_id, status=status, result_message=result_message)
        if result.disposition != Disposition.OK:
            self._log(f"[api] コマンド{command_id}のack送信に失敗しました: {result.error}")
