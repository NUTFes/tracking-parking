"""
アノテーション動画生成モジュール
検知結果を可視化した動画を生成
"""

import cv2
import numpy as np
from typing import Dict, Tuple
from detection.config import Line
from detection.tracker import VehicleTracker, VehicleState


class VideoAnnotator:
    """動画アノテーションクラス"""

    def __init__(self,
                 line1: Line,
                 line2: Line,
                 parking_ref_point: Tuple[float, float]):
        """
        Args:
            line1: Line1(入口側)
            line2: Line2(駐車場側)
            parking_ref_point: 駐車場基準点
        """
        self.line1 = line1
        self.line2 = line2
        self.parking_ref_point = parking_ref_point

        # 色定義
        self.COLOR_LINE1 = (0, 255, 0)  # 緑
        self.COLOR_LINE2 = (0, 255, 255)  # 黄色
        self.COLOR_PARKING_REF = (255, 0, 255)  # マゼンタ
        self.COLOR_VEHICLE_POINT = (255, 0, 0)  # 青
        self.COLOR_TEXT = (255, 255, 255)  # 白
        self.COLOR_BG = (0, 0, 0)  # 黒

    def draw_lines(self, frame: np.ndarray) -> np.ndarray:
        """
        ライン を描画

        Args:
            frame: 入力フレーム

        Returns:
            np.ndarray: ライン描画後のフレーム
        """
        # Line1 (入口側) を緑で描画
        cv2.line(
            frame,
            tuple(map(int, self.line1.start)),
            tuple(map(int, self.line1.end)),
            self.COLOR_LINE1,
            3
        )
        # Line1のラベル
        line1_mid = (
            int((self.line1.start[0] + self.line1.end[0]) / 2),
            int((self.line1.start[1] + self.line1.end[1]) / 2)
        )
        self._draw_text_with_background(
            frame,
            "Line1 (入口側)",
            (line1_mid[0], line1_mid[1] - 10),
            self.COLOR_LINE1
        )

        # Line2 (駐車場側) を黄色で描画
        cv2.line(
            frame,
            tuple(map(int, self.line2.start)),
            tuple(map(int, self.line2.end)),
            self.COLOR_LINE2,
            3
        )
        # Line2のラベル
        line2_mid = (
            int((self.line2.start[0] + self.line2.end[0]) / 2),
            int((self.line2.start[1] + self.line2.end[1]) / 2)
        )
        self._draw_text_with_background(
            frame,
            "Line2 (駐車場側)",
            (line2_mid[0], line2_mid[1] - 10),
            self.COLOR_LINE2
        )

        # 駐車場基準点をマゼンタで描画
        cv2.circle(
            frame,
            tuple(map(int, self.parking_ref_point)),
            8,
            self.COLOR_PARKING_REF,
            -1
        )

        return frame

    def draw_vehicle_states(self,
                           frame: np.ndarray,
                           tracker: VehicleTracker) -> np.ndarray:
        """
        車両状態を描画

        Args:
            frame: 入力フレーム
            tracker: VehicleTracker

        Returns:
            np.ndarray: 車両状態描画後のフレーム
        """
        for track_id, state in tracker.states.items():
            if state.curr_point is None:
                continue

            # 車両代表点を描画
            point = tuple(map(int, state.curr_point))
            cv2.circle(frame, point, 5, self.COLOR_VEHICLE_POINT, -1)

            # track_idと状態を表示
            label = f"ID:{track_id}"
            if state.line1_direction:
                label += f" {state.line1_direction}"
            if state.confidence:
                label += f" ({state.confidence})"

            self._draw_text_with_background(
                frame,
                label,
                (point[0] + 10, point[1] - 5),
                self.COLOR_VEHICLE_POINT,
                font_scale=0.5
            )

        return frame

    def draw_count_overlay(self,
                          frame: np.ndarray,
                          tracker: VehicleTracker,
                          frame_id: int,
                          processing_time_ms: float) -> np.ndarray:
        """
        カウント情報をオーバーレイ表示

        Args:
            frame: 入力フレーム
            tracker: VehicleTracker
            frame_id: フレーム番号
            processing_time_ms: 処理時間(ms)

        Returns:
            np.ndarray: オーバーレイ表示後のフレーム
        """
        summary = tracker.get_summary()

        # 背景を半透明の黒で描画
        overlay = frame.copy()
        cv2.rectangle(overlay, (10, 10), (350, 180), self.COLOR_BG, -1)
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

        # 統計情報を表示
        y = 35
        line_height = 25

        texts = [
            f"Frame: {frame_id}",
            f"IN: {summary['total_in']}  OUT: {summary['total_out']}",
            f"Parked: {summary['current_parked']}",
            f"High: {summary['high_confidence_events']}  Normal: {summary['normal_confidence_events']}",
            f"Active: {summary['active_tracks']}",
            f"Time: {processing_time_ms:.1f}ms"
        ]

        for text in texts:
            cv2.putText(
                frame,
                text,
                (20, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                self.COLOR_TEXT,
                2
            )
            y += line_height

        return frame

    def annotate_frame(self,
                      frame: np.ndarray,
                      tracker: VehicleTracker,
                      frame_id: int,
                      processing_time_ms: float = 0.0) -> np.ndarray:
        """
        フレームに全てのアノテーションを追加

        Args:
            frame: 入力フレーム
            tracker: VehicleTracker
            frame_id: フレーム番号
            processing_time_ms: 処理時間(ms)

        Returns:
            np.ndarray: アノテーション後のフレーム
        """
        # フレームをコピー
        annotated = frame.copy()

        # ラインを描画
        annotated = self.draw_lines(annotated)

        # 車両状態を描画
        annotated = self.draw_vehicle_states(annotated, tracker)

        # カウント情報をオーバーレイ
        annotated = self.draw_count_overlay(
            annotated,
            tracker,
            frame_id,
            processing_time_ms
        )

        return annotated

    def _draw_text_with_background(self,
                                   frame: np.ndarray,
                                   text: str,
                                   position: Tuple[int, int],
                                   color: Tuple[int, int, int],
                                   font_scale: float = 0.6):
        """
        背景付きテキストを描画

        Args:
            frame: フレーム
            text: テキスト
            position: 位置 (x, y)
            color: テキスト色
            font_scale: フォントスケール
        """
        # テキストサイズを取得
        (text_width, text_height), baseline = cv2.getTextSize(
            text,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            2
        )

        # 背景を描画
        cv2.rectangle(
            frame,
            (position[0] - 2, position[1] - text_height - 2),
            (position[0] + text_width + 2, position[1] + baseline + 2),
            self.COLOR_BG,
            -1
        )

        # テキストを描画
        cv2.putText(
            frame,
            text,
            position,
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color,
            2
        )
