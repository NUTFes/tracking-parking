"""API送信設定（ApiSettings）の読み込みに関するテスト。

API_ENABLED=false（既定）はrequests未importの検知処理を含む全ての既存
利用者が通る経路なので、URL/キーが無くても正常であることを固定する。
有効時に必須値が欠けた場合は、Config.validate()と同じくerrorsを蓄積して
1回のValueErrorにまとめることも確認する。
"""
import pytest

from tracking_parking.api.settings import ApiSettings, is_local_network_url

API_ENV_KEYS = (
    "API_ENABLED", "API_BASE_URL", "DEVICE_API_KEY",
    "API_CONNECT_TIMEOUT_SEC", "API_READ_TIMEOUT_SEC",
    "HEARTBEAT_INTERVAL_SEC", "SHUTDOWN_FLUSH_SEC", "SPOOL_PATH",
    "HOME_DIR",
)


@pytest.fixture
def clean_env(monkeypatch):
    """API関連のenv varを全て消してから始める。開発者のシェルに残った値に左右されないよう。"""
    for key in API_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_既定値(clean_env):
    settings = ApiSettings.from_env()
    assert settings.enabled is False
    assert settings.base_url == ""
    assert settings.api_key == ""
    assert settings.connect_timeout_sec == 3.0
    assert settings.read_timeout_sec == 5.0
    assert settings.heartbeat_interval_sec == 30
    assert settings.shutdown_flush_sec == 10
    settings.validate()  # 例外を出さない


def test_無効時はURLもキーも無くて通る(clean_env):
    """既存利用者全員が通る既定経路。"""
    settings = ApiSettings.from_env()
    assert settings.enabled is False
    settings.validate()


def test_有効時にURLとキーが両方欠けていると1回のValueErrorに2件とも出る(clean_env, monkeypatch):
    monkeypatch.setenv("API_ENABLED", "true")
    settings = ApiSettings.from_env()
    with pytest.raises(ValueError) as exc_info:
        settings.validate()
    message = str(exc_info.value)
    assert "API_BASE_URL" in message
    assert "DEVICE_API_KEY" in message


def test_有効時にURLとキーが揃っていれば通る(clean_env, monkeypatch):
    monkeypatch.setenv("API_ENABLED", "true")
    monkeypatch.setenv("API_BASE_URL", "http://localhost:8000/api/v1")
    monkeypatch.setenv("DEVICE_API_KEY", "secret-key")
    settings = ApiSettings.from_env()
    settings.validate()


@pytest.mark.parametrize("key,value", [
    ("API_CONNECT_TIMEOUT_SEC", "0"),
    ("API_CONNECT_TIMEOUT_SEC", "-1"),
    ("API_READ_TIMEOUT_SEC", "0"),
    ("HEARTBEAT_INTERVAL_SEC", "0"),
    ("SHUTDOWN_FLUSH_SEC", "-1"),
])
def test_不正な数値を拒否する(clean_env, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    settings = ApiSettings.from_env()
    with pytest.raises(ValueError):
        settings.validate()


def test_SHUTDOWN_FLUSH_SECは0を許容する(clean_env, monkeypatch):
    """0秒 = 待たずに即スプールへ落とす、という有効な設定。"""
    monkeypatch.setenv("SHUTDOWN_FLUSH_SEC", "0")
    settings = ApiSettings.from_env()
    settings.validate()


def test_非数値の設定はfrom_envの時点でエラーになる(clean_env, monkeypatch):
    monkeypatch.setenv("API_CONNECT_TIMEOUT_SEC", "abc")
    with pytest.raises(ValueError):
        ApiSettings.from_env()


def test_相対SPOOL_PATHはHOME_DIR基準で絶対化される(clean_env, monkeypatch):
    monkeypatch.setenv("HOME_DIR", "/tmp/trapa-home")
    settings = ApiSettings.from_env()
    assert str(settings.spool_path) == "/tmp/trapa-home/data/outputs/unsent_events.jsonl"


def test_絶対SPOOL_PATHはそのまま使う(clean_env, monkeypatch):
    monkeypatch.setenv("HOME_DIR", "/tmp/trapa-home")
    monkeypatch.setenv("SPOOL_PATH", "/var/spool/events.jsonl")
    settings = ApiSettings.from_env()
    assert str(settings.spool_path) == "/var/spool/events.jsonl"


def test_home_dir引数がHOME_DIR環境変数より優先される(clean_env, monkeypatch):
    monkeypatch.setenv("HOME_DIR", "/tmp/env-home")
    settings = ApiSettings.from_env(home_dir="/tmp/explicit-home")
    assert str(settings.spool_path) == "/tmp/explicit-home/data/outputs/unsent_events.jsonl"


def test_timeoutプロパティはconnectとreadのタプルを返す(clean_env, monkeypatch):
    monkeypatch.setenv("API_CONNECT_TIMEOUT_SEC", "2.0")
    monkeypatch.setenv("API_READ_TIMEOUT_SEC", "4.0")
    settings = ApiSettings.from_env()
    assert settings.timeout == (2.0, 4.0)


class Test_is_local_network_url:
    """--simulate-camera-input（動画をカメラ扱いにする検証フラグ）と
    check_api_connection.pyの両方が、本番/stagingへ誤って送らないための
    安全判定。エッジ機からLAN上の開発機スタックを指す場合（localhostでは
    なくIPやmDNS名になる）でも通り、実際の本番ドメインは確実に弾かれる
    ことを境界値で固定する。
    """

    def test_localhostはTrue(self):
        assert is_local_network_url("http://localhost:8000/api/v1") is True

    def test_ループバックIPはTrue(self):
        assert is_local_network_url("http://127.0.0.1:8000/api/v1") is True

    def test_プライベートIP_192はTrue(self):
        assert is_local_network_url("http://192.168.1.10:8000/api/v1") is True

    def test_プライベートIP_10はTrue(self):
        assert is_local_network_url("http://10.0.0.5:8000/api/v1") is True

    def test_mDNS名はTrue(self):
        assert is_local_network_url("http://jetson.local:8000/api/v1") is True

    def test_ドットを含まない裸のホスト名はTrue(self):
        """LAN上のマシン名やDockerサービス名（例: dev-machine, api）を想定。"""
        assert is_local_network_url("http://dev-machine:8000/api/v1") is True

    def test_本番ドメインはFalse(self):
        assert is_local_network_url("https://api.trapa.nutfes.net/api/v1") is False

    def test_パブリックIPはFalse(self):
        assert is_local_network_url("http://8.8.8.8/api/v1") is False

    def test_空文字はFalse(self):
        assert is_local_network_url("") is False

    def test_ホスト名を取れないURLはFalse(self):
        assert is_local_network_url("not-a-url") is False
