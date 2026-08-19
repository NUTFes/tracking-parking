import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import pytest

from src.roi import (
    check_roi_geometry,
    get_roi_y_range,
    is_convex_quad,
    is_in_roi,
    nearest_vertex_index,
    roi_orientation_sign,
)

ROI = [(100, 100), (300, 100), (300, 300), (100, 300)]


def test_point_inside_roi():
    assert is_in_roi((200.0, 200.0), ROI) is True


def test_point_outside_roi():
    assert is_in_roi((50.0, 50.0), ROI) is False


def test_point_on_boundary():
    assert is_in_roi((100.0, 100.0), ROI) is True


def test_get_roi_y_range():
    y_min, y_max = get_roi_y_range(ROI)
    assert y_min == 100.0
    assert y_max == 300.0


# 実データ（roi-counter/data/inputs/configs/IMG_2787_gt.json）と同じ、
# 要求順序（奥左, 奥右, 入右, 入左）の台形ROI。
TRAPEZOID_ROI = [(690, 430), (1310, 430), (1550, 660), (500, 660)]

# 回転ROI（tests/test_progress.pyのtest_rotated_roi_edge_distance_is_monotonicと同一）。
ROTATED_ROI = [(0.0, 0.0), (70.71, 70.71), (0.0, 141.42), (-70.71, 70.71)]


def test_roi_orientation_sign_is_positive_for_required_order():
    assert roi_orientation_sign(TRAPEZOID_ROI) == 1.0


def test_roi_orientation_sign_is_negative_for_reversed_order():
    reversed_roi = [TRAPEZOID_ROI[1], TRAPEZOID_ROI[0], TRAPEZOID_ROI[3], TRAPEZOID_ROI[2]]
    assert roi_orientation_sign(reversed_roi) == -1.0


def test_is_convex_quad_accepts_trapezoid():
    assert is_convex_quad(TRAPEZOID_ROI) is True


def test_is_convex_quad_accepts_rotated_roi():
    assert is_convex_quad(ROTATED_ROI) is True


def test_is_convex_quad_rejects_self_intersecting_order():
    # p1とp2を入れ替えると辺が交差する「8の字」になる。
    far_left, far_right, near_right, near_left = TRAPEZOID_ROI
    crossed = [far_left, near_right, far_right, near_left]
    assert is_convex_quad(crossed) is False


def test_check_roi_geometry_passes_for_reference_config():
    errors, warnings = check_roi_geometry(TRAPEZOID_ROI)
    assert errors == []
    assert warnings == []


def test_check_roi_geometry_passes_for_rotated_roi():
    # 回転ROIはy方向の前提を満たさないが、順序・凸性は正しいのでエラーなし。
    errors, warnings = check_roi_geometry(ROTATED_ROI)
    assert errors == []


def test_check_roi_geometry_reports_reversed_winding():
    reversed_roi = [TRAPEZOID_ROI[1], TRAPEZOID_ROI[0], TRAPEZOID_ROI[3], TRAPEZOID_ROI[2]]
    errors, warnings = check_roi_geometry(reversed_roi)
    assert any("逆回り" in message for message in errors)


def test_check_roi_geometry_reports_self_intersection():
    far_left, far_right, near_right, near_left = TRAPEZOID_ROI
    crossed = [far_left, near_right, far_right, near_left]
    errors, warnings = check_roi_geometry(crossed)
    assert any("自己交差" in message for message in errors)


def test_check_roi_geometry_warns_when_far_edge_is_below_near_edge():
    # TRAPEZOID_ROIを2つ回転させた並び。同じ多角形なので巻き方向・凸性は
    # 保たれるが、far/nearのラベル対応がずれ「入口側から先に打った」形になる。
    far_left, far_right, near_right, near_left = TRAPEZOID_ROI
    rotated_start = [near_right, near_left, far_left, far_right]
    errors, warnings = check_roi_geometry(rotated_start)
    assert errors == []
    assert any("順序を取り違えて" in message for message in warnings)


def test_check_roi_geometry_warns_for_degenerate_short_edge():
    tiny_edge = [(690, 430), (695, 430), (1550, 660), (500, 660)]
    errors, warnings = check_roi_geometry(tiny_edge)
    assert any("最短辺" in message for message in warnings)


def test_check_roi_geometry_raises_validation_errors_first():
    errors, warnings = check_roi_geometry([(0, 0), (1, 0), (1, 1)])
    assert any("4頂点" in message for message in errors)
    assert warnings == []


def test_nearest_vertex_index_returns_index_within_radius():
    points = [(10, 10), (20, 10), (20, 20), (10, 20)]
    assert nearest_vertex_index(points, 11, 11, radius=5) == 0


def test_nearest_vertex_index_returns_none_outside_radius():
    points = [(10, 10), (20, 10), (20, 20), (10, 20)]
    assert nearest_vertex_index(points, 100, 100, radius=5) is None


def test_nearest_vertex_index_returns_closest_of_two_candidates():
    points = [(0, 0), (10, 0), (100, 100)]
    assert nearest_vertex_index(points, 4, 0, radius=50) == 0
    assert nearest_vertex_index(points, 6, 0, radius=50) == 1
