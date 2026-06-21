import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import cv2
from ultralytics import YOLO

from src.counter import Counter
from src.roi import get_roi_y_range, is_in_roi
from src.progress import calc_s
from src.visualizer import draw_band_lines, draw_bbox_with_info, draw_counts, draw_roi

# ── パラメータ ──────────────────────────────────────────────────────────────
VIDEO_SOURCE: str | int = "data/inputs/xxxx.mov"

ROI_POINTS = [
    (100, 100),
    (300, 100),
    (300, 300),
    (100, 300),
]
S_LOW  = 0.25
S_HIGH = 0.75
VEHICLE_CLASSES = [2, 7]  # COCO: 2=car, 7=truck
# ────────────────────────────────────────────────────────────────────────────


def main() -> None:
    model = YOLO("yolov8s.pt")
    cap = cv2.VideoCapture(VIDEO_SOURCE)
    if not cap.isOpened():
        print(f"[ERROR] 入力を開けません: {VIDEO_SOURCE}")
        sys.exit(1)

    counter = Counter(S_LOW, S_HIGH)
    y_min, y_max = get_roi_y_range(ROI_POINTS)

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
                if not is_in_roi((cx, cy), ROI_POINTS):
                    continue
                s = calc_s(cy, y_min, y_max)
                track_id = int(tid)
                counter.update(track_id, s)
                state = counter.tracks[track_id].state
                draw_bbox_with_info(frame, (x1, y1, x2, y2), track_id, s, state)

        draw_roi(frame, ROI_POINTS)
        draw_band_lines(frame, ROI_POINTS, y_min, y_max, S_LOW, S_HIGH)
        draw_counts(frame, counter.count_in, counter.count_out)
        cv2.imshow("roi-counter", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()
    print(f"入庫: {counter.count_in}  出庫: {counter.count_out}")


if __name__ == "__main__":
    main()
