#!/usr/bin/env python3
"""
ライン位置と車両検出位置を可視化
車両代表点がラインのどの位置を通過しているかを確認
"""

import cv2
import sys
import os
from ultralytics import YOLO

sys.path.insert(0, os.path.dirname(__file__))

from detection.config import Config
from detection.line_crossing import get_vehicle_point, side_of_line, signed_distance


def visualize(video_path: str, config: Config, output_path: str = None, start_frame: int = 0, end_frame: int = 300):
    """
    ライン位置と車両検出を可視化

    Args:
        video_path: 動画ファイルのパス
        config: 設定
        output_path: 出力動画パス（Noneの場合は保存しない）
        start_frame: 開始フレーム
        end_frame: 終了フレーム
    """
    print("\n" + "=" * 80)
    print("ライン・車両可視化")
    print("=" * 80)
    print(f"動画: {video_path}")
    print(f"フレーム範囲: {start_frame} - {end_frame}")
    print(f"Line1: {config.line1.start} → {config.line1.end}")
    print(f"Line2: {config.line2.start} → {config.line2.end}")
    print(f"駐車場基準点: {config.parking_ref_point}")
    print(f"MARGIN_PX: {config.margin_px}, ENDPOINT_MARGIN_PX: {config.endpoint_margin_px}")
    print("=" * 80 + "\n")

    # YOLOモデルをロード
    model = YOLO(config.model_path)

    # 動画キャプチャを開く
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"エラー: 動画を開けません: {video_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # 出力動画
    out = None
    if output_path:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        print(f"出力動画: {output_path}\n")

    # 駐車場側の符号を事前計算
    parking_side_line1 = side_of_line(
        config.parking_ref_point,
        config.line1.start,
        config.line1.end
    )
    parking_side_line2 = side_of_line(
        config.parking_ref_point,
        config.line2.start,
        config.line2.end
    )

    # 開始フレームまでスキップ
    if start_frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        print(f"フレーム {start_frame} までスキップ中...\n")

    frame_id = start_frame
    vehicle_points_history = {}  # track_id -> [(x, y), ...]

    while cap.isOpened() and frame_id < end_frame:
        ret, frame = cap.read()
        if not ret:
            break

        # フレームをコピー
        vis_frame = frame.copy()

        # YOLO検知+トラッキング
        results = model.track(
            frame,
            persist=True,
            conf=config.confidence_threshold,
            iou=config.iou_threshold,
            classes=config.vehicle_classes,
            verbose=False
        )

        # Line1を描画（緑）
        cv2.line(
            vis_frame,
            tuple(map(int, config.line1.start)),
            tuple(map(int, config.line1.end)),
            (0, 255, 0),
            3
        )

        # Line2を描画（黄色）
        cv2.line(
            vis_frame,
            tuple(map(int, config.line2.start)),
            tuple(map(int, config.line2.end)),
            (0, 255, 255),
            3
        )

        # 駐車場基準点を描画（マゼンタ）
        cv2.circle(
            vis_frame,
            tuple(map(int, config.parking_ref_point)),
            10,
            (255, 0, 255),
            -1
        )

        # 車両検出
        if results[0].boxes.id is not None:
            track_ids = results[0].boxes.id.int().tolist()
            bboxes = results[0].boxes.xyxy.tolist()

            for track_id, bbox in zip(track_ids, bboxes):
                # 車両代表点（底面中央）
                vehicle_point = get_vehicle_point(bbox)

                # 履歴に追加
                if track_id not in vehicle_points_history:
                    vehicle_points_history[track_id] = []
                vehicle_points_history[track_id].append(vehicle_point)

                # バウンディングボックスを描画（青）
                x1, y1, x2, y2 = map(int, bbox)
                cv2.rectangle(vis_frame, (x1, y1), (x2, y2), (255, 0, 0), 2)

                # 車両代表点を描画（赤、大きめ）
                cv2.circle(
                    vis_frame,
                    tuple(map(int, vehicle_point)),
                    8,
                    (0, 0, 255),
                    -1
                )

                # Line1/Line2からの符号付き距離(px)を計算
                side1 = signed_distance(vehicle_point, config.line1)
                side2 = signed_distance(vehicle_point, config.line2)

                # 符号付き距離とMARGIN_PX比較を表示
                status1 = "OK" if abs(side1) >= config.margin_px else f"小({abs(side1):.1f}<{config.margin_px})"
                status2 = "OK" if abs(side2) >= config.margin_px else f"小({abs(side2):.1f}<{config.margin_px})"

                # 駐車場側かどうか
                is_parking_side1 = "駐車場側" if side1 * parking_side_line1 > 0 else "入口側"
                is_parking_side2 = "駐車場側" if side2 * parking_side_line2 > 0 else "入口側"

                # 情報を表示
                info_text = [
                    f"ID:{track_id}",
                    f"L1:{side1:.1f} [{status1}] {is_parking_side1}",
                    f"L2:{side2:.1f} [{status2}] {is_parking_side2}"
                ]

                y_offset = int(vehicle_point[1]) - 20
                for i, text in enumerate(info_text):
                    cv2.putText(
                        vis_frame,
                        text,
                        (int(vehicle_point[0]) + 15, y_offset - i * 20),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 0, 255),
                        2
                    )

                # 軌跡を描画（最新30点）
                if len(vehicle_points_history[track_id]) > 1:
                    points = vehicle_points_history[track_id][-30:]
                    for i in range(len(points) - 1):
                        cv2.line(
                            vis_frame,
                            tuple(map(int, points[i])),
                            tuple(map(int, points[i + 1])),
                            (255, 0, 255),
                            2
                        )

        # フレーム情報を表示
        cv2.putText(
            vis_frame,
            f"Frame: {frame_id}",
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (255, 255, 255),
            2
        )

        # 凡例を表示
        legend_y = 60
        legends = [
            ("Line1 (緑): 入口側ライン", (0, 255, 0)),
            ("Line2 (黄): 駐車場側ライン", (0, 255, 255)),
            ("赤点: 車両代表点", (0, 0, 255)),
            ("マゼンタ: 駐車場基準点", (255, 0, 255))
        ]
        for text, color in legends:
            cv2.putText(vis_frame, text, (10, legend_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            legend_y += 25

        # 保存
        if out:
            out.write(vis_frame)

        # 表示
        cv2.imshow("Visualization", vis_frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        if frame_id % 30 == 0:
            print(f"処理中... {frame_id}/{end_frame}")

        frame_id += 1

    cap.release()
    if out:
        out.release()
    cv2.destroyAllWindows()

    print(f"\n✓ 完了: {frame_id}フレーム処理")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python visualize_lines_and_vehicles.py <動画パス> [出力動画パス] [開始フレーム] [終了フレーム]")
        print("\n例:")
        print("  python visualize_lines_and_vehicles.py data/inputs/IMG_2787.mp4")
        print("  python visualize_lines_and_vehicles.py data/inputs/IMG_2787.mp4 debug_vis.mp4")
        print("  python visualize_lines_and_vehicles.py data/inputs/IMG_2787.mp4 debug_vis.mp4 300 600")
        sys.exit(1)

    video_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    start_frame = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    end_frame = int(sys.argv[4]) if len(sys.argv) > 4 else 300

    # 設定を読み込み
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        print(f"エラー: .envファイルが見つかりません: {env_path}")
        sys.exit(1)

    config = Config.from_env(env_path)
    config.validate()

    visualize(video_path, config, output_path, start_frame, end_frame)
