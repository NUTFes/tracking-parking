import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

from src.tracker import CountedEvent, VehicleState, VehicleTrack


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


def test_track_metadata_defaults_are_empty():
    track = VehicleTrack(track_id=1)

    assert track.first_seen_frame is None
    assert track.last_seen_frame is None
    assert track.s_min is None
    assert track.s_max is None
    assert track.s_first is None
    assert track.s_last is None
    assert track.n_samples == 0


def test_counted_event_is_defined_with_track_metadata():
    event = CountedEvent(
        track_id=1,
        counted_as="IN",
        counted_frame=10,
        first_seen_frame=0,
        last_seen_frame=10,
        s_min=0.1,
        s_max=0.8,
        s_first=0.1,
        s_last=0.8,
        n_samples=2,
    )

    assert event.track_id == 1
    assert event.n_samples == 2
