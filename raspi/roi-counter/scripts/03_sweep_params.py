"""
02_run_analysis.py のコア処理ループを流用し，S_LOW × S_HIGH の全組み合わせを実行して
Count Error を results.csv に記録する．（ファイル入力専用）
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import pandas as pd
from ultralytics import YOLO
import cv2

from src.counter import Counter
from src.roi import get_roi_y_range, is_in_roi
from src.progress import calc_s

# ── パラメータ ──────────────────────────────────────────────────────────────
VIDEO_SOURCE = "data/inputs/IMG_2788_fixed.MOV"  # ファイル専用
GT_PATH      = "data/inputs/IMG_2788_gt.json"    # 空文字の場合は VIDEO_SOURCE から自動導出
EXP_NAME     = "exp1_2788_fixed"

ROI_POINTS = [
    (630, 770),
    (1270, 770),
    (1530, 1000),
    (390, 1000),
]
S_LOW_RANGE  = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
S_HIGH_RANGE = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
VEHICLE_CLASSES = [2, 7]  # COCO: 2=car, 7=truck
# ────────────────────────────────────────────────────────────────────────────


def load_gt(video_source: str, gt_path_str: str) -> dict:
    if gt_path_str:
        gt_path = Path(gt_path_str)
    else:
        gt_path = Path(video_source).parent / (Path(video_source).stem + "_gt.json")
    if not gt_path.exists():
        print(f"[WARN] GT ファイルが見つかりません: {gt_path}")
        return {"in": None, "out": None}
    return json.loads(gt_path.read_text())


def run_once(model: YOLO, video_source: str, roi_points, y_min: float, y_max: float,
             s_low: float, s_high: float) -> dict:
    # TODO(wandb連携・§4.2): 同一 YOLO インスタンスを persist=True で使い回しているため，
    #   前 run のトラック ID 状態が次 run に持ち越され run の独立性が崩れる．
    #   04_multi_video_mae.py の reset_or_reload_model() と同様に run 冒頭で
    #   トラッカー状態をリセットすること（本スクリプトへの適用は別途スコープ）．
    cap = cv2.VideoCapture(video_source)
    counter = Counter(s_low, s_high)
    frame_times = []

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        t0 = time.perf_counter()
        results = model.track(frame, persist=True, verbose=False, classes=VEHICLE_CLASSES)
        boxes = results[0].boxes
        if boxes.id is not None:
            for xyxy, tid in zip(boxes.xyxy.cpu().numpy(), boxes.id.cpu().numpy()):
                x1, _, x2, y2 = map(int, xyxy)
                cx, cy = (x1 + x2) / 2, float(y2)
                if not is_in_roi((cx, cy), roi_points):
                    continue
                counter.update(int(tid), calc_s(cy, y_min, y_max))
        frame_times.append((time.perf_counter() - t0) * 1000)

    cap.release()
    return {
        "count_in":      counter.count_in,
        "count_out":     counter.count_out,
        "elapsed_ms":    sum(frame_times),
        "mean_frame_ms": sum(frame_times) / len(frame_times) if frame_times else 0,
        "max_frame_ms":  max(frame_times) if frame_times else 0,
    }


def main() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path("data/outputs") / EXP_NAME if EXP_NAME else Path("data/outputs")
    out_dir = base / f"sweep_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "results.csv"

    gt = load_gt(VIDEO_SOURCE, GT_PATH)
    gt_in  = gt.get("in")
    gt_out = gt.get("out")

    y_min, y_max = get_roi_y_range(ROI_POINTS)
    model = YOLO("yolov8s.pt")

    total = len(S_LOW_RANGE) * len(S_HIGH_RANGE)
    done = 0
    rows = []

    for s_low in S_LOW_RANGE:
        for s_high in S_HIGH_RANGE:
            if s_low >= s_high:
                continue
            res = run_once(model, VIDEO_SOURCE, ROI_POINTS, y_min, y_max, s_low, s_high)
            count_error = None
            if gt_in is not None and gt_out is not None:
                count_error = abs(res["count_in"] - gt_in) + abs(res["count_out"] - gt_out)
            row = {
                "s_low":          s_low,
                "s_high":         s_high,
                "count_in":       res["count_in"],
                "count_out":      res["count_out"],
                "gt_in":          gt_in,
                "gt_out":         gt_out,
                "count_error":    count_error,
                "elapsed_ms":     res["elapsed_ms"],
                "mean_frame_ms":  res["mean_frame_ms"],
                "max_frame_ms":   res["max_frame_ms"],
            }
            rows.append(row)
            pd.DataFrame(rows).to_csv(csv_path, index=False)
            done += 1
            print(f"[{done}/{total}] s_low={s_low:.2f} s_high={s_high:.2f} "
                  f"IN={res['count_in']} OUT={res['count_out']} err={count_error}")

    print(f"\n出力: {csv_path}")


if __name__ == "__main__":
    main()
