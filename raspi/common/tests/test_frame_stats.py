import numpy as np

from common.frame_stats import compute_frame_stats, compute_timing_stats
from common.frame_timing import FrameTiming


def test_basic_stats():
    frame_ms = [10.0, 20.0, 30.0, 40.0, 50.0]
    stats = compute_frame_stats(frame_ms, source_fps=30.0)

    assert stats["frame_ms_min"] == 10.0
    assert stats["frame_ms_max"] == 50.0
    assert stats["frame_ms_mean"] == 30.0
    assert stats["frame_ms_p50"] == 30.0
    assert stats["frame_ms_p95"] == np.percentile(frame_ms, 95)
    assert stats["frame_ms_p99"] == np.percentile(frame_ms, 99)
    assert stats["total_ms"] == 150.0
    # 1000 / 30ms = 33.33 fps >= 30fps
    assert stats["effective_fps"] == 1000.0 / 30.0
    assert stats["realtime_ok"] is True


def test_realtime_not_ok():
    # 平均 100ms → 10fps < 30fps
    stats = compute_frame_stats([100.0, 100.0], source_fps=30.0)
    assert stats["effective_fps"] == 10.0
    assert stats["realtime_ok"] is False


def test_empty_list_no_exception():
    stats = compute_frame_stats([], source_fps=30.0)
    assert stats["frame_ms_mean"] == 0.0
    assert stats["frame_ms_p95"] == 0.0
    assert stats["total_ms"] == 0.0
    assert stats["effective_fps"] == 0.0
    assert stats["realtime_ok"] is False


def test_zero_source_fps():
    # source_fps=0 でも例外を出さず realtime_ok=False
    stats = compute_frame_stats([10.0, 20.0], source_fps=0.0)
    assert stats["realtime_ok"] is False


def test_timing_stats_use_core_for_comparison_and_end_to_end_for_deadline():
    records = [
        FrameTiming(0, 1.0, 20.0, 5.0, 2.0, 30.0, False),
        FrameTiming(1, 1.0, 25.0, 5.0, 2.0, 40.0, False),
    ]
    stats = compute_timing_stats(records, source_fps=30.0)

    assert stats["core_ms_mean"] == 27.5
    assert stats["frame_ms_mean"] == stats["core_ms_mean"]
    assert stats["frame_budget_ms"] == 1000.0 / 30.0
    assert stats["deadline_miss_count"] == 1
    assert stats["deadline_miss_rate"] == 0.5
    assert stats["end_to_end_realtime_ok"] is False
