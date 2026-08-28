import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import numpy as np
import pytest

from src.tracker import VehicleState
from src.visualizer import (
    draw_band_lines,
    draw_band_lines_edge_distance,
    draw_band_lines_for_method,
    draw_bbox_with_info,
    draw_counts,
    draw_grid,
    draw_roi,
)

ROI = [(100, 100), (300, 100), (300, 200), (100, 200)]


def make_frame():
    return np.zeros((300, 400, 3), dtype=np.uint8)


def test_draw_roi_no_error():
    draw_roi(make_frame(), ROI)


def test_draw_band_lines_no_error():
    draw_band_lines(make_frame(), ROI, 100.0, 200.0, 0.25, 0.75)


def test_draw_band_lines_draws_on_frame():
    frame = make_frame()
    draw_band_lines(frame, ROI, 100.0, 200.0, 0.25, 0.75)
    assert frame.sum() > 0


def test_draw_band_lines_s_low_y():
    # s_low=0.25 → y = 200 - 0.25*(200-100) = 175
    # s_high=0.75 → y = 200 - 0.75*(200-100) = 125
    # 両ラインが描画されたあとにフレームが変化していることを確認
    frame = make_frame()
    draw_band_lines(frame, ROI, 100.0, 200.0, 0.25, 0.75)
    assert frame[175, 200].sum() > 0  # s_low ライン上のピクセル
    assert frame[125, 200].sum() > 0  # s_high ライン上のピクセル


def test_draw_counts_no_error():
    draw_counts(make_frame(), 3, 1)


def test_draw_bbox_with_info_no_error():
    draw_bbox_with_info(make_frame(), (50, 50, 150, 150), 1, 0.5, VehicleState.IN_CANDIDATE)


def test_draw_grid_draws_on_frame():
    frame = make_frame()
    draw_grid(frame)
    assert frame.sum() > 0


def test_draw_band_lines_edge_distance_no_error():
    draw_band_lines_edge_distance(make_frame(), ROI, 0.25, 0.75)


def test_draw_band_lines_edge_distance_draws_on_frame():
    frame = make_frame()
    draw_band_lines_edge_distance(frame, ROI, 0.25, 0.75)
    assert frame.sum() > 0


def test_draw_band_lines_for_method_y_normalized_matches_draw_band_lines():
    # ROIは正方形なのでy_normalizedとdraw_band_linesの直接呼び出しは
    # 同一のピクセルを描く。
    frame_a = make_frame()
    draw_band_lines(frame_a, ROI, 100.0, 200.0, 0.25, 0.75)

    frame_b = make_frame()
    draw_band_lines_for_method(frame_b, ROI, 0.25, 0.75, "y_normalized")

    assert np.array_equal(frame_a, frame_b)


def test_draw_band_lines_for_method_edge_distance_matches_direct_call():
    frame_a = make_frame()
    draw_band_lines_edge_distance(frame_a, ROI, 0.25, 0.75)

    frame_b = make_frame()
    draw_band_lines_for_method(frame_b, ROI, 0.25, 0.75, "edge_distance")

    assert np.array_equal(frame_a, frame_b)


def test_draw_band_lines_for_method_rejects_unknown_method():
    with pytest.raises(ValueError):
        draw_band_lines_for_method(make_frame(), ROI, 0.25, 0.75, "unknown")
