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


def test_update_tracks_frame_and_s_summaries():
    c = Counter(s_history_limit=3)
    for frame_idx, s in enumerate([0.1, 0.4, 0.8, 0.6]):
        c.update(1, s, frame_idx)

    track = c.tracks[1]
    assert track.first_seen_frame == 0
    assert track.last_seen_frame == 3
    assert track.s_first == 0.1
    assert track.s_last == 0.6
    assert track.s_min == 0.1
    assert track.s_max == 0.8
    assert track.n_samples == 4
    assert track.s_history == [0.4, 0.8, 0.6]


def test_s_history_limit_zero_keeps_all_samples():
    c = Counter(s_history_limit=0)
    for frame_idx, s in enumerate([0.1, 0.2, 0.3]):
        c.update(1, s, frame_idx)

    assert c.tracks[1].s_history == [0.1, 0.2, 0.3]


def test_cleanup_boundary_keeps_unknown_then_removes_at_plus_one():
    c = Counter(cleanup_threshold=10)
    c.update(1, 0.5, 0)

    c.cleanup(10)
    assert 1 in c.tracks

    c.cleanup(11)
    assert 1 not in c.tracks


def test_candidate_expires_from_first_seen_frame():
    c = Counter(max_candidate_age=3, cleanup_threshold=10)
    c.update(1, 0.1, 0)
    c.update(1, 0.5, 3)
    c.cleanup(3)
    assert c.tracks[1].state == VehicleState.IN_CANDIDATE

    c.update(1, 0.5, 4)
    c.cleanup(4)
    assert c.tracks[1].state == VehicleState.UNKNOWN


def test_counted_track_moves_to_archive_without_changing_count():
    c = Counter(cleanup_threshold=10)
    c.update(1, 0.1, 0)
    c.update(1, 0.8, 1)
    assert c.count_in == 1

    c.cleanup(12)

    assert c.count_in == 1
    assert c.tracks == {}
    assert len(c.archive) == 1
    archived = c.archive[0]
    assert archived.track_id == 1
    assert archived.counted_as == "IN"
    assert archived.counted_frame == 1
    assert archived.s_first == 0.1
    assert archived.s_max == 0.8


def test_reused_track_id_gets_a_new_state_after_cleanup():
    c = Counter(cleanup_threshold=10)
    c.update(1, 0.1, 0)
    c.update(1, 0.8, 1)
    c.cleanup(12)

    c.update(1, 0.1, 20)

    assert c.count_in == 1
    assert c.tracks[1].first_seen_frame == 20
    assert c.tracks[1].counted_as is None
    assert len(c.archive) == 1


def test_long_sequence_keeps_retained_states_bounded():
    c = Counter(cleanup_threshold=10, s_history_limit=3)
    max_retained = 0
    for frame_idx in range(10_000):
        c.update(frame_idx, 0.5, frame_idx)
        c.cleanup(frame_idx)
        max_retained = max(max_retained, len(c.tracks))

    assert max_retained <= 11
    assert len(c.tracks) <= 11
