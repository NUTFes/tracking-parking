#!/usr/bin/env python3
"""カメラの画角を見ながら調整するためのライブプレビュー。

設置カメラの向き・高さ・傾きを合わせる作業は1枚のフレームでは足りない
（動かす → 映りを見る、を繰り返すため）。setup_lines.py は先頭フレームで
止まるので、調整中はこちらを使う。

    .venv/bin/python scripts/preview_camera.py --camera 0 --env jetson-newcam.env

検知ループと同じ解像度でフレームを掴む（ライン座標は画角に紐づくため）。
設定済みのライン座標があれば重ねて描くので、「前と同じ画角へ戻す」作業にも使える。

カメラは1プロセスしか開けない。調整が終わったらこれを止めてから
scripts/run_production.sh を起動すること。
"""

import argparse
import os
import time
from datetime import datetime, timezone

import cv2

from tracking_parking.common.camera import apply_camera_capture_settings
from tracking_parking.common.preflight import check_line_bounds
from tracking_parking.config import CameraCaptureSettings, Config
from tracking_parking.output.video_writer import VideoAnnotator, format_jst

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# カメラを開いた直後は露出が安定しない。捨てる枚数（setup_lines.pyと揃える）。
CAMERA_WARMUP_FRAMES = 10

# fps表示の平滑化に使う直近フレーム数。1フレームごとの差分は揺れが大きく、
# 画角調整中に見る値としては読めないため。
FPS_WINDOW = 30


def load_annotator(env_path):
    """設定済みのライン座標を描くためのアノテータを返す。

    ライン座標がまだ無い状態（画角を決めてから設定する）でも動かせるよう、
    設定を読めなければNoneを返して映像だけを出す。モデルファイルの有無は
    見ない（プレビューは推論しないため、Config.validate()は通さない）。

    Returns:
        (annotator, config)。読めなければ (None, None)。
    """
    try:
        config = Config.from_env(env_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] ライン座標を読めませんでした（映像のみ表示します）: {exc}")
        return None, None

    # 5点すべて0は「まだ設定していない」状態。原点に線を描いても意味がない。
    points = [config.line1.start, config.line1.end,
              config.line2.start, config.line2.end, config.parking_ref_point]
    if all(x == 0 and y == 0 for x, y in points):
        print("[INFO] ライン座標が未設定です（映像のみ表示します）")
        return None, None

    return VideoAnnotator(config.line1, config.line2, config.parking_ref_point), config


def draw_status(frame, text_lines):
    """左上へ状態を焼き込む。ASCIIのみ（Hersheyフォントの制約）。"""
    for i, text in enumerate(text_lines):
        position = (10, 30 + i * 28)
        (w, h), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(frame, (position[0] - 3, position[1] - h - 3),
                      (position[0] + w + 3, position[1] + baseline + 3), (0, 0, 0), -1)
        cv2.putText(frame, text, position, cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 2)


def main() -> int:
    parser = argparse.ArgumentParser(description="カメラ画角のライブプレビュー")
    parser.add_argument("--camera", type=int, default=0, help="カメラデバイスID")
    parser.add_argument("--env", default=None,
                        help="設定ファイル（既定: リポジトリルートの.env）")
    parser.add_argument("--no-lines", action="store_true",
                        help="ライン座標を重ねない")
    parser.add_argument("--output", default="data/outputs",
                        help="スナップショットの保存先")
    args = parser.parse_args()

    env_path = args.env or os.path.join(REPO_ROOT, ".env")
    if not os.path.exists(env_path):
        print(f"エラー: 設定ファイルが見つかりません: {env_path}")
        return 1

    camera = CameraCaptureSettings.from_env(env_path)
    errors = camera.validation_errors()
    if errors:
        print("設定エラー:\n" + "\n".join(f"  - {e}" for e in errors))
        return 1

    annotator, config = (None, None) if args.no_lines else load_annotator(env_path)

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"エラー: カメラ{args.camera}を開けません")
        print("  前回のプロセスが残っていないか確認する: fuser -v /dev/video0")
        return 1

    try:
        apply_camera_capture_settings(
            cap, width=camera.width, height=camera.height, fourcc=camera.fourcc
        )
        for _ in range(CAMERA_WARMUP_FRAMES):
            cap.read()

        actual = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                  int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        print(f"✓ カメラ{args.camera}: {actual[0]}x{actual[1]}")
        if camera.width is not None and actual != (camera.width, camera.height):
            print(f"[WARN] カメラが要求解像度を受理しませんでした: "
                  f"要求 {camera.width}x{camera.height} → 実際 {actual[0]}x{actual[1]}")

        if config is not None:
            # 画角の外に出た線は描画されず、画面からは「線が無い」と区別できない。
            for problem in check_line_bounds(config, actual[0], actual[1]):
                print(f"[WARN] {problem}")

        print("操作: q または ESC で終了 / s でスナップショット保存 / "
              "l でライン表示の切り替え")

        window_name = "Camera Preview"  # ASCII固定（setup_lines.pyと同じ理由）
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window_name, actual[0], actual[1])

        show_lines = annotator is not None
        timestamps = []

        while True:
            ret, frame = cap.read()
            if not ret:
                print("エラー: フレームを読み込めません（カメラが外れた可能性）")
                return 1

            timestamps.append(time.monotonic())
            if len(timestamps) > FPS_WINDOW:
                timestamps.pop(0)
            fps = 0.0
            if len(timestamps) > 1:
                span = timestamps[-1] - timestamps[0]
                fps = (len(timestamps) - 1) / span if span > 0 else 0.0

            display = frame.copy()
            if show_lines and annotator is not None:
                annotator.draw_lines(display)

            draw_status(display, [
                format_jst(datetime.now(timezone.utc)),
                f"{actual[0]}x{actual[1]}  {fps:.1f} fps",
                "Lines: ON" if show_lines else "Lines: OFF",
            ])
            cv2.imshow(window_name, display)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("l"):
                if annotator is None:
                    print("ライン座標が無いので切り替えられません")
                else:
                    show_lines = not show_lines
            if key == ord("s"):
                os.makedirs(args.output, exist_ok=True)
                path = os.path.join(
                    args.output,
                    f"preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg",
                )
                cv2.imwrite(path, display)
                print(f"✓ 保存: {path}")

            # ウィンドウを×で閉じられたときも抜ける（setup_lines.pyと同じ事情で
            # getWindowPropertyが例外を投げることがある）。
            try:
                if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                    break
            except cv2.error:
                break
    except KeyboardInterrupt:
        print("\n中断しました")
    finally:
        cap.release()
        cv2.destroyAllWindows()

    print("カメラを解放しました（run_production.sh を起動できます）")
    return 0


if __name__ == "__main__":
    exit(main())
