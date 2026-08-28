import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

sweep = importlib.import_module("03_sweep_params")


def test_build_result_row_records_tracker_reset_metadata():
    res = {
        "count_in": 3,
        "count_out": 1,
        "elapsed_ms": 100.0,
        "mean_frame_ms": 10.0,
        "max_frame_ms": 20.0,
    }
    reset_result = sweep.TrackerResetResult(
        model=object(),
        succeeded=True,
        method="tracker_reset",
        ultralytics_version="8.4.72",
    )

    row = sweep.build_result_row(
        0.25, 0.75, res, {"in": 3, "out": 2}, reset_result
    )

    assert row["count_error"] == 1
    assert row["tracker_reset"] is True
    assert row["tracker_reset_method"] == "tracker_reset"
    assert row["ultralytics_version"] == "8.4.72"


def test_build_result_row_allows_missing_ground_truth():
    res = {
        "count_in": 3,
        "count_out": 1,
        "elapsed_ms": 100.0,
        "mean_frame_ms": 10.0,
        "max_frame_ms": 20.0,
    }
    reset_result = sweep.TrackerResetResult(
        model=object(),
        succeeded=True,
        method="clean_start",
        ultralytics_version="8.4.72",
    )

    row = sweep.build_result_row(
        0.25, 0.75, res, {"in": None, "out": None}, reset_result
    )

    assert row["count_error"] is None
