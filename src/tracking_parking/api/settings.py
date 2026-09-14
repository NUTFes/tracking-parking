"""
API送信の接続設定
.envファイルから読み込み、ApiSettingsオブジェクトとして提供する
"""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApiSettings:
    """tracking-parking-apiへの接続設定。

    Config（config.py）にもRuntimeSettings（scripts/run_detection.py）にも
    含めず独立させている。理由は2つ。(1) Config/RuntimeSettingsのフィールドは
    run_configへ手で写され、ExperimentLogger経由でW&Bへアップロードされる。
    api_keyをそこへ混入させると秘密情報が外部サービスへ漏れる。(2) enabled=False
    のときbase_url/api_keyが空でも正常でなければならず、Config.validate()の
    無条件チェックとは意味論が異なる。
    """

    enabled: bool
    base_url: str
    api_key: str
    connect_timeout_sec: float
    read_timeout_sec: float
    heartbeat_interval_sec: float
    shutdown_flush_sec: float
    spool_path: Path

    @classmethod
    def from_env(cls, home_dir: str | None = None) -> "ApiSettings":
        """
        .envファイルから設定を読み込む

        Config.from_env()が .env を読み込んだ後に呼ぶ想定（load_dotenvは
        ここでは呼ばない。既存の環境変数を上書きしないload_dotenvの仕様上、
        二重に呼んでも害はないが、RuntimeSettings.from_env()と同じ前提を踏襲する）。

        Args:
            home_dir: 相対SPOOL_PATHの解決基準。Noneなら os.getenv("HOME_DIR")。
                実機はカメラ常駐でカレントディレクトリが不定なため、
                CWD基準ではなくHOME_DIR基準で解決する。

        Returns:
            ApiSettings: 設定オブジェクト
        """
        enabled = os.getenv("API_ENABLED", "false").lower() == "true"
        base_url = os.getenv("API_BASE_URL", "")
        api_key = os.getenv("DEVICE_API_KEY", "")
        connect_timeout_sec = float(os.getenv("API_CONNECT_TIMEOUT_SEC", "3.0"))
        read_timeout_sec = float(os.getenv("API_READ_TIMEOUT_SEC", "5.0"))
        heartbeat_interval_sec = float(os.getenv("HEARTBEAT_INTERVAL_SEC", "30"))
        shutdown_flush_sec = float(os.getenv("SHUTDOWN_FLUSH_SEC", "10"))

        spool_path_str = os.getenv("SPOOL_PATH", "data/outputs/unsent_events.jsonl")
        spool_path = Path(spool_path_str)
        if not spool_path.is_absolute():
            base = home_dir if home_dir is not None else os.getenv("HOME_DIR")
            if base:
                spool_path = Path(base) / spool_path

        return cls(
            enabled=enabled,
            base_url=base_url,
            api_key=api_key,
            connect_timeout_sec=connect_timeout_sec,
            read_timeout_sec=read_timeout_sec,
            heartbeat_interval_sec=heartbeat_interval_sec,
            shutdown_flush_sec=shutdown_flush_sec,
            spool_path=spool_path,
        )

    @property
    def timeout(self) -> tuple[float, float]:
        """requestsへ渡す (connect, read) タプル。"""
        return (self.connect_timeout_sec, self.read_timeout_sec)

    def validate(self) -> None:
        """設定値の妥当性をチェック（Config.validate()と同じくerrorsを蓄積して最後にまとめてraiseする）。

        enabled=Falseのときはbase_url/api_keyが空でも正常（既存利用者全員が
        通る既定経路）。数値系のチェックはenabledに関わらず常に行う。
        """
        errors = []

        if self.enabled:
            if not self.base_url:
                errors.append("API_ENABLED=true のとき API_BASE_URL が .env に設定されている必要があります")
            if not self.api_key:
                errors.append("API_ENABLED=true のとき DEVICE_API_KEY が .env に設定されている必要があります")

        if self.connect_timeout_sec <= 0:
            errors.append(f"API_CONNECT_TIMEOUT_SEC は正の値である必要があります: {self.connect_timeout_sec}")

        if self.read_timeout_sec <= 0:
            errors.append(f"API_READ_TIMEOUT_SEC は正の値である必要があります: {self.read_timeout_sec}")

        if self.heartbeat_interval_sec <= 0:
            errors.append(f"HEARTBEAT_INTERVAL_SEC は正の値である必要があります: {self.heartbeat_interval_sec}")

        if self.shutdown_flush_sec < 0:
            errors.append(f"SHUTDOWN_FLUSH_SEC は0以上の値である必要があります: {self.shutdown_flush_sec}")

        if errors:
            raise ValueError("API設定エラー:\n" + "\n".join(f"  - {e}" for e in errors))
