import sys
from pathlib import Path

import pytest


LINE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(LINE_ROOT))

from detection.config import Line
from detection.line_crossing import (
    LineCrossingDetector,
    LineTransitionState,
    classify_side,
    line_length,
    segment_crossing_geometry,
    segment_crossing_param,
    side_of_line,
    signed_distance,
)


LINE = Line(start=(0, 0), end=(100, 0))


# --- 幾何関数の単体テスト -------------------------------------------------


def test_line_length_horizontal():
    assert line_length(LINE) == pytest.approx(100.0)


def test_signed_distance_is_px_invariant_to_line_length():
    short_line = Line(start=(0, 0), end=(100, 0))
    long_line = Line(start=(0, 0), end=(400, 0))
    # 短い/長いラインそれぞれから同じ物理的な5px離れた点
    d_short = signed_distance((50, 5), short_line)
    d_long = signed_distance((200, 5), long_line)
    assert abs(d_short) == pytest.approx(5.0)
    assert abs(d_long) == pytest.approx(5.0)


def test_signed_distance_sign_matches_side_of_line():
    point_above = (50, 10)
    point_below = (50, -10)
    assert (signed_distance(point_above, LINE) > 0) == (
        side_of_line(point_above, LINE.start, LINE.end) > 0
    )
    assert (signed_distance(point_below, LINE) > 0) == (
        side_of_line(point_below, LINE.start, LINE.end) > 0
    )


def test_classify_side_stable_positive():
    assert classify_side((50, 10), LINE, margin_px=5) == 1


def test_classify_side_stable_negative():
    assert classify_side((50, -10), LINE, margin_px=5) == -1


def test_classify_side_dead_zone():
    assert classify_side((50, 3), LINE, margin_px=5) == 0


def test_classify_side_boundary_is_dead_zone():
    # d == margin_px はどちらの安定側でもなく判定保留帯(境界含む)
    assert classify_side((50, 5.0), LINE, margin_px=5) == 0
    assert classify_side((50, -5.0), LINE, margin_px=5) == 0


def test_segment_crossing_param_interior():
    t = segment_crossing_param((40, -20), (40, 30), LINE)
    assert t == pytest.approx(0.40)


def test_segment_crossing_param_beyond_b_endpoint():
    t = segment_crossing_param((150, -20), (150, 30), LINE)
    assert t == pytest.approx(1.50)


def test_segment_crossing_param_before_a_endpoint():
    t = segment_crossing_param((-30, -20), (-30, 30), LINE)
    assert t == pytest.approx(-0.30)


def test_segment_crossing_param_same_side_returns_none():
    assert segment_crossing_param((40, 10), (60, 20), LINE) is None


def test_segment_crossing_param_on_boundary_same_side_returns_none():
    # 片方がライン上(d=0)で反対側の符号ではない場合はNone
    assert segment_crossing_param((40, 0), (60, 10), LINE) is None


def test_segment_crossing_geometry_returns_line_and_movement_parameters():
    geometry = segment_crossing_geometry((40, -20), (40, 30), LINE)

    assert geometry is not None
    assert geometry.t == pytest.approx(0.40)
    assert geometry.u == pytest.approx(0.40)
    assert geometry.point == pytest.approx((40.0, 0.0))


def test_endpoint_margin_widens_valid_range():
    # t=1.50 のケースを、endpoint_margin_pxを介した許容範囲で判定する
    t = segment_crossing_param((150, -20), (150, 30), LINE)
    line_len = line_length(LINE)

    e_narrow = 0.0 / line_len
    assert not (-e_narrow <= t <= 1.0 + e_narrow)

    e_wide = 60.0 / line_len
    assert -e_wide <= t <= 1.0 + e_wide


def test_side_of_line_still_exported():
    # visualize_lines_and_vehicles.py が直接importして使うため、
    # 削除されていないことを回帰確認する
    value = side_of_line((50, 10), LINE.start, LINE.end)
    assert isinstance(value, float)


# --- ヒステリシス統合テスト(LineCrossingDetector + LineTransitionState) ----


def make_detector(margin_px=5.0, endpoint_margin_px=0.0):
    return LineCrossingDetector(
        line1=LINE,
        line2=Line(start=(0, 200), end=(100, 200)),
        parking_ref_point=(50, 100),  # LINEに対してy>0側 = IN方向
        margin_px=margin_px,
        endpoint_margin_px=endpoint_margin_px,
    )


def test_hysteresis_jitter_inside_dead_zone_never_crosses():
    detector = make_detector(margin_px=5)
    state = LineTransitionState()
    points = [(50, -12), (50, -2), (50, 3), (50, -1), (50, -9)]

    results = [detector.update_line1_crossing(state, p) for p in points]

    assert results == [None, None, None, None, None]
    assert state.stable_side == -1


def test_hysteresis_slow_crossing_detected_exactly_once():
    detector = make_detector(margin_px=5)
    state = LineTransitionState()
    points = [(50, -12), (50, -3), (50, 1), (50, 4), (50, 11), (50, 18)]

    results = [detector.update_line1_crossing(state, p) for p in points]

    assert [result.direction if result else None for result in results] == [
        None, None, None, None, "IN", None
    ]


def test_hysteresis_large_single_frame_jump_still_detected():
    detector = make_detector(margin_px=5)
    state = LineTransitionState()

    assert detector.update_line1_crossing(state, (50, -12)) is None
    result = detector.update_line1_crossing(state, (50, 18))
    assert result.direction == "IN"


def test_hysteresis_extension_flip_reports_no_event_but_updates_stable_side():
    detector = make_detector(margin_px=5, endpoint_margin_px=0.0)
    state = LineTransitionState()

    assert detector.update_line1_crossing(state, (-30, -20)) is None
    assert state.stable_side == -1

    result = detector.update_line1_crossing(state, (-30, 30))

    assert result is None
    assert state.stable_side == 1
    assert state.last_stable_point == (-30, 30)


def test_hysteresis_extension_flip_then_real_crossing_detected():
    detector = make_detector(margin_px=5, endpoint_margin_px=0.0)
    state = LineTransitionState()

    detector.update_line1_crossing(state, (-30, -20))
    detector.update_line1_crossing(state, (-30, 30))  # 延長線での反転(不成立)

    result = detector.update_line1_crossing(state, (50, -20))

    assert result.direction == "OUT"


def test_hysteresis_never_initializes_from_dead_zone_point():
    detector = make_detector(margin_px=5)
    state = LineTransitionState()

    assert detector.update_line1_crossing(state, (50, 3)) is None
    assert state.stable_side is None

    assert detector.update_line1_crossing(state, (50, 10)) is None
    assert state.stable_side == 1


def test_hysteresis_endpoint_margin_zero_rejects_extension_crossing():
    detector = make_detector(margin_px=5, endpoint_margin_px=0.0)
    state = LineTransitionState()

    detector.update_line1_crossing(state, (-30, -20))
    result = detector.update_line1_crossing(state, (-30, 30))

    assert result is None


def test_hysteresis_endpoint_margin_widened_accepts_near_extension_crossing():
    # t=-0.30 の交差(line_length=100) を受理するには e>=0.3 が必要
    detector = make_detector(margin_px=5, endpoint_margin_px=40.0)
    state = LineTransitionState()

    detector.update_line1_crossing(state, (-30, -20))
    result = detector.update_line1_crossing(state, (-30, 30))

    assert result.direction == "IN"
