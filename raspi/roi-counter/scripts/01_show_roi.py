import argparse
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import cv2

from src.roi import check_roi_geometry, get_roi_y_range
from src.roi_config import load_roi_config
from src.visualizer import draw_band_lines_for_method, draw_grid, draw_roi

# ── パラメータ ──────────────────────────────────────────────────────────────
# ROI・s_low/s_highは設定ファイル（--config）から読む。ここでのハードコード
# は既定パスとシーク秒数・出力先だけ（ROI契約ではなく表示の都合）。
CONFIG_PATH = "data/inputs/configs/IMG_2787_gt.json"
SEEK_SEC = 5.0  # 表示するフレームの秒数
# ────────────────────────────────────────────────────────────────────────────

OUTPUT_PATH = Path("data/outputs/roi_check.png")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ROI（+ 等s線）を静止フレームに重ねて確認する"
    )
    parser.add_argument("--config", default=CONFIG_PATH, help="設定ファイルのパス")
    parser.add_argument("--seek-sec", type=float, default=SEEK_SEC, help="表示するフレームの秒数")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="保存先PNGのパス")
    parser.add_argument(
        "--progress-method",
        default=os.getenv("PROGRESS_METHOD", "y_normalized"),
        choices=["y_normalized", "edge_distance"],
        help="等s線の計算方式（既定は環境変数PROGRESS_METHOD、未設定ならy_normalized）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        cfg = load_roi_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[ERROR] 設定ファイルを読み込めません: {exc}")
        sys.exit(1)

    errors, warnings = check_roi_geometry(cfg.roi)
    for message in warnings:
        print(f"[WARN] {message}")
    for message in errors:
        print(f"[ERROR] {message}")
    if errors:
        sys.exit(1)

    cap = cv2.VideoCapture(cfg.video)
    if not cap.isOpened():
        print(f"[ERROR] 動画を開けません: {cfg.video}")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_POS_MSEC, args.seek_sec * 1000)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        print(f"[ERROR] {args.seek_sec}秒地点のフレームを取得できません")
        sys.exit(1)

    draw_grid(frame)
    draw_roi(frame, cfg.roi)
    draw_band_lines_for_method(frame, cfg.roi, cfg.s_low, cfg.s_high, args.progress_method)

    if args.progress_method == "y_normalized":
        y_min, y_max = get_roi_y_range(cfg.roi)
        info_text = f"y_min={y_min:.0f}  y_max={y_max:.0f}"
    else:
        info_text = f"method={args.progress_method}"
    cv2.putText(frame, info_text,
                (10, frame.shape[0] - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), frame)
    print(f"保存: {output_path}")

    cv2.imshow("ROI Check", frame)
    while True:
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
