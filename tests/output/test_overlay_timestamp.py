"""オーバーレイに焼き込む時刻に関するテスト。

事後分析では、この時刻がイベント記録（APIへ送るdetected_at）と動画の位置を
突き合わせる手がかりになる。機体のタイムゾーン設定に関係なく日本時刻が出ること、
秒まで出ること、ASCIIに収まること（非ASCIIは'?'になるだけで例外は出ない）を固定する。
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from tracking_parking.config import Line
from tracking_parking.detection.tracker import VehicleTracker
from tracking_parking.output.video_writer import (
    VideoAnnotator,
    build_overlay_lines,
    format_jst,
)

SUMMARY = {
    "total_in": 10,
    "total_out": 3,
    "current_parked": 7,
    "high_confidence_events": 8,
    "normal_confidence_events": 2,
    "active_tracks": 12,
}


def test_UTCの時刻を日本時刻へ直す():
    moment = datetime(2026, 9, 18, 2, 27, 6, tzinfo=timezone.utc)
    assert format_jst(moment) == "2026-09-18 11:27:06 JST"


def test_機体のタイムゾーンに関係なく日本時刻になる():
    """機体がUTC設定のままでも、動画には日本時刻を焼き込む。"""
    same_moment_utc = datetime(2026, 9, 18, 2, 27, 6, tzinfo=timezone.utc)
    same_moment_jst = datetime(2026, 9, 18, 11, 27, 6,
                               tzinfo=timezone(timedelta(hours=9)))
    same_moment_hawaii = datetime(2026, 9, 17, 16, 27, 6,
                                  tzinfo=timezone(timedelta(hours=-10)))
    assert (format_jst(same_moment_utc)
            == format_jst(same_moment_jst)
            == format_jst(same_moment_hawaii))


def test_日付をまたぐ変換():
    """UTCの夜はJSTでは翌日。日付ごとズレると事後分析で別の日を見ることになる。"""
    moment = datetime(2026, 9, 18, 20, 0, 0, tzinfo=timezone.utc)
    assert format_jst(moment) == "2026-09-19 05:00:00 JST"


def test_秒まで出す():
    """イベント記録と動画の位置を突き合わせるのに秒が要る。"""
    moment = datetime(2026, 9, 18, 11, 27, 6, tzinfo=timezone(timedelta(hours=9)))
    assert ":06 JST" in format_jst(moment)


def test_時刻はASCIIに収まる():
    """cv2.putTextはASCIIしか描けない。"""
    assert format_jst(datetime.now(timezone.utc)).isascii()


def test_時刻は最初の行に出る():
    lines = build_overlay_lines(SUMMARY, 170, 116.9, datetime.now(timezone.utc))
    assert "JST" in lines[0]
    assert lines[1] == "Frame: 170"


def test_時刻を渡さなければ行が増えない():
    """動画ファイル入力など、取得時刻が意味を持たない場合に空欄を出さない。"""
    without = build_overlay_lines(SUMMARY, 170, 116.9, None)
    with_time = build_overlay_lines(SUMMARY, 170, 116.9, datetime.now(timezone.utc))
    assert len(with_time) == len(without) + 1
    assert all("JST" not in line for line in without)


def test_全行がASCII():
    lines = build_overlay_lines(SUMMARY, 170, 116.9, datetime.now(timezone.utc))
    assert all(line.isascii() for line in lines)


@pytest.mark.parametrize("captured_at", [None, datetime.now(timezone.utc)])
def test_背景枠が全行を覆う(captured_at):
    """枠の高さを固定値にしていたため、行を足すと文字が枠の外へ出ていた。

    枠の外に白文字が出ると、明るい背景では読めなくなる。
    """
    annotator = VideoAnnotator(
        line1=Line(start=(0, 300), end=(600, 300)),
        line2=Line(start=(0, 400), end=(600, 400)),
        parking_ref_point=(300.0, 450.0),
    )
    tracker = VehicleTracker(max_gap_sec=3.0, cleanup_threshold_sec=5.0)

    # 一様な白地に描き、枠（暗い矩形）が最終行のベースラインより下まで
    # 伸びていることを画素で確かめる。
    frame = np.full((500, 700, 3), 255, np.uint8)
    out = annotator.draw_count_overlay(frame, tracker, 170, 116.9, captured_at)

    lines = build_overlay_lines(tracker.get_summary(), 170, 116.9, captured_at)
    last_baseline = 35 + 25 * (len(lines) - 1)
    # 最終行のベースラインの数px下が、まだ枠の中（暗い）であること
    assert out[last_baseline + 3, 20].max() < 200
