import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

from src.progress import calc_s


def test_s_at_y_max():
    assert calc_s(300.0, 100.0, 300.0) == 0.0


def test_s_at_y_min():
    assert calc_s(100.0, 100.0, 300.0) == 1.0


def test_s_midpoint():
    assert abs(calc_s(200.0, 100.0, 300.0) - 0.5) < 1e-9


def test_zero_division_guard():
    assert calc_s(100.0, 100.0, 100.0) == 0.0
