#!/usr/bin/env python3
"""
GUI ROI座標設定ツール

設定JSON（data/inputs/configs/*.json）が指す動画の1フレームを表示し、
マウスクリックで以下の4点を設定する:
1. 奥側左 (far_left)
2. 奥側右 (far_right)
3. 入口側右 (near_right)
4. 入口側左 (near_left)

この順序は src/progress.py の calc_s_edge_distance（edge_distance方式）が
要求する順序と同一。順序を間違えると透視変換が壊れるため、頂点は必ず
この順にクリックすること。

このツールが編集するのはROI4頂点だけ。s_low/s_highは設定JSONから読んで
確認表示するのみで、書き込まない（無次元の進行度閾値はスイープの検証結果に
従うべきで、手動決定の対象ではないため）。

設定完了後、`s`キーで明示的に保存する。保存すると:
- クリーンな参照フレーム（ROI線等を焼き込まないフレーム）を
  data/inputs/reference_frames/ へPNGとして保存
- 設定JSONの`roi`と`roi_setup`キーだけを更新（in/out/events/
  tolerance_sec・未知キーはそのまま保持）
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parents[1]))          # roi-counter/
sys.path.insert(0, str(Path(__file__).parents[2]))          # raspi/（common共有のため）

import cv2

from common.frame_timing import sha256_file
from src.roi import VERTEX_ORDER, check_roi_geometry, nearest_vertex_index
from src.roi_config import (
    build_roi_setup_metadata,
    load_roi_config,
    resolve_reference_frame_path,
    roi_points_changed,
    update_roi_config,
    write_roi_config,
)
from src.visualizer import draw_band_lines_for_method, draw_grid, draw_roi

HIT_RADIUS_PX = 12.0
SEEK_SMALL_SEC = 1.0
SEEK_LARGE_SEC = 10.0

# src.roi.VERTEX_ORDER（= edge_distance方式が要求する頂点順序）から
# 日本語ラベルを生成する。二重管理を避けるため、日本語名の対応表だけを持つ。
_VERTEX_LABELS_JA = {
    "far_left": "奥側左",
    "far_right": "奥側右",
    "near_right": "入口側右",
    "near_left": "入口側左",
}
LABELS = [
    f"{i + 1}. {_VERTEX_LABELS_JA[name]} ({name})"
    for i, name in enumerate(VERTEX_ORDER)
]


class RoiSetupGUI:
    """ROI4頂点設定GUI"""

    def __init__(self, config_path: str, seek_sec: float, progress_method: str):
        self.config_path = Path(config_path)
        self.cfg = load_roi_config(self.config_path)

        self.cap = cv2.VideoCapture(self.cfg.video)
        if not self.cap.isOpened():
            raise RuntimeError(f"動画/カメラを開けません: {self.cfg.video}")

        self.points: List[Tuple[int, int]] = list(self.cfg.roi)
        self.dragging_index: Optional[int] = None

        self.show_grid = False
        self.progress_method = progress_method

        self.frame = None
        self.display_frame = None
        self.frame_index: Optional[int] = None
        self.position_sec: Optional[float] = None

        self._last_messages: Tuple[str, ...] = ()
        self.window_name = "ROI座標設定"

        self._is_camera = isinstance(self.cfg.video, int)
        if not self._seek_to(seek_sec):
            raise RuntimeError("初期フレームを取得できませんでした")

    # ── フレーム取得 ────────────────────────────────────────────────

    def _seek_to(self, sec: float) -> bool:
        """指定秒数へシークして1フレーム読み込む（カメラ入力ではno-op）。"""
        if self._is_camera:
            print("警告: ライブ入力ではシークできません（spaceキーで再取得してください）")
            return self._refresh_frame()

        self.cap.set(cv2.CAP_PROP_POS_MSEC, max(sec, 0.0) * 1000.0)
        return self._refresh_frame()

    def _refresh_frame(self) -> bool:
        """現在位置から1フレーム読み込み、実測位置を読み戻す。"""
        ret, frame = self.cap.read()
        if not ret:
            print("エラー: フレームを取得できません")
            return False

        self.frame = frame
        self.frame_index = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
        pos_msec = self.cap.get(cv2.CAP_PROP_POS_MSEC)
        self.position_sec = pos_msec / 1000.0 if pos_msec >= 0 else None
        return True

    def _seek_relative(self, delta_sec: float) -> None:
        if self._is_camera:
            print("警告: ライブ入力ではシークできません（spaceキーで再取得してください）")
            return
        current = self.position_sec or 0.0
        self._seek_to(current + delta_sec)
        self.update_display()

    # ── マウス操作 ──────────────────────────────────────────────────

    def mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            hit = nearest_vertex_index(self.points, x, y, HIT_RADIUS_PX)
            if hit is not None:
                self.dragging_index = hit
            elif len(self.points) < 4:
                self.points.append((x, y))
                print(f"✓ {LABELS[len(self.points) - 1]}: ({x}, {y})")
            self.update_display()

        elif event == cv2.EVENT_MOUSEMOVE:
            if self.dragging_index is not None:
                self.points[self.dragging_index] = (x, y)
                self.update_display()

        elif event == cv2.EVENT_LBUTTONUP:
            if self.dragging_index is not None:
                i = self.dragging_index
                print(f"✓ 頂点{i}（{LABELS[i]}）を移動: {self.points[i]}")
                self.dragging_index = None
                self.update_display()

    # ── 描画 ────────────────────────────────────────────────────────

    def update_display(self) -> None:
        self.display_frame = self.frame.copy()

        if self.show_grid:
            draw_grid(self.display_frame)

        if self.points:
            draw_roi(self.display_frame, self.points)

        errors: List[str] = []
        warnings: List[str] = []
        if len(self.points) == 4:
            errors, warnings = check_roi_geometry(self.points)
            if not errors:
                draw_band_lines_for_method(
                    self.display_frame, self.points,
                    self.cfg.s_low, self.cfg.s_high, self.progress_method,
                )

        self._render_status_text(errors, warnings)
        self._log_message_changes(errors, warnings)

        cv2.imshow(self.window_name, self.display_frame)

    def _render_status_text(self, errors: List[str], warnings: List[str]) -> None:
        y = 24
        if len(self.points) < 4:
            text = f"次: {LABELS[len(self.points)]} をクリック"
            cv2.putText(self.display_frame, text, (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            y += 28
        else:
            status = (
                f"s_low={self.cfg.s_low} s_high={self.cfg.s_high} "
                f"method={self.progress_method}"
            )
            cv2.putText(self.display_frame, status, (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
            y += 26

        for message in errors:
            cv2.putText(self.display_frame, f"エラー: {message}", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
            y += 22
        for message in warnings:
            cv2.putText(self.display_frame, f"警告: {message}", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 200), 2)
            y += 22

        pos_text = f"frame={self.frame_index}  t={self.position_sec:.2f}s" \
            if self.position_sec is not None else f"frame={self.frame_index}"
        h = self.display_frame.shape[0]
        cv2.putText(self.display_frame, pos_text, (10, h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

    def _log_message_changes(self, errors: List[str], warnings: List[str]) -> None:
        messages = tuple(f"エラー: {m}" for m in errors) + tuple(f"警告: {m}" for m in warnings)
        if messages != self._last_messages:
            for message in messages:
                print(message)
            self._last_messages = messages

    # ── キー操作 ────────────────────────────────────────────────────

    def _undo(self) -> None:
        if self.dragging_index is not None:
            print("警告: ドラッグ中は操作できません")
            return
        if not self.points:
            return
        removed = self.points.pop()
        print(f"✓ 直前の点を取り消しました: {removed}")
        self.update_display()

    def _reset(self) -> None:
        if self.dragging_index is not None:
            print("警告: ドラッグ中は操作できません")
            return
        self.points = []
        self._last_messages = ()
        print("\nやり直します。以下の順番で4点をクリックしてください:")
        for label in LABELS:
            print(f"  {label}")
        self.update_display()

    def _toggle_method(self) -> None:
        self.progress_method = (
            "edge_distance" if self.progress_method == "y_normalized" else "y_normalized"
        )
        print(f"✓ 表示方式を切り替えました: {self.progress_method}（設定には書き込みません）")
        self.update_display()

    def _toggle_grid(self) -> None:
        self.show_grid = not self.show_grid
        self.update_display()

    def _save(self) -> None:
        if len(self.points) != 4:
            print(f"警告: 4点すべてが設定されていません（{len(self.points)}/4）。保存できません。")
            return

        errors, _ = check_roi_geometry(self.points)
        if errors:
            print("エラー: 頂点の妥当性エラーがあるため保存できません:")
            for message in errors:
                print(f"  - {message}")
            return

        roi_points = tuple(self.points)
        if not roi_points_changed(self.cfg.raw, roi_points):
            print("変更がないため保存をスキップしました。")
            return

        sha256_file.cache_clear()
        old_sha256 = sha256_file(str(self.config_path))

        now = datetime.now().astimezone()
        ref_path = resolve_reference_frame_path(self.cfg.video, timestamp=now)
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        # self.frame（クリーンなフレーム）を書く。self.display_frameは
        # ROI線・グリッド・テキストが焼き込まれているため使わない。
        cv2.imwrite(str(ref_path), self.frame)

        sha256_file.cache_clear()
        ref_sha256 = sha256_file(str(ref_path))

        source_sha256 = None if self._is_camera else sha256_file(self.cfg.video)

        metadata = build_roi_setup_metadata(
            frame_width=self.frame.shape[1],
            frame_height=self.frame.shape[0],
            baseline_roi=roi_points,
            reference_frame_path=str(ref_path),
            reference_frame_sha256=ref_sha256,
            source=self.cfg.video,
            source_sha256=source_sha256,
            frame_index=self.frame_index,
            position_sec=self.position_sec,
            set_by=os.environ.get("USER", "unknown"),
            now=now,
        )

        updated, _ = update_roi_config(self.cfg.raw, roi_points, metadata)
        write_roi_config(self.config_path, updated)

        sha256_file.cache_clear()
        new_sha256 = sha256_file(str(self.config_path))

        print(f"\n✓ 保存しました: {self.config_path}")
        print(f"  参照フレーム: {ref_path}")
        print(f"  ground_truth_sha256: {old_sha256} → {new_sha256}")
        print("  （condition_keyもこれに伴って変わります）")

        # ここで読み直し、以後のroi_points_changedが直近の保存済み状態を
        # 正しく基準にするようにする。
        self.cfg = load_roi_config(self.config_path)

    # ── メインループ ────────────────────────────────────────────────

    def run(self) -> None:
        cv2.namedWindow(self.window_name)
        cv2.setMouseCallback(self.window_name, self.mouse_callback)

        print("=" * 60)
        print("ROI座標設定ツール")
        print("=" * 60)
        print("\n以下の順番で4点をクリックしてください:\n")
        for label in LABELS:
            print(f"  {label}")
        print("\n操作:")
        print("  - 左クリック: 点を設定 / 既存の点の近くをクリック&ドラッグで移動")
        print("  - 'u'キー: 直前の点を取り消し")
        print("  - 'r'キー: 全リセット")
        print("  - '.'/','キー: 1秒 進む/戻る（動画のみ）")
        print("  - ']'/'['キー: 10秒 進む/戻る（動画のみ）")
        print("  - 'space'キー: 現在位置を再取得（カメラではこれが唯一の更新手段）")
        print("  - 'm'キー: 表示方式の切り替え（y_normalized / edge_distance、表示のみ）")
        print("  - 'g'キー: グリッド表示の切り替え")
        print("  - 's'キー: 保存（エラーがあると保存できません）")
        print("  - 'q'キーまたはウィンドウを閉じる: 終了（保存せずに終了）")
        print("=" * 60)

        self.update_display()

        while True:
            key = cv2.waitKey(1) & 0xFF

            if key == ord('q') or cv2.getWindowProperty(self.window_name, cv2.WND_PROP_VISIBLE) < 1:
                break
            elif key == ord('u'):
                self._undo()
            elif key == ord('r'):
                self._reset()
            elif key == ord('.'):
                self._seek_relative(SEEK_SMALL_SEC)
            elif key == ord(','):
                self._seek_relative(-SEEK_SMALL_SEC)
            elif key == ord(']'):
                self._seek_relative(SEEK_LARGE_SEC)
            elif key == ord('['):
                self._seek_relative(-SEEK_LARGE_SEC)
            elif key == ord(' '):
                if self._refresh_frame():
                    self.update_display()
            elif key == ord('m'):
                self._toggle_method()
            elif key == ord('g'):
                self._toggle_grid()
            elif key == ord('s'):
                self._save()

        self.cap.release()
        cv2.destroyAllWindows()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GUIでROI4頂点を設定（設定JSONのroi/roi_setupキーを更新）"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="設定ファイルのパス（例: data/inputs/configs/IMG_2787_gt.json）",
    )
    parser.add_argument(
        "--seek-sec",
        type=float,
        default=0.0,
        help="初期表示するフレームの秒数（既定: 0.0、動画のみ）",
    )
    parser.add_argument(
        "--progress-method",
        default=os.environ.get("PROGRESS_METHOD", "y_normalized"),
        choices=["y_normalized", "edge_distance"],
        help="初期の等s線表示方式（表示のみ。設定には書き込まない）",
    )

    args = parser.parse_args()

    if not os.path.exists(args.config):
        print(f"エラー: 設定ファイルが見つかりません: {args.config}")
        return 1

    try:
        gui = RoiSetupGUI(args.config, args.seek_sec, args.progress_method)
    except (RuntimeError, ValueError) as exc:
        print(f"エラー: {exc}")
        return 1

    gui.run()
    print("\n完了!")
    return 0


if __name__ == "__main__":
    exit(main())
