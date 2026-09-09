import math
import sys
from pathlib import Path


LINE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(LINE_ROOT))

from detection.config import Line
from detection.line_crossing import LineCrossingDetector
from detection.tracker import VehicleTracker
from result_output.event_logger import EventLogger


LINE1 = Line(start=(0, 0), end=(100, 0))
LINE2 = Line(start=(0, 50), end=(100, 50))
PARKING_REF_POINT = (50, 100)


def process_frame(tracker, detector, event_logger, track_id, point, frame_id):
    """Corrected main.py per-frame ordering for one detection."""
    state = tracker.update(track_id, point, frame_id)

    line1_result = detector.update_line1_crossing(
        state.line1_transition, state.curr_point
    )
    line2_result = detector.update_line2_crossing(
        state.line2_transition, state.curr_point
    )
    crossings = []
    if line1_result is not None:
        crossings.append(("line1", line1_result))
    if line2_result is not None:
        crossings.append(("line2", line2_result))
    if len(crossings) == 2:
        crossings.sort(
            key=lambda item: math.dist(state.curr_point, item[1].point),
            reverse=True,
        )

    for line_name, result in crossings:
        if line_name == "line1":
            if not state.counted:
                state.record_line1_crossing(result.direction, frame_id)
        else:
            state.record_line2_crossing(result.direction, frame_id)

    pending_events = []
    if tracker.should_count_event(state):
        event_type = tracker.mark_as_counted(track_id)
        pending_events.append({
            "track_id": track_id,
            "event_type": event_type,
            "frame_id": frame_id,
            "fps": 30.0,
            "confidence": state.confidence,
            "line2_crossed": state.line2_direction is not None,
        })

    tracker.cleanup_stale_tracks(frame_id)

    for event in pending_events:
        event_id = event_logger.record_event(**event)
        state = tracker.get_state(event["track_id"])
        if state is not None:
            state.pending_event_id = event_id

    # The event must be recorded before its event_id can receive a confidence update.
    confidence_updates = tracker.resolve_pending_confidences(frame_id)
    for update in confidence_updates:
        assert event_logger.update_confidence(
            update.event_id,
            update.confidence,
            line2_crossed=update.line2_crossed,
        ) is True
        for event in pending_events:
            if event["track_id"] == update.track_id:
                event["confidence"] = update.confidence
                event["line2_crossed"] = update.line2_crossed

    return state


def test_same_frame_double_crossing_wires_event_id_before_confidence_update():
    detector = LineCrossingDetector(
        line1=LINE1,
        line2=LINE2,
        parking_ref_point=PARKING_REF_POINT,
        margin_px=5.0,
        endpoint_margin_px=0.0,
    )
    tracker = VehicleTracker(max_frame_gap=90, cleanup_threshold=150)
    event_logger = EventLogger(video_path="test.mp4")

    process_frame(tracker, detector, event_logger, 1, (50, -11), frame_id=0)
    state = process_frame(
        tracker, detector, event_logger, 1, (50, 61), frame_id=1
    )

    assert state.passed_order == ["line1", "line2"]
    assert state.confidence == "high"
    assert state.pending_event_id == event_logger.events[0].event_id
    assert event_logger.events[0].confidence == "high"
    assert event_logger.events[0].line2_crossed is True
