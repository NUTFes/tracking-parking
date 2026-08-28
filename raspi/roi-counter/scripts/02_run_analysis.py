import json
import os
import platform
import sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))   # 既存: roi-counter/
sys.path.insert(0, str(Path(__file__).parents[2]))   # 追加: raspi/（common 共有のため）

import cv2
import pandas as pd
from ultralytics import YOLO

from src.counter import Counter
from src.events import EVENT_COLUMNS, build_event_rows
from src.roi import is_in_roi
from src.progress import get_progress_fn
from src.visualizer import draw_band_lines_for_method, draw_bbox_with_info, draw_counts, draw_roi

from common.wandb_logger import (
    ExperimentLogger,
    next_log_boundary,
    should_log_frame,
    validate_log_interval_sec,
)
from common.run_identity import (
    build_display_name,
    build_run_identity,
    collect_reproducibility_info,
    write_run_manifest,
)
from common.frame_stats import compute_timing_stats
from common.time_windows import frames_from_seconds
from common.frame_timing import (
    DEFAULT_WARMUP_FRAMES,
    TIMING_SCHEMA_VERSION,
    FrameTiming,
    build_comparison_key,
    elapsed_timer,
    model_synchronizer,
    require_measured_timings,
    resolve_model_device,
    sha256_file,
    validate_warmup_frames,
)

# ── パラメータ ──────────────────────────────────────────────────────────────
VIDEO_SOURCE: str | int = "data/inputs/1787014266.421887.mp4"
EXP_NAME = "diag_track_attribution"  # 空文字 → data/outputs/ 直下

# roi_setup/setup_roi.py で決めた新画角のROI（2026-08-26設定、5本共通）。
ROI_POINTS = [
    (577, 614),
    (1343, 612),
    (1615, 894),
    (252, 872),
]
S_LOW  = 0.26
S_HIGH = 0.32
# 時間窓は秒で持ち、動画のfpsからフレーム数へ変換する（common/time_windows.py）。
# フレーム数で直接持つと、同じ値が撮影fpsによって別の長さを意味してしまう。
CLEANUP_THRESHOLD_SEC = 5.0   # 旧既定の150フレームは30fpsで5秒
MAX_CANDIDATE_AGE_SEC = 10.0  # 旧既定の300フレームは30fpsで10秒
S_HISTORY_LIMIT = 300
VEHICLE_CLASSES = [2, 7]  # COCO: 2=car, 7=truck
MODEL_PATH = "yolov8s.pt"

# ── W&B 実験管理設定（すべて環境変数で上書き可）─────────────────────────────
USE_WANDB = os.getenv("USE_WANDB", "false").lower() == "true"
WANDB_PROJECT = os.getenv("WANDB_PROJECT", "tracking-parking")
EXP_DEVICE_NAME = os.getenv("EXP_DEVICE_NAME", platform.node())
EXP_DEVICE_ACCELERATOR = os.getenv("EXP_DEVICE_ACCELERATOR", "cpu")
# 台数推移は dataset 内の相対時間ベースでサンプリングする（既定 5 秒間隔）
LOG_INTERVAL_SEC = validate_log_interval_sec(os.getenv("LOG_INTERVAL_SEC", "5"))
# model.track に実際に渡す値のみを記録する（記録専用の乖離した定数を持たない）
YOLO_CONF = 0.25
YOLO_IOU = 0.7
YOLO_DEVICE = os.getenv("YOLO_DEVICE") or None  # 未指定は Ultralytics の自動選択に委ねる
YOLO_IMGSZ = int(os.getenv("YOLO_IMGSZ", "640"))
YOLO_TRACKER = os.getenv("YOLO_TRACKER", "botsort.yaml")
WARMUP_FRAMES = validate_warmup_frames(os.getenv("WARMUP_FRAMES", DEFAULT_WARMUP_FRAMES))
SAVE_VIDEO = os.getenv("SAVE_VIDEO", "true").lower() == "true"
SHOW_DISPLAY = os.getenv("SHOW_DISPLAY", "true").lower() == "true"
PROGRESS_METHOD = os.getenv("PROGRESS_METHOD", "edge_distance")
# ────────────────────────────────────────────────────────────────────────────

WEBCAM_FPS = 30.0


def resolve_output_dir(video_source: str | int, exp_name: str) -> Path:
    stem = Path(str(video_source)).stem if isinstance(video_source, str) else "webcam"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path("data/outputs") / exp_name if exp_name else Path("data/outputs")
    return base / f"{stem}_{ts}"


def build_state_metrics(counter: Counter, active_detections: int) -> dict[str, int]:
    """W&Bへ出す検出数、保持状態数、archive数をまとめる。"""
    return {
        "active_detections": active_detections,
        "retained_states": len(counter.tracks),
        "archived_events": len(counter.archive),
    }


def main() -> None:
    progress_fn = get_progress_fn(PROGRESS_METHOD)
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
    writer = None
    if SAVE_VIDEO:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(out_dir / "annotated.mp4"), fourcc, fps, (w, h))

    cleanup_threshold = frames_from_seconds(CLEANUP_THRESHOLD_SEC, fps)
    max_candidate_age = frames_from_seconds(MAX_CANDIDATE_AGE_SEC, fps)

    counter = Counter(
        S_LOW,
        S_HIGH,
        cleanup_threshold=cleanup_threshold,
        max_candidate_age=max_candidate_age,
        s_history_limit=S_HISTORY_LIMIT,
    )

    # ── W&B 初期化 ──────────────────────────────────────────────────────────
    input_type = "file" if isinstance(VIDEO_SOURCE, str) else "camera"
    dataset = Path(str(VIDEO_SOURCE)).stem if isinstance(VIDEO_SOURCE, str) else "webcam"
    exp_params = {"s_low": S_LOW, "s_high": S_HIGH, "progress_method": PROGRESS_METHOD}
    input_sha256 = sha256_file(str(VIDEO_SOURCE)) if isinstance(VIDEO_SOURCE, str) else None
    model_sha256 = sha256_file(MODEL_PATH)
    roi_points = [list(point) for point in ROI_POINTS]
    reproducibility = collect_reproducibility_info()
    config = {
        "logic_name": "roi_counter",
        "dataset": dataset,
        "input_type": input_type,
        "input_source": str(VIDEO_SOURCE),
        "device_name": EXP_DEVICE_NAME,
        "device_accelerator": EXP_DEVICE_ACCELERATOR,
        "model_path": MODEL_PATH,
        "input_sha256": input_sha256,
        "model_sha256": model_sha256,
        "roi_points": roi_points,
        "frame_width": w,
        "frame_height": h,
        "source_fps": float(fps),
        "vehicle_classes": VEHICLE_CLASSES,
        "tracker_reset": True,  # 02 は run 開始時に Counter を新規生成するため常に独立
        "log_interval_sec": LOG_INTERVAL_SEC,
        "yolo_conf": YOLO_CONF,
        "yolo_iou": YOLO_IOU,
        "yolo_device_requested": YOLO_DEVICE,
        "yolo_device": resolve_model_device(model, YOLO_DEVICE),
        "yolo_imgsz": YOLO_IMGSZ,
        "tracker_config": YOLO_TRACKER,
        "tracker_config_sha256": sha256_file(YOLO_TRACKER),
        "warmup_frames": WARMUP_FRAMES,
        "save_video": SAVE_VIDEO,
        "show_display": SHOW_DISPLAY,
        "timing_schema_version": TIMING_SCHEMA_VERSION,
        "s_low": S_LOW,
        "s_high": S_HIGH,
        "progress_method": PROGRESS_METHOD,
        "cleanup_threshold_sec": CLEANUP_THRESHOLD_SEC,
        "max_candidate_age_sec": MAX_CANDIDATE_AGE_SEC,
        "cleanup_threshold": cleanup_threshold,
        "max_candidate_age": max_candidate_age,
        "s_history_limit": S_HISTORY_LIMIT,
        **reproducibility,
    }
    config["comparison_key"] = build_comparison_key(config)
    condition = {
        key: config.get(key)
        for key in (
            "logic_name", "input_type", "input_sha256", "model_sha256", "roi_points",
            "vehicle_classes", "yolo_conf", "yolo_iou", "yolo_device", "yolo_imgsz",
            "tracker_config", "tracker_config_sha256", "device_name", "device_accelerator",
            "frame_width", "frame_height", "source_fps", "warmup_frames", "save_video",
            "show_display", "timing_schema_version", "s_low", "s_high",
            "progress_method",
            "cleanup_threshold", "max_candidate_age", "s_history_limit", "git_sha",
            "git_dirty", "git_dirty_fingerprint", "python_version", "library_versions",
        )
    }
    identity = build_run_identity(
        condition,
        display_name=build_display_name("roi_counter", dataset, exp_params),
    )
    config["condition"] = condition
    config.update(identity)
    config["exp_key"] = config["condition_key"]  # 旧データ利用箇所向けの互換alias

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
    logger.define_metric("net_flow", step_metric="t_rel_sec")

    timing_records: list[FrameTiming] = []
    frame_idx = 0
    num_tracks = 0
    exit_code = 0
    # 相対時間サンプリング用の状態
    next_log_sec = 0.0
    prev_count_in = 0
    prev_count_out = 0
    synchronize_model = model_synchronizer(model, YOLO_DEVICE)

    try:
        while cap.isOpened():
            with elapsed_timer() as end_to_end_timer:
                with elapsed_timer() as read_timer:
                    ret, frame = cap.read()
                read_ms = read_timer.elapsed_ms
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
                        xyxy_values = boxes.xyxy.cpu().numpy()
                        track_ids = boxes.id.cpu().numpy()
                        detections = list(zip(xyxy_values, track_ids))
                    num_tracks = len(detections)

                with elapsed_timer() as counting_timer:
                    for xyxy, tid in detections:
                        x1, y1, x2, y2 = map(int, xyxy)
                        cx, cy = (x1 + x2) / 2, float(y2)
                        if not is_in_roi((cx, cy), ROI_POINTS):
                            continue
                        s = progress_fn((cx, cy), ROI_POINTS)
                        track_id = int(tid)
                        counter.update(track_id, s, frame_idx)
                    counter.cleanup(frame_idx)

                quit_requested = False
                with elapsed_timer() as output_timer:
                    if writer is not None or SHOW_DISPLAY:
                        for xyxy, tid in detections:
                            x1, y1, x2, y2 = map(int, xyxy)
                            cx, cy = (x1 + x2) / 2, float(y2)
                            if not is_in_roi((cx, cy), ROI_POINTS):
                                continue
                            s = progress_fn((cx, cy), ROI_POINTS)
                            track_id = int(tid)
                            state = counter.tracks[track_id].state
                            draw_bbox_with_info(
                                frame, (x1, y1, x2, y2), track_id, s, state
                            )
                        draw_roi(frame, ROI_POINTS)
                        draw_band_lines_for_method(
                            frame, ROI_POINTS, S_LOW, S_HIGH, PROGRESS_METHOD
                        )
                        draw_counts(frame, counter.count_in, counter.count_out)
                    if writer is not None:
                        writer.write(frame)
                    if SHOW_DISPLAY:
                        cv2.imshow("02_run_analysis", frame)
                        quit_requested = cv2.waitKey(1) & 0xFF == ord("q")

            timing = FrameTiming(
                frame_index=frame_idx,
                read_ms=read_ms,
                inference_tracking_ms=inference_timer.elapsed_ms,
                counting_logic_ms=counting_timer.elapsed_ms,
                output_ms=output_timer.elapsed_ms,
                end_to_end_ms=end_to_end_timer.elapsed_ms,
                is_warmup=frame_idx < WARMUP_FRAMES,
            )
            timing_records.append(timing)

            # ── W&B 時系列ログ（相対時間ベース＋カウント変化時は必ず記録）──────
            t_rel_sec = frame_idx / fps if fps > 0 else 0.0
            count_changed = (
                counter.count_in != prev_count_in or counter.count_out != prev_count_out
            )
            if should_log_frame(t_rel_sec, next_log_sec, count_changed):
                logger.log_frame(
                    step=frame_idx,
                    metrics={
                        "t_rel_sec": t_rel_sec,
                        "net_flow": counter.count_in - counter.count_out,
                        "cumulative_in": counter.count_in,
                        "cumulative_out": counter.count_out,
                        "read_ms": timing.read_ms,
                        "inference_tracking_ms": timing.inference_tracking_ms,
                        "counting_logic_ms": timing.counting_logic_ms,
                        "core_ms": timing.core_ms,
                        "output_ms": timing.output_ms,
                        "end_to_end_ms": timing.end_to_end_ms,
                        "frame_ms": timing.core_ms,
                        "is_warmup": timing.is_warmup,
                        "num_tracks": num_tracks,
                        **build_state_metrics(counter, num_tracks),
                    },
                )
                # 次の定期サンプリング境界へ進める（変化ログで飛んでも間隔を維持）
                next_log_sec = next_log_boundary(next_log_sec, t_rel_sec, LOG_INTERVAL_SEC)
            prev_count_in = counter.count_in
            prev_count_out = counter.count_out

            frame_idx += 1
            if quit_requested:
                break

        cap.release()
        if writer is not None:
            writer.release()
        if SHOW_DISPLAY:
            cv2.destroyAllWindows()

        measured = require_measured_timings(timing_records)
        stats = compute_timing_stats(measured, float(fps))
        result = {
            "count_in":    counter.count_in,
            "count_out":   counter.count_out,
            "total_frames": frame_idx,
            "mean_frame_ms": stats["frame_ms_mean"],
            "max_frame_ms":  stats["frame_ms_max"],
            "total_ms":    stats["total_ms"],
            "timing_schema_version": TIMING_SCHEMA_VERSION,
            "warmup_frames": WARMUP_FRAMES,
            "measured_frames": len(measured),
            "s_low":  S_LOW,
            "s_high": S_HIGH,
            "progress_method": PROGRESS_METHOD,
            "cleanup_threshold_sec": CLEANUP_THRESHOLD_SEC,
            "max_candidate_age_sec": MAX_CANDIDATE_AGE_SEC,
            "cleanup_threshold": cleanup_threshold,
            "max_candidate_age": max_candidate_age,
            "s_history_limit": S_HISTORY_LIMIT,
            **build_state_metrics(counter, num_tracks),
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
        event_rows = build_event_rows(
            counter.get_all_tracks(),
            float(fps),
            WARMUP_FRAMES,
            archive=counter.get_archived_events(),
        )
        pd.DataFrame(event_rows, columns=list(EVENT_COLUMNS)).to_csv(
            out_dir / "events.csv", index=False
        )
        pd.DataFrame([record.to_dict() for record in timing_records]).to_csv(
            out_dir / "frames.csv", index=False
        )

        # ── W&B summary（速度統計＋台数）──────────────────────────────────────
        logger.set_summaries({
            "count_in": counter.count_in,
            "count_out": counter.count_out,
            "total_frames": frame_idx,
            "measured_frames": len(measured),
            **build_state_metrics(counter, num_tracks),
            **stats,
        })
        logger.save_run_id(out_dir)
        logger.append_to_result_json(out_dir / "result.json")
        output_paths = ["result.json", "vehicles.csv", "events.csv", "frames.csv"]
        if SAVE_VIDEO:
            output_paths.append("annotated.mp4")
        if USE_WANDB:
            output_paths.append("wandb_run_id.txt")
        write_run_manifest(
            out_dir / "run_manifest.json",
            config=config,
            output_dir=out_dir,
            output_paths=output_paths,
            wandb_run_id=logger.run_id,
        )

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
