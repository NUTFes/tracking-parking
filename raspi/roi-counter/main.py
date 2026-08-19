import argparse
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import cv2
from ultralytics import YOLO

from src.counter import Counter
from src.progress import get_progress_fn
from src.roi import is_in_roi
from src.roi_config import load_roi_config
from src.visualizer import draw_band_lines_for_method, draw_bbox_with_info, draw_counts, draw_roi

# ── パラメータ ──────────────────────────────────────────────────────────────
# ROI・s_low/s_highは設定ファイル（--config）から読む。GUI（roi_setup/
# setup_roi.py）が更新した内容がここに反映される単一情報源になる。
CONFIG_PATH = "data/inputs/configs/IMG_2787_gt.json"
VEHICLE_CLASSES = [2, 7]  # COCO: 2=car, 7=truck

# progress_methodは環境変数PROGRESS_METHODで上書き可能（既定y_normalizedで
# 従来どおりの挙動）。scripts/04_multi_video_mae.py:105と同じ流儀。
PROGRESS_METHOD = os.getenv("PROGRESS_METHOD", "y_normalized")
# ────────────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ROI方式の入出庫カウント（本番推論）")
    parser.add_argument("--config", default=CONFIG_PATH, help="設定ファイルのパス")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        cfg = load_roi_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[ERROR] 設定ファイルを読み込めません: {exc}")
        sys.exit(1)

    progress_fn = get_progress_fn(PROGRESS_METHOD)

    model = YOLO("yolov8s.pt")
    cap = cv2.VideoCapture(cfg.video)
    if not cap.isOpened():
        print(f"[ERROR] 入力を開けません: {cfg.video}")
        sys.exit(1)

    counter = Counter(cfg.s_low, cfg.s_high)

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        results = model.track(frame, persist=True, verbose=False, classes=VEHICLE_CLASSES)
        boxes = results[0].boxes

        if boxes.id is not None:
            for xyxy, tid in zip(boxes.xyxy.cpu().numpy(), boxes.id.cpu().numpy()):
                x1, y1, x2, y2 = map(int, xyxy)
                cx, cy = (x1 + x2) / 2, float(y2)
                if not is_in_roi((cx, cy), cfg.roi):
                    continue
                s = progress_fn((cx, cy), cfg.roi)
                track_id = int(tid)
                counter.update(track_id, s)
                state = counter.tracks[track_id].state
                draw_bbox_with_info(frame, (x1, y1, x2, y2), track_id, s, state)

        draw_roi(frame, cfg.roi)
        draw_band_lines_for_method(frame, cfg.roi, cfg.s_low, cfg.s_high, PROGRESS_METHOD)
        draw_counts(frame, counter.count_in, counter.count_out)
        cv2.imshow("roi-counter", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    print(f"入庫: {counter.count_in}  出庫: {counter.count_out}")


if __name__ == "__main__":
    main()
