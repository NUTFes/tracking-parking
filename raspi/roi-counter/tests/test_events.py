import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

from src.counter import CountedEvent, Counter
from src.events import EVENT_COLUMNS, build_event_rows
from src.tracker import VehicleTrack


def test_returns_one_row_per_counted_track():
    tracks = [
        VehicleTrack(track_id=1, counted_as="IN", counted_frame=10),
        VehicleTrack(track_id=2, counted_as="OUT", counted_frame=20),
    ]
    rows = build_event_rows(tracks, fps=20.0, warmup_frames=30)
    assert len(rows) == 2


def test_excludes_uncounted_tracks():
    tracks = [
        VehicleTrack(track_id=1, counted_as="IN", counted_frame=10),
        VehicleTrack(track_id=2, counted_as=None),
    ]
    rows = build_event_rows(tracks, fps=20.0, warmup_frames=30)
    assert len(rows) == 1
    assert rows[0]["track_id"] == 1


def test_orders_by_counted_frame():
    tracks = [
        VehicleTrack(track_id=2, counted_as="OUT", counted_frame=50),
        VehicleTrack(track_id=1, counted_as="IN", counted_frame=10),
    ]
    rows = build_event_rows(tracks, fps=20.0, warmup_frames=30)
    assert [row["track_id"] for row in rows] == [1, 2]


def test_computes_timestamp_from_fps():
    tracks = [VehicleTrack(track_id=1, counted_as="IN", counted_frame=40)]
    rows = build_event_rows(tracks, fps=20.0, warmup_frames=30)
    assert rows[0]["timestamp_sec"] == 2.0


def test_timestamp_is_none_when_fps_is_zero():
    tracks = [VehicleTrack(track_id=1, counted_as="IN", counted_frame=40)]
    rows = build_event_rows(tracks, fps=0.0, warmup_frames=30)
    assert rows[0]["timestamp_sec"] is None


def test_marks_warmup_frames():
    tracks = [
        VehicleTrack(track_id=1, counted_as="IN", counted_frame=10),
        VehicleTrack(track_id=2, counted_as="IN", counted_frame=30),
    ]
    rows = build_event_rows(tracks, fps=20.0, warmup_frames=30)
    assert rows[0]["is_warmup"] is True
    assert rows[1]["is_warmup"] is False


def test_handles_missing_counted_frame():
    tracks = [
        VehicleTrack(track_id=1, counted_as="IN", counted_frame=None),
        VehicleTrack(track_id=2, counted_as="IN", counted_frame=5),
    ]
    rows = build_event_rows(tracks, fps=20.0, warmup_frames=30)
    # frame不明のトラックは末尾に並び、timestamp/is_warmupもNone
    assert rows[-1]["track_id"] == 1
    assert rows[-1]["frame_index"] is None
    assert rows[-1]["timestamp_sec"] is None
    assert rows[-1]["is_warmup"] is None


def test_column_order_is_stable():
    tracks = [VehicleTrack(track_id=1, counted_as="IN", counted_frame=10)]
    rows = build_event_rows(tracks, fps=20.0, warmup_frames=30)
    assert list(rows[0].keys()) == list(EVENT_COLUMNS)


def test_event_count_matches_counter_totals():
    counter = Counter(s_low=0.25, s_high=0.75)
    for frame_idx, s in enumerate([0.1, 0.3, 0.5, 0.8]):
        counter.update(1, s, frame_idx)
    for frame_idx, s in enumerate([0.9, 0.6, 0.3, 0.1]):
        counter.update(2, s, frame_idx)

    rows = build_event_rows(counter.get_all_tracks(), fps=20.0, warmup_frames=30)
    assert len(rows) == counter.count_in + counter.count_out


def test_build_event_rows_includes_archive_and_active_tracks_in_order():
    active = VehicleTrack(track_id=3, counted_as="IN", counted_frame=30)
    archived = CountedEvent(
        track_id=1,
        counted_as="OUT",
        counted_frame=10,
        first_seen_frame=0,
        candidate_started_frame=0,
        last_seen_frame=10,
        s_min=0.1,
        s_max=0.9,
        s_first=0.9,
        s_last=0.1,
        n_samples=4,
    )

    rows = build_event_rows(
        [active],
        fps=20.0,
        warmup_frames=30,
        archive=[archived],
    )

    assert [row["track_id"] for row in rows] == [1, 3]
    assert [row["event_type"] for row in rows] == ["OUT", "IN"]
