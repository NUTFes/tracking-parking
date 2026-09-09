import sys
import math
from pathlib import Path


LINE_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(LINE_ROOT))

from detection.config import Line
from detection.line_crossing import LineCrossingDetector
from detection.tracker import VehicleTracker


# Line1(入口側、y=0)→Line2(駐車場側、y=50)→駐車場基準点(y=100)の順に並ぶ、
# main.py の実運用構成を模した幾何。両ラインとも「yが大きい側=駐車場側=IN」で揃える。
LINE1 = Line(start=(0, 0), end=(100, 0))
LINE2 = Line(start=(0, 50), end=(100, 50))
PARKING_REF_POINT = (50, 100)


def make_tracker_and_detector(margin_px=5.0, endpoint_margin_px=0.0,
                               max_frame_gap=90, cleanup_threshold=150):
    detector = LineCrossingDetector(
        line1=LINE1,
        line2=LINE2,
        parking_ref_point=PARKING_REF_POINT,
        margin_px=margin_px,
        endpoint_margin_px=endpoint_margin_px,
    )
    tracker = VehicleTracker(max_frame_gap=max_frame_gap, cleanup_threshold=cleanup_threshold)
    return tracker, detector


def process_frame(tracker, detector, track_id, point, frame_id):
    """main.py の per-frame ループ本体(cleanup呼び出しを除く)を1track分再現する。"""
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
    if tracker.should_count_event(state):
        tracker.mark_as_counted(track_id)
    tracker.resolve_pending_confidences(frame_id)

    return state


def test_jitter_across_line1_does_not_double_count():
    tracker, detector = make_tracker_and_detector(margin_px=5)
    points = [(50, -12), (50, -2), (50, 3), (50, -1), (50, -9)]

    for frame_id, point in enumerate(points):
        process_frame(tracker, detector, track_id=1, point=point, frame_id=frame_id)

    assert tracker.total_in == 0
    assert tracker.total_out == 0


def test_slow_crossing_across_line1_counts_exactly_once():
    tracker, detector = make_tracker_and_detector(margin_px=5)
    points = [(50, -12), (50, -3), (50, 1), (50, 4), (50, 11), (50, 18)]

    state = None
    for frame_id, point in enumerate(points):
        state = process_frame(tracker, detector, track_id=1, point=point, frame_id=frame_id)

    assert tracker.total_in == 1
    assert state.counted is True

    # 同じ側に留まったまま再度フレームを処理しても二重カウントしない
    process_frame(tracker, detector, track_id=1, point=(50, 18), frame_id=len(points))
    assert tracker.total_in == 1


def test_line2_jitter_does_not_corrupt_passed_order():
    tracker, detector = make_tracker_and_detector(margin_px=5)

    # Line1をゆっくり通過してINを確定させる
    line1_crossing_points = [(50, -12), (50, -3), (50, 1), (50, 4), (50, 11)]
    for frame_id, point in enumerate(line1_crossing_points):
        state = process_frame(tracker, detector, track_id=1, point=point, frame_id=frame_id)
    assert state.passed_order == ["line1"]

    # Line2の安定側(道路側)へ到達したのち、判定保留帯の中で揺れる
    next_frame_id = len(line1_crossing_points)
    line2_jitter_points = [(50, 44), (50, 47), (50, 53), (50, 48), (50, 52), (50, 46)]
    for offset, point in enumerate(line2_jitter_points):
        state = process_frame(
            tracker, detector, track_id=1, point=point, frame_id=next_frame_id + offset
        )

    assert state.passed_order == ["line1"]
    assert state.line2_direction is None


def test_in_direction_line1_then_line2_slow_crossing_matches_expected_order():
    tracker, detector = make_tracker_and_detector(margin_px=5)

    line1_crossing_points = [(50, -12), (50, -3), (50, 1), (50, 4), (50, 11)]
    for frame_id, point in enumerate(line1_crossing_points):
        state = process_frame(tracker, detector, track_id=1, point=point, frame_id=frame_id)

    next_frame_id = len(line1_crossing_points)
    line2_crossing_points = [(50, 44), (50, 47), (50, 51), (50, 54), (50, 61)]
    for offset, point in enumerate(line2_crossing_points):
        state = process_frame(
            tracker, detector, track_id=1, point=point, frame_id=next_frame_id + offset
        )

    assert state.passed_order == ["line1", "line2"]
    assert state.line1_direction == "IN"
    assert state.line2_direction == "IN"


def test_track_id_reuse_after_cleanup_gets_fresh_transition_state():
    tracker, detector = make_tracker_and_detector(margin_px=5, cleanup_threshold=10)

    process_frame(tracker, detector, track_id=1, point=(50, -12), frame_id=0)
    old_state = tracker.get_state(1)
    assert old_state.line1_transition.stable_side == -1

    tracker.cleanup_stale_tracks(current_frame=0 + tracker.cleanup_threshold + 1)
    assert tracker.get_state(1) is None

    # 同じ数値のtrack_idが再度現れても、古いstable_sideを引き継がない。
    # もし引き継いでいたら(stale -1のまま)、(50,80)への到達は「反対側への
    # 反転」とみなされ、その場でIN判定が発火してしまう。
    new_state = process_frame(tracker, detector, track_id=1, point=(50, 80), frame_id=100)

    assert new_state is not old_state
    assert new_state.line1_direction is None  # 反転扱いされていない(=初回観測扱い)
    assert new_state.line1_transition.stable_side == 1


def test_cleanup_threshold_boundary_exact_and_plus_one():
    tracker, _ = make_tracker_and_detector(cleanup_threshold=10)
    tracker.update(track_id=1, point=(0, 0), frame_id=0)

    tracker.cleanup_stale_tracks(current_frame=10)
    assert tracker.get_state(1) is not None

    tracker.cleanup_stale_tracks(current_frame=11)
    assert tracker.get_state(1) is None


def test_frame_id_zero_line1_crossing_recorded():
    # ヒステリシス方式では初回観測フレーム自体では交差が確定しない設計のため
    # (side反転の相手が存在しないため)、frame_id=0での交差確定そのものは
    # 起こり得ない。ここでは record_line1_crossing 以降のカウント経路が
    # line1_frame の値(0はfalsy)に依存していないことを直接確認する。
    tracker, _ = make_tracker_and_detector()
    state = tracker.update(track_id=1, point=(50, 20), frame_id=0)
    state.record_line1_crossing("IN", frame_id=0)

    assert state.line1_frame == 0
    assert tracker.should_count_event(state) is True

    event_type = tracker.mark_as_counted(1)

    assert event_type == "IN"
    assert tracker.total_in == 1


def test_large_frame_gap_single_jump_across_line1_still_counts():
    tracker, detector = make_tracker_and_detector(margin_px=5)

    process_frame(tracker, detector, track_id=1, point=(50, -12), frame_id=0)
    process_frame(tracker, detector, track_id=1, point=(50, 18), frame_id=50)

    assert tracker.total_in == 1


def test_in_line1_then_line2_resolves_high_after_line2():
    tracker, detector = make_tracker_and_detector(margin_px=5)

    points = [
        (50, -12), (50, -3), (50, 1), (50, 4), (50, 11),
        (50, 44), (50, 47), (50, 51), (50, 54), (50, 61),
    ]
    states = []
    for frame_id, point in enumerate(points):
        states.append(process_frame(tracker, detector, 1, point, frame_id))

    state = states[-1]
    assert state.confidence == "high"
    assert tracker.total_in == 1
    assert tracker.high_confidence_count == 1
    assert tracker.normal_confidence_count == 0


def test_out_line2_then_line1_resolves_high_on_line1_frame():
    tracker, detector = make_tracker_and_detector(margin_px=5)

    points = [(50, 61), (50, 39), (50, 11), (50, -11)]
    for frame_id, point in enumerate(points):
        state = process_frame(tracker, detector, 1, point, frame_id)

    assert state.line2_direction == "OUT"
    assert state.line1_direction == "OUT"
    assert state.passed_order == ["line2", "line1"]
    assert state.confidence == "high"
    assert tracker.total_out == 1
    assert tracker.high_confidence_count == 1


def test_out_single_frame_double_crossing_resolves_high_in_physical_order():
    tracker, detector = make_tracker_and_detector(margin_px=5)

    process_frame(tracker, detector, 1, (50, 61), frame_id=0)
    state = process_frame(tracker, detector, 1, (50, -11), frame_id=1)

    assert state.passed_order == ["line2", "line1"]
    assert state.confidence == "high"


def test_in_single_frame_double_crossing_resolves_high_in_physical_order():
    tracker, detector = make_tracker_and_detector(margin_px=5)

    process_frame(tracker, detector, 1, (50, -11), frame_id=0)
    state = process_frame(tracker, detector, 1, (50, 61), frame_id=1)

    assert state.passed_order == ["line1", "line2"]
    assert state.confidence == "high"


def test_same_frame_order_uses_crossing_points_when_start_points_differ():
    tracker, detector = make_tracker_and_detector(margin_px=5)

    process_frame(tracker, detector, 1, (50, 61), frame_id=0)
    process_frame(tracker, detector, 1, (50, 58), frame_id=1)
    state = process_frame(tracker, detector, 1, (50, 54), frame_id=2)

    assert state.line1_transition.last_stable_point == (50, 54)
    assert state.line2_transition.last_stable_point == (50, 58)

    state = process_frame(tracker, detector, 1, (50, -11), frame_id=3)

    assert state.passed_order == ["line2", "line1"]
    assert state.confidence == "high"


def test_pending_in_resolves_normal_after_gap_exceeds_boundary():
    tracker, _ = make_tracker_and_detector(max_frame_gap=3)
    state = tracker.update(1, (50, 10), frame_id=0)
    state.record_line1_crossing("IN", frame_id=0)
    tracker.mark_as_counted(1)

    assert tracker.resolve_pending_confidences(3) == []
    assert state.confidence == "pending"

    updates = tracker.resolve_pending_confidences(4)
    assert [(u.track_id, u.confidence) for u in updates] == [(1, "normal")]
    assert tracker.normal_confidence_count == 1


def test_reverse_order_in_is_normal():
    tracker, _ = make_tracker_and_detector()
    state = tracker.update(1, (50, 10), frame_id=0)
    state.record_line2_crossing("IN", frame_id=0)
    state.record_line1_crossing("IN", frame_id=1)
    tracker.mark_as_counted(1)

    updates = tracker.resolve_pending_confidences(1)
    assert [(u.track_id, u.confidence) for u in updates] == [(1, "normal")]


def test_direction_mismatch_is_normal():
    tracker, _ = make_tracker_and_detector()
    state = tracker.update(1, (50, 10), frame_id=0)
    state.record_line1_crossing("IN", frame_id=0)
    state.record_line2_crossing("OUT", frame_id=1)
    tracker.mark_as_counted(1)

    assert state.resolve_confidence(1, 90) == "normal"


def test_duplicate_line2_before_line1_is_normal_for_out():
    tracker, _ = make_tracker_and_detector()
    state = tracker.update(1, (50, 10), frame_id=0)
    state.record_line2_crossing("OUT", frame_id=0)
    state.record_line2_crossing("OUT", frame_id=1)
    state.record_line1_crossing("OUT", frame_id=2)
    tracker.mark_as_counted(1)

    assert state.resolve_confidence(2, 90) == "normal"


def test_correct_pair_beyond_gap_is_normal():
    tracker, _ = make_tracker_and_detector(max_frame_gap=3)
    state = tracker.update(1, (50, 10), frame_id=0)
    state.record_line1_crossing("IN", frame_id=0)
    state.record_line2_crossing("IN", frame_id=4)
    tracker.mark_as_counted(1)

    assert state.resolve_confidence(4, 3) == "normal"


def test_pending_state_survives_cleanup_until_confidence_is_resolved():
    tracker, _ = make_tracker_and_detector(max_frame_gap=90, cleanup_threshold=10)
    state = tracker.update(1, (50, 10), frame_id=0)
    state.record_line1_crossing("IN", frame_id=0)
    tracker.mark_as_counted(1)

    tracker.cleanup_stale_tracks(11)
    assert tracker.get_state(1) is state

    updates = tracker.resolve_pending_confidences(91)
    assert updates[0].confidence == "normal"
    tracker.cleanup_stale_tracks(91)
    assert tracker.get_state(1) is None


def test_finalize_pending_confidences_marks_remaining_events_normal():
    tracker, _ = make_tracker_and_detector()
    state = tracker.update(1, (50, 10), frame_id=0)
    state.record_line1_crossing("IN", frame_id=0)
    tracker.mark_as_counted(1)

    updates = tracker.finalize_pending_confidences()
    assert [(u.track_id, u.confidence) for u in updates] == [(1, "normal")]
    assert state.confidence == "normal"
    assert tracker.normal_confidence_count == 1


def test_frame_zero_line1_event_starts_pending_confidence():
    tracker, _ = make_tracker_and_detector()
    state = tracker.update(1, (50, 20), frame_id=0)
    state.record_line1_crossing("IN", frame_id=0)

    assert tracker.should_count_event(state) is True
    assert tracker.mark_as_counted(1) == "IN"
    assert state.confidence == "pending"
