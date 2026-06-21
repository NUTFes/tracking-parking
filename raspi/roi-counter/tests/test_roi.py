import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

from src.roi import is_in_roi, get_roi_y_range

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
