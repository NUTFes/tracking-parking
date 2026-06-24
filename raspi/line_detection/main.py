#!/usr/bin/env python3
"""
2ライン検知システム メイン処理

YOLOv8トラッキングと外積法を使用した高精度な入出庫カウント
"""

import cv2
import argparse
import os
import sys
import time
from ultralytics import YOLO

# 親ディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(__file__))

from detection.config import Config
from detection.line_crossing import LineCrossingDetector, get_vehicle_point
from detection.tracker import VehicleTracker
from result_output.video_writer import VideoAnnotator
from result_output.event_logger import EventLogger


def process_video(video_path: str, config: Config, output_dir: str):
    """
    動画を処理

    Args:
        video_path: 入力動画のパス
        config: 設定
        output_dir: 出力ディレクトリ
    """
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
    cap = cv2.VideoCapture(video_path if video_path else 0)

    if not cap.isOpened():
        print(f"エラー: 動画を開けません: {video_path}")
        return

    # 動画情報を取得
    fps = cap.get(cv2.CAP_PROP_FPS)
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
    logger = EventLogger(video_path=video_path)
    print("✓ イベントロガー初期化")

    # 出力動画ライターを初期化
    out = None
    if config.save_video:
        os.makedirs(os.path.join(output_dir, "videos"), exist_ok=True)
        output_video_path = os.path.join(
            output_dir,
            "videos",
            f"annotated_{os.path.basename(video_path)}"
        )
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))
        print(f"✓ 出力動画: {output_video_path}")

    print("\n処理開始...\n")

    # 2. フレーム毎処理
    frame_id = 0

    while cap.isOpened():
        start_time = time.perf_counter()

        ret, frame = cap.read()
        if not ret:
            break

        # 2.1 YOLO検知+トラッキング
        results = model.track(
            frame,
            persist=True,
            conf=config.confidence_threshold,
            verbose=False
        )

        # 2.2 各車両の処理
        if results[0].boxes.id is not None:
            track_ids = results[0].boxes.id.int().tolist()
            bboxes = results[0].boxes.xyxy.tolist()

            for track_id, bbox in zip(track_ids, bboxes):
                # 車両代表点取得
                vehicle_point = get_vehicle_point(bbox)

                # 状態更新
                state = tracker.update(track_id, vehicle_point, frame_id)

                # ライン交差検知
                if state.prev_point is not None:
                    # Line1交差検知
                    line1_dir = detector.detect_line1_crossing(
                        state.prev_point,
                        state.curr_point
                    )

                    # Line2交差検知
                    line2_crossed = detector.detect_line2_crossing(
                        state.prev_point,
                        state.curr_point
                    )

                    # Line1交差イベントを記録
                    if line1_dir and not state.counted:
                        state.record_line1_crossing(line1_dir, frame_id)

                    # Line2交差を記録
                    if line2_crossed:
                        state.record_line2_crossing(frame_id)

                    # ハイブリッド方式でイベント判定
                    if tracker.should_count_event(state):
                        # カウント済みとしてマーク
                        event_type = tracker.mark_as_counted(track_id)

                        # イベントをログに記録
                        logger.record_event(
                            track_id=track_id,
                            event_type=event_type,
                            frame_id=frame_id,
                            fps=fps,
                            confidence=state.confidence,
                            line2_crossed=state.line2_passed
                        )

                        print(f"[Frame {frame_id}] ID:{track_id} {event_type} (信頼度: {state.confidence})")

        # 2.3 古い追跡をクリーンアップ
        tracker.cleanup_stale_tracks(frame_id)

        # 2.4 処理時間を記録
        processing_time_ms = (time.perf_counter() - start_time) * 1000
        logger.record_frame_time(processing_time_ms)

        # 2.5 アノテーション
        annotated_frame = annotator.annotate_frame(
            frame,
            tracker,
            frame_id,
            processing_time_ms
        )

        # 2.6 出力
        if config.save_video and out:
            out.write(annotated_frame)

        if config.show_display:
            cv2.imshow("2ライン検知", annotated_frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("\nユーザーによる中断")
                break

        # 進捗表示
        if frame_id % 30 == 0:
            progress = (frame_id / total_frames * 100) if total_frames > 0 else 0
            print(f"処理中... {frame_id}/{total_frames}フレーム ({progress:.1f}%)")

        frame_id += 1

    # 3. クリーンアップ
    cap.release()
    if out:
        out.release()
    if config.show_display:
        cv2.destroyAllWindows()

    print("\n処理完了!")

    # 4. ログを保存
    if config.save_logs:
        log_dir = os.path.join(output_dir, "logs")
        logger.save_json(log_dir, tracker.get_summary())
        logger.save_csv(log_dir)

    # 5. サマリーを表示
    logger.print_summary(tracker.get_summary())


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

    except Exception as e:
        print(f"設定エラー: {e}")
        return 1

    # 動画を処理
    try:
        process_video(video_path, config, output_dir)
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
