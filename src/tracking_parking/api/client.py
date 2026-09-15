"""
tracking-parking-api への HTTP クライアント

requestsはこのモジュール内で一切importしない。ApiClient.__init__の中で
遅延importする（common/wandb_logger.pyのExperimentLoggerが無効時にwandbを
importしない方針と同じ）。api/ 配下のモジュールをimportしただけでは
requestsが読み込まれない。
"""

from dataclasses import dataclass
from typing import Any

from tracking_parking.api.failures import Disposition, classify_exception, classify_status
from tracking_parking.api.settings import ApiSettings


@dataclass(frozen=True)
class EventPayload:
    """POST /events へ送るペイロード。"""

    request_id: str  # EventLogger.record_event()が返すuuid4().hexをそのまま使う（べき等キー）
    event_type: str  # "entry" / "exit"（呼び出し側で"IN"/"OUT"から変換済み）
    detected_at: str  # フレームを読んだ時点の壁時計時刻。オフセット付きISO8601
    vehicle_track_id: str | None


@dataclass(frozen=True)
class SendResult:
    disposition: Disposition
    status_code: int | None = None
    error: str | None = None
    body: dict[str, Any] | None = None


class ApiClient:
    """デバイス視点のAPI呼び出し（イベント登録・ハートビート・コマンドack・ヘルスチェック）。

    requests.Sessionはスレッドセーフを保証していないため、送信ワーカーと
    ハートビートスレッドで別々のApiClientインスタンスを持つこと（同じ
    ApiSettingsから2つ作ればよい）。
    """

    def __init__(self, settings: ApiSettings, *, session: Any = None):
        self._settings = settings
        if session is not None:
            self._session = session
        else:
            import requests

            self._session = requests.Session()
            # 誰かが将来Retryを足しても失敗分類（failures.py）の前提が
            # 崩れないよう、自動リトライを明示的に0へ固定する。
            adapter = requests.adapters.HTTPAdapter(max_retries=0)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)

    def close(self) -> None:
        self._session.close()

    def _url(self, path: str) -> str:
        # urllib.parse.urljoinは使わない。urljoin("http://h/api/v1", "/events")は
        # "/api/v1" を落として "http://h/events" になってしまう。
        return self._settings.base_url.rstrip("/") + path

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self._settings.api_key}

    def _result_from_response(self, resp: Any) -> SendResult:
        disposition = classify_status(resp.status_code)
        try:
            body = resp.json()
        except ValueError:
            body = None
        error = None if disposition == Disposition.OK else (getattr(resp, "text", "") or "")[:500]
        return SendResult(disposition=disposition, status_code=resp.status_code, body=body, error=error)

    def _post(self, path: str, *, json_body: dict[str, Any], auth: bool) -> SendResult:
        headers = self._headers() if auth else None
        try:
            resp = self._session.post(
                self._url(path),
                json=json_body,
                headers=headers,
                timeout=self._settings.timeout,
                allow_redirects=False,
            )
        except Exception as exc:  # noqa: BLE001 — 分類はclassify_exceptionに委ねる
            return SendResult(disposition=classify_exception(exc), error=str(exc))
        return self._result_from_response(resp)

    def health(self) -> SendResult:
        """GET /health。認証不要。疎通確認用。"""
        try:
            resp = self._session.get(
                self._url("/health"), timeout=self._settings.timeout, allow_redirects=False
            )
        except Exception as exc:  # noqa: BLE001
            return SendResult(disposition=classify_exception(exc), error=str(exc))
        return self._result_from_response(resp)

    def post_event(self, event: EventPayload) -> SendResult:
        """POST /events。同じrequest_idの2回目もサーバーが2xxで既存イベントを返す。"""
        body = {
            "request_id": event.request_id,
            "event_type": event.event_type,
            "detected_at": event.detected_at,
            "vehicle_track_id": event.vehicle_track_id,
        }
        return self._post("/events", json_body=body, auth=True)

    def post_heartbeat(self, status: str = "ok") -> SendResult:
        """POST /heartbeat。応答のcommandsがコマンドの唯一の配送路。"""
        return self._post("/heartbeat", json_body={"status": status}, auth=True)

    def ack_command(self, command_id: int, *, status: str, result_message: str | None) -> SendResult:
        """POST /commands/{command_id}/ack。"""
        body = {"status": status, "result_message": result_message}
        return self._post(f"/commands/{command_id}/ack", json_body=body, auth=True)
