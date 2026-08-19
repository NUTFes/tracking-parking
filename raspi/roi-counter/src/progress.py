from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeAlias

import cv2
import numpy as np


Point: TypeAlias = tuple[float, float]
RoiPoints: TypeAlias = Sequence[tuple[float, float]]
ProgressFn: TypeAlias = Callable[[Point, RoiPoints], float]

# calc_s_edge_distance・iso_s_segment が共有する透視変換の写像先。
# OpenCVの画像座標で、上側の奥辺をv=1、下側の入口辺をv=0へ対応させる。
# ここに1箇所だけ持ち、視覚化側（visualizer.py）には複製しない。
_DESTINATION = np.array(
    [[0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]],
    dtype=np.float32,
)


def calc_s_y_normalized(y: float, y_min: float, y_max: float) -> float:
    """ROIのy範囲だけを使って進行度を計算する。

    y=y_max（ROI入口側）を0.0、y=y_min（ROI奥側）を1.0とする。
    """
    if y_max == y_min:
        return 0.0
    return (y_max - y) / (y_max - y_min)


def validate_roi_points(roi_points: RoiPoints) -> np.ndarray:
    """4頂点・数値・有限であることだけを検証する（順序・凸性は見ない）。

    順序・凸性の検証は src/roi.py の check_roi_geometry が担う。
    """
    if len(roi_points) != 4:
        raise ValueError("ROIは4頂点で指定する必要があります")
    try:
        points = np.asarray(roi_points, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ValueError("ROI頂点は数値の(x, y)で指定する必要があります") from exc
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError("ROI頂点は有限な(x, y)の4点で指定する必要があります")
    return points


def calc_s_edge_distance(point: Point, roi_points: RoiPoints) -> float:
    """入口辺から奥辺までの透視変換上の正規化距離を返す。

    ROI頂点は「奥側左、奥側右、入口側右、入口側左」の順序で指定する。
    入口辺をs=0、奥辺をs=1へ写像する。ROI外の点では0未満または1超の
    値を返すことがあるが、検出処理ではROI内の点だけを渡す。
    """
    points = validate_roi_points(roi_points)
    try:
        point_array = np.asarray(point, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ValueError("pointは数値の(x, y)で指定する必要があります") from exc
    if point_array.shape != (2,) or not np.isfinite(point_array).all():
        raise ValueError("pointは有限な(x, y)で指定する必要があります")

    try:
        transform = cv2.getPerspectiveTransform(points, _DESTINATION)
        mapped = cv2.perspectiveTransform(point_array.reshape(1, 1, 2), transform)
    except cv2.error as exc:
        raise ValueError("ROIから進行度変換を構成できません") from exc
    return float(mapped[0, 0, 1])


def iso_s_segment(s: float, roi_points: RoiPoints) -> tuple[Point, Point]:
    """edge_distance方式で進行度がsになる線分の両端点を、画像座標で返す。

    calc_s_edge_distanceが使う透視変換（_DESTINATION）の逆写像で
    (0, s) と (1, s) を画像座標へ戻す。同一の変換を逆に使うだけなので、
    このセグメント上の任意の点をcalc_s_edge_distanceに通すと、
    誤差の範囲でsが返ることが構成上保証される。

    描画（visualizer.draw_band_lines_edge_distance）が実際の判定と
    一致することを保証するための幾何関数。可視化ロジックはvisualizer.py側に
    置き、ここでは幾何計算のみを行う。
    """
    points = validate_roi_points(roi_points)
    try:
        inverse = cv2.getPerspectiveTransform(_DESTINATION, points)
        ends = cv2.perspectiveTransform(
            np.array([[[0.0, s], [1.0, s]]], dtype=np.float32), inverse
        )
    except cv2.error as exc:
        raise ValueError("ROIから進行度変換を構成できません") from exc
    start = (float(ends[0, 0, 0]), float(ends[0, 0, 1]))
    end = (float(ends[0, 1, 0]), float(ends[0, 1, 1]))
    return start, end


def _calc_s_y_normalized_from_point(point: Point, roi_points: RoiPoints) -> float:
    points = validate_roi_points(roi_points)
    y_min = float(points[:, 1].min())
    y_max = float(points[:, 1].max())
    return calc_s_y_normalized(float(point[1]), y_min, y_max)


PROGRESS_METHODS: dict[str, ProgressFn] = {
    "y_normalized": _calc_s_y_normalized_from_point,
    "edge_distance": calc_s_edge_distance,
}


def get_progress_fn(name: str) -> ProgressFn:
    """名前から統一シグネチャの進行度計算関数を取得する。"""
    try:
        return PROGRESS_METHODS[name]
    except KeyError as exc:
        available = ", ".join(sorted(PROGRESS_METHODS))
        raise ValueError(f"未知のprogress_method: {name!r}（利用可能: {available}）") from exc


# 既存のテストとscripts/03_sweep_params.py向けの後方互換alias。
calc_s = calc_s_y_normalized

# src/roi_config.py・src/roi.py（roi_setup/）向けの公開名。旧名は内部・外部の
# 呼び出し互換のために残す。
_validate_roi_points = validate_roi_points
