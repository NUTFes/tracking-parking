import cv2
import numpy as np
from typing import List, Optional, Tuple

from .progress import calc_s_edge_distance, validate_roi_points

# GUI・progress.py（edge_distance方式）が要求する頂点順序。
VERTEX_ORDER = ("far_left", "far_right", "near_right", "near_left")


def is_in_roi(point: Tuple[float, float], roi_points: List[Tuple[int, int]]) -> bool:
    contour = np.array(roi_points, dtype=np.float32)
    return cv2.pointPolygonTest(contour, point, False) >= 0


def get_roi_y_range(roi_points: List[Tuple[int, int]]) -> Tuple[float, float]:
    ys = [p[1] for p in roi_points]
    return float(min(ys)), float(max(ys))


def roi_orientation_sign(roi_points: List[Tuple[float, float]]) -> float:
    """頂点列のshoelace公式による符号付き面積の符号を返す。

    画像座標系（y下向き）で、要求順序 [奥左, 奥右, 入右, 入左] は正になる。
    退化（面積0）の場合は0.0を返す。
    """
    xs = [p[0] for p in roi_points]
    ys = [p[1] for p in roi_points]
    n = len(roi_points)
    area2 = 0.0
    for i in range(n):
        j = (i + 1) % n
        area2 += xs[i] * ys[j] - xs[j] * ys[i]
    if area2 > 0:
        return 1.0
    if area2 < 0:
        return -1.0
    return 0.0


def is_convex_quad(roi_points: List[Tuple[float, float]]) -> bool:
    """4頂点が単純（自己交差なし）な凸多角形をなすかを判定する。

    連続する3頂点の外積の符号が全て一致していれば凸（自己交差もしない）。
    退化（外積が0の辺を含む）場合はFalseとする。
    """
    if len(roi_points) != 4:
        return False
    n = len(roi_points)
    signs = []
    for i in range(n):
        ax, ay = roi_points[i]
        bx, by = roi_points[(i + 1) % n]
        cx, cy = roi_points[(i + 2) % n]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if cross == 0:
            return False
        signs.append(cross > 0)
    return all(signs) or not any(signs)


def check_roi_geometry(
    roi_points: List[Tuple[float, float]],
) -> Tuple[List[str], List[str]]:
    """ROI4頂点の妥当性を検証し、(errors, warnings) を返す。

    errors: 保存をブロックすべき問題（順序が奥左→奥右→入右→入左の凸四角形を
    なしていない等）。
    warnings: 保存は妨げないが誤クリックの疑いがある問題。
    """
    errors: List[str] = []
    warnings: List[str] = []

    # progress.pyのvalidate_roi_points相当（4点・数値・有限）を先に満たさない
    # 限り、以降の幾何判定は意味を持たない。
    try:
        points = validate_roi_points(roi_points)
    except ValueError as exc:
        errors.append(str(exc))
        return errors, warnings

    pts = [(float(x), float(y)) for x, y in points]

    if not is_convex_quad(pts):
        errors.append(
            "頂点が自己交差しているか凹んでいます。"
            "奥側左→奥側右→入口側右→入口側左の順で凸四角形になるように打ち直してください。"
        )
        return errors, warnings

    if roi_orientation_sign(pts) < 0:
        errors.append(
            "頂点の順序が逆回りです。"
            "奥側左→奥側右→入口側右→入口側左の順でクリックしてください。"
        )
        return errors, warnings

    try:
        calc_s_edge_distance(pts[0], pts)
    except ValueError as exc:
        errors.append(f"ROIから進行度変換を構成できません: {exc}")
        return errors, warnings

    far_left, far_right, near_right, near_left = pts
    far_y = (far_left[1] + far_right[1]) / 2.0
    near_y = (near_right[1] + near_left[1]) / 2.0
    if far_y >= near_y:
        warnings.append(
            "奥側の辺が入口側の辺より下（画面手前）にあります。"
            "頂点の順序を取り違えていないか確認してください。"
        )

    min_edge = min(
        _dist(pts[i], pts[(i + 1) % 4]) for i in range(4)
    )
    if min_edge < 10.0:
        warnings.append(f"最短辺が{min_edge:.1f}pxと非常に短く、誤クリックの疑いがあります。")

    min_vertex_gap = min(
        _dist(pts[i], pts[j])
        for i in range(4)
        for j in range(i + 1, 4)
    )
    if min_vertex_gap < 20.0:
        warnings.append(
            f"最も近い頂点間の距離が{min_vertex_gap:.1f}pxしかありません。"
            "誤クリックの疑いがあります。"
        )

    return errors, warnings


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return float(np.hypot(a[0] - b[0], a[1] - b[1]))


def nearest_vertex_index(
    points: List[Tuple[int, int]],
    x: float,
    y: float,
    radius: float,
) -> Optional[int]:
    """(x, y)から半径radius以内にある最も近い頂点のインデックスを返す。

    該当する頂点が無ければNone。同距離の候補が複数あるときは、pointsで
    先に現れる方（インデックスが小さい方）を返す。
    """
    best_index: Optional[int] = None
    best_dist = radius
    for i, p in enumerate(points):
        d = _dist(p, (x, y))
        if d <= best_dist:
            if best_index is None or d < best_dist:
                best_index = i
                best_dist = d
    return best_index
