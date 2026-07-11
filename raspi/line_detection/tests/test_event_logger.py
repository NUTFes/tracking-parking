import json
import sys
from pathlib import Path


LINE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(LINE_ROOT))

from result_output.event_logger import EventLogger


TRACKER_SUMMARY = {
    "total_in": 2,
    "total_out": 1,
    "current_parked": 1,
    "high_confidence_events": 2,
    "normal_confidence_events": 1,
}


def test_save_json_includes_timing_and_wandb_reference(tmp_path):
    logger = EventLogger(video_path="test.mp4")
    logger.record_frame_time(100.0)
    timing = {
        "timing_schema_version": 2,
        "warmup_frames": 30,
        "measured_frames": 100,
        "core_ms_mean": 20.0,
    }

    path = logger.save_json(
        str(tmp_path),
        TRACKER_SUMMARY,
        wandb_run_id="run-1",
        exp_key="exp-1",
        timing_summary=timing,
    )
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    assert data["avg_processing_time_ms"] == 20.0
    assert data["summary"]["avg_processing_time_ms"] == 20.0
    assert data["timing"] == timing
    assert data["wandb_run_id"] == "run-1"
    assert data["exp_key"] == "exp-1"


def test_save_json_keeps_wandb_keys_absent_when_disabled(tmp_path):
    logger = EventLogger(video_path="test.mp4")
    path = logger.save_json(str(tmp_path), TRACKER_SUMMARY)
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    assert "wandb_run_id" not in data
    assert "exp_key" not in data
