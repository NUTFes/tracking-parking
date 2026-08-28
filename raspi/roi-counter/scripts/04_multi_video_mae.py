"""
複数動画にわたるMAEを計算するスクリプト．
GT_DIR 配下の各 JSON（video・roi・in・out を含む）を読み込み，
PARAM_LIST の (s_low, s_high) ごとに全動画を処理してMAEを算出する．

W&B 連携: (s_low, s_high, video) の組ごとに 1 run（config + summary のみ・時系列なし）．

動画1本ぶんのYOLO推論は build_detection_trace() でs_low/s_high全組み合わせに対して
1回だけ実行し、閾値ごとのカウントロジックは replay_counts() がそのキャッシュを
再生する（検出結果はs_low/s_highに一切依存しないため）。
"""
import json
import os
import platform
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
sys.path.insert(0, str(Path(__file__).parents[1]))   # 既存: roi-counter/
sys.path.insert(0, str(Path(__file__).parents[2]))   # 追加: raspi/（common 共有のため）

import cv2
import itertools
import pandas as pd
from ultralytics import YOLO

from src.counter import Counter
from src.events import EVENT_COLUMNS, build_event_rows
from src.progress import get_progress_fn
from src.progress_diagnostics import (
    build_progress_diagnostics,
    snapshot_in_candidate_tracks,
)
from src.roi import is_in_roi
from src.tracker_lifecycle import prepare_model_for_run

from common.wandb_logger import ExperimentLogger
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
from common.ground_truth import load_ground_truth

def parse_float_list(raw: str | None, default: list[float], *, source: str) -> list[float]:
    """カンマ区切りの閾値リストを環境変数から読む。未設定・空文字なら default を返す。

    各要素は 0.0〜1.0 の範囲の有限な数値である必要がある（比較実験の条件を
    誤って壊さないよう、不正値は起動時に ValueError で明示的に拒否する）。
    """
    if raw is None or raw.strip() == "":
        return default
    values = []
    for item in raw.split(","):
        item = item.strip()
        if item == "":
            raise ValueError(f"{source} に空の要素が含まれています: {raw!r}")
        try:
            value = float(item)
        except ValueError as exc:
            raise ValueError(f"{source} の要素が数値として解釈できません: {item!r}") from exc
        if not (0.0 <= value <= 1.0) or value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"{source} の要素は0.0〜1.0の範囲である必要があります: {value!r}")
        values.append(value)
    return values


# ── パラメータ ──────────────────────────────────────────────────────────────
GT_DIR   = "data/inputs/configs"   # 動画設定JSONのディレクトリ
EXP_NAME = os.getenv("EXP_NAME", "exp1_mae")

S_LOW_LIST  = parse_float_list(
    os.getenv("S_LOW_LIST"),
    [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45],
    source="S_LOW_LIST",
)
S_HIGH_LIST = parse_float_list(
    os.getenv("S_HIGH_LIST"),
    [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95],
    source="S_HIGH_LIST",
)
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
# model.track に実際に渡す値のみを記録する（記録専用の乖離した定数を持たない）
YOLO_CONF = 0.25
YOLO_IOU = 0.7
YOLO_DEVICE = os.getenv("YOLO_DEVICE") or None  # 未指定は Ultralytics の自動選択に委ねる
YOLO_IMGSZ = int(os.getenv("YOLO_IMGSZ", "640"))
YOLO_TRACKER = os.getenv("YOLO_TRACKER", "botsort.yaml")
WARMUP_FRAMES = validate_warmup_frames(os.getenv("WARMUP_FRAMES", DEFAULT_WARMUP_FRAMES))
PROGRESS_METHOD = os.getenv("PROGRESS_METHOD", "edge_distance")
# ────────────────────────────────────────────────────────────────────────────

SWEEP_CONDITION_KEYS = (
    "logic_name", "input_type", "input_sha256", "model_sha256", "roi_points",
    "ground_truth_sha256", "gt_in", "gt_out", "vehicle_classes", "yolo_conf",
    "yolo_iou", "yolo_device", "yolo_imgsz", "tracker_config",
    "tracker_config_sha256", "tracker_reset", "ultralytics_version", "device_name",
    "device_accelerator", "frame_width", "frame_height", "source_fps",
    "warmup_frames", "save_video", "show_display", "timing_schema_version",
    "s_low", "s_high", "cleanup_threshold", "max_candidate_age", "s_history_limit",
    "progress_method",
    "git_sha", "git_dirty", "git_dirty_fingerprint",
    "python_version", "library_versions",
)

EVENT_CSV_COLUMNS = ("s_low", "s_high", "video", *EVENT_COLUMNS)


def load_configs(gt_dir: str) -> list[dict]:
    configs = []
    for p in sorted(Path(gt_dir).glob("*.json")):
        raw = json.loads(p.read_text())
        if "video" not in raw or "roi" not in raw:
            print(f"[WARN] {p.name} に 'video' または 'roi' がありません．スキップします．")
            continue
        try:
            gt = load_ground_truth(raw["video"], explicit_path=str(p))
        except (ValueError, FileNotFoundError) as exc:
            print(f"[WARN] {p.name} の読み込みに失敗しました．スキップします： {exc}")
            continue
        if gt.gt_in is None or gt.gt_out is None:
            print(f"[WARN] {p.name} に 'in' または 'out' がありません．スキップします．")
            continue
        cfg = dict(raw)
        cfg["in"] = gt.gt_in
        cfg["out"] = gt.gt_out
        cfg["_config_path"] = gt.path
        cfg["_config_sha256"] = gt.sha256
        cfg["_gt"] = gt
        configs.append(cfg)
    if not configs:
        print(f"[ERROR] {gt_dir} に有効なJSONが見つかりません")
        sys.exit(1)
    return configs


def build_sweep_condition(config: dict) -> dict:
    """結果へ影響する条件を抽出する。

    tracker_reset_method は clean_start / tracker_reset / model_reload のように
    実行順や内部API対応状況で変わる実行時情報なので、condition_keyには含めない。
    成否を示す tracker_reset は、不正なrunとの区別のため条件に含める。
    detection_cached/detection_cache_id も同じ理由（実行方法を示す情報であり
    結果に影響する条件ではない）で条件キーには含めない。
    """
    return {key: config.get(key) for key in SWEEP_CONDITION_KEYS}


def build_detail_row(s_low: float, s_high: float, video_name: str, res: dict,
                      gt_in: int, gt_out: int, count_error: int, stats: dict,
                      use_wandb: bool, wandb_run_id, execution_id: str,
                      condition_key: str, exp_key: str) -> dict:
    """results.csv の1行を組み立てる。

    W&Bとの突合列は use_wandb=True のときのみ追加する
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
        "tracker_reset":        res["tracker_reset"],
        "tracker_reset_method": res["tracker_reset_method"],
        "ultralytics_version":  res["ultralytics_version"],
    }
    if use_wandb:
        row["wandb_run_id"] = wandb_run_id
        row["execution_id"] = execution_id
        row["condition_key"] = condition_key
        row["exp_key"] = exp_key
    return row


def empty_run_result() -> dict:
    """動画が開けない場合に返す、下流の全キーを満たす空の結果。"""
    return {
        "count_in": 0, "count_out": 0, "total_frames": 0,
        "frame_times": [],
        "timings": [],
        "events": [],
        "frame_width": 0, "frame_height": 0, "source_fps": 0.0,
        "cleanup_threshold": 0,
        "max_candidate_age": 0,
        "active_detections": 0,
        "retained_states": 0,
        "archived_events": 0,
        "total_track_instances": 0,
        "progress_method": PROGRESS_METHOD,
        "diagnostics": {},
    }


@dataclass(frozen=True)
class CachedFrame:
    """1フレームぶんの生の検出結果とread/inferenceタイミング。

    s_low/s_high/ROI/progress_methodのいずれにも依存しない
    （これらに依存する処理はreplay_counts側で行う）。
    """

    frame_index: int
    detections: list[tuple[Any, float]]  # (xyxy, track_id)
    read_ms: float
    inference_tracking_ms: float
    is_warmup: bool


@dataclass(frozen=True)
class DetectionTrace:
    """動画1本ぶんのYOLO推論結果をキャッシュしたもの。

    build_detection_trace()が動画を1周する間に1回だけ構築し、
    以降のs_low/s_highスイープではreplay_counts()がこれを繰り返し再生する。
    """

    frame_width: int
    frame_height: int
    source_fps: float
    frames: list[CachedFrame]
    active_detections: int


def build_detection_trace(model: YOLO, video_source: str) -> DetectionTrace | None:
    """動画1本ぶんYOLO推論を1回だけ実行し、フレームごとの生の検出結果と
    read/inferenceタイミングをキャッシュする。

    is_in_roi判定・進行度計算・Counter更新は一切行わない
    （s_low/s_high/ROI/progress_methodのいずれにも依存しないため）。
    動画を開けない場合はNoneを返す。
    """
    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened():
        print(f"[ERROR] 動画を開けません: {video_source}")
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    if fps <= 0:
        # 時間窓（cleanup / candidate age）をフレーム数へ変換できないため、
        # 窓の長さが不定のまま計測することになる。動画を開けない場合と同じ扱いにする。
        print(f"[ERROR] fpsを取得できません: {video_source}")
        cap.release()
        return None
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    synchronize_model = model_synchronizer(model, YOLO_DEVICE)

    frames: list[CachedFrame] = []
    max_active_detections = 0
    frame_idx = 0

    while cap.isOpened():
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
            max_active_detections = max(max_active_detections, len(detections))

        frames.append(CachedFrame(
            frame_index=frame_idx,
            detections=detections,
            read_ms=read_timer.elapsed_ms,
            inference_tracking_ms=inference_timer.elapsed_ms,
            is_warmup=frame_idx < WARMUP_FRAMES,
        ))
        frame_idx += 1

    cap.release()
    return DetectionTrace(
        frame_width=w,
        frame_height=h,
        source_fps=float(fps),
        frames=frames,
        active_detections=max_active_detections,
    )


def replay_counts(
    trace: DetectionTrace, roi_points: list, progress_method: str,
    s_low: float, s_high: float,
) -> dict:
    """キャッシュ済みDetectionTraceから、指定の閾値・進行度方式でCounterを
    1回分だけ再生する。YOLO推論は一切行わない。返り値のキー構成は
    リファクタ前のrun_once()と同一。

    FrameTimingのread_ms/inference_tracking_msはCachedFrameの実測値を
    そのままコピーする（同一DetectionTraceを共有する全閾値runで同一値になる）。
    counting_logic_msだけがこの呼び出しごとに新規に計測される。
    end_to_end_msはinference_tracking_ms + counting_logic_msとして再構成する
    （core_msの定義（common/frame_timing.py）と一致させ、frame_times/
    compute_timing_statsの意味をリファクタ前後で変えないため。
    read+inference+countingを1本のwall-clockで測るという元の定義は、
    read/inferenceが別呼び出しで既に終わっているため再現できない）。
    """
    progress_fn = get_progress_fn(progress_method)
    cleanup_threshold = frames_from_seconds(CLEANUP_THRESHOLD_SEC, trace.source_fps)
    max_candidate_age = frames_from_seconds(MAX_CANDIDATE_AGE_SEC, trace.source_fps)
    counter = Counter(
        s_low,
        s_high,
        cleanup_threshold=cleanup_threshold,
        max_candidate_age=max_candidate_age,
        s_history_limit=S_HISTORY_LIMIT,
    )
    timing_records: list[FrameTiming] = []
    candidate_snapshots = {}

    for cached_frame in trace.frames:
        with elapsed_timer() as counting_timer:
            for xyxy, tid in cached_frame.detections:
                x1, _, x2, y2 = map(int, xyxy)
                cx, cy = (x1 + x2) / 2, float(y2)
                if not is_in_roi((cx, cy), roi_points):
                    continue
                counter.update(
                    int(tid), progress_fn((cx, cy), roi_points), cached_frame.frame_index
                )
            for track in counter.tracks.values():
                key = (track.track_id, track.first_seen_frame)
                if track.counted_as is not None:
                    candidate_snapshots.pop(key, None)
            candidate_snapshots.update(
                snapshot_in_candidate_tracks(counter.tracks.values())
            )
            counter.cleanup(cached_frame.frame_index)

        timing_records.append(FrameTiming(
            frame_index=cached_frame.frame_index,
            read_ms=cached_frame.read_ms,
            inference_tracking_ms=cached_frame.inference_tracking_ms,
            counting_logic_ms=counting_timer.elapsed_ms,
            output_ms=0.0,
            end_to_end_ms=cached_frame.inference_tracking_ms + counting_timer.elapsed_ms,
            is_warmup=cached_frame.is_warmup,
        ))

    frame_times = [timing.core_ms for timing in timing_records]
    events = build_event_rows(
        counter.get_all_tracks(),
        trace.source_fps,
        WARMUP_FRAMES,
        archive=counter.get_archived_events(),
    )
    diagnostics = build_progress_diagnostics(
        counter.get_all_tracks(),
        counter.get_archived_events(),
        total_track_instances=counter.total_track_instances,
        count_in=counter.count_in,
        count_out=counter.count_out,
        in_candidate_tracks=candidate_snapshots.values(),
    )
    if len(events) != counter.count_in + counter.count_out:
        raise ValueError(
            "イベント行数とカウント値が一致しません: "
            f"events={len(events)}, counts={counter.count_in + counter.count_out}"
        )
    return {
        "count_in":      counter.count_in,
        "count_out":     counter.count_out,
        "total_frames":  len(trace.frames),
        "frame_times":   frame_times,
        "timings":       timing_records,
        "events":        events,
        "frame_width":   trace.frame_width,
        "frame_height":  trace.frame_height,
        "source_fps":    trace.source_fps,
        "cleanup_threshold": cleanup_threshold,
        "max_candidate_age": max_candidate_age,
        "active_detections": trace.active_detections,
        "retained_states": len(counter.tracks),
        "archived_events": len(counter.archive),
        "total_track_instances": counter.total_track_instances,
        "progress_method": progress_method,
        "diagnostics": diagnostics,
    }


def main() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path("data/outputs") / EXP_NAME if EXP_NAME else Path("data/outputs")
    out_dir = base / f"mae_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    configs = load_configs(GT_DIR)
    param_list = list(itertools.product(S_LOW_LIST, S_HIGH_LIST))
    invalid_pairs = [(lo, hi) for lo, hi in param_list if lo >= hi]
    if invalid_pairs:
        raise ValueError(
            f"s_low は s_high より小さい必要があります（不正な組み合わせ: {invalid_pairs}）"
        )
    print(f"動画数: {len(configs)}  パラメータ組み合わせ: {len(param_list)}")

    model = YOLO(MODEL_PATH)
    model_sha256 = sha256_file(MODEL_PATH)
    tracker_config_sha256 = sha256_file(YOLO_TRACKER)
    reproducibility = collect_reproducibility_info()
    detail_rows = []
    event_rows = []
    errors_by_params: dict[tuple[float, float], list[int]] = {p: [] for p in param_list}
    elapsed_by_params: dict[tuple[float, float], list[float]] = {p: [] for p in param_list}

    for cfg in configs:
        video  = cfg["video"]
        roi    = [tuple(p) for p in cfg["roi"]]
        gt_in  = cfg["in"]
        gt_out = cfg["out"]

        print(f"  検出中: {Path(video).name} ...", end=" ", flush=True)
        reset_result = prepare_model_for_run(model, MODEL_PATH)
        model = reset_result.model
        trace = build_detection_trace(model, video)
        detection_cache_id = uuid.uuid4().hex
        print("done" if trace is not None else "動画を開けません")

        for s_low, s_high in param_list:
            res = (
                replay_counts(trace, roi, PROGRESS_METHOD, s_low, s_high)
                if trace is not None else empty_run_result()
            )
            res.update({
                "tracker_reset": reset_result.succeeded,
                "tracker_reset_method": reset_result.method,
                "ultralytics_version": reset_result.ultralytics_version,
            })
            count_error = abs(res["count_in"] - gt_in) + abs(res["count_out"] - gt_out)
            measured = require_measured_timings(res["timings"])
            stats = compute_timing_stats(measured, res["source_fps"])
            errors_by_params[(s_low, s_high)].append(count_error)
            elapsed_by_params[(s_low, s_high)].append(stats["core_ms_total"])

            # ── W&B: (s_low, s_high, video) の組ごとに 1 run（config + summary のみ）──
            dataset = Path(video).stem
            exp_params = {
                "s_low": s_low,
                "s_high": s_high,
                "progress_method": PROGRESS_METHOD,
            }
            config = {
                "logic_name": "roi_counter",
                "dataset": dataset,
                "input_type": "file",
                "input_source": video,
                "device_name": EXP_DEVICE_NAME,
                "device_accelerator": EXP_DEVICE_ACCELERATOR,
                "model_path": MODEL_PATH,
                "input_sha256": sha256_file(video),
                "model_sha256": model_sha256,
                "roi_points": [list(point) for point in roi],
                "ground_truth_config": cfg["_config_path"],
                "ground_truth_sha256": cfg["_config_sha256"],
                "gt_in": gt_in,
                "gt_out": gt_out,
                "frame_width": res["frame_width"],
                "frame_height": res["frame_height"],
                "source_fps": res["source_fps"],
                "vehicle_classes": VEHICLE_CLASSES,
                "tracker_reset": res["tracker_reset"],
                "tracker_reset_method": res["tracker_reset_method"],
                "ultralytics_version": res["ultralytics_version"],
                "yolo_conf": YOLO_CONF,
                "yolo_iou": YOLO_IOU,
                "yolo_device_requested": YOLO_DEVICE,
                "yolo_device": resolve_model_device(model, YOLO_DEVICE),
                "yolo_imgsz": YOLO_IMGSZ,
                "tracker_config": YOLO_TRACKER,
                "tracker_config_sha256": tracker_config_sha256,
                "warmup_frames": WARMUP_FRAMES,
                "save_video": False,
                "show_display": False,
                "timing_schema_version": TIMING_SCHEMA_VERSION,
                "s_low": s_low,
                "s_high": s_high,
                "progress_method": PROGRESS_METHOD,
                "cleanup_threshold_sec": CLEANUP_THRESHOLD_SEC,
                "max_candidate_age_sec": MAX_CANDIDATE_AGE_SEC,
                "cleanup_threshold": res["cleanup_threshold"],
                "max_candidate_age": res["max_candidate_age"],
                "s_history_limit": S_HISTORY_LIMIT,
                "detection_cached": True,
                "detection_cache_id": detection_cache_id,
                **reproducibility,
            }
            config["comparison_key"] = build_comparison_key(config)
            condition = build_sweep_condition(config)
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
                    "active_detections": res["active_detections"],
                    "retained_states": res["retained_states"],
                    "archived_events": res["archived_events"],
                    "total_track_instances": res["total_track_instances"],
                    "counted_track_instances": res["diagnostics"]["counted_track_instances"],
                    "in_candidate_stuck_count": res["diagnostics"]["in_candidate_stuck_count"],
                    "in_candidate_s_max_min": res["diagnostics"]["s_max_summary"]["min"],
                    "in_candidate_s_max_median": res["diagnostics"]["s_max_summary"]["median"],
                    "in_candidate_s_max_mean": res["diagnostics"]["s_max_summary"]["mean"],
                    "in_candidate_s_max_max": res["diagnostics"]["s_max_summary"]["max"],
                    **stats,
                })
            except BaseException:
                run_exit_code = 1
                raise
            finally:
                logger.finish(exit_code=run_exit_code)

            detail_rows.append(build_detail_row(
                s_low, s_high, Path(video).name, res, gt_in, gt_out, count_error,
                stats, USE_WANDB, logger.run_id, config["execution_id"],
                config["condition_key"], config["exp_key"],
            ))
            event_rows.extend(
                {"s_low": s_low, "s_high": s_high, "video": Path(video).name, **row}
                for row in res["events"]
            )
            write_run_manifest(
                out_dir / "manifests" / f"{config['execution_id']}.json",
                config=config,
                output_dir=out_dir,
                output_paths=[
                    "results.csv", "mae_summary.csv", "events.csv",
                    f"diagnostics/{config['execution_id']}.json",
                    f"diagnostics/{config['execution_id']}.csv",
                ],
                wandb_run_id=logger.run_id,
            )
            diagnostics_dir = out_dir / "diagnostics"
            diagnostics_dir.mkdir(parents=True, exist_ok=True)
            diagnostics_path = diagnostics_dir / f"{config['execution_id']}.json"
            diagnostics_path.write_text(
                json.dumps(res["diagnostics"], indent=2, ensure_ascii=False)
            )
            pd.DataFrame(res["diagnostics"]["in_candidate_tracks"]).to_csv(
                diagnostics_dir / f"{config['execution_id']}.csv", index=False
            )
            print(f"  [{s_low:.2f}/{s_high:.2f}] IN={res['count_in']} OUT={res['count_out']} "
                  f"err={count_error} reset={res['tracker_reset_method']}")

        # results.csv / events.csv は動画ごとに逐次書き込み（各行は書いた時点で確定値）
        pd.DataFrame(detail_rows).to_csv(out_dir / "results.csv", index=False)
        pd.DataFrame(event_rows, columns=list(EVENT_CSV_COLUMNS)).to_csv(
            out_dir / "events.csv", index=False
        )
        print()

    # mae_summary.csv は全動画処理後に1回だけ書く。動画外側ループでは各(s_low,s_high)の
    # 平均が全動画分そろうまで確定しないため、逐次書き込みすると未確定の部分平均を
    # 最終値と誤って読まれるリスクがある。
    summary_rows = [
        {
            "s_low": lo,
            "s_high": hi,
            "mae": sum(errs) / len(errs),
            "mean_elapsed_ms": sum(elapsed_by_params[(lo, hi)]) / len(elapsed_by_params[(lo, hi)]),
        }
        for (lo, hi), errs in errors_by_params.items() if errs
    ]
    pd.DataFrame(summary_rows).to_csv(out_dir / "mae_summary.csv", index=False)

    print(f"出力: {out_dir}")
    if summary_rows:
        best = min(summary_rows, key=lambda r: r["mae"])
        print(f"MAE最小: s_low={best['s_low']:.2f} s_high={best['s_high']:.2f} mae={best['mae']:.2f}")


if __name__ == "__main__":
    main()
