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
