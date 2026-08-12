import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from src.counter import Counter
from src.progress_diagnostics import (
    build_progress_diagnostics,
    snapshot_in_candidate_tracks,
)


def test_diagnostics_projects_s_max_with_strict_threshold():
    counter = Counter(s_low=0.25, s_high=0.75)
    for frame, value in enumerate((0.1, 0.3, 0.7)):
        counter.update(1, value, frame)
    counter.update(2, 0.1, 0)
    counter.update(2, 0.75, 1)
    diagnostics = build_progress_diagnostics(
        counter.get_all_tracks(), counter.get_archived_events(),
        total_track_instances=counter.total_track_instances,
        count_in=counter.count_in, count_out=counter.count_out,
    )
    assert diagnostics["in_candidate_stuck_count"] == 2
    assert diagnostics["threshold_projection"]["0.75"] == 0
    assert diagnostics["threshold_projection"]["0.70"] == 1
    assert diagnostics["threshold_projection"]["0.65"] == 2
    assert diagnostics["s_max_summary"]["max"] == pytest.approx(0.75)


def test_diagnostics_counts_archive_and_active_events():
    counter = Counter(cleanup_threshold=2)
    counter.update(1, 0.1, 0)
    counter.update(1, 0.8, 1)
    counter.update(2, 0.1, 0)
    counter.update(2, 0.8, 1)
    counter.cleanup(4)
    diagnostics = build_progress_diagnostics(
        counter.get_all_tracks(), counter.get_archived_events(),
        total_track_instances=counter.total_track_instances,
        count_in=counter.count_in, count_out=counter.count_out,
    )
    assert diagnostics["counted_track_instances"] == 2
    assert diagnostics["count_in"] + diagnostics["count_out"] == 2


def test_diagnostics_rejects_inconsistent_event_count():
    counter = Counter()
    counter.update(1, 0.1, 0)
    with pytest.raises(ValueError):
        build_progress_diagnostics(
            counter.get_all_tracks(), counter.get_archived_events(),
            total_track_instances=counter.total_track_instances,
            count_in=1, count_out=0,
        )


def test_candidate_snapshots_survive_cleanup_and_id_reuse():
    counter = Counter(cleanup_threshold=1)
    counter.update(1, 0.1, 0)
    first = snapshot_in_candidate_tracks(counter.tracks.values())
    counter.cleanup(2)
    counter.update(1, 0.1, 10)
    second = snapshot_in_candidate_tracks(counter.tracks.values())
    assert list(first) == [(1, 0)]
    assert list(second) == [(1, 10)]
