"""
送信ガードとランタイム組み立て

run_detection.py が触る唯一の面。カメラ入力 かつ API_ENABLED=true のときだけ
EventSenderとApiClientを実際に生成する。無効時はExperimentLogger
（common/wandb_logger.py）のenabled=False完全no-opパターンをそっくり
踏襲する（requestsも一度もimportされない）。

動画ファイル入力では絶対に送信しない。検証の再実行がそのまま本番の
system_countへ積み上がるためで、これは利便性ではなく安全性の要件。
逆向きの「ファイル入力でも強制送信する」オプションは設けない。
"""

import logging
from typing import Callable

from tracking_parking.api.client import ApiClient, EventPayload
from tracking_parking.api.sender import EventSender
from tracking_parking.api.settings import ApiSettings

logger = logging.getLogger(__name__)

# 内部の"IN"/"OUT"（tracker.pyのVehicleState.line1_direction等）をAPIの
# event_type語彙（"entry"/"exit"）へ変換する。ここへ集約することで、
# run_detection.py側の組み込み箇所を増やさない。
_EVENT_TYPE_MAP = {"IN": "entry", "OUT": "exit"}


class ApiRuntime:
    """検知ループから見たAPI送信機能の窓口。"""

    def __init__(self, *, sender: EventSender | None, client: ApiClient | None, settings: ApiSettings, enabled: bool, log: Callable[[str], None]):
        self._sender = sender
        self._client = client
        self._settings = settings
        self._enabled = enabled
        self._log = log

    @property
    def enabled(self) -> bool:
        return self._enabled

    @classmethod
    def create(
        cls,
        settings: ApiSettings,
        *,
        input_type: str,
        execution_id: str,
        force_disabled: bool = False,
        log: Callable[[str], None] = print,
    ) -> "ApiRuntime":
        """送信ガード：カメラ入力であること かつ API_ENABLED が真であること。

        force_disabledはCLIの--no-apiフラグ相当。.envを書き換えずに送信
        だけ止めたいときに使う。逆向きの「ファイル入力でも強制送信する」
        引数は提供しない（ガードは利便性ではなく安全性の要件のため）。
        """
        enabled = settings.enabled and input_type == "camera" and not force_disabled
        if not enabled:
            return cls(sender=None, client=None, settings=settings, enabled=False, log=log)

        settings.validate()
        client = ApiClient(settings)
        sender = EventSender(client, settings.spool_path, execution_id=execution_id, log=log)
        return cls(sender=sender, client=client, settings=settings, enabled=True, log=log)

    def start(self) -> None:
        if not self._enabled:
            return
        self._log(f"✓ API送信を有効化: {self._settings.base_url}")
        self._sender.start()

    def enqueue_event(self, *, event_id: str, event_type: str, detected_at, track_id) -> None:
        """検出ループから呼ばれる。無効時はno-op。

        "IN"/"OUT" → "entry"/"exit" の変換とtrack_idの文字列化をここへ
        集約する。detected_atはdatetimeオブジェクトを受け取り、この中で
        ISO8601へ変換する（呼び出し側の組み込み行数を増やさないため）。
        """
        if not self._enabled:
            return
        payload = EventPayload(
            request_id=event_id,
            event_type=_EVENT_TYPE_MAP.get(event_type, event_type),
            detected_at=detected_at.isoformat(),
            vehicle_track_id=str(track_id) if track_id is not None else None,
        )
        self._sender.enqueue(payload)

    def shutdown(self) -> None:
        """finally節から呼ばれる想定。内部で全例外を握る。

        ここで例外を外へ出すと、呼び出し元のcap.release()以降の後片付け
        （特にwandb_logger.finish()）がスキップされてしまうため。
        """
        if not self._enabled:
            return
        try:
            self._sender.shutdown(self._settings.shutdown_flush_sec)
        except Exception:
            logger.exception("[api] 送信キューの終了処理で例外が発生しました")
        finally:
            try:
                self._client.close()
            except Exception:
                logger.exception("[api] APIクライアントの終了処理で例外が発生しました")
