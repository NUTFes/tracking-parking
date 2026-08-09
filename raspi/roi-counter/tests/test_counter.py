import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

from src.counter import Counter
from src.tracker import VehicleState


def test_entry_counted():
    c = Counter(s_low=0.25, s_high=0.75)
    for s in [0.1, 0.3, 0.5, 0.8]:
        c.update(1, s)
    assert c.count_in == 1
    assert c.count_out == 0
    assert c.tracks[1].counted_as == "IN"


def test_exit_counted():
    c = Counter(s_low=0.25, s_high=0.75)
    for s in [0.9, 0.6, 0.3, 0.1]:
        c.update(1, s)
    assert c.count_out == 1
    assert c.count_in == 0
    assert c.tracks[1].counted_as == "OUT"


def test_no_count_if_turned_back():
    c = Counter(s_low=0.25, s_high=0.75)
    for s in [0.1, 0.3, 0.5, 0.3, 0.2]:
        c.update(1, s)
    assert c.count_in == 0
    assert c.count_out == 0
    assert c.tracks[1].state == VehicleState.IN_CANDIDATE


def test_no_duplicate_count():
    c = Counter(s_low=0.25, s_high=0.75)
    for s in [0.1, 0.8]:
        c.update(1, s)
    assert c.count_in == 1
    c.update(1, 0.9)
    assert c.count_in == 1


def test_starts_in_central_band():
    # 中央バンドから開始し奥側バンドに達した場合
    # → UNKNOWN のまま中央を通過し，奥側で OUT_CANDIDATE に遷移する
    # → 入口側バンドに到達しない限りカウントされない
    c = Counter(s_low=0.25, s_high=0.75)
    for s in [0.5, 0.8]:
        c.update(1, s)
    assert c.count_in == 0
    assert c.count_out == 0
    assert c.tracks[1].state == VehicleState.OUT_CANDIDATE


def test_counted_frame_recorded_on_in_transition():
    c = Counter(s_low=0.25, s_high=0.75)
    for frame_idx, s in enumerate([0.1, 0.3, 0.5, 0.8]):
        c.update(1, s, frame_idx)
    assert c.tracks[1].counted_frame == 3


def test_counted_frame_recorded_on_out_transition():
    c = Counter(s_low=0.25, s_high=0.75)
    for frame_idx, s in enumerate([0.9, 0.6, 0.3, 0.1]):
        c.update(1, s, frame_idx)
    assert c.tracks[1].counted_frame == 3


def test_counted_frame_is_none_when_frame_index_omitted():
    c = Counter(s_low=0.25, s_high=0.75)
    for s in [0.1, 0.3, 0.5, 0.8]:
        c.update(1, s)
    assert c.count_in == 1
    assert c.tracks[1].counted_frame is None


def test_counted_frame_not_overwritten_after_counted():
    c = Counter(s_low=0.25, s_high=0.75)
    for frame_idx, s in enumerate([0.1, 0.8]):
        c.update(1, s, frame_idx)
    assert c.tracks[1].counted_frame == 1
    c.update(1, 0.9, 99)
    assert c.tracks[1].counted_frame == 1


def test_counted_frame_stays_none_before_transition():
    c = Counter(s_low=0.25, s_high=0.75)
    c.update(1, 0.1, 0)
    assert c.tracks[1].counted_frame is None
