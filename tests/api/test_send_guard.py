"""送信ガードとランタイム組み立て（ApiRuntime）に関するテスト。

カメラ入力 かつ API_ENABLED=true のときだけ実際に送信機能を生成する、
という送信ガードは安全性の要件（ファイル入力での検証再実行が本番の
system_countを壊さないようにするため）。3通りの組み合わせをすべて
確認する。無効時にApiClientが一切生成されず、requestsも一度もimport
されないことも、設計の前提そのものなので固定する。
"""
import sys
from datetime import datetime

from tracking_parking.api.runtime import ApiRuntime
from tracking_parking.api.settings import ApiSettings


def make_settings(**overrides):
    base = dict(
        enabled=True,
        base_url="http://localhost:8000/api/v1",
        api_key="secret",
        connect_timeout_sec=3.0,
        read_timeout_sec=5.0,
        heartbeat_interval_sec=30,
        shutdown_flush_sec=10,
        spool_path="/tmp/unused-api-runtime-test.jsonl",
    )
    base.update(overrides)
    return ApiSettings(**base)


def test_ファイル入力ではAPI_ENABLED_trueでも無効になる():
    runtime = ApiRuntime.create(make_settings(enabled=True), input_type="file", execution_id="exec-1")
    assert runtime.enabled is False


def test_カメラ入力でもAPI_ENABLED_falseなら無効になる():
    runtime = ApiRuntime.create(make_settings(enabled=False), input_type="camera", execution_id="exec-1")
    assert runtime.enabled is False


def test_カメラ入力かつAPI_ENABLED_trueで有効になる():
    runtime = ApiRuntime.create(make_settings(enabled=True), input_type="camera", execution_id="exec-1")
    assert runtime.enabled is True


def test_force_disabledはカメラ入力かつ有効設定でも無効化する():
    """--no-apiフラグ相当。逆方向（ファイル入力での強制有効化）は提供しない。"""
    runtime = ApiRuntime.create(
        make_settings(enabled=True), input_type="camera", execution_id="exec-1", force_disabled=True
    )
    assert runtime.enabled is False


def test_無効時はApiClientを一度も生成しない(monkeypatch):
    def fail_if_called(self, *args, **kwargs):
        raise AssertionError("無効なのにApiClientが生成された")

    monkeypatch.setattr("tracking_parking.api.client.ApiClient.__init__", fail_if_called)
    runtime = ApiRuntime.create(make_settings(enabled=False), input_type="camera", execution_id="exec-1")
    assert runtime.enabled is False


def test_無効時は全メソッドが例外を出さない():
    runtime = ApiRuntime.create(make_settings(enabled=False), input_type="file", execution_id="exec-1")
    runtime.start()
    runtime.enqueue_event(event_id="e1", event_type="IN", detected_at=datetime.now(), track_id=1)
    runtime.shutdown()


def test_無効時はrequestsを一度もimportしない(monkeypatch):
    """requests未import、という設計の前提そのものを固定する。"""
    monkeypatch.delitem(sys.modules, "requests", raising=False)
    ApiRuntime.create(make_settings(enabled=False), input_type="camera", execution_id="exec-1")
    assert "requests" not in sys.modules


def test_run_multi_videoはcameraオプションを渡さない(monkeypatch, tmp_path):
    """run_multi_video.pyは常にファイル入力で子プロセスを起動するため、
    子プロセス側の送信ガードにより自動的に送信対象外になる。"""
    import run_multi_video

    captured = {}

    class FakeCompletedProcess:
        returncode = 0

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        return FakeCompletedProcess()

    monkeypatch.setattr(run_multi_video.subprocess, "run", fake_run)
    run_multi_video.run_one("dummy.mp4", ".env", tmp_path)

    assert "--camera" not in captured["cmd"]
    assert "--input" in captured["cmd"]
