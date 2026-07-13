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
