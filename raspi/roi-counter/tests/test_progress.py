import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import pytest

from src.progress import (
    PROGRESS_METHODS,
    _validate_roi_points,
    calc_s,
    calc_s_edge_distance,
    calc_s_y_normalized,
    get_progress_fn,
    iso_s_segment,
    validate_roi_points,
)

# 正方形・台形・回転ROI。台形・回転は上のテストで使っている座標と同一にし、
# 期待値の根拠を再利用する。
_SQUARE_ROI = [(0, 0), (100, 0), (100, 100), (0, 100)]
_TRAPEZOID_ROI = [(20, 0), (80, 0), (100, 100), (0, 100)]
_ROTATED_ROI = [(0.0, 0.0), (70.71, 70.71), (0.0, 141.42), (-70.71, 70.71)]


def test_s_at_y_max():
    assert calc_s(300.0, 100.0, 300.0) == 0.0


def test_s_at_y_min():
    assert calc_s(100.0, 100.0, 300.0) == 1.0


def test_s_midpoint():
    assert abs(calc_s(200.0, 100.0, 300.0) - 0.5) < 1e-9


def test_zero_division_guard():
    assert calc_s(100.0, 100.0, 100.0) == 0.0


def test_calc_s_alias_is_y_normalized():
    assert calc_s is calc_s_y_normalized
    assert get_progress_fn("y_normalized")((50.0, 200.0), [(0, 100), (100, 100), (100, 300), (0, 300)]) == 0.5


def test_square_roi_methods_agree():
    roi = [(0, 0), (100, 0), (100, 100), (0, 100)]
    point = (50.0, 50.0)
    assert calc_s_edge_distance(point, roi) == pytest.approx(0.5)
    assert get_progress_fn("y_normalized")(point, roi) == pytest.approx(0.5)


def test_trapezoid_methods_differ_quantitatively():
    roi = [(20, 0), (80, 0), (100, 100), (0, 100)]
    point = (50.0, 50.0)
    assert calc_s_y_normalized(point[1], 0.0, 100.0) == pytest.approx(0.5)
    assert calc_s_edge_distance(point, roi) == pytest.approx(0.375)

    near_right = (80.0, 50.0)
    assert calc_s_edge_distance(near_right, roi) != pytest.approx(
        calc_s_y_normalized(near_right[1], 0.0, 100.0)
    )


def test_rotated_roi_edge_distance_is_monotonic():
    roi = [(0.0, 0.0), (70.71, 70.71), (0.0, 141.42), (-70.71, 70.71)]
    points = [
        (35.355, 35.355), (17.6775, 52.6775), (0.0, 70.71),
        (-17.6775, 88.7425), (-35.355, 105.355),
    ]
    values = [calc_s_edge_distance(point, roi) for point in points]
    assert values == pytest.approx([1.0, 0.75, 0.5, 0.25, 0.0], abs=1e-2)
    y_values = [calc_s_y_normalized(point[1], 0.0, 141.42) for point in points]
    assert y_values != pytest.approx(values, abs=1e-2)


def test_progress_method_registry_and_validation():
    assert set(PROGRESS_METHODS) == {"y_normalized", "edge_distance"}
    with pytest.raises(ValueError):
        get_progress_fn("unknown")
    with pytest.raises(ValueError):
        calc_s_edge_distance((0.0, 0.0), [(0, 0), (1, 0), (1, 1)])


def test_validate_roi_points_public_alias():
    assert _validate_roi_points is validate_roi_points


@pytest.mark.parametrize("roi", [_SQUARE_ROI, _TRAPEZOID_ROI, _ROTATED_ROI])
@pytest.mark.parametrize("s", [0.15, 0.5, 0.6])
def test_iso_s_segment_endpoints_have_requested_s(roi, s):
    # 描画（visualizer.draw_band_lines_edge_distance）が実際の判定境界と
    # 一致することを保証する要のテスト。iso_s_segmentが返す線分の両端点を
    # 実際の判定関数calc_s_edge_distanceへ通し、要求したsが返ることを固定する。
    start, end = iso_s_segment(s, roi)
    assert calc_s_edge_distance(start, roi) == pytest.approx(s, abs=1e-4)
    assert calc_s_edge_distance(end, roi) == pytest.approx(s, abs=1e-4)


def test_iso_s_segment_is_horizontal_for_axis_aligned_rectangle():
    start, end = iso_s_segment(0.25, _SQUARE_ROI)
    assert start[1] == pytest.approx(end[1])


def test_iso_s_segment_matches_draw_band_lines_y_for_rectangle():
    # 矩形ROIではy_normalizedの水平線とedge_distanceの等s線が一致する
    # （src/visualizer.pyのdraw_band_linesが使うy=y_max-s*(y_max-y_min)と
    # 同じ高さになる）。tests/test_visualizer.pyのs_low=0.25の期待値と揃える。
    roi = [(100, 100), (300, 100), (300, 200), (100, 200)]
    start, end = iso_s_segment(0.25, roi)
    assert start[1] == pytest.approx(175.0)
    assert end[1] == pytest.approx(175.0)


def test_iso_s_segment_rejects_degenerate_roi():
    with pytest.raises(ValueError):
        iso_s_segment(0.5, [(0, 0), (1, 0), (1, 1)])
