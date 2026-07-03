import json
import os
import platform
import sys
import time
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))   # 既存: roi-counter/
sys.path.insert(0, str(Path(__file__).parents[2]))   # 追加: raspi/（common 共有のため）

import cv2
import pandas as pd
from ultralytics import YOLO

from src.counter import Counter
from src.roi import get_roi_y_range, is_in_roi
from src.progress import calc_s
from src.visualizer import draw_band_lines, draw_bbox_with_info, draw_counts, draw_roi

from common.wandb_logger import ExperimentLogger, build_exp_key
from common.frame_stats import compute_frame_stats

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
MODEL_PATH = "yolov8s.pt"

# ── W&B 実験管理設定（すべて環境変数で上書き可）─────────────────────────────
USE_WANDB = os.getenv("USE_WANDB", "false").lower() == "true"
WANDB_PROJECT = os.getenv("WANDB_PROJECT", "tracking-parking")
EXP_DEVICE_NAME = os.getenv("EXP_DEVICE_NAME", platform.node())
EXP_DEVICE_ACCELERATOR = os.getenv("EXP_DEVICE_ACCELERATOR", "cpu")
# 台数推移は dataset 内の相対時間ベースでサンプリングする（既定 5 秒間隔）
LOG_INTERVAL_SEC = float(os.getenv("LOG_INTERVAL_SEC", "5"))
# roi-counter は model.track で conf/iou を指定していないため既定値を明示記録する
YOLO_CONF = 0.25
YOLO_IOU = 0.7
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

    model = YOLO(MODEL_PATH)
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

    # ── W&B 初期化 ──────────────────────────────────────────────────────────
    input_type = "file" if isinstance(VIDEO_SOURCE, str) else "camera"
    dataset = Path(str(VIDEO_SOURCE)).stem if isinstance(VIDEO_SOURCE, str) else "webcam"
    exp_params = {"s_low": S_LOW, "s_high": S_HIGH}
    config = {
        "logic_name": "roi_counter",
        "dataset": dataset,
        "input_type": input_type,
        "device_name": EXP_DEVICE_NAME,
        "device_accelerator": EXP_DEVICE_ACCELERATOR,
        "model_path": MODEL_PATH,
        "frame_width": w,
        "frame_height": h,
        "source_fps": float(fps),
        "vehicle_classes": VEHICLE_CLASSES,
        "tracker_reset": True,  # 02 は run 開始時に Counter を新規生成するため常に独立
        "log_interval_sec": LOG_INTERVAL_SEC,
        "yolo_conf": YOLO_CONF,
        "yolo_iou": YOLO_IOU,
        "s_low": S_LOW,
        "s_high": S_HIGH,
    }
    config["exp_key"] = build_exp_key("roi_counter", dataset, EXP_DEVICE_NAME, exp_params)

    logger = ExperimentLogger(
        project=WANDB_PROJECT,
        config=config,
        group="roi_counter",
        job_type="speed_eval",
        tags=[EXP_DEVICE_NAME, input_type],
        enabled=USE_WANDB,
    )
    logger.init_accuracy_placeholders()
    # 台数推移の x 軸を相対経過秒にする
    logger.define_metric("current_parked", step_metric="t_rel_sec")

    frame_records = []
    frame_idx = 0
    exit_code = 0
    # 相対時間サンプリング用の状態
    next_log_sec = 0.0
    prev_count_in = 0
    prev_count_out = 0

    try:
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

            # ── W&B 時系列ログ（相対時間ベース＋カウント変化時は必ず記録）──────
            t_rel_sec = frame_idx / fps if fps > 0 else 0.0
            count_changed = (
                counter.count_in != prev_count_in or counter.count_out != prev_count_out
            )
            if t_rel_sec >= next_log_sec or count_changed:
                logger.log_frame(
                    step=frame_idx,
                    metrics={
                        "t_rel_sec": t_rel_sec,
                        "current_parked": counter.count_in - counter.count_out,
                        "cumulative_in": counter.count_in,
                        "cumulative_out": counter.count_out,
                        "frame_ms": frame_ms,
                    },
                )
                # 次の定期サンプリング境界へ進める（変化ログで飛んでも間隔を維持）
                while next_log_sec <= t_rel_sec:
                    next_log_sec += LOG_INTERVAL_SEC
            prev_count_in = counter.count_in
            prev_count_out = counter.count_out

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
        stats = compute_frame_stats(frame_ms_list, float(fps))
        result = {
            "count_in":    counter.count_in,
            "count_out":   counter.count_out,
            "total_frames": frame_idx,
            "mean_frame_ms": stats["frame_ms_mean"],
            "max_frame_ms":  stats["frame_ms_max"],
            "total_ms":    stats["total_ms"],
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

        # ── W&B summary（速度統計＋台数）──────────────────────────────────────
        logger.set_summaries({
            "count_in": counter.count_in,
            "count_out": counter.count_out,
            "total_frames": frame_idx,
            **stats,
        })
        logger.save_run_id(out_dir)
        logger.append_to_result_json(out_dir / "result.json")

        print(f"入庫: {counter.count_in}  出庫: {counter.count_out}")
        print(f"出力: {out_dir}")

    except BaseException:
        # 例外・KeyboardInterrupt でも run を finish（exit_code=1）
        exit_code = 1
        raise
    finally:
        logger.finish(exit_code=exit_code)


if __name__ == "__main__":
    main()
