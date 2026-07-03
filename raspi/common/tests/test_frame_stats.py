import numpy as np

from common.frame_stats import compute_frame_stats


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
