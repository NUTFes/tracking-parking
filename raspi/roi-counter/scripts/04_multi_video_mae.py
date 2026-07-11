"""
複数動画にわたるMAEを計算するスクリプト．
GT_DIR 配下の各 JSON（video・roi・in・out を含む）を読み込み，
PARAM_LIST の (s_low, s_high) ごとに全動画を処理してMAEを算出する．

W&B 連携: (s_low, s_high, video) の組ごとに 1 run（config + summary のみ・時系列なし）．
"""
import json
import os
import platform
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))   # 既存: roi-counter/
sys.path.insert(0, str(Path(__file__).parents[2]))   # 追加: raspi/（common 共有のため）

import cv2
import itertools
import pandas as pd
from ultralytics import YOLO

from src.counter import Counter
from src.roi import get_roi_y_range, is_in_roi
from src.progress import calc_s

from common.wandb_logger import ExperimentLogger, build_exp_key
from common.frame_stats import compute_timing_stats
from common.frame_timing import (
    DEFAULT_WARMUP_FRAMES,
    TIMING_SCHEMA_VERSION,
    FrameTiming,
    build_comparison_key,
    elapsed_timer,
    model_synchronizer,
    require_measured_timings,
    sha256_file,
    validate_warmup_frames,
)

# ── パラメータ ──────────────────────────────────────────────────────────────
GT_DIR   = "data/inputs/configs"   # 動画設定JSONのディレクトリ
EXP_NAME = "exp1_mae"

S_LOW_LIST  = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
S_HIGH_LIST = [0.60, 0.65]
VEHICLE_CLASSES = [2, 7]  # COCO: 2=car, 7=truck
MODEL_PATH = "yolov8s.pt"

# ── W&B 実験管理設定（すべて環境変数で上書き可）─────────────────────────────
USE_WANDB = os.getenv("USE_WANDB", "false").lower() == "true"
WANDB_PROJECT = os.getenv("WANDB_PROJECT", "tracking-parking")
EXP_DEVICE_NAME = os.getenv("EXP_DEVICE_NAME", platform.node())
EXP_DEVICE_ACCELERATOR = os.getenv("EXP_DEVICE_ACCELERATOR", "cpu")
# model.track に実際に渡す値のみを記録する（記録専用の乖離した定数を持たない）
YOLO_CONF = 0.25
YOLO_IOU = 0.7
YOLO_DEVICE = os.getenv("YOLO_DEVICE") or None  # 未指定は Ultralytics の自動選択に委ねる
YOLO_IMGSZ = int(os.getenv("YOLO_IMGSZ", "640"))
YOLO_TRACKER = os.getenv("YOLO_TRACKER", "botsort.yaml")
WARMUP_FRAMES = validate_warmup_frames(os.getenv("WARMUP_FRAMES", DEFAULT_WARMUP_FRAMES))
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


def reset_or_reload_model(model: YOLO) -> tuple[YOLO, bool]:
    """run 間でトラッカー状態をリセットし，独立した run を保証する．

    現状は同一 YOLO インスタンスを persist=True で使い回すため，前 run のトラック
    ID 状態が次 run に持ち越される．これでは run が独立でなく W&B 上の比較が成立しない．

    優先順（§4.2）:
      1. model.predictor.trackers[*].reset()（ultralytics のバージョン依存のため hasattr で確認）
         初回 run では predictor 未生成＝持ち越し状態が無いので clean 扱い．
      2. reset 不可なら YOLO(MODEL_PATH) を再生成（ロード時間は増えるが正しさを優先）．

    Returns:
        (model, tracker_reset): 使用すべきモデルと，独立性を担保できたか．
    """
    predictor = getattr(model, "predictor", None)
    trackers = getattr(predictor, "trackers", None) if predictor is not None else None

    # 初回 run など持ち越し状態が無い場合は clean
    if not trackers:
        return model, True

    if all(hasattr(t, "reset") for t in trackers):
        for t in trackers:
            t.reset()
        return model, True

    # フォールバック: reset 不可なので再生成して独立性を保証
    print("[WARN] tracker.reset() が使えないため YOLO を再生成します")
    return YOLO(MODEL_PATH), True


def build_detail_row(s_low: float, s_high: float, video_name: str, res: dict,
                      gt_in: int, gt_out: int, count_error: int, stats: dict,
                      use_wandb: bool, wandb_run_id, exp_key: str) -> dict:
    """results.csv の1行を組み立てる。

    wandb_run_id / exp_key は use_wandb=True のときのみ追加する
    （USE_WANDB=false で W&B 導入前と同じ列構成を維持するため）。
    """
    row = {
        "s_low":          s_low,
        "s_high":         s_high,
        "video":          video_name,
        "count_in":       res["count_in"],
        "count_out":      res["count_out"],
        "gt_in":          gt_in,
        "gt_out":         gt_out,
        "count_error":    count_error,
        "mean_frame_ms":  stats["frame_ms_mean"],
        "max_frame_ms":   stats["frame_ms_max"],
        "elapsed_ms":     stats["total_ms"],
    }
    if use_wandb:
        row["wandb_run_id"] = wandb_run_id
        row["exp_key"] = exp_key
    return row


def run_once(model: YOLO, video_source: str, roi_points: list,
             s_low: float, s_high: float) -> dict:
    # run 冒頭でトラッカー状態をリセット（前 run のトラック ID を持ち越さない）
    model, tracker_reset = reset_or_reload_model(model)

    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened():
        print(f"[ERROR] 動画を開けません: {video_source}")
        return {"count_in": 0, "count_out": 0, "total_frames": 0,
                "frame_times": [], "tracker_reset": tracker_reset,
                "timings": [],
                "frame_width": 0, "frame_height": 0, "source_fps": 0.0}

    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    y_min, y_max = get_roi_y_range(roi_points)
    counter = Counter(s_low, s_high)
    timing_records: list[FrameTiming] = []
    frame_idx = 0
    synchronize_model = model_synchronizer(model, YOLO_DEVICE)

    while cap.isOpened():
        with elapsed_timer() as end_to_end_timer:
            with elapsed_timer() as read_timer:
                ret, frame = cap.read()
            if not ret:
                break

            with elapsed_timer(synchronize_model) as inference_timer:
                results = model.track(
                    frame, persist=True, verbose=False, classes=VEHICLE_CLASSES,
                    conf=YOLO_CONF, iou=YOLO_IOU, device=YOLO_DEVICE,
                    imgsz=YOLO_IMGSZ, tracker=YOLO_TRACKER,
                )
                boxes = results[0].boxes
                if boxes.id is None:
                    detections = []
                else:
                    detections = list(zip(
                        boxes.xyxy.cpu().numpy(), boxes.id.cpu().numpy()
                    ))

            with elapsed_timer() as counting_timer:
                for xyxy, tid in detections:
                    x1, _, x2, y2 = map(int, xyxy)
                    cx, cy = (x1 + x2) / 2, float(y2)
                    if not is_in_roi((cx, cy), roi_points):
                        continue
                    counter.update(int(tid), calc_s(cy, y_min, y_max))

        timing_records.append(FrameTiming(
            frame_index=frame_idx,
            read_ms=read_timer.elapsed_ms,
            inference_tracking_ms=inference_timer.elapsed_ms,
            counting_logic_ms=counting_timer.elapsed_ms,
            output_ms=0.0,
            end_to_end_ms=end_to_end_timer.elapsed_ms,
            is_warmup=frame_idx < WARMUP_FRAMES,
        ))
        frame_idx += 1

    cap.release()
    frame_times = [timing.core_ms for timing in timing_records]
    return {
        "count_in":      counter.count_in,
        "count_out":     counter.count_out,
        "total_frames":  frame_idx,
        "frame_times":   frame_times,
        "timings":       timing_records,
        "tracker_reset": tracker_reset,
        "frame_width":   w,
        "frame_height":  h,
        "source_fps":    float(fps),
    }


def main() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path("data/outputs") / EXP_NAME if EXP_NAME else Path("data/outputs")
    out_dir = base / f"mae_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    configs = load_configs(GT_DIR)
    param_list = list(itertools.product(S_LOW_LIST, S_HIGH_LIST))
    print(f"動画数: {len(configs)}  パラメータ組み合わせ: {len(param_list)}")

    model = YOLO(MODEL_PATH)
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
            if not res["tracker_reset"]:
                print("[WARN] トラッカー状態をリセットできませんでした（run 独立性に注意）")
            count_error = abs(res["count_in"] - gt_in) + abs(res["count_out"] - gt_out)
            errors.append(count_error)
            measured = require_measured_timings(res["timings"])
            stats = compute_timing_stats(measured, res["source_fps"])
            elapsed_list.append(stats["core_ms_total"])

            # ── W&B: (s_low, s_high, video) の組ごとに 1 run（config + summary のみ）──
            dataset = Path(video).stem
            exp_params = {"s_low": s_low, "s_high": s_high}
            config = {
                "logic_name": "roi_counter",
                "dataset": dataset,
                "input_type": "file",
                "device_name": EXP_DEVICE_NAME,
                "device_accelerator": EXP_DEVICE_ACCELERATOR,
                "model_path": MODEL_PATH,
                "input_sha256": sha256_file(video),
                "model_sha256": sha256_file(MODEL_PATH),
                "frame_width": res["frame_width"],
                "frame_height": res["frame_height"],
                "source_fps": res["source_fps"],
                "vehicle_classes": VEHICLE_CLASSES,
                "tracker_reset": res["tracker_reset"],
                "yolo_conf": YOLO_CONF,
                "yolo_iou": YOLO_IOU,
                "yolo_device": YOLO_DEVICE,
                "yolo_imgsz": YOLO_IMGSZ,
                "tracker_config": YOLO_TRACKER,
                "warmup_frames": WARMUP_FRAMES,
                "save_video": False,
                "show_display": False,
                "timing_schema_version": TIMING_SCHEMA_VERSION,
                "s_low": s_low,
                "s_high": s_high,
            }
            config["comparison_key"] = build_comparison_key(config)
            config["exp_key"] = build_exp_key("roi_counter", dataset, EXP_DEVICE_NAME, exp_params)

            logger = ExperimentLogger(
                project=WANDB_PROJECT,
                config=config,
                group="roi_counter",
                job_type="speed_eval",
                tags=[EXP_DEVICE_NAME, "file"],
                enabled=USE_WANDB,
            )
            run_exit_code = 0
            try:
                logger.init_accuracy_placeholders()
                logger.set_summaries({
                    "count_in": res["count_in"],
                    "count_out": res["count_out"],
                    "total_frames": res["total_frames"],
                    "measured_frames": len(measured),
                    "count_error": count_error,
                    "gt_in": gt_in,
                    "gt_out": gt_out,
                    **stats,
                })
            except BaseException:
                run_exit_code = 1
                raise
            finally:
                logger.finish(exit_code=run_exit_code)

            detail_rows.append(build_detail_row(
                s_low, s_high, Path(video).name, res, gt_in, gt_out, count_error,
                stats, USE_WANDB, logger.run_id, config["exp_key"],
            ))
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
