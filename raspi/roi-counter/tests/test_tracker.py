import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

from src.tracker import VehicleState, VehicleTrack


def test_initial_state():
    t = VehicleTrack(track_id=1)
    assert t.state == VehicleState.UNKNOWN
    assert t.s_history == []
    assert t.counted_as is None
    assert t.counted_frame is None


def test_s_history_independent():
    t1 = VehicleTrack(track_id=1)
    t2 = VehicleTrack(track_id=2)
    t1.s_history.append(0.1)
    assert t2.s_history == []
