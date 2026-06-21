import json
import sys
import time
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import cv2
import pandas as pd
from ultralytics import YOLO

from src.counter import Counter
from src.roi import get_roi_y_range, is_in_roi
from src.progress import calc_s
from src.visualizer import draw_band_lines, draw_bbox_with_info, draw_counts, draw_roi

# ── パラメータ ──────────────────────────────────────────────────────────────
VIDEO_SOURCE: str | int = "data/inputs/IMG_2788.MOV"
EXP_NAME = ""  # 空文字 → data/outputs/ 直下

ROI_POINTS = [
    (630, 770),
    (1270, 770),
    (1530, 1000),
    (390, 1000),
]
S_LOW  = 0.25
S_HIGH = 0.75
VEHICLE_CLASSES = [2, 7]  # COCO: 2=car, 7=truck
# ────────────────────────────────────────────────────────────────────────────

WEBCAM_FPS = 30.0


def resolve_output_dir(video_source: str | int, exp_name: str) -> Path:
    stem = Path(str(video_source)).stem if isinstance(video_source, str) else "webcam"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path("data/outputs") / exp_name if exp_name else Path("data/outputs")
    return base / f"{stem}_{ts}"


def main() -> None:
    out_dir = resolve_output_dir(VIDEO_SOURCE, EXP_NAME)
    out_dir.mkdir(parents=True, exist_ok=True)

    model = YOLO("yolov8s.pt")
    cap = cv2.VideoCapture(VIDEO_SOURCE)
    if not cap.isOpened():
        print(f"[ERROR] 入力を開けません: {VIDEO_SOURCE}")
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS) or WEBCAM_FPS
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_dir / "annotated.mp4"), fourcc, fps, (w, h))

    counter = Counter(S_LOW, S_HIGH)
    y_min, y_max = get_roi_y_range(ROI_POINTS)

    frame_records = []
    frame_idx = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        t_start = time.perf_counter()
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

        frame_ms = (time.perf_counter() - t_start) * 1000
        frame_records.append({"frame_index": frame_idx, "frame_ms": frame_ms})

        draw_roi(frame, ROI_POINTS)
        draw_band_lines(frame, ROI_POINTS, y_min, y_max, S_LOW, S_HIGH)
        draw_counts(frame, counter.count_in, counter.count_out)
        writer.write(frame)
        cv2.imshow("02_run_analysis", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

        frame_idx += 1

    cap.release()
    writer.release()
    cv2.destroyAllWindows()

    frame_ms_list = [r["frame_ms"] for r in frame_records]
    result = {
        "count_in":    counter.count_in,
        "count_out":   counter.count_out,
        "total_frames": frame_idx,
        "mean_frame_ms": sum(frame_ms_list) / len(frame_ms_list) if frame_ms_list else 0,
        "max_frame_ms":  max(frame_ms_list) if frame_ms_list else 0,
        "total_ms":    sum(frame_ms_list),
        "s_low":  S_LOW,
        "s_high": S_HIGH,
    }
    (out_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))

    vehicles = [
        {
            "track_id":   t.track_id,
            "counted_as": t.counted_as,
            "state":      t.state.value,
            "s_history":  json.dumps(t.s_history),
        }
        for t in counter.get_all_tracks()
    ]
    pd.DataFrame(vehicles).to_csv(out_dir / "vehicles.csv", index=False)
    pd.DataFrame(frame_records).to_csv(out_dir / "frames.csv", index=False)

    print(f"入庫: {counter.count_in}  出庫: {counter.count_out}")
    print(f"出力: {out_dir}")


if __name__ == "__main__":
    main()
