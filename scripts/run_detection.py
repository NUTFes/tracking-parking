#!/usr/bin/env python3
"""
2ライン検知システム メイン処理

YOLOv8トラッキングと外積法を使用した高精度な入出庫カウント
"""

import cv2
import argparse
import math
import os
import platform
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from ultralytics import YOLO

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from tracking_parking.config import Config
from tracking_parking.detection.line_crossing import LineCrossingDetector, get_vehicle_point
from tracking_parking.detection.tracker import VehicleTracker
from tracking_parking.output.video_writer import VideoAnnotator
from tracking_parking.output.video_recorder import SEGMENT_PATTERN, open_recorder
from tracking_parking.output.event_logger import EventLogger
from tracking_parking.common.camera import apply_camera_capture_settings as apply_capture_settings
from tracking_parking.common.frame_stats import compute_timing_stats
from tracking_parking.common.time_windows import frames_from_seconds
from tracking_parking.common.frame_timing import (
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
from tracking_parking.common.wandb_logger import (
    ExperimentLogger,
    next_log_boundary,
    should_log_frame,
    validate_log_interval_sec,
)
from tracking_parking.common.run_identity import (
    build_display_name,
    build_run_identity,
    collect_reproducibility_info,
    write_run_manifest,
)
from tracking_parking.common.ground_truth import (
    GroundTruth,
    build_ground_truth_config,
    build_ground_truth_summary,
    load_ground_truth,
)
from tracking_parking.api.runtime import ApiRuntime
from tracking_parking.api.settings import ApiSettings, is_local_network_url


WEBCAM_FPS = 30.0
CROSSING_METHOD = "hysteresis_v1"  # W&B上でPre/Post-3bのrunを区別する固定タグ(可変設定ではない)


def compute_stream_time_sec(
    *, is_camera_input: bool, frame_id: int, fps: float, elapsed_sec: float
) -> float:
    """時間窓（Line1とLine2の対応付け、trackのクリーンアップ）の判定に使う
    ストリーム時刻(秒)を返す。

    動画ファイルでは frame_id / fps が厳密なストリーム時刻になる。全フレームを
    順に処理するため、処理が何秒かかろうと映像内の経過は変わらない。

    カメラでは違う。処理が撮影レートに追いつかないとドライバのバッファ（4枚）で
    古いフレームが捨てられるため、処理したフレーム数は実際の経過より少ない。
    30fps宣言のカメラを実測14fpsで処理すると frame_id / fps は実経過の半分以下に
    なり、「3秒」の窓が実時間で6秒以上に伸びる。カメラだけ実時刻を使う。

    Args:
        is_camera_input: カメラ入力ならTrue
        frame_id: 現在のフレーム番号（動画入力でのみ使う）
        fps: 動画のfps（動画入力でのみ使う）
        elapsed_sec: 処理開始からの実経過秒（カメラ入力でのみ使う）
    """
    if is_camera_input:
        return elapsed_sec
    return frame_id / fps if fps > 0 else 0.0


def build_recording_target(output_dir: str, video_path, *, segment_mb: int,
                           started_at: datetime) -> tuple:
    """録画の出力先と1本あたりの上限バイト数を決める。

    カメラ入力は実行開始時刻のディレクトリへ分割して書く。以前は
    'annotated_camera.mp4' の固定名で、起動するたびに前回の録画を上書きして
    いた。本番で録り続ける用途では、これは黙って証跡を失う。

    動画ファイル入力は従来どおり単一ファイルにする。入力が有限で、名前が
    入力に紐づいているほうが扱いやすく、分割の動機（落ちたときに失う範囲を
    限る）も当てはまらないため。

    Args:
        output_dir: 出力ディレクトリ
        video_path: 入力（strなら動画ファイル、intならカメラID）
        segment_mb: 1本あたりの上限(MB)。0で分割しない。
        started_at: 実行開始時刻。カメラ入力のディレクトリ名に使う。

    Returns:
        (出力パス, 1本あたりの上限バイト数)。分割しないときは上限0。
    """
    videos_dir = os.path.join(output_dir, "videos")

    if isinstance(video_path, str):
        os.makedirs(videos_dir, exist_ok=True)
        return os.path.join(videos_dir, f"annotated_{Path(video_path).name}"), 0

    if segment_mb <= 0:
        # 分割しない指定でも、固定名による上書きは避ける。
        os.makedirs(videos_dir, exist_ok=True)
        stamp = started_at.strftime("%Y%m%d_%H%M%S")
        return os.path.join(videos_dir, f"annotated_camera_{stamp}.mp4"), 0

    run_dir = os.path.join(
        videos_dir, f"camera_{started_at.strftime('%Y%m%d_%H%M%S')}"
    )
    os.makedirs(run_dir, exist_ok=True)
    return os.path.join(run_dir, SEGMENT_PATTERN), segment_mb * 1024 * 1024


def apply_camera_capture_settings(cap, config: Config) -> None:
    """Configのカメラ設定をキャプチャへ要求する。

    実処理は common/camera.py に置いている。setup_lines.py がライン設定に
    使うフレームを、この検知ループと同じ解像度で掴む必要があるため。
    """
    apply_capture_settings(
        cap,
        width=config.camera_width,
        height=config.camera_height,
        fourcc=config.camera_fourcc,
    )


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
    "ground_truth_sha256",
    "gt_in",
    "gt_out",
    "vehicle_classes",
    "method",
    "margin_px",
    "endpoint_margin_px",
    "crossing_method",
    "max_frame_gap_sec",
    "cleanup_threshold_sec",
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
    "video_encoder",
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
    no_api: bool = False,
    simulate_camera_input: bool = False,
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

    is_camera_input = not isinstance(video_path, str)
    if is_camera_input:
        apply_camera_capture_settings(cap, config)

    # 動画情報を取得
    # カメラの場合、ここで読む値は「要求した値」ではなくドライバが受理した実測値。
    fps = cap.get(cv2.CAP_PROP_FPS) or WEBCAM_FPS
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"✓ 動画情報: {width}x{height} @ {fps}fps, {total_frames}フレーム")

    # 要求が丸められたら黙って進まない。ライン座標がこの解像度前提で設定されて
    # いるため、気づかないまま走らせると検知位置が静かにずれる。
    if (
        is_camera_input
        and config.camera_width is not None
        and (width, height) != (config.camera_width, config.camera_height)
    ):
        print(
            f"[WARN] カメラが要求解像度を受理しませんでした: "
            f"要求 {config.camera_width}x{config.camera_height} → 実際 {width}x{height}"
            + (
                ""
                if config.camera_fourcc
                else "（CAMERA_FOURCC=MJPG の指定が必要な場合があります）"
            )
        )

    # 時間窓は秒のままトラッカーへ渡し、判定にはストリーム時刻を使う（stream_time_sec）。
    # 換算後のフレーム数は記録のためだけに残す（動画入力でのみ意味を持つ）。
    max_frame_gap = frames_from_seconds(config.max_frame_gap_sec, fps) if not is_camera_input else None
    cleanup_threshold = frames_from_seconds(config.cleanup_threshold_sec, fps) if not is_camera_input else None

    # トラッカーを初期化
    tracker = VehicleTracker(
        max_gap_sec=config.max_frame_gap_sec,
        cleanup_threshold_sec=config.cleanup_threshold_sec
    )
    print(
        f"✓ トラッカー初期化: "
        f"max_frame_gap={config.max_frame_gap_sec}秒, "
        f"cleanup={config.cleanup_threshold_sec}秒 "
        f"({'実時刻' if is_camera_input else f'frame_id/{fps}fps'}基準)"
    )

    # ライン交差検知器を初期化
    detector = LineCrossingDetector(
        line1=config.line1,
        line2=config.line2,
        parking_ref_point=config.parking_ref_point,
        margin_px=config.margin_px,
        endpoint_margin_px=config.endpoint_margin_px
    )
    print(f"✓ ライン検知器初期化: margin_px={config.margin_px}, endpoint_margin_px={config.endpoint_margin_px}")

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
        output_video_path, segment_bytes = build_recording_target(
            output_dir,
            video_path,
            segment_mb=config.video_segment_mb,
            started_at=datetime.now().astimezone(),
        )
        # ここはtry:の外なので、例外が出るとfinallyのcap.release()が飛ぶ。
        # VIDEO_ENCODER=nvencを指定したが使えない場合にValueErrorが出るため、
        # 明示的に後片付けしてから投げ直す。
        try:
            out = open_recorder(
                output_video_path,
                width=width, height=height, fps=fps,
                encoder=config.video_encoder,
                segment_bytes=segment_bytes,
                max_segments=config.video_max_segments,
            )
        except Exception:
            cap.release()
            raise
        print(f"✓ 出力動画: {output_video_path} (encoder={out.name})")
        if segment_bytes:
            free_gb = shutil.disk_usage(os.path.dirname(output_video_path)).free / 1024**3
            keep = (f"最大{config.video_max_segments}本"
                    if config.video_max_segments else "本数制限なし")
            print(f"  分割: {config.video_segment_mb}MBごと / {keep} / 空き{free_gb:.1f}GB")
            if config.video_max_segments:
                # 保持数を有効にするとファイル名が循環する（splitmuxsinkの
                # max-filesがリングバッファ）。名前の順に読むと時系列を誤る。
                print("  [注意] 保持数を有効にしたためファイル名は循環します。"
                      "時系列はmtimeか焼き込んだJSTで判断してください")
                need_gb = (config.video_segment_mb * config.video_max_segments) / 1024
                if need_gb > free_gb:
                    print(f"  [WARN] 保持数ぶんの容量が足りません: "
                          f"必要{need_gb:.1f}GB > 空き{free_gb:.1f}GB")

    print("\n処理開始...\n")

    input_type = "file" if isinstance(video_path, str) else "camera"
    dataset = Path(str(video_path)).stem if isinstance(video_path, str) else f"camera_{video_path}"
    # 表示名と記録に使う。トラッカーの判定単位は秒なので、ここも秒を出す。
    # 換算後のフレーム数は下のrun_configへ参考値として別途残す。
    exp_params = {
        "cleanup_threshold_sec": config.cleanup_threshold_sec,
        "margin_px": config.margin_px,
        "endpoint_margin_px": config.endpoint_margin_px,
        "max_frame_gap_sec": config.max_frame_gap_sec,
        "crossing_method": CROSSING_METHOD,
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
        # 要求値も残す。frame_width/heightは実測値なので、両方ないと
        # 「指定したのに丸められた」のか「指定していない」のかが後から分からない。
        # 結果に効くのは実測値のほうなので、condition_keyへは入れない。
        "camera_width_requested": config.camera_width if is_camera_input else None,
        "camera_height_requested": config.camera_height if is_camera_input else None,
        "camera_fourcc_requested": config.camera_fourcc if is_camera_input else None,
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
        # 要求値と実際に選ばれたエンコーダの両方を残す。autoは機体によって
        # 解決先が変わり（NVENCの有無）、output_msが変わるため。
        "video_encoder_requested": config.video_encoder,
        "video_encoder": out.name if out is not None else None,
        "video_segment_mb": config.video_segment_mb,
        "video_max_segments": config.video_max_segments,
        "save_logs": config.save_logs,
        "show_display": config.show_display,
        "timing_schema_version": TIMING_SCHEMA_VERSION,
        # 換算後のフレーム数は参考値。動画入力では frame_id/fps がそのまま
        # ストリーム時刻なので秒と1対1に対応するが、カメラでは対応しないためNone。
        "max_frame_gap_frames": max_frame_gap,
        "cleanup_threshold_frames": cleanup_threshold,
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
    # カメラ入力でストリーム時刻の起点に使う。動画入力では使わない。
    stream_t0 = time.monotonic()
    exit_code = 0
    # try:の外で例外が出るとfinallyのapi.shutdown()がNameErrorになるため、
    # ApiRuntime.create()より先にNoneで初期化しておく。
    api: ApiRuntime | None = None

    try:
        # API送信ランタイムを組み立てる。送信ガード（カメラ入力 かつ
        # API_ENABLED=true）はApiRuntime.create()の内部で判定する。動画
        # ファイル入力では常に無効になる。DEVICE_API_KEY未設定などで
        # settings.validate()がValueErrorを出す場合があるため、try:の中で
        # 行う（外だとcap.release()等の後片付けがfinallyで飛ばされる）。
        api = ApiRuntime.create(
            ApiSettings.from_env(home_dir=config.home_dir),
            input_type=input_type,
            execution_id=run_config["execution_id"],
            force_disabled=no_api,
            simulate_camera_input=simulate_camera_input,
        )
        api.start()

        while cap.isOpened():
            with elapsed_timer() as end_to_end_timer:
                with elapsed_timer() as read_timer:
                    ret, frame = cap.read()
                # API送信の有無に関わらず無条件で取得する。api.enabledで分岐すると
                # 有効run/無効runでend_to_end_msの測り方が変わり、run間の比較可能性が崩れる。
                frame_read_at = datetime.now().astimezone()
                if not ret:
                    break

                stream_time_sec = compute_stream_time_sec(
                    is_camera_input=is_camera_input,
                    frame_id=frame_id,
                    fps=fps,
                    elapsed_sec=time.monotonic() - stream_t0,
                )

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
                        state = tracker.update(track_id, vehicle_point, stream_time_sec)

                        line1_result = detector.update_line1_crossing(
                            state.line1_transition, state.curr_point
                        )
                        line2_result = detector.update_line2_crossing(
                            state.line2_transition, state.curr_point
                        )
                        crossings = []
                        if line1_result is not None:
                            crossings.append(("line1", line1_result))
                        if line2_result is not None:
                            crossings.append(("line2", line2_result))
                        if len(crossings) == 2:
                            crossings.sort(
                                key=lambda item: math.dist(
                                    state.curr_point, item[1].point
                                ),
                                reverse=True,
                            )
                        for line_name, result in crossings:
                            if line_name == "line1":
                                if not state.counted:
                                    state.record_line1_crossing(
                                        result.direction, stream_time_sec
                                    )
                            else:
                                state.record_line2_crossing(
                                    result.direction, stream_time_sec
                                )
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
                    tracker.cleanup_stale_tracks(stream_time_sec)

                core_ms = inference_timer.elapsed_ms + counting_timer.elapsed_ms
                quit_requested = False
                with elapsed_timer() as output_timer:
                    for event in pending_events:
                        event_id = event_logger.record_event(**event)
                        event["event_id"] = event_id
                        state = tracker.get_state(event["track_id"])
                        if state is not None:
                            state.pending_event_id = event_id
                    # event_idを割り当ててからconfidenceをイベントへ反映する必要がある。
                    confidence_updates = tracker.resolve_pending_confidences(stream_time_sec)
                    for update in confidence_updates:
                        if not event_logger.update_confidence(
                            update.event_id,
                            update.confidence,
                            line2_crossed=update.line2_crossed,
                        ):
                            raise RuntimeError(
                                "confidence更新対象のイベントが見つかりません: "
                                f"event_id={update.event_id}"
                            )
                        for event in pending_events:
                            if event["track_id"] == update.track_id:
                                event["confidence"] = update.confidence
                                event["line2_crossed"] = update.line2_crossed
                    if config.save_video or config.show_display:
                        # frame_read_at はAPIへ送る detected_at と同じ値。
                        # 動画に焼き込む時刻をイベント記録と一致させるため、
                        # ここで別に now() を取らない。
                        annotated_frame = annotator.annotate_frame(
                            frame, tracker, frame_id, core_ms,
                            captured_at=frame_read_at,
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
            t_rel_sec = stream_time_sec
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
                # confidenceの確定を待たずに送る（high/normalを区別せず全件送信する方針）。
                api.enqueue_event(
                    event_id=event["event_id"],
                    event_type=event["event_type"],
                    detected_at=frame_read_at,
                    track_id=event["track_id"],
                )

            frame_id += 1
            if quit_requested:
                print("\nユーザーによる中断")
                break

        final_confidence_updates = tracker.finalize_pending_confidences()
        for update in final_confidence_updates:
            if not event_logger.update_confidence(
                update.event_id,
                update.confidence,
                line2_crossed=update.line2_crossed,
            ):
                raise RuntimeError(
                    "終了時confidence更新対象のイベントが見つかりません: "
                    f"event_id={update.event_id}"
                )
        orphan_pending = event_logger.finalize_pending_confidences()
        if orphan_pending:
            raise RuntimeError(
                f"trackerに存在しないpendingイベントが残っています: {orphan_pending}件"
            )

        measured = require_measured_timings(timing_records)
        timing_stats = compute_timing_stats(measured, float(fps))
        tracker_summary = tracker.get_summary()
        event_logger.validate_finalized(tracker_summary)
        accuracy_summary = build_ground_truth_summary(
            tracker_summary["total_in"], tracker_summary["total_out"], gt
        )
        wandb_logger.set_summaries({
            "count_in": tracker_summary["total_in"],
            "count_out": tracker_summary["total_out"],
            "total_frames": frame_id,
            "measured_frames": len(measured),
            "high_confidence_events": tracker_summary["high_confidence_events"],
            "normal_confidence_events": tracker_summary["normal_confidence_events"],
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
                accuracy_summary=accuracy_summary if gt.is_available else None,
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
        if api is not None:
            api.shutdown()
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
        help=".envファイルのパス(デフォルト: リポジトリルートの.env)"
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
        "--no-api",
        action="store_true",
        help=".envのAPI_ENABLEDに関わらず、API送信だけを無効化する（実機デバッグ用）"
    )
    parser.add_argument(
        "--simulate-camera-input",
        action="store_true",
        help="動画ファイル入力をカメラ入力とみなしてAPI送信を有効化する（送信経路の検証用。"
             "API_BASE_URLがローカル/LAN以外のときは起動を拒否する。解除する手段は無い）"
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
        print("  python scripts/run_detection.py --input data/inputs/test.mp4")
        print("  python scripts/run_detection.py --camera 0 --display")
        return 1

    if args.simulate_camera_input and args.camera is not None:
        print("エラー: --simulate-camera-inputはカメラ入力（--camera）には不要です")
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
            # リポジトリルートの.envを探す
            env_path = os.path.join(REPO_ROOT, ".env")
            if not os.path.exists(env_path):
                print(f"エラー: .envファイルが見つかりません: {env_path}")
                print("\nまず scripts/setup_lines.py を実行してライン座標を設定してください:")
                print("  python scripts/setup_lines.py --video data/inputs/test.mp4")
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

    # --simulate-camera-inputの宛先チェックをここで先に行う（fail fast）。
    # ApiRuntime.create()内でも同じ判定を行う（権威的なチェック）が、ここで
    # 弾いておけばYOLOモデルの読み込み前に終了でき、実機でのデバッグ体験が良い。
    if args.simulate_camera_input:
        api_settings = ApiSettings.from_env(home_dir=config.home_dir)
        if not is_local_network_url(api_settings.base_url):
            print(
                f"エラー: --simulate-camera-inputはAPI_BASE_URLがローカル/LAN以外のときは"
                f"使えません: {api_settings.base_url}\n"
                "動画をカメラ扱いにする検証は、本番/stagingのsystem_countを"
                "誤って動かさないためローカル/LAN限定です。"
            )
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
            no_api=args.no_api,
            simulate_camera_input=args.simulate_camera_input,
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
