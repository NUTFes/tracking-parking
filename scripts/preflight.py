#!/usr/bin/env python3
"""本番実行の前に、黙って失敗する条件を検査する。

起動はするが結果が静かにおかしくなる条件を、実行前にまとめて出す。
`scripts/run_production.sh` から呼ばれるが、単体でも使える。

    .venv/bin/python scripts/preflight.py --camera 0 --env jetson-newcam.env

問題があれば終了コード1で、見つかった分をすべて出力する。
"""

import argparse
import os
import shutil
import sys

import cv2

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from tracking_parking.common.camera import apply_camera_capture_settings
from tracking_parking.common.preflight import (
    check_disk_space,
    check_line_bounds,
    describe_frame_mismatch,
)
from tracking_parking.config import Config

# 録画の空き容量の目安。1280x720で約37GB/日なので、2日分とその余裕。
DISK_NEED_BYTES = 100 * 1024**3


def check_cuda() -> list:
    """GPUが使えるかを見る。uv sync / uv run で .venv が作り直されると壊れる。"""
    try:
        import torch
    except ImportError as exc:
        return [f"torchを読み込めません: {exc}"]

    if not torch.cuda.is_available():
        return [
            f"CUDAが使えません (torch {torch.__version__})。"
            "uv sync / uv run で .venv が作り直された可能性があります。"
            "READMEの「エッジ機」の手順で再構築してください"
        ]
    return []


def open_camera(device: int, config: Config):
    """検知ループと同じ手順でカメラを開き、実測の解像度を返す。"""
    cap = cv2.VideoCapture(device)
    if not cap.isOpened():
        return None, (0, 0)
    apply_camera_capture_settings(
        cap,
        width=config.camera_width,
        height=config.camera_height,
        fourcc=config.camera_fourcc,
    )
    # 要求が反映されるまで数フレーム読む（設定直後のgetは古い値を返しうる）。
    for _ in range(5):
        cap.read()
    actual = (
        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    )
    cap.release()
    return True, actual


def main() -> int:
    parser = argparse.ArgumentParser(description="本番実行の事前チェック")
    parser.add_argument("--camera", type=int, default=0, help="カメラデバイスID")
    parser.add_argument("--env", required=True, help="検知設定の.envファイル")
    parser.add_argument("--output", default="data/outputs", help="出力ディレクトリ")
    args = parser.parse_args()

    problems = []
    notes = []

    # 1. 設定を読めるか
    try:
        config = Config.from_env(args.env)
        config.validate()
    except Exception as exc:  # noqa: BLE001
        print(f"設定を読めません ({args.env}):\n{exc}")
        return 1

    # 2. GPU
    problems += check_cuda()

    # 3. カメラを開けるか、要求解像度が通ったか
    opened, actual = open_camera(args.camera, config)
    if opened is None:
        problems.append(f"カメラ{args.camera}を開けません（/dev/video* を確認）")
    else:
        problems += describe_frame_mismatch(
            (config.camera_width, config.camera_height), actual
        )
        # 4. ライン座標が画角の内側にあるか
        problems += check_line_bounds(config, actual[0], actual[1])
        notes.append(f"カメラ{args.camera}: {actual[0]}x{actual[1]}")

    # 5. API設定（プロセス環境から読む。run_detectionと同じ経路）
    if os.getenv("API_ENABLED", "false").lower() == "true":
        base_url = os.getenv("API_BASE_URL", "")
        if not os.getenv("DEVICE_API_KEY"):
            problems.append("API_ENABLED=true ですが DEVICE_API_KEY が空です")
        notes.append(f"API送信: 有効 → {base_url}")
    else:
        notes.append("API送信: 無効（API_ENABLED が true でない）")

    # 6. 録画の設定と空き容量
    if config.save_video:
        videos_dir = os.path.join(args.output, "videos")
        os.makedirs(videos_dir, exist_ok=True)
        free = shutil.disk_usage(videos_dir).free
        problems += check_disk_space(free, need_bytes=DISK_NEED_BYTES)
        notes.append(
            f"録画: 有効 / {config.video_segment_mb}MBごと / "
            f"空き{free / 1024**3:.1f}GB"
        )
    else:
        notes.append("録画: 無効（SAVE_VIDEO=false）")

    for note in notes:
        print(f"  {note}")

    if problems:
        print("\n事前チェックで問題が見つかりました:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\n事前チェック: 問題なし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
