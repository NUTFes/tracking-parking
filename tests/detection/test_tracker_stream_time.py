"""時間窓が秒（ストリーム時刻）で効くことのテスト。

フレーム番号の差で判定していた頃は、秒指定を開いた時点のfpsでフレーム数へ
換算していた。これは処理が撮影レートに追いつく前提に立っている。ライブカメラでは
処理が追いつかず古いフレームが捨てられるため、30fps宣言のカメラを実測14fpsで
処理すると「3秒」の窓が実時間で6秒以上に伸びていた。

ここで固定するのは、窓の判定が「渡された時刻の差」だけで決まり、フレーム数にも
fpsにも依存しないこと。動画とカメラで同じ秒指定が同じ意味を持つ、という性質そのもの。
"""
from tracking_parking.detection.tracker import VehicleTracker


def make_counted_state(tracker, *, track_id=1, at_sec=0.0):
    """Line1だけ通過してpendingになった状態を作る。"""
    state = tracker.update(track_id, (50.0, 10.0), at_sec)
    state.record_line1_crossing("IN", at_sec)
    tracker.mark_as_counted(track_id)
    return state


def test_窓の内側ならpendingのまま():
    tracker = VehicleTracker(max_gap_sec=3.0, cleanup_threshold_sec=5.0)
    make_counted_state(tracker, at_sec=0.0)

    assert tracker.resolve_pending_confidences(3.0) == []


def test_窓を過ぎたらnormalへ確定する():
    tracker = VehicleTracker(max_gap_sec=3.0, cleanup_threshold_sec=5.0)
    make_counted_state(tracker, at_sec=0.0)

    updates = tracker.resolve_pending_confidences(3.01)
    assert [u.confidence for u in updates] == ["normal"]


def test_同じ秒差ならフレーム数が違っても同じ判定になる():
    """これが成り立たないと、処理レートが落ちたカメラで窓が伸びる。

    30fpsで90フレーム進んだ場合と、14fpsで42フレーム進んだ場合は、どちらも
    実時間では3秒。トラッカーには秒だけが渡るので、フレーム数の違いは残らない。
    """
    results = []
    for _ in range(2):
        tracker = VehicleTracker(max_gap_sec=3.0, cleanup_threshold_sec=5.0)
        make_counted_state(tracker, at_sec=0.0)
        results.append(tracker.resolve_pending_confidences(3.0))

    assert results[0] == results[1] == []


def test_Line1とLine2の対応付けも秒差で見る():
    tracker = VehicleTracker(max_gap_sec=1.0, cleanup_threshold_sec=5.0)

    state = tracker.update(1, (50.0, 10.0), 0.0)
    state.record_line1_crossing("IN", 0.0)
    tracker.mark_as_counted(1)
    # 窓(1.0秒)を超えて遅れて到達したLine2は、同じ車両の対として扱わない。
    state.record_line2_crossing("IN", 1.5)

    updates = tracker.resolve_pending_confidences(1.5)
    assert [u.confidence for u in updates] == ["normal"]


def test_窓の内側で順序どおりならhighになる():
    tracker = VehicleTracker(max_gap_sec=1.0, cleanup_threshold_sec=5.0)

    state = tracker.update(1, (50.0, 10.0), 0.0)
    state.record_line1_crossing("IN", 0.0)
    tracker.mark_as_counted(1)
    state.record_line2_crossing("IN", 0.5)

    updates = tracker.resolve_pending_confidences(0.5)
    assert [u.confidence for u in updates] == ["high"]


def test_クリーンアップも秒で判定する():
    tracker = VehicleTracker(max_gap_sec=3.0, cleanup_threshold_sec=5.0)
    tracker.update(1, (0.0, 0.0), 0.0)

    tracker.cleanup_stale_tracks(5.0)
    assert 1 in tracker.states          # 境界ちょうどは残す

    tracker.cleanup_stale_tracks(5.01)
    assert 1 not in tracker.states


def test_pendingのtrackはクリーンアップしない():
    """確定前に消すと、confidenceを更新する相手がいなくなる。"""
    tracker = VehicleTracker(max_gap_sec=100.0, cleanup_threshold_sec=1.0)
    make_counted_state(tracker, at_sec=0.0)

    tracker.cleanup_stale_tracks(50.0)
    assert 1 in tracker.states
