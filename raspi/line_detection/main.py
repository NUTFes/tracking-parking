#!/usr/bin/env python3
"""
2ライン検知システム メイン処理

YOLOv8トラッキングと外積法を使用した高精度な入出庫カウント
"""

import cv2
import argparse
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from ultralytics import YOLO

# 自ディレクトリと raspi/ をパスに追加
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from detection.config import Config
from detection.line_crossing import LineCrossingDetector, get_vehicle_point
from detection.tracker import VehicleTracker
from result_output.video_writer import VideoAnnotator
from result_output.event_logger import EventLogger
from common.frame_stats import compute_timing_stats
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
from common.ground_truth import (
    GroundTruth,
    build_ground_truth_config,
    build_ground_truth_summary,
    load_ground_truth,
)


WEBCAM_FPS = 30.0


@dataclass(frozen=True)
class RuntimeSettings:
    use_wandb: bool
    wandb_project: str
    device_accelerator: str
    log_interval_sec: float
    yolo_device: str | None
    yolo_imgsz: int
    yolo_tracker: str
    warmup_frames: int

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        """Config.from_env() が .env を読み込んだ後に呼ぶ。"""

        return cls(
            use_wandb=os.getenv("USE_WANDB", "false").lower() == "true",
            wandb_project=os.getenv("WANDB_PROJECT", "tracking-parking"),
            device_accelerator=os.getenv("EXP_DEVICE_ACCELERATOR", "cpu"),
            log_interval_sec=validate_log_interval_sec(os.getenv("LOG_INTERVAL_SEC", "5")),
            yolo_device=os.getenv("YOLO_DEVICE") or None,
            yolo_imgsz=int(os.getenv("YOLO_IMGSZ", "640")),
            yolo_tracker=os.getenv("YOLO_TRACKER", "botsort.yaml"),
            warmup_frames=validate_warmup_frames(
                os.getenv("WARMUP_FRAMES", DEFAULT_WARMUP_FRAMES)
            ),
        )


LINE_CONDITION_KEYS = (
    "logic_name",
    "input_type",
    "input_sha256",
    "model_sha256",
    "line1_points",
    "line2_points",
    "parking_reference_point",
    "vehicle_classes",
    "method",
    "margin",
    "max_frame_gap",
    "cleanup_threshold",
    "tracker_reset",
    "log_interval_sec",
    "yolo_conf",
    "yolo_iou",
    "yolo_device",
    "yolo_imgsz",
    "tracker_config",
    "tracker_config_sha256",
    "device_name",
    "device_accelerator",
    "frame_width",
    "frame_height",
    "source_fps",
    "warmup_frames",
    "save_video",
    "save_logs",
    "show_display",
    "timing_schema_version",
    "git_sha",
    "git_dirty",
    "git_dirty_fingerprint",
    "python_version",
    "library_versions",
)


def build_line_condition(run_config: dict) -> dict:
    """2ライン方式の結果・記録へ影響する条件だけを抽出する。"""

    return {key: run_config.get(key) for key in LINE_CONDITION_KEYS}


def process_video(
    video_path: str | int,
    config: Config,
    output_dir: str,
    *,
    use_wandb: bool = False,
    device_name: str = platform.node(),
    runtime: RuntimeSettings | None = None,
    ground_truth: GroundTruth | None = None,
):
    """
    動画を処理

    Args:
        video_path: 入力動画のパス
        config: 設定
        output_dir: 出力ディレクトリ
        ground_truth: 正解台数(GT)。省略時は比較なし
    """
    runtime = runtime or RuntimeSettings.from_env()
    gt = ground_truth or GroundTruth.absent()

    print("\n" + "=" * 60)
    print("2ライン検知システム")
    print("=" * 60)
    print(f"入力動画: {video_path}")
    print(f"出力先: {output_dir}")
    print("=" * 60 + "\n")

    # 1. 初期化
    print("初期化中...")

    # YOLOモデルをロード
    model = YOLO(config.model_path)
    print(f"✓ YOLOモデル読み込み: {config.model_path}")

    # 動画キャプチャを開く
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        print(f"エラー: 動画を開けません: {video_path}")
        return

    # 動画情報を取得
    fps = cap.get(cv2.CAP_PROP_FPS) or WEBCAM_FPS
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"✓ 動画情報: {width}x{height} @ {fps}fps, {total_frames}フレーム")

    # トラッカーを初期化
    tracker = VehicleTracker(
        max_frame_gap=config.max_frame_gap,
        cleanup_threshold=config.cleanup_threshold
    )
    print(f"✓ トラッカー初期化: max_frame_gap={config.max_frame_gap}, cleanup={config.cleanup_threshold}")

    # ライン交差検知器を初期化
    detector = LineCrossingDetector(
        line1=config.line1,
        line2=config.line2,
        parking_ref_point=config.parking_ref_point,
        margin=config.margin
    )
    print(f"✓ ライン検知器初期化: margin={config.margin}")

    # アノテーターを初期化
    annotator = VideoAnnotator(
        line1=config.line1,
        line2=config.line2,
        parking_ref_point=config.parking_ref_point
    )
    print("✓ アノテーター初期化")

    # イベントロガーを初期化
    event_logger = EventLogger(video_path=video_path)
    print("✓ イベントロガー初期化")

    # 出力動画ライターを初期化
    out = None
    output_video_path = None
    if config.save_video:
        os.makedirs(os.path.join(output_dir, "videos"), exist_ok=True)
        output_video_path = os.path.join(
            output_dir,
            "videos",
            f"annotated_{Path(str(video_path)).name if isinstance(video_path, str) else 'camera.mp4'}"
        )
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))
        print(f"✓ 出力動画: {output_video_path}")

    print("\n処理開始...\n")

    input_type = "file" if isinstance(video_path, str) else "camera"
    dataset = Path(str(video_path)).stem if isinstance(video_path, str) else f"camera_{video_path}"
    exp_params = {
        "cleanup_threshold": config.cleanup_threshold,
        "margin": config.margin,
        "max_frame_gap": config.max_frame_gap,
    }
    reproducibility = collect_reproducibility_info()
    run_config = {
        "logic_name": "line_detection",
        "dataset": dataset,
        "input_type": input_type,
        "input_source": str(video_path),
        "device_name": device_name,
        "device_accelerator": runtime.device_accelerator,
        "model_path": config.model_path,
        "input_sha256": sha256_file(str(video_path)) if isinstance(video_path, str) else None,
        "model_sha256": sha256_file(config.model_path),
        "line1_points": [list(config.line1.start), list(config.line1.end)],
        "line2_points": [list(config.line2.start), list(config.line2.end)],
        "parking_reference_point": list(config.parking_ref_point),
        "frame_width": width,
        "frame_height": height,
        "source_fps": float(fps),
        "vehicle_classes": config.vehicle_classes,
        "method": config.method,
        "tracker_reset": True,
        "log_interval_sec": runtime.log_interval_sec,
        "yolo_conf": config.confidence_threshold,
        "yolo_iou": config.iou_threshold,
        "yolo_device_requested": runtime.yolo_device,
        "yolo_device": resolve_model_device(model, runtime.yolo_device),
        "yolo_imgsz": runtime.yolo_imgsz,
        "tracker_config": runtime.yolo_tracker,
        "tracker_config_sha256": sha256_file(runtime.yolo_tracker),
        "warmup_frames": runtime.warmup_frames,
        "save_video": config.save_video,
        "save_logs": config.save_logs,
        "show_display": config.show_display,
        "timing_schema_version": TIMING_SCHEMA_VERSION,
        **exp_params,
        **reproducibility,
        **build_ground_truth_config(gt),
    }
    run_config["comparison_key"] = build_comparison_key(run_config)
    condition = build_line_condition(run_config)
    identity = build_run_identity(
        condition,
        display_name=build_display_name("line_detection", dataset, exp_params),
    )
    run_config["condition"] = condition
    run_config.update(identity)
    run_config["exp_key"] = run_config["condition_key"]  # 旧データ利用箇所向けの互換alias
    wandb_logger = ExperimentLogger(
        project=runtime.wandb_project,
        config=run_config,
        group="line_detection",
        job_type="speed_eval",
        tags=[device_name, input_type],
        enabled=use_wandb,
    )
    wandb_logger.init_accuracy_placeholders()
    wandb_logger.define_metric("net_flow", step_metric="t_rel_sec")

    # 2. フレーム毎処理
    frame_id = 0
    timing_records: list[FrameTiming] = []
    next_log_sec = 0.0
    prev_count_in = 0
    prev_count_out = 0
    synchronize_model = model_synchronizer(model, runtime.yolo_device)
    exit_code = 0

    try:
        while cap.isOpened():
            with elapsed_timer() as end_to_end_timer:
                with elapsed_timer() as read_timer:
                    ret, frame = cap.read()
                if not ret:
                    break

                # 2.1 YOLO検知+トラッキング。CPU化までを共通推論区間に含める。
                with elapsed_timer(synchronize_model) as inference_timer:
                    results = model.track(
                        frame,
                        persist=True,
                        conf=config.confidence_threshold,
                        iou=config.iou_threshold,
                        classes=config.vehicle_classes,
                        verbose=False,
                        device=runtime.yolo_device,
                        imgsz=runtime.yolo_imgsz,
                        tracker=runtime.yolo_tracker,
                    )
                    boxes = results[0].boxes
                    if boxes.id is None:
                        detections = []
                    else:
                        detections = list(zip(
                            boxes.id.int().cpu().tolist(),
                            boxes.xyxy.cpu().tolist(),
                        ))

                pending_events = []
                with elapsed_timer() as counting_timer:
                    for track_id, bbox in detections:
                        vehicle_point = get_vehicle_point(bbox)
                        state = tracker.update(track_id, vehicle_point, frame_id)
                        if state.prev_point is None:
                            continue

                        line1_dir = detector.detect_line1_crossing(
                            state.prev_point, state.curr_point
                        )
                        line2_dir = detector.detect_line2_crossing(
                            state.prev_point, state.curr_point
                        )
                        if line1_dir and not state.counted:
                            state.record_line1_crossing(line1_dir, frame_id)
                        if line2_dir:
                            state.record_line2_crossing(line2_dir, frame_id)
                        if tracker.should_count_event(state):
                            event_type = tracker.mark_as_counted(track_id)
                            pending_events.append({
                                "track_id": track_id,
                                "event_type": event_type,
                                "frame_id": frame_id,
                                "fps": fps,
                                "confidence": state.confidence,
                                "line2_crossed": state.line2_direction is not None,
                            })
                    tracker.cleanup_stale_tracks(frame_id)

                core_ms = inference_timer.elapsed_ms + counting_timer.elapsed_ms
                quit_requested = False
                with elapsed_timer() as output_timer:
                    for event in pending_events:
                        event_logger.record_event(**event)
                    if config.save_video or config.show_display:
                        annotated_frame = annotator.annotate_frame(
                            frame, tracker, frame_id, core_ms
                        )
                    else:
                        annotated_frame = frame
                    if config.save_video and out:
                        out.write(annotated_frame)
                    if config.show_display:
                        cv2.imshow("2ライン検知", annotated_frame)
                        quit_requested = cv2.waitKey(1) & 0xFF == ord("q")

            timing = FrameTiming(
                frame_index=frame_id,
                read_ms=read_timer.elapsed_ms,
                inference_tracking_ms=inference_timer.elapsed_ms,
                counting_logic_ms=counting_timer.elapsed_ms,
                output_ms=output_timer.elapsed_ms,
                end_to_end_ms=end_to_end_timer.elapsed_ms,
                is_warmup=frame_id < runtime.warmup_frames,
            )
            timing_records.append(timing)
            event_logger.record_frame_time(timing.core_ms)

            # 観測処理は end_to_end 計測後に行う。
            summary = tracker.get_summary()
            count_in = summary["total_in"]
            count_out = summary["total_out"]
            count_changed = count_in != prev_count_in or count_out != prev_count_out
            t_rel_sec = frame_id / fps if fps > 0 else 0.0
            if should_log_frame(t_rel_sec, next_log_sec, count_changed):
                wandb_logger.log_frame(
                    step=frame_id,
                    metrics={
                        "t_rel_sec": t_rel_sec,
                        "net_flow": count_in - count_out,
                        "cumulative_in": count_in,
                        "cumulative_out": count_out,
                        **timing.to_dict(),
                        "num_tracks": len(detections),
                        "retained_states": len(tracker.states),
                    },
                )
                next_log_sec = next_log_boundary(
                    next_log_sec, t_rel_sec, runtime.log_interval_sec
                )
            prev_count_in = count_in
            prev_count_out = count_out

            if frame_id % 300 == 0:
                wandb_logger.update_running_summary({
                    "count_in": count_in,
                    "count_out": count_out,
                    "total_frames": frame_id + 1,
                })
            if frame_id % 30 == 0:
                progress = (frame_id / total_frames * 100) if total_frames > 0 else 0
                print(f"処理中... {frame_id}/{total_frames}フレーム ({progress:.1f}%)")
            for event in pending_events:
                print(
                    f"[Frame {frame_id}] ID:{event['track_id']} "
                    f"{event['event_type']} (信頼度: {event['confidence']})"
                )

            frame_id += 1
            if quit_requested:
                print("\nユーザーによる中断")
                break

        measured = require_measured_timings(timing_records)
        timing_stats = compute_timing_stats(measured, float(fps))
        tracker_summary = tracker.get_summary()
        accuracy_summary = build_ground_truth_summary(
            tracker_summary["total_in"], tracker_summary["total_out"], gt
        )
        wandb_logger.set_summaries({
            "count_in": tracker_summary["total_in"],
            "count_out": tracker_summary["total_out"],
            "total_frames": frame_id,
            "measured_frames": len(measured),
            **accuracy_summary,
            **timing_stats,
        })
        if gt.is_available:
            print(
                f"GT比較: count_error={accuracy_summary['count_error']} "
                f"(in={accuracy_summary['count_error_in']}, "
                f"out={accuracy_summary['count_error_out']})"
            )

        print("\n処理完了!")
        log_dir = Path(output_dir) / "logs"
        output_paths = []
        if config.save_logs:
            json_path = event_logger.save_json(
                str(log_dir),
                tracker_summary,
                wandb_run_id=wandb_logger.run_id,
                execution_id=run_config["execution_id"],
                condition_key=run_config["condition_key"],
                exp_key=run_config["exp_key"],
                timing_summary={
                    "timing_schema_version": TIMING_SCHEMA_VERSION,
                    "warmup_frames": runtime.warmup_frames,
                    "measured_frames": len(measured),
                    **timing_stats,
                },
            )
            csv_path = event_logger.save_csv(str(log_dir))
            output_paths.extend([Path(json_path).resolve(), Path(csv_path).resolve()])
        wandb_logger.save_run_id(log_dir)
        if use_wandb:
            output_paths.append((log_dir / "wandb_run_id.txt").resolve())
        if output_video_path is not None:
            output_paths.append(Path(output_video_path).resolve())
        write_run_manifest(
            Path(output_dir) / "manifests" / f"{run_config['execution_id']}.json",
            config=run_config,
            output_dir=Path(output_dir),
            output_paths=output_paths,
            wandb_run_id=wandb_logger.run_id,
        )
        event_logger.print_summary(tracker_summary, timing_summary=timing_stats)
        return timing_stats
    except BaseException:
        exit_code = 1
        raise
    finally:
        cap.release()
        if out:
            out.release()
        if config.show_display:
            cv2.destroyAllWindows()
        wandb_logger.finish(exit_code=exit_code)


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description="2ライン検知システム - 高精度な駐車場入出庫カウント"
    )
    parser.add_argument(
        "--input",
        help="入力動画のパス"
    )
    parser.add_argument(
        "--camera",
        type=int,
        help="カメラデバイスID(0=デフォルトカメラ)"
    )
    parser.add_argument(
        "--output",
        default="data/outputs",
        help="出力ディレクトリ(デフォルト: data/outputs)"
    )
    parser.add_argument(
        "--env",
        default=None,
        help=".envファイルのパス(デフォルト: カレントディレクトリの.env)"
    )
    parser.add_argument(
        "--display",
        action="store_true",
        help="処理中の動画を表示"
    )
    parser.add_argument(
        "--wandb",
        action="store_true",
        help="W&Bへ速度・台数メトリクスを記録"
    )
    parser.add_argument(
        "--device-name",
        default=None,
        help="比較対象デバイス名"
    )
    parser.add_argument(
        "--gt",
        default=None,
        help="正解台数JSONのパス(省略時は<動画名>_gt.jsonを自動探索)"
    )

    args = parser.parse_args()

    # 入力ソースのチェック
    if args.input and args.camera is not None:
        print("エラー: --inputと--cameraは同時に指定できません")
        return 1

    if not args.input and args.camera is None:
        print("エラー: --inputまたは--cameraを指定してください")
        print("\n使用例:")
        print("  python main.py --input data/inputs/test.mp4")
        print("  python main.py --camera 0 --display")
        return 1

    # 入力ソースを決定
    video_path = args.input if args.input else args.camera

    # 出力ディレクトリの絶対パス
    output_dir = os.path.abspath(args.output)

    # 設定を読み込み
    try:
        if args.env:
            config = Config.from_env(args.env)
        else:
            # カレントディレクトリの.envを探す
            env_path = os.path.join(os.path.dirname(__file__), ".env")
            if not os.path.exists(env_path):
                print(f"エラー: .envファイルが見つかりません: {env_path}")
                print("\nまず line_setup/setup_lines.py を実行してライン座標を設定してください:")
                print("  python line_setup/setup_lines.py --video data/inputs/test.mp4")
                return 1
            config = Config.from_env(env_path)

        # 設定を検証
        config.validate()

        # 表示設定を上書き
        if args.display:
            config.show_display = True

        # GTを読み込み(--gt省略時は動画名から自動探索。無ければ比較なしで続行)
        ground_truth = load_ground_truth(video_path, args.gt)

    except Exception as e:
        print(f"設定エラー: {e}")
        return 1

    # 動画を処理
    try:
        runtime = RuntimeSettings.from_env()
        process_video(
            video_path,
            config,
            output_dir,
            use_wandb=args.wandb or runtime.use_wandb,
            device_name=args.device_name or os.getenv("EXP_DEVICE_NAME", platform.node()),
            runtime=runtime,
            ground_truth=ground_truth,
        )
        return 0
    except KeyboardInterrupt:
        print("\n\nユーザーによる中断")
        return 1
    except Exception as e:
        print(f"\nエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
