"""送信キューとワーカースレッド（EventSender）に関するテスト。

「応答を受け取ってから要素を消す」という不変条件と、ワーカースレッドが
どんな例外でも死なないことが中核。threading.Eventで同期を取り、
time.sleepのポーリングには頼らない（CIの不安定要因になるため）。
"""
import threading

from tracking_parking.api.client import EventPayload, SendResult
from tracking_parking.api.failures import Disposition
from tracking_parking.api.sender import EventSender
from tracking_parking.api.spool import load


def make_payload(request_id="r1"):
    return EventPayload(
        request_id=request_id, event_type="entry", detected_at="2026-09-15T10:00:00+09:00", vehicle_track_id="7"
    )


def no_sleep(_seconds):
    """バックオフ待ちを飛ばして再送テストを高速にする。"""


class CountingClient:
    """毎回同じ結果を返すだけの単純なフェイク。呼ばれた回数を記録する。"""

    def __init__(self, disposition, *, status_code=None, error=None):
        self.disposition = disposition
        self.status_code = status_code
        self.error = error
        self.calls = 0

    def post_event(self, event):
        self.calls += 1
        return SendResult(disposition=self.disposition, status_code=self.status_code, error=self.error)


class BlockingClient:
    """post_eventが呼ばれたことをstartedで知らせ、gateがセットされるまで待つ。"""

    def __init__(self, result: SendResult):
        self.started = threading.Event()
        self.gate = threading.Event()
        self.result = result
        self.calls = 0

    def post_event(self, event):
        self.calls += 1
        self.started.set()
        self.gate.wait(timeout=5.0)
        return self.result


class RaisingClient:
    """ApiClient自体のバグを模してRuntimeErrorを直接投げる。"""

    def __init__(self):
        self.calls = 0

    def post_event(self, event):
        self.calls += 1
        raise RuntimeError("client blew up")


def test_応答を受け取るまでキューから消えない(tmp_path):
    client = BlockingClient(SendResult(disposition=Disposition.OK, status_code=201))
    spool_path = tmp_path / "spool.jsonl"
    sender = EventSender(client, spool_path, sleep=no_sleep, log=lambda *_: None)
    sender.start()
    assert sender.enqueue(make_payload("r1"))
    assert client.started.wait(timeout=2.0), "workerがpost_eventへ到達しなかった"

    # まだ応答は返っていない。この時点でshutdownすると「決着していない」
    # ものとしてスプールへ退避されるはず。
    stats = sender.shutdown(flush_timeout_sec=0.1)
    contents = load(spool_path)
    assert [r.request_id for r in contents.records] == ["r1"]
    assert stats["spooled"] == 1

    client.gate.set()  # 後片付け：ブロックしていたワーカーを解放する


def test_成功したらスプールに残らない(tmp_path):
    client = CountingClient(Disposition.OK, status_code=201)
    spool_path = tmp_path / "spool.jsonl"
    sender = EventSender(client, spool_path, sleep=no_sleep, log=lambda *_: None)
    sender.start()
    sender.enqueue(make_payload())
    stats = sender.shutdown(flush_timeout_sec=2.0)
    assert stats["sent"] == 1
    assert stats["spooled"] == 0
    assert not spool_path.exists()


def test_失敗が続くとバックオフを経てスプールへ落ちる(tmp_path):
    client = CountingClient(Disposition.UNKNOWN, error="timeout")
    spool_path = tmp_path / "spool.jsonl"
    sender = EventSender(client, spool_path, sleep=no_sleep, log=lambda *_: None)
    sender.start()
    sender.enqueue(make_payload("r-retry"))
    stats = sender.shutdown(flush_timeout_sec=2.0)
    assert client.calls == 4  # 初回 + 最大3回の再送
    assert stats["spooled"] == 1
    contents = load(spool_path)
    assert [r.request_id for r in contents.records] == ["r-retry"]


def test_DROP分類は再送せずスプールに残らない(tmp_path):
    client = CountingClient(Disposition.DROP, status_code=401, error="invalid api key")
    spool_path = tmp_path / "spool.jsonl"
    sender = EventSender(client, spool_path, sleep=no_sleep, log=lambda *_: None)
    sender.start()
    sender.enqueue(make_payload())
    stats = sender.shutdown(flush_timeout_sec=2.0)
    assert client.calls == 1  # 再送しない
    assert stats["dropped"] == 1
    assert stats["spooled"] == 0
    assert not spool_path.exists()


def test_flush上限で打ち切りキューと_inflightの両方がスプールへ出る(tmp_path):
    client = BlockingClient(SendResult(disposition=Disposition.OK, status_code=201))
    spool_path = tmp_path / "spool.jsonl"
    sender = EventSender(client, spool_path, sleep=no_sleep, log=lambda *_: None)
    sender.start()
    sender.enqueue(make_payload("inflight-one"))
    assert client.started.wait(timeout=2.0)
    sender.enqueue(make_payload("still-queued"))  # workerは1件目で塞がっているので処理されない

    stats = sender.shutdown(flush_timeout_sec=0.1)
    contents = load(spool_path)
    ids = {r.request_id for r in contents.records}
    assert ids == {"inflight-one", "still-queued"}
    assert stats["spooled"] == 2

    client.gate.set()


def test_フェイクがRuntimeErrorを投げてもワーカーが死なない(tmp_path):
    client = RaisingClient()
    spool_path = tmp_path / "spool.jsonl"
    sender = EventSender(client, spool_path, sleep=no_sleep, log=lambda *_: None)
    sender.start()
    sender.enqueue(make_payload("boom-1"))
    sender.enqueue(make_payload("boom-2"))
    stats = sender.shutdown(flush_timeout_sec=2.0)
    assert client.calls == 2  # 2件目も処理を試みている＝ワーカーは生きていた
    assert stats["spooled"] == 2
    contents = load(spool_path)
    assert {r.request_id for r in contents.records} == {"boom-1", "boom-2"}


def test_停止中のenqueueは捨てて溜めない(tmp_path):
    client = CountingClient(Disposition.OK, status_code=201)
    spool_path = tmp_path / "spool.jsonl"
    sender = EventSender(client, spool_path, sleep=no_sleep, log=lambda *_: None)
    sender.set_sending_enabled(False)
    assert sender.enqueue(make_payload()) is False
    sender.start()
    stats = sender.shutdown(flush_timeout_sec=0.5)
    assert stats["sent"] == 0
    assert client.calls == 0


def test_キュー満杯でenqueueがブロックせずFalseを返す(tmp_path):
    client = BlockingClient(SendResult(disposition=Disposition.OK, status_code=201))
    spool_path = tmp_path / "spool.jsonl"
    sender = EventSender(client, spool_path, max_queue=1, sleep=no_sleep, log=lambda *_: None)
    sender.start()
    assert sender.enqueue(make_payload("first"))
    assert client.started.wait(timeout=2.0)  # 1件目はワーカーが取り出し済み（_inflight）
    assert sender.enqueue(make_payload("second"))  # キューの空き1つ分
    assert sender.enqueue(make_payload("third")) is False  # キューが満杯
    assert sender.stats["queue_full"] == 1

    client.gate.set()
    sender.shutdown(flush_timeout_sec=2.0)


def test_replay_spoolは既存のスプールを送り直す(tmp_path):
    from tracking_parking.api.spool import append_record, new_record

    spool_path = tmp_path / "spool.jsonl"
    append_record(
        spool_path,
        new_record(
            spooled_at="2026-09-15T09:00:00+09:00",
            request_id="replay-me",
            event_type="exit",
            detected_at="2026-09-15T08:59:00+09:00",
            vehicle_track_id="3",
            disposition="unknown",
            error="previous failure",
            execution_id="exec-old",
        ),
    )

    client = CountingClient(Disposition.OK, status_code=201)
    sender = EventSender(client, spool_path, sleep=no_sleep, log=lambda *_: None)
    replayed = sender.replay_spool()

    assert replayed == 1
    assert client.calls == 1
    assert not spool_path.exists()  # 成功したので消える


def test_replay_spoolで送るrequest_idはスプールのものと同じ(tmp_path):
    """べき等の前提そのもの。再送は同じrequest_idで行われる。"""
    from tracking_parking.api.spool import append_record, new_record

    spool_path = tmp_path / "spool.jsonl"
    append_record(
        spool_path,
        new_record(
            spooled_at="x", request_id="same-id", event_type="entry",
            detected_at="y", vehicle_track_id=None,
            disposition="unknown", error=None, execution_id=None,
        ),
    )

    seen = {}

    class RecordingClient:
        def post_event(self, event):
            seen["request_id"] = event.request_id
            return SendResult(disposition=Disposition.OK, status_code=201)

    sender = EventSender(RecordingClient(), spool_path, sleep=no_sleep, log=lambda *_: None)
    sender.replay_spool()
    assert seen["request_id"] == "same-id"


def test_replayで失敗し続けるレコードはattemptsが更新されて残る(tmp_path):
    """replay対象が今回も送信できなかった場合、with_retry_result()で
    attempts/last_disposition/last_errorを更新した上でスプールに残ることを
    確認する。merge方式の書き戻し（現在のファイルを読み直して更新する）でも
    この更新が失われないことの固定。"""
    from tracking_parking.api.spool import append_record, load, new_record

    spool_path = tmp_path / "spool.jsonl"
    append_record(
        spool_path,
        new_record(
            spooled_at="2026-09-15T09:00:00+09:00", request_id="still-failing",
            event_type="entry", detected_at="2026-09-15T08:59:00+09:00",
            vehicle_track_id=None, disposition="unknown", error="first failure", execution_id=None,
        ),
    )

    client = CountingClient(Disposition.UNKNOWN, error="second failure")
    sender = EventSender(client, spool_path, sleep=no_sleep, log=lambda *_: None)
    sender.replay_spool()

    contents = load(spool_path)
    assert len(contents.records) == 1
    record = contents.records[0]
    assert record.request_id == "still-failing"
    assert record.attempts == 2  # 1（初期スプール時）+ 1（今回のreplay）
    assert record.last_disposition == "unknown"
    assert record.last_error == "second failure"


def test_replay中に追記されたレコードはrewriteで消えない(tmp_path):
    """レビュー指摘1の回帰テスト。replay_spool()の書き戻しがロード時の
    スナップショットに基づいていると、replay実行中に（shutdown()などが）
    追記したレコードを、replay完了時のrewrite()が上書きして消してしまう。
    postEventの呼び出し中（=replayがまだ実行中）に別のレコードを追記して
    この状況を再現し、追記分が生き残ることを確認する。"""
    from tracking_parking.api.spool import append_record, load, new_record

    spool_path = tmp_path / "spool.jsonl"
    append_record(
        spool_path,
        new_record(
            spooled_at="2026-09-15T09:00:00+09:00", request_id="replay-target",
            event_type="entry", detected_at="2026-09-15T08:59:00+09:00",
            vehicle_track_id="1", disposition="unknown", error="prev", execution_id=None,
        ),
    )

    class AppendingClient:
        """post_eventの最中に、shutdown()が別のイベントを退避する状況を模す。"""

        def post_event(self, event):
            append_record(
                spool_path,
                new_record(
                    spooled_at="2026-09-15T09:05:00+09:00", request_id="shutdown-added",
                    event_type="exit", detected_at="2026-09-15T09:04:00+09:00",
                    vehicle_track_id="2", disposition="unknown", error="shutdown中の退避", execution_id=None,
                ),
            )
            return SendResult(disposition=Disposition.OK, status_code=201)

    sender = EventSender(AppendingClient(), spool_path, sleep=no_sleep, log=lambda *_: None)
    sender.replay_spool()

    contents = load(spool_path)
    ids = {r.request_id for r in contents.records}
    assert ids == {"shutdown-added"}  # replay対象は成功して消え、追記分だけが残る


def test_replay中に積まれた新規イベントを次のreplay対象より先に処理する(tmp_path):
    """レビュー指摘4の回帰テスト。スプールに複数件残っている状況でreplayが
    長引くと、検知ループが新規にenqueueしたイベントがキュー満杯（かつ
    スプールにも書かれず）で破棄される。1件replayするたびにキューを
    優先的に処理することで、新規イベントを待たせないことを確認する。"""
    from tracking_parking.api.spool import append_record, new_record

    spool_path = tmp_path / "spool.jsonl"
    for i in range(2):
        append_record(
            spool_path,
            new_record(
                spooled_at="x", request_id=f"spool-{i}", event_type="entry",
                detected_at="y", vehicle_track_id=None,
                disposition="unknown", error=None, execution_id=None,
            ),
        )

    order: list[str] = []
    sender_holder: dict = {}

    class OrderRecordingClient:
        def post_event(self, event):
            order.append(event.request_id)
            if event.request_id == "spool-0":
                # spool-0の送信中に、検知ループが新規イベントをenqueueしたとみなす。
                sender_holder["sender"].enqueue(make_payload("live-event"))
            return SendResult(disposition=Disposition.OK, status_code=201)

    sender = EventSender(OrderRecordingClient(), spool_path, sleep=no_sleep, log=lambda *_: None)
    sender_holder["sender"] = sender
    sender.replay_spool()

    assert order == ["spool-0", "live-event", "spool-1"]


def test_取り出しとinflight代入はshutdownのドレインと排他する(tmp_path, monkeypatch):
    """レビュー指摘2の回帰テスト。

    queue.get()と_inflightへの代入を別々の文で書くと、その間にshutdown()の
    ドレインが割り込み、イベントがキューにも_inflightにも属さない瞬間が
    できて取りこぼす。この窓は1バイトコード分程度しかなく、多数回試行する
    ストレステストでは（実際に試したところ）ほぼ再現しなかったため、
    タイミングに依存しない形で直接確認する。

    _try_process_one()のqueue.get_nowait()を差し替えて、_lockを保持した
    ままわざと止める。その間、shutdown()のドレインが使う同じ_lockを
    別スレッドから取ろうとしても取れない（＝取り出しと代入の間に
    割り込めない）ことを見る。
    """
    client = CountingClient(Disposition.OK, status_code=201)
    spool_path = tmp_path / "spool.jsonl"
    sender = EventSender(client, spool_path, sleep=no_sleep, log=lambda *_: None)
    sender.enqueue(make_payload("r1"))

    entered_critical_section = threading.Event()
    release_critical_section = threading.Event()
    original_get_nowait = sender._queue.get_nowait

    def slow_get_nowait():
        item = original_get_nowait()
        entered_critical_section.set()
        release_critical_section.wait(timeout=5.0)
        return item

    monkeypatch.setattr(sender._queue, "get_nowait", slow_get_nowait)

    worker = threading.Thread(target=sender._try_process_one)
    worker.start()
    assert entered_critical_section.wait(timeout=2.0), "get_nowait()に到達しなかった"

    # ここでワーカーは_lockを保持したまま（get_nowait()の中で）止まっている。
    # shutdown()のドレインが使う_lockを、別スレッドから同じように取ろうと
    # 試みる。取れてしまえば排他になっていない。
    lock_acquired = threading.Event()

    def try_acquire_same_lock():
        with sender._lock:
            pass
        lock_acquired.set()

    contender = threading.Thread(target=try_acquire_same_lock)
    contender.start()
    assert not lock_acquired.wait(timeout=0.3), (
        "ワーカーが取り出し中にもかかわらず、shutdown側が同じロックを取得できてしまった"
        "（取り出しと_inflight代入がshutdownのドレインと排他されていない）"
    )

    release_critical_section.set()
    worker.join(timeout=2.0)
    contender.join(timeout=2.0)
    assert lock_acquired.is_set(), "ロック解放後もshutdown側が取得できなかった"


def test_連続したenqueueとshutdownでイベントを取りこぼさない(tmp_path):
    """上のテストが単一のタイミングを直接確認するのに対し、こちらは
    実運用に近い形（start()した実スレッド相手にenqueueしてすぐshutdown）
    を繰り返し、毎回必ず送信済みかスプールのどちらかに記録されることを
    確認する。"""
    for i in range(50):
        client = CountingClient(Disposition.OK, status_code=201)
        spool_path = tmp_path / f"spool_{i}.jsonl"
        sender = EventSender(client, spool_path, sleep=no_sleep, log=lambda *_: None)
        sender.start()
        sender.enqueue(make_payload(f"r{i}"))
        stats = sender.shutdown(flush_timeout_sec=0.5)
        assert stats["sent"] + stats["spooled"] == 1, f"iteration {i}: イベントを取りこぼした"
