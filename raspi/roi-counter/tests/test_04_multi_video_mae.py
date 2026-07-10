import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))          # roi-counter/
sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))  # roi-counter/scripts/
sys.path.insert(0, str(Path(__file__).parents[2]))           # raspi/（common 共有のため）

mae = importlib.import_module("04_multi_video_mae")

RES = {"count_in": 3, "count_out": 1}
STATS = {"frame_ms_mean": 10.0, "frame_ms_max": 20.0, "total_ms": 1000.0}


def test_build_detail_row_excludes_wandb_columns_when_disabled():
    row = mae.build_detail_row(
        0.25, 0.75, "video.mp4", RES, gt_in=3, gt_out=1, count_error=0,
        stats=STATS, use_wandb=False, wandb_run_id="run1", exp_key="key1",
    )
    assert "wandb_run_id" not in row
    assert "exp_key" not in row
    assert list(row.keys()) == [
        "s_low", "s_high", "video", "count_in", "count_out",
        "gt_in", "gt_out", "count_error", "mean_frame_ms", "max_frame_ms", "elapsed_ms",
    ]


def test_build_detail_row_includes_wandb_columns_when_enabled():
    row = mae.build_detail_row(
        0.25, 0.75, "video.mp4", RES, gt_in=3, gt_out=1, count_error=0,
        stats=STATS, use_wandb=True, wandb_run_id="run1", exp_key="key1",
    )
    assert row["wandb_run_id"] == "run1"
    assert row["exp_key"] == "key1"
    # 既存列の順序は変わらず、末尾に追加される
    assert list(row.keys())[:11] == [
        "s_low", "s_high", "video", "count_in", "count_out",
        "gt_in", "gt_out", "count_error", "mean_frame_ms", "max_frame_ms", "elapsed_ms",
    ]
    assert list(row.keys())[11:] == ["wandb_run_id", "exp_key"]
