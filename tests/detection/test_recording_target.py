"""録画の出力先の決め方に関するテスト。

カメラ入力の出力名は 'annotated_camera.mp4' の固定名で、起動するたびに前回の
録画を上書きしていた。本番で録り続ける用途では黙って証跡を失うため、実行開始
時刻をパスへ入れる。動画ファイル入力は入力名に紐づいた従来の単一ファイルを保つ。
"""
from datetime import datetime, timedelta, timezone

import run_detection
from run_detection import build_recording_target

STARTED = datetime(2026, 9, 18, 14, 30, 0, tzinfo=timezone(timedelta(hours=9)))


def test_動画ファイル入力は入力名の単一ファイル(tmp_path):
    path, segment_bytes = build_recording_target(
        str(tmp_path), "data/inputs/clip.mp4", segment_mb=256, started_at=STARTED
    )
    assert path.endswith("videos/annotated_clip.mp4")
    assert segment_bytes == 0          # 有限の入力なので分割しない


def test_カメラ入力は実行開始時刻のディレクトリへ分割(tmp_path):
    path, segment_bytes = build_recording_target(
        str(tmp_path), 0, segment_mb=256, started_at=STARTED
    )
    assert path.endswith("videos/camera_20260918_143000/segment_%05d.mp4")
    assert segment_bytes == 256 * 1024 * 1024


def test_カメラ入力のディレクトリが作られる(tmp_path):
    path, _ = build_recording_target(
        str(tmp_path), 0, segment_mb=16, started_at=STARTED
    )
    assert (tmp_path / "videos" / "camera_20260918_143000").is_dir()


def test_分割しない指定でも固定名にはしない(tmp_path):
    """上書き事故は分割の有無とは別の問題。分割を切っても起きないようにする。"""
    path, segment_bytes = build_recording_target(
        str(tmp_path), 0, segment_mb=0, started_at=STARTED
    )
    assert path.endswith("videos/annotated_camera_20260918_143000.mp4")
    assert segment_bytes == 0


def test_実行ごとに別の場所へ書く(tmp_path):
    """同じカメラで2回起動しても、前回の録画を上書きしない。"""
    first, _ = build_recording_target(
        str(tmp_path), 0, segment_mb=256, started_at=STARTED
    )
    second, _ = build_recording_target(
        str(tmp_path), 0, segment_mb=256,
        started_at=STARTED + timedelta(seconds=1),
    )
    assert first != second


def test_セグメントの書式はvideo_recorderと共有する(tmp_path):
    """名前の規則が2箇所に分かれると、片方だけ変えたときに気づけない。"""
    path, _ = build_recording_target(
        str(tmp_path), 0, segment_mb=256, started_at=STARTED
    )
    assert path.endswith(run_detection.SEGMENT_PATTERN)
