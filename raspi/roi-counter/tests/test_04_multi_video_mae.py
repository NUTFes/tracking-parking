import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))          # roi-counter/
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))  # roi-counter/scripts/
sys.path.insert(0, str(Path(__file__).parents[2]))           # raspi/（common 共有のため）

mae = importlib.import_module("04_multi_video_mae")

from common.run_identity import build_condition_key

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


def test_progress_method_is_part_of_sweep_condition_and_defaults_to_y_normalized():
    assert "progress_method" in mae.SWEEP_CONDITION_KEYS
    assert mae.PROGRESS_METHOD == "y_normalized"


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
        for lo, hi in itertools.product(
            [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40], [0.60, 0.65]
        )
        if lo >= hi
    ]
    assert invalid == []
