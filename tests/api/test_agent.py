"""ハートビートとコマンド処理（HeartbeatAgent）に関するテスト。

threading.Eventベースの同期を使い、time.sleepのポーリングには頼らない。
POST /heartbeatの応答がコマンドの唯一の配送路であり、応答受信からack
までの間にプロセスが落ちると二度と届かないという制約の下で、ローカルの
状態変更を先に適用してから同じtick内でackすることが正しいことを確認する。
"""
import threading

from tracking_parking.api.agent import RESTART_UNSUPPORTED_MESSAGE, HeartbeatAgent
from tracking_parking.api.client import SendResult
from tracking_parking.api.failures import Disposition


def heartbeat_ok(commands=None):
    return SendResult(disposition=Disposition.OK, status_code=200, body={"commands": commands or []})


class FakeHeartbeatClient:
    """post_heartbeatを呼ぶたびに、あらかじめ渡した結果を順に返す。"""

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0
        self.ack_calls = []
        self._ack_result = SendResult(disposition=Disposition.OK, status_code=200)
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

    def post_heartbeat(self, status="ok"):
        with self._lock:
            self.calls += 1
            self._cond.notify_all()
        if self._results:
            return self._results.pop(0)
        return heartbeat_ok()

    def ack_command(self, command_id, *, status, result_message):
        self.ack_calls.append((command_id, status, result_message))
        return self._ack_result

    def wait_for_calls(self, n, timeout=2.0):
        with self._lock:
            return self._cond.wait_for(lambda: self.calls >= n, timeout=timeout)


def make_agent(client, *, interval_sec=0.01, on_start_counting=None, on_stop_counting=None):
    return HeartbeatAgent(
        client,
        interval_sec,
        on_start_counting=on_start_counting or (lambda: None),
        on_stop_counting=on_stop_counting or (lambda: None),
        log=lambda *_: None,
    )


def test_start_countingコマンドでコールバックが呼ばれcompletedでackする():
    called = []
    client = FakeHeartbeatClient([heartbeat_ok([{"id": 1, "command_type": "start_counting"}])])
    agent = make_agent(client, on_start_counting=lambda: called.append(True))
    agent.tick()
    assert called == [True]
    assert client.ack_calls == [(1, "completed", None)]


def test_stop_countingコマンドでコールバックが呼ばれcompletedでackする():
    called = []
    client = FakeHeartbeatClient([heartbeat_ok([{"id": 2, "command_type": "stop_counting"}])])
    agent = make_agent(client, on_stop_counting=lambda: called.append(True))
    agent.tick()
    assert called == [True]
    assert client.ack_calls == [(2, "completed", None)]


def test_restartはfailedでackしresult_messageが空でない():
    client = FakeHeartbeatClient([heartbeat_ok([{"id": 3, "command_type": "restart"}])])
    agent = make_agent(client)
    agent.tick()
    assert client.ack_calls == [(3, "failed", RESTART_UNSUPPORTED_MESSAGE)]
    assert RESTART_UNSUPPORTED_MESSAGE  # 空文字列ではない


def test_未知のcommand_typeはfailedでackする():
    client = FakeHeartbeatClient([heartbeat_ok([{"id": 4, "command_type": "reboot_into_bios"}])])
    agent = make_agent(client)
    agent.tick()
    command_id, status, message = client.ack_calls[0]
    assert command_id == 4
    assert status == "failed"
    assert "reboot_into_bios" in message


def test_複数コマンドを順に処理する():
    client = FakeHeartbeatClient([
        heartbeat_ok([
            {"id": 1, "command_type": "start_counting"},
            {"id": 2, "command_type": "restart"},
        ])
    ])
    started = []
    agent = make_agent(client, on_start_counting=lambda: started.append(True))
    agent.tick()
    assert started == [True]
    assert [c[0] for c in client.ack_calls] == [1, 2]


def test_ハートビート自体が失敗したらコマンド処理をせずログだけ出す():
    client = FakeHeartbeatClient([SendResult(disposition=Disposition.UNKNOWN, error="timeout")])
    agent = make_agent(client)
    agent.tick()
    assert client.ack_calls == []


def test_ackが失敗してもローカルの状態変更は巻き戻さない():
    called = []
    client = FakeHeartbeatClient([heartbeat_ok([{"id": 5, "command_type": "stop_counting"}])])
    client._ack_result = SendResult(disposition=Disposition.UNKNOWN, error="ack timeout")
    agent = make_agent(client, on_stop_counting=lambda: called.append(True))
    agent.tick()
    # ackが失敗していても、on_stop_countingは既に呼ばれている（巻き戻さない）
    assert called == [True]


def test_コールバックが例外を投げてもワーカースレッドは死なない():
    """_run()のtry/exceptがtick()全体を包むため、次のtickも実行され続ける。"""

    def raising_start():
        raise RuntimeError("boom")

    client = FakeHeartbeatClient([
        heartbeat_ok([{"id": 1, "command_type": "start_counting"}]),
        heartbeat_ok(),
        heartbeat_ok(),
    ])
    agent = make_agent(client, interval_sec=0.01, on_start_counting=raising_start)
    agent.start()
    try:
        assert client.wait_for_calls(3, timeout=2.0), "例外の後、ワーカーが止まってしまった"
    finally:
        agent.stop(timeout_sec=1.0)


def test_stopはinterval_secの途中でも即座に抜ける():
    client = FakeHeartbeatClient([heartbeat_ok()])
    agent = make_agent(client, interval_sec=5.0)  # 十分長い間隔
    agent.start()
    assert client.wait_for_calls(1, timeout=2.0)

    import time

    started_at = time.monotonic()
    agent.stop(timeout_sec=2.0)
    elapsed = time.monotonic() - started_at
    assert elapsed < 1.0, f"stop()がinterval_secの終了を待ってしまった: {elapsed}秒"


def test_起動直後に1回目のtickが即座に走る():
    """30秒後ではなく即座にオンライン表示させるため。"""
    client = FakeHeartbeatClient([heartbeat_ok()])
    agent = make_agent(client, interval_sec=30.0)
    agent.start()
    try:
        assert client.wait_for_calls(1, timeout=1.0)
    finally:
        agent.stop(timeout_sec=1.0)
