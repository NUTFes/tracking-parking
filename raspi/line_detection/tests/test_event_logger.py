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
        execution_id="execution-1",
        condition_key="condition-1",
        exp_key="condition-1",
        timing_summary=timing,
    )
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    assert data["avg_processing_time_ms"] == 20.0
    assert data["summary"]["avg_processing_time_ms"] == 20.0
    assert data["timing"] == timing
    assert data["wandb_run_id"] == "run-1"
    assert data["execution_id"] == "execution-1"
    assert data["condition_key"] == "condition-1"
    assert data["exp_key"] == "condition-1"


def test_save_json_keeps_wandb_keys_absent_when_disabled(tmp_path):
    logger = EventLogger(video_path="test.mp4")
    path = logger.save_json(str(tmp_path), TRACKER_SUMMARY)
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    assert "wandb_run_id" not in data
    assert "execution_id" not in data
    assert "condition_key" not in data
    assert "exp_key" not in data


def test_save_json_includes_accuracy_block_when_provided(tmp_path):
    logger = EventLogger(video_path="test.mp4")
    accuracy = {"gt_in": 22, "gt_out": 0, "count_error": 2, "count_error_in": 2, "count_error_out": 0}

    path = logger.save_json(
        str(tmp_path),
        TRACKER_SUMMARY,
        accuracy_summary=accuracy,
    )
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    assert data["accuracy"] == accuracy


def test_save_json_omits_accuracy_block_when_absent(tmp_path):
    logger = EventLogger(video_path="test.mp4")
    path = logger.save_json(str(tmp_path), TRACKER_SUMMARY)
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    assert "accuracy" not in data


def test_update_confidence_updates_event_and_line2_crossing():
    logger = EventLogger(video_path="test.mp4")
    event_id = logger.record_event(
        track_id=7,
        event_type="IN",
        frame_id=10,
        fps=30.0,
        confidence="pending",
        line2_crossed=False,
    )

    assert logger.update_confidence(event_id, "high", line2_crossed=True) is True
    assert logger.events[0].confidence == "high"
    assert logger.events[0].line2_crossed is True


def test_update_confidence_returns_false_for_unknown_event():
    logger = EventLogger(video_path="test.mp4")
    assert logger.update_confidence("missing-event-id", "normal") is False


def test_record_event_generates_unique_event_ids():
    logger = EventLogger(video_path="test.mp4")
    event_ids = {
        logger.record_event(1, "IN", frame_id, 30.0, "pending", False)
        for frame_id in range(3)
    }

    assert len(event_ids) == 3


def test_update_confidence_targets_reused_track_id_event_by_event_id():
    logger = EventLogger(video_path="test.mp4")
    resolved_event_id = logger.record_event(7, "IN", 1, 30.0, "high", True)
    pending_event_id = logger.record_event(7, "IN", 2, 30.0, "pending", False)

    assert logger.update_confidence(
        pending_event_id, "normal", line2_crossed=True
    ) is True
    assert logger.events[0].event_id == resolved_event_id
    assert logger.events[0].confidence == "high"
    assert logger.events[1].event_id == pending_event_id
    assert logger.events[1].confidence == "normal"
    assert logger.events[1].line2_crossed is True


def test_finalize_pending_confidences_and_validate_summary():
    logger = EventLogger(video_path="test.mp4")
    logger.record_event(1, "IN", 1, 30.0, "pending", False)
    logger.record_event(2, "OUT", 2, 30.0, "high", True)

    assert logger.finalize_pending_confidences() == 1
    summary = {
        "total_in": 1,
        "total_out": 1,
        "high_confidence_events": 1,
        "normal_confidence_events": 1,
    }
    logger.validate_finalized(summary)
