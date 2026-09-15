#!/usr/bin/env python3
"""tracking-parking-api への実疎通確認スクリプト。

`tests/api/` の単体テストは `ApiClient` / `EventSender` / `HeartbeatAgent` を
すべて手書きフェイク相手に検証している。フェイクは「送る側が期待する形」を
返すだけなので、ヘッダ名・URL・フィールド名・応答の形が実物のFastAPIと
一致していることは一度も検証されていない。このスクリプトは `run_detection.py`
を経由せず、`ApiSettings.from_env()` が読む設定でこれらのクラスを直接、
実物のAPI相手に動かす。カメラも動画もモデル重みも要らない。

`run_detection.py` の送信ガード（カメラ入力 かつ API_ENABLED=true）に
相当する条件は、このスクリプト自体には無い。代わりに、API_BASE_URLが
ローカル/LAN以外を指しているとき（`is_local_network_url()`、詳細は
`tracking_parking/api/settings.py`）は即座に終了する
（--i-know-this-is-not-localで解除できる）。ローカル/LAN開発スタック以外へ
誤って本物のイベントを送り込まないための安全弁。

使い方:
    uv run python scripts/check_api_connection.py health
    uv run python scripts/check_api_connection.py event
    uv run python scripts/check_api_connection.py idempotency
    uv run python scripts/check_api_connection.py heartbeat
    uv run python scripts/check_api_connection.py sender --count 5
"""
import argparse
import os
import sys
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

from tracking_parking.api.client import ApiClient, EventPayload
from tracking_parking.api.sender import EventSender
from tracking_parking.api.agent import HeartbeatAgent
from tracking_parking.api.settings import ApiSettings, is_local_network_url


def _load_settings(env_path: str | None) -> ApiSettings:
    """Config.from_env()と同じ流儀で.envを読み、ApiSettingsを組み立てる。

    このスクリプトはConfigを経由しない（YOLOやライン設定は不要なため）ので、
    load_dotenvをここで直接呼ぶ。
    """
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv(os.path.join(REPO_ROOT, ".env"))
    return ApiSettings.from_env()


def _guard_local_only(settings: ApiSettings, *, override: bool) -> None:
    """API_BASE_URLがローカル/LAN開発スタック以外を指していないか確認する。

    run_detection.pyの送信ガード（カメラ入力かどうか）に相当する条件が
    このスクリプトには無い。誤って本番やstagingへ向けたまま実行すると、
    テスト用のダミーイベントがそのまま本物のsystem_countを動かしてしまう。

    判定はis_local_network_url()に委ねる（--simulate-camera-inputと共有）。
    localhost完全一致より広く、LAN上のIPやmDNS名も許可する一方、
    本番ドメインは確実に弾く。
    """
    if override:
        return
    if not is_local_network_url(settings.base_url):
        print(
            f"エラー: API_BASE_URLがローカル/LAN以外を指しています: {settings.base_url}\n"
            "本番/stagingへ向けて実行しないでください。意図してのことなら "
            "--i-know-this-is-not-local を付けてください。",
            file=sys.stderr,
        )
        sys.exit(1)


def _print_result(label: str, result) -> None:
    print(f"[{label}] disposition={result.disposition} status_code={result.status_code}")
    if result.body is not None:
        print(f"  body: {result.body}")
    if result.error:
        print(f"  error: {result.error}")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def cmd_health(args, settings: ApiSettings) -> None:
    client = ApiClient(settings)
    result = client.health()
    _print_result("health", result)
    client.close()


def cmd_event(args, settings: ApiSettings) -> None:
    client = ApiClient(settings)
    request_id = args.request_id or uuid.uuid4().hex
    payload = EventPayload(
        request_id=request_id,
        event_type=args.event_type,
        detected_at=_now_iso(),
        vehicle_track_id=args.track_id,
    )
    print(f"送信するrequest_id: {request_id}")
    result = client.post_event(payload)
    _print_result("event", result)
    client.close()


def cmd_idempotency(args, settings: ApiSettings) -> None:
    """同じrequest_idで2回送り、応答のidが一致することを確認する。

    system_countがいつ動くかはPOSTの応答では分からない（202 Accepted +
    バックグラウンド処理のため）。GET /parking-lotsをポーリングするのは
    このスクリプトの役目ではなく、手順としてplanに書いた通り別途確認する。
    """
    client = ApiClient(settings)
    request_id = args.request_id or uuid.uuid4().hex
    payload = EventPayload(
        request_id=request_id,
        event_type=args.event_type,
        detected_at=_now_iso(),
        vehicle_track_id=args.track_id,
    )
    print(f"送信するrequest_id: {request_id}（同じ値で2回送る）")
    result1 = client.post_event(payload)
    _print_result("1回目", result1)
    result2 = client.post_event(payload)
    _print_result("2回目", result2)

    id1 = (result1.body or {}).get("id")
    id2 = (result2.body or {}).get("id")
    if id1 is not None and id1 == id2:
        print(f"OK: 両方の応答のidが一致（id={id1}）。べき等キーが効いています。")
    else:
        print(f"NG: idが一致しません（1回目={id1}, 2回目={id2}）。フィールド名のずれ、"
              "または受信側のrequest_id対応が未デプロイの可能性があります。")
    client.close()


def cmd_heartbeat(args, settings: ApiSettings) -> None:
    client = ApiClient(settings)

    def _on_start():
        print("  → on_start_counting が呼ばれました")

    def _on_stop():
        print("  → on_stop_counting が呼ばれました")

    agent = HeartbeatAgent(
        client, settings.heartbeat_interval_sec,
        on_start_counting=_on_start, on_stop_counting=_on_stop,
    )
    agent.tick()
    client.close()


def cmd_sender(args, settings: ApiSettings) -> None:
    """EventSenderを起動し、指定件数enqueueしてからshutdownする。

    --count 0 で呼べば、enqueueせずに起動時のreplay_spool()だけを走らせる
    （第4層の「復帰後の再送」確認に使う）。
    """
    client = ApiClient(settings)
    sender = EventSender(client, settings.spool_path, execution_id="check_api_connection")
    sender.start()

    for i in range(args.count):
        request_id = uuid.uuid4().hex
        payload = EventPayload(
            request_id=request_id,
            event_type="entry" if i % 2 == 0 else "exit",
            detected_at=_now_iso(),
            vehicle_track_id=str(1000 + i),
        )
        ok = sender.enqueue(payload)
        print(f"enqueue[{i}] request_id={request_id} accepted={ok}")

    stats = sender.shutdown(settings.shutdown_flush_sec)
    print(f"shutdown後の統計: {stats}")
    print(f"スプール: {settings.spool_path}")
    if settings.spool_path.exists():
        print(settings.spool_path.read_text(encoding="utf-8"))
    else:
        print("(スプールファイルなし)")
    client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env", help=".envファイルのパス（既定: リポジトリルートの.env）")
    parser.add_argument(
        "--i-know-this-is-not-local", action="store_true", dest="override_guard",
        help="API_BASE_URLがローカル/LAN（is_local_network_url()の判定範囲）以外でも"
             "実行を許可する（通常は使わない）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health", help="GET /health")

    p_event = sub.add_parser("event", help="POST /events を1件送る")
    p_event.add_argument("--request-id", help="省略時はuuid4().hexを生成")
    p_event.add_argument("--event-type", dest="event_type", default="entry", choices=["entry", "exit"])
    p_event.add_argument("--track-id", dest="track_id", default="1")

    p_idem = sub.add_parser("idempotency", help="同じrequest_idで2回POSTする")
    p_idem.add_argument("--request-id", help="省略時はuuid4().hexを生成")
    p_idem.add_argument("--event-type", dest="event_type", default="entry", choices=["entry", "exit"])
    p_idem.add_argument("--track-id", dest="track_id", default="1")

    sub.add_parser("heartbeat", help="HeartbeatAgent.tick()を1回実行する")

    p_sender = sub.add_parser("sender", help="EventSenderで複数件enqueue→shutdownする")
    p_sender.add_argument("--count", type=int, default=1, help="enqueueする件数（既定1、0なら起動時再送のみ）")

    args = parser.parse_args()

    settings = _load_settings(args.env)
    _guard_local_only(settings, override=args.override_guard)

    if not settings.enabled:
        print("警告: API_ENABLED=false です。.envまたは環境変数でtrueにしてください。", file=sys.stderr)
        return 1
    settings.validate()

    handlers = {
        "health": cmd_health,
        "event": cmd_event,
        "idempotency": cmd_idempotency,
        "heartbeat": cmd_heartbeat,
        "sender": cmd_sender,
    }
    handlers[args.command](args, settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
