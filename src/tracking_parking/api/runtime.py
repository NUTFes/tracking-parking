"""
送信ガードとランタイム組み立て

run_detection.py が触る唯一の面。カメラ入力 かつ API_ENABLED=true のときだけ
EventSender・HeartbeatAgent・ApiClientを実際に生成する。無効時は
ExperimentLogger（common/wandb_logger.py）のenabled=False完全no-op
パターンをそっくり踏襲する（requestsも一度もimportされない）。

動画ファイル入力では絶対に送信しない。検証の再実行がそのまま本番の
system_countへ積み上がるためで、これは利便性ではなく安全性の要件。
「ファイル入力でも本番へ強制送信する」オプションは設けない。

一方、simulate_camera_input（--simulate-camera-input）は上とは別物。
カメラがまだ使えない段階で、動画による検知結果が実際に送信コードへ
正しく届くこと（配線そのもの）を検証するための、送信先がローカル/LAN
（is_local_network_url()）のときだけ働く手段。本番/staging相当のURLでは
create()がValueErrorを出して起動させない（逃げ道なし）。
「本番へは構造的に届かない」ことでADRの意図と両立させている。

requests.Sessionはスレッドセーフを保証していないため、送信ワーカーと
ハートビートスレッドで別々のApiClientインスタンスを持つ。
"""

import logging
from typing import Callable

from tracking_parking.api.agent import HeartbeatAgent
from tracking_parking.api.client import ApiClient, EventPayload
from tracking_parking.api.sender import EventSender
from tracking_parking.api.settings import ApiSettings, is_local_network_url

logger = logging.getLogger(__name__)

# 内部の"IN"/"OUT"（tracker.pyのVehicleState.line1_direction等）をAPIの
# event_type語彙（"entry"/"exit"）へ変換する。ここへ集約することで、
# run_detection.py側の組み込み箇所を増やさない。
_EVENT_TYPE_MAP = {"IN": "entry", "OUT": "exit"}


class ApiRuntime:
    """検知ループから見たAPI送信機能の窓口。"""

    def __init__(
        self,
        *,
        sender: EventSender | None,
        agent: HeartbeatAgent | None,
        event_client: ApiClient | None,
        heartbeat_client: ApiClient | None,
        settings: ApiSettings,
        enabled: bool,
        log: Callable[[str], None],
    ):
        self._sender = sender
        self._agent = agent
        self._event_client = event_client
        self._heartbeat_client = heartbeat_client
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
        simulate_camera_input: bool = False,
        log: Callable[[str], None] = print,
    ) -> "ApiRuntime":
        """送信ガード：カメラ入力であること かつ API_ENABLED が真であること。

        force_disabledはCLIの--no-apiフラグ相当。.envを書き換えずに送信
        だけ止めたいときに使う。

        simulate_camera_inputは--simulate-camera-inputフラグ相当。ファイル
        入力をガード判定上だけカメラ扱いにする（input_type自体は書き換え
        ない。LINE_CONDITION_KEYSのハッシュ元であり、run_configへ嘘を
        記録しないため）。force_disabledが真なら、simulate_camera_inputが
        真でも送信は無効になる（--no-apiは「何があっても送らない」で
        あるべきため）。

        simulate_camera_input=Trueのとき、settings.base_urlが
        is_local_network_url()でTrueと判定できなければ、force_disabledの
        値に関わらずValueErrorを送出し起動させない（逃げ道なし）。本番/
        stagingのsystem_countを動画の繰り返し検証で汚さないという設計上
        の保証を、規約ではなくコードで強制する。
        """
        if simulate_camera_input and not is_local_network_url(settings.base_url):
            raise ValueError(
                "--simulate-camera-inputはAPI_BASE_URLがローカル/LAN以外のときは使えません: "
                f"{settings.base_url}\n"
                "動画をカメラ扱いにする検証は、本番/stagingのsystem_countを"
                "誤って動かさないためローカル/LAN限定です。"
            )
        effective_input_type = "camera" if simulate_camera_input else input_type
        enabled = settings.enabled and effective_input_type == "camera" and not force_disabled
        if not enabled:
            return cls(
                sender=None, agent=None, event_client=None, heartbeat_client=None,
                settings=settings, enabled=False, log=log,
            )

        settings.validate()
        event_client = ApiClient(settings)
        heartbeat_client = ApiClient(settings)
        sender = EventSender(event_client, settings.spool_path, execution_id=execution_id, log=log)
        agent = HeartbeatAgent(
            heartbeat_client,
            settings.heartbeat_interval_sec,
            # stop_countingは送信だけ止める。検出・トラッキング・ローカル
            # JSONログは続ける。停止中に検出したイベントは送信対象から
            # 外して捨てる（EventSender.enqueue()自体が判定する）。
            on_start_counting=lambda: sender.set_sending_enabled(True),
            on_stop_counting=lambda: sender.set_sending_enabled(False),
            log=log,
        )
        return cls(
            sender=sender, agent=agent, event_client=event_client, heartbeat_client=heartbeat_client,
            settings=settings, enabled=True, log=log,
        )

    def start(self) -> None:
        if not self._enabled:
            return
        self._log(f"✓ API送信を有効化: {self._settings.base_url}")
        self._sender.start()
        self._agent.start()

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

        ハートビートを先に止める：sending_enabledを途中で切り替える
        コマンドがシャットダウン中に届いて状態が読みにくくなることを
        避けるため。その後、送信キューをflushしてクライアントを閉じる。
        """
        if not self._enabled:
            return
        try:
            self._agent.stop()
        except Exception:
            logger.exception("[api] ハートビートの終了処理で例外が発生しました")

        try:
            self._sender.shutdown(self._settings.shutdown_flush_sec)
        except Exception:
            logger.exception("[api] 送信キューの終了処理で例外が発生しました")

        for client in (self._event_client, self._heartbeat_client):
            try:
                client.close()
            except Exception:
                logger.exception("[api] APIクライアントの終了処理で例外が発生しました")
