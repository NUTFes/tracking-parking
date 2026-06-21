import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import numpy as np

from src.tracker import VehicleState
from src.visualizer import draw_band_lines, draw_bbox_with_info, draw_counts, draw_roi

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
