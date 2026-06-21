"""
複数動画にわたるMAEを計算するスクリプト．
GT_DIR 配下の各 JSON（video・roi・in・out を含む）を読み込み，
PARAM_LIST の (s_low, s_high) ごとに全動画を処理してMAEを算出する．
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import cv2
import itertools
import pandas as pd
from ultralytics import YOLO

from src.counter import Counter
from src.roi import get_roi_y_range, is_in_roi
from src.progress import calc_s

# ── パラメータ ──────────────────────────────────────────────────────────────
GT_DIR   = "data/inputs/configs"   # 動画設定JSONのディレクトリ
EXP_NAME = "exp1_mae"

S_LOW_LIST  = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
S_HIGH_LIST = [0.60, 0.65]
VEHICLE_CLASSES = [2, 7]  # COCO: 2=car, 7=truck
# ────────────────────────────────────────────────────────────────────────────


def load_configs(gt_dir: str) -> list[dict]:
    configs = []
    for p in sorted(Path(gt_dir).glob("*.json")):
        cfg = json.loads(p.read_text())
        for key in ("video", "roi", "in", "out"):
            if key not in cfg:
                print(f"[WARN] {p.name} に '{key}' がありません．スキップします．")
                break
        else:
            configs.append(cfg)
    if not configs:
        print(f"[ERROR] {gt_dir} に有効なJSONが見つかりません")
        sys.exit(1)
    return configs


def run_once(model: YOLO, video_source: str, roi_points: list,
             s_low: float, s_high: float) -> dict:
    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened():
        print(f"[ERROR] 動画を開けません: {video_source}")
        return {"count_in": 0, "count_out": 0,
                "elapsed_ms": 0, "mean_frame_ms": 0, "max_frame_ms": 0}

    y_min, y_max = get_roi_y_range(roi_points)
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
    out_dir = base / f"mae_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    configs = load_configs(GT_DIR)
    param_list = list(itertools.product(S_LOW_LIST, S_HIGH_LIST))
    print(f"動画数: {len(configs)}  パラメータ組み合わせ: {len(param_list)}")

    model = YOLO("yolov8s.pt")
    detail_rows = []
    summary_rows = []

    for s_low, s_high in param_list:
        errors = []
        elapsed_list = []

        for cfg in configs:
            video  = cfg["video"]
            roi    = [tuple(p) for p in cfg["roi"]]
            gt_in  = cfg["in"]
            gt_out = cfg["out"]

            print(f"  [{s_low:.2f}/{s_high:.2f}] {Path(video).name} ...", end=" ", flush=True)
            res = run_once(model, video, roi, s_low, s_high)
            count_error = abs(res["count_in"] - gt_in) + abs(res["count_out"] - gt_out)
            errors.append(count_error)
            elapsed_list.append(res["elapsed_ms"])

            detail_rows.append({
                "s_low":          s_low,
                "s_high":         s_high,
                "video":          Path(video).name,
                "count_in":       res["count_in"],
                "count_out":      res["count_out"],
                "gt_in":          gt_in,
                "gt_out":         gt_out,
                "count_error":    count_error,
                "mean_frame_ms":  res["mean_frame_ms"],
                "max_frame_ms":   res["max_frame_ms"],
                "elapsed_ms":     res["elapsed_ms"],
            })
            print(f"IN={res['count_in']} OUT={res['count_out']} err={count_error}")

        mae = sum(errors) / len(errors)
        summary_rows.append({
            "s_low":            s_low,
            "s_high":           s_high,
            "mae":              mae,
            "mean_elapsed_ms":  sum(elapsed_list) / len(elapsed_list),
        })
        print(f"  → MAE={mae:.2f}\n")

        # 逐次書き込み
        pd.DataFrame(detail_rows).to_csv(out_dir / "results.csv", index=False)
        pd.DataFrame(summary_rows).to_csv(out_dir / "mae_summary.csv", index=False)

    print(f"出力: {out_dir}")


if __name__ == "__main__":
    main()
