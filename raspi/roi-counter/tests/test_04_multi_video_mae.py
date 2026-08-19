import importlib
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1]))          # roi-counter/
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))  # roi-counter/scripts/
sys.path.insert(0, str(Path(__file__).parents[2]))           # raspi/（common 共有のため）

mae = importlib.import_module("04_multi_video_mae")

from common.run_identity import build_condition_key

# replay_counts用の固定ROI（正方形、y_normalizedとedge_distanceが一致する形）。
# tests/test_visualizer.py・tests/test_progress.pyと同じ座標系を踏襲。
REPLAY_ROI = [(100, 100), (300, 100), (300, 200), (100, 200)]


def make_cached_frame(frame_index, cy, track_id=1.0, is_warmup=False):
    """cy（bbox下端のy座標）だけを指定してCachedFrameを作る。

    y_normalized方式でのs = (200 - cy) / (200 - 100) になるよう、
    xyxyのx幅・y1は固定値で埋める（ROI内に収まる範囲であれば値自体は無意味）。
    """
    xyxy = np.array([150.0, cy - 10.0, 170.0, cy])
    return mae.CachedFrame(
        frame_index=frame_index,
        detections=[(xyxy, track_id)],
        read_ms=1.0,
        inference_tracking_ms=5.0,
        is_warmup=is_warmup,
    )

RES = {
    "count_in": 3,
    "count_out": 1,
    "tracker_reset": True,
    "tracker_reset_method": "tracker_reset",
    "ultralytics_version": "8.4.72",
}
STATS = {"frame_ms_mean": 10.0, "frame_ms_max": 20.0, "total_ms": 1000.0}


def test_build_detail_row_excludes_wandb_columns_when_disabled():
    row = mae.build_detail_row(
        0.25, 0.75, "video.mp4", RES, gt_in=3, gt_out=1, count_error=0,
        stats=STATS, use_wandb=False, wandb_run_id="run1",
        execution_id="execution1", condition_key="condition1", exp_key="condition1",
    )
    assert "wandb_run_id" not in row
    assert "execution_id" not in row
    assert "condition_key" not in row
    assert "exp_key" not in row
    assert list(row.keys()) == [
        "s_low", "s_high", "video", "count_in", "count_out",
        "gt_in", "gt_out", "count_error", "mean_frame_ms", "max_frame_ms", "elapsed_ms",
        "tracker_reset", "tracker_reset_method", "ultralytics_version",
    ]


def test_build_detail_row_includes_wandb_columns_when_enabled():
    row = mae.build_detail_row(
        0.25, 0.75, "video.mp4", RES, gt_in=3, gt_out=1, count_error=0,
        stats=STATS, use_wandb=True, wandb_run_id="run1",
        execution_id="execution1", condition_key="condition1", exp_key="condition1",
    )
    assert row["wandb_run_id"] == "run1"
    assert row["execution_id"] == "execution1"
    assert row["condition_key"] == "condition1"
    assert row["exp_key"] == "condition1"
    # 既存列の順序は変わらず、末尾に追加される
    assert list(row.keys())[:14] == [
        "s_low", "s_high", "video", "count_in", "count_out",
        "gt_in", "gt_out", "count_error", "mean_frame_ms", "max_frame_ms", "elapsed_ms",
        "tracker_reset", "tracker_reset_method", "ultralytics_version",
    ]
    assert list(row.keys())[14:] == [
        "wandb_run_id", "execution_id", "condition_key", "exp_key"
    ]


def test_tracker_reset_method_does_not_change_condition_key():
    base = {
        key: f"value-{key}"
        for key in mae.SWEEP_CONDITION_KEYS
    }
    clean_start = {**base, "tracker_reset_method": "clean_start"}
    tracker_reset = {**base, "tracker_reset_method": "tracker_reset"}

    first = mae.build_sweep_condition(clean_start)
    second = mae.build_sweep_condition(tracker_reset)

    assert "tracker_reset_method" not in first
    assert build_condition_key(first) == build_condition_key(second)


def test_empty_run_result_contains_all_downstream_keys():
    result = mae.empty_run_result()
    assert set(result) >= {
        "count_in", "count_out", "total_frames", "frame_times", "timings",
        "frame_width", "frame_height", "source_fps", "events",
    }
    assert result["events"] == []
    assert result["active_detections"] == 0
    assert result["retained_states"] == 0
    assert result["archived_events"] == 0


def test_cleanup_parameters_are_part_of_sweep_condition():
    assert "cleanup_threshold" in mae.SWEEP_CONDITION_KEYS
    assert "max_candidate_age" in mae.SWEEP_CONDITION_KEYS
    assert "s_history_limit" in mae.SWEEP_CONDITION_KEYS


def test_progress_method_is_part_of_sweep_condition_and_defaults_to_edge_distance():
    assert "progress_method" in mae.SWEEP_CONDITION_KEYS
    assert mae.PROGRESS_METHOD == "edge_distance"


def test_event_csv_columns_prefix_sweep_identity():
    assert mae.EVENT_CSV_COLUMNS[:3] == ("s_low", "s_high", "video")
    assert mae.EVENT_CSV_COLUMNS[3:] == mae.EVENT_COLUMNS


def test_parse_float_list_returns_default_when_unset():
    default = [0.1, 0.2]
    assert mae.parse_float_list(None, default, source="TEST") == default
    assert mae.parse_float_list("", default, source="TEST") == default
    assert mae.parse_float_list("   ", default, source="TEST") == default


def test_parse_float_list_parses_single_value():
    assert mae.parse_float_list("0.25", [0.1], source="TEST") == [0.25]


def test_parse_float_list_parses_multiple_values_with_whitespace():
    assert mae.parse_float_list("0.10, 0.15,0.20", [], source="TEST") == [0.10, 0.15, 0.20]


def test_parse_float_list_rejects_non_numeric_element():
    try:
        mae.parse_float_list("0.1,abc", [], source="S_LOW_LIST")
        assert False, "ValueError が発生しませんでした"
    except ValueError as exc:
        assert "S_LOW_LIST" in str(exc)


def test_parse_float_list_rejects_empty_element():
    try:
        mae.parse_float_list("0.1,,0.2", [], source="S_LOW_LIST")
        assert False, "ValueError が発生しませんでした"
    except ValueError as exc:
        assert "S_LOW_LIST" in str(exc)


def test_parse_float_list_rejects_out_of_range():
    for raw in ("-0.1", "1.5"):
        try:
            mae.parse_float_list(raw, [], source="S_HIGH_LIST")
            assert False, f"{raw!r} で ValueError が発生しませんでした"
        except ValueError as exc:
            assert "S_HIGH_LIST" in str(exc)


def test_parse_float_list_rejects_nan_and_inf():
    for raw in ("nan", "inf", "-inf"):
        try:
            mae.parse_float_list(raw, [], source="TEST")
            assert False, f"{raw!r} で ValueError が発生しませんでした"
        except ValueError:
            pass


def test_default_grid_has_no_invalid_low_high_pairs():
    import itertools
    invalid = [
        (lo, hi)
        for lo, hi in itertools.product(mae.S_LOW_LIST, mae.S_HIGH_LIST)
        if lo >= hi
    ]
    assert invalid == []


def test_build_detection_trace_returns_none_when_video_cannot_be_opened():
    # cap.isOpened()がFalseになる時点でreturnするため、modelは一度も使われない
    # （Noneを渡しても安全）。
    trace = mae.build_detection_trace(model=None, video_source="/no/such/video.mp4")
    assert trace is None


def test_replay_counts_produces_in_event_for_low_to_high_crossing():
    # フレーム0: s=0.1 (< s_low=0.3) → IN_CANDIDATE
    # フレーム1: s=0.9 (> s_high=0.7) → COUNTED IN
    trace = mae.DetectionTrace(
        frame_width=400, frame_height=300, source_fps=30.0,
        frames=[
            make_cached_frame(frame_index=0, cy=190.0),  # s=0.1
            make_cached_frame(frame_index=1, cy=110.0),  # s=0.9
        ],
        active_detections=1,
    )

    res = mae.replay_counts(trace, REPLAY_ROI, "y_normalized", s_low=0.3, s_high=0.7)

    assert res["count_in"] == 1
    assert res["count_out"] == 0
    assert len(res["events"]) == 1
    assert res["total_frames"] == 2
    assert len(res["timings"]) == 2
    # read_ms/inference_tracking_msはCachedFrameの実測値をそのままコピーする。
    assert res["timings"][0].read_ms == trace.frames[0].read_ms
    assert res["timings"][0].inference_tracking_ms == trace.frames[0].inference_tracking_ms
    # end_to_end_msはinference_tracking_ms + counting_logic_msとして再構成される。
    assert res["timings"][0].end_to_end_ms == (
        res["timings"][0].inference_tracking_ms + res["timings"][0].counting_logic_ms
    )


def test_replay_counts_does_not_count_when_thresholds_not_crossed():
    trace = mae.DetectionTrace(
        frame_width=400, frame_height=300, source_fps=30.0,
        frames=[
            make_cached_frame(frame_index=0, cy=190.0),  # s=0.1
            make_cached_frame(frame_index=1, cy=110.0),  # s=0.9
        ],
        active_detections=1,
    )

    # s_low=0.05なので s=0.1 は IN_CANDIDATE にすらならない。
    res = mae.replay_counts(trace, REPLAY_ROI, "y_normalized", s_low=0.05, s_high=0.95)

    assert res["count_in"] == 0
    assert res["count_out"] == 0
    assert res["events"] == []


def test_replay_counts_is_independent_across_repeated_calls():
    # 同一DetectionTraceに対してreplay_countsを2回呼んでも、1回目の呼び出しが
    # 2回目に影響しない（CachedFrame/DetectionTraceがイミュータブルに扱われている）。
    trace = mae.DetectionTrace(
        frame_width=400, frame_height=300, source_fps=30.0,
        frames=[
            make_cached_frame(frame_index=0, cy=190.0),
            make_cached_frame(frame_index=1, cy=110.0),
        ],
        active_detections=1,
    )

    first = mae.replay_counts(trace, REPLAY_ROI, "y_normalized", s_low=0.3, s_high=0.7)
    second = mae.replay_counts(trace, REPLAY_ROI, "y_normalized", s_low=0.3, s_high=0.7)

    assert first["count_in"] == second["count_in"] == 1
    assert len(first["events"]) == len(second["events"]) == 1
    assert len(trace.frames[0].detections) == 1
    assert len(trace.frames[1].detections) == 1


def test_replay_counts_returns_empty_result_shape_matching_empty_run_result():
    trace = mae.DetectionTrace(
        frame_width=0, frame_height=0, source_fps=0.0, frames=[], active_detections=0,
    )
    res = mae.replay_counts(trace, REPLAY_ROI, "y_normalized", s_low=0.3, s_high=0.7)
    assert set(res) == set(mae.empty_run_result())
    assert res["count_in"] == 0
    assert res["events"] == []
