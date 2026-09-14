"""APIクライアント（ApiClient）に関するテスト。

requestsの実体をモックせず、SimpleNamespaceでsessionを差し替える
（unittest.mockは使わず手書きフェイクを使う既存の流儀に合わせる。
tests/common/test_wandb_logger.pyのSimpleNamespaceフェイクが雛形）。
"""
from types import SimpleNamespace

from tracking_parking.api.client import ApiClient, EventPayload
from tracking_parking.api.failures import Disposition
from tracking_parking.api.settings import ApiSettings


def make_settings(**overrides) -> ApiSettings:
    base = dict(
        enabled=True,
        base_url="http://localhost:8000/api/v1",
        api_key="secret-key",
        connect_timeout_sec=3.0,
        read_timeout_sec=5.0,
        heartbeat_interval_sec=30,
        shutdown_flush_sec=10,
        spool_path="/tmp/unused.jsonl",
    )
    base.update(overrides)
    return ApiSettings(**base)


class FakeResponse:
    def __init__(self, status_code=201, json_body=None, text=""):
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {}
        self.text = text

    def json(self):
        return self._json_body


class FakeSession:
    """get/postの呼び出し引数を記録するだけの手書きフェイク。"""

    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.response

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.response


def test_X_API_Keyヘッダーが付く():
    session = FakeSession(FakeResponse())
    client = ApiClient(make_settings(), session=session)
    client.post_event(EventPayload(request_id="r1", event_type="entry", detected_at="2026-09-15T10:00:00+09:00", vehicle_track_id="7"))
    _, _, kwargs = session.calls[0]
    assert kwargs["headers"]["X-API-Key"] == "secret-key"


def test_timeoutがconnectとreadのタプルで渡る():
    session = FakeSession(FakeResponse())
    client = ApiClient(make_settings(connect_timeout_sec=2.5, read_timeout_sec=6.5), session=session)
    client.post_event(EventPayload(request_id="r1", event_type="entry", detected_at="x", vehicle_track_id=None))
    _, _, kwargs = session.calls[0]
    assert kwargs["timeout"] == (2.5, 6.5)


def test_URL結合はurljoinのapi_v1消失事故を起こさない():
    """urljoin("http://h/api/v1", "/events") は "/api/v1" を落として http://h/events になる。

    base_url.rstrip("/") + path の単純結合で組み立てることの回帰テスト。
    """
    session = FakeSession(FakeResponse())
    client = ApiClient(make_settings(base_url="http://localhost:8000/api/v1"), session=session)
    client.post_event(EventPayload(request_id="r1", event_type="entry", detected_at="x", vehicle_track_id=None))
    _, url, _ = session.calls[0]
    assert url == "http://localhost:8000/api/v1/events"


def test_末尾スラッシュ付きbase_urlでも二重スラッシュにならない():
    session = FakeSession(FakeResponse())
    client = ApiClient(make_settings(base_url="http://localhost:8000/api/v1/"), session=session)
    client.post_event(EventPayload(request_id="r1", event_type="entry", detected_at="x", vehicle_track_id=None))
    _, url, _ = session.calls[0]
    assert url == "http://localhost:8000/api/v1/events"


def test_POSTはallow_redirects_Falseで送る():
    """リダイレクト追従はPOSTを黙って再送しうるので、常に無効化する。"""
    session = FakeSession(FakeResponse())
    client = ApiClient(make_settings(), session=session)
    client.post_event(EventPayload(request_id="r1", event_type="entry", detected_at="x", vehicle_track_id=None))
    _, _, kwargs = session.calls[0]
    assert kwargs["allow_redirects"] is False


def test_post_eventのbodyはrequest_idを含む4キーちょうど():
    session = FakeSession(FakeResponse())
    client = ApiClient(make_settings(), session=session)
    client.post_event(EventPayload(request_id="r1", event_type="entry", detected_at="2026-09-15T10:00:00+09:00", vehicle_track_id="7"))
    _, _, kwargs = session.calls[0]
    body = kwargs["json"]
    assert set(body.keys()) == {"request_id", "event_type", "detected_at", "vehicle_track_id"}
    assert body["request_id"] == "r1"
    assert body["event_type"] == "entry"
    assert body["vehicle_track_id"] == "7"


def test_post_heartbeatはcommandsを含む応答を返す():
    session = FakeSession(FakeResponse(json_body={"server_time": "x", "commands": [{"id": 1}]}))
    client = ApiClient(make_settings(), session=session)
    result = client.post_heartbeat()
    assert result.disposition == Disposition.OK
    assert result.body["commands"] == [{"id": 1}]


def test_ack_commandは指定した宛先へ送る():
    session = FakeSession(FakeResponse())
    client = ApiClient(make_settings(), session=session)
    client.ack_command(42, status="completed", result_message="12台を検出")
    _, url, kwargs = session.calls[0]
    assert url.endswith("/commands/42/ack")
    assert kwargs["json"] == {"status": "completed", "result_message": "12台を検出"}


def test_healthは認証ヘッダーを付けない():
    session = FakeSession(FakeResponse(status_code=200, json_body={"status": "ok"}))
    client = ApiClient(make_settings(), session=session)
    client.health()
    _, _, kwargs = session.calls[0]
    assert kwargs.get("headers") is None


def test_例外は送らずにfailuresの分類へ委ねる():
    class RaisingSession:
        def post(self, *args, **kwargs):
            raise ConnectionError("boom")

    client = ApiClient(make_settings(), session=RaisingSession())
    result = client.post_event(EventPayload(request_id="r1", event_type="entry", detected_at="x", vehicle_track_id=None))
    assert result.disposition == Disposition.UNKNOWN
    assert "boom" in result.error


def test_自前で作るSessionは自動リトライが0():
    """誰かが将来Retryを足しても、この初期化がその変更を無効化する。"""
    client = ApiClient(make_settings())
    try:
        adapter = client._session.get_adapter("https://localhost/x")
        assert adapter.max_retries.total == 0
    finally:
        client.close()
