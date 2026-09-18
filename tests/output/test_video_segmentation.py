"""録画のファイル分割に関するテスト。

分割の目的は、mp4のインデックス(moov atom)が終了時に書かれるため、途中で
プロセスが落ちるとそれまでの全録画が再生不能になるのを防ぐこと。失う範囲を
1本に限る。ここで固定するのは命名・閾値・保持数の規則と、分割指定なのに
連番の書式が無いまま同じ名前へ書き続ける事故が起きないこと。
"""
import os

import numpy as np
import pytest

from tracking_parking.output import video_recorder
from tracking_parking.output.video_recorder import (
    SEGMENT_PATTERN,
    Cv2Recorder,
    Cv2SegmentedRecorder,
    NvencRecorder,
    open_recorder,
)


@pytest.fixture
def no_nvenc(monkeypatch):
    monkeypatch.setattr(video_recorder, "nvenc_available", lambda: False)


@pytest.fixture
def has_nvenc(monkeypatch):
    monkeypatch.setattr(video_recorder, "nvenc_available", lambda: True)
    created = {}

    class FakeProc:
        def __init__(self, *a, **kw):
            created["argv"] = a[0]
            self.stdin = None
            self.stderr = None

        def poll(self):
            return None

    monkeypatch.setattr(video_recorder.subprocess, "Popen", FakeProc)
    return created


def test_分割指定でsplitmuxsinkを使う(has_nvenc, tmp_path):
    """splitmuxsinkはセグメントごとにmoovを書いて確定させる。filesinkのままだと
    最後まで走り切らない限り再生できない。"""
    pattern = str(tmp_path / SEGMENT_PATTERN)
    open_recorder(pattern, width=1280, height=720, fps=12.0,
                  encoder="nvenc", segment_bytes=1024 * 1024, max_segments=5)
    argv = has_nvenc["argv"]
    assert "splitmuxsink" in argv
    assert "mp4mux" not in argv and "filesink" not in argv
    assert f"location={pattern}" in argv
    assert "max-size-bytes=1048576" in argv
    assert "max-files=5" in argv


def test_分割しない指定はfilesinkのまま(has_nvenc, tmp_path):
    open_recorder(str(tmp_path / "a.mp4"), width=1280, height=720, fps=12.0,
                  encoder="nvenc", segment_bytes=0)
    argv = has_nvenc["argv"]
    assert "splitmuxsink" not in argv
    assert "filesink" in argv


def test_時間ではなくサイズで区切る(has_nvenc, tmp_path):
    """書き出しfpsが実効fpsと一致しないため、時間指定は実時間とずれる。"""
    open_recorder(str(tmp_path / SEGMENT_PATTERN), width=1280, height=720,
                  fps=12.0, encoder="nvenc", segment_bytes=1024)
    argv = has_nvenc["argv"]
    split_at = argv.index("splitmuxsink")
    assert not any(a.startswith("max-size-time=") for a in argv[split_at:])


def test_連番の書式が無いまま分割しようとしたら弾く(has_nvenc, tmp_path):
    """書式が無いと同じ名前へ上書きし続け、分割した意味が無くなる。
    しかも失敗としては現れない。"""
    with pytest.raises(ValueError, match="連番の書式"):
        open_recorder(str(tmp_path / "a.mp4"), width=1280, height=720,
                      fps=12.0, encoder="nvenc", segment_bytes=1024)


def test_cv2経路も分割する(no_nvenc, tmp_path):
    rec = open_recorder(str(tmp_path / SEGMENT_PATTERN), width=64, height=48,
                        fps=12.0, encoder="cv2", segment_bytes=1024)
    assert isinstance(rec, Cv2SegmentedRecorder)
    rec.release()


def test_cv2経路で分割しない指定は単一ファイル(no_nvenc, tmp_path):
    rec = open_recorder(str(tmp_path / "a.mp4"), width=64, height=48,
                        fps=12.0, encoder="cv2", segment_bytes=0)
    assert isinstance(rec, Cv2Recorder)
    rec.release()


def test_cv2経路の分割は連番で増える(tmp_path):
    """閾値を極端に小さくして、複数本に分かれることを確かめる。"""
    pattern = str(tmp_path / SEGMENT_PATTERN)
    rec = Cv2SegmentedRecorder(pattern, width=64, height=48, fps=12.0,
                               segment_bytes=1)
    frame = np.zeros((48, 64, 3), np.uint8)
    for _ in range(3):
        rec.write(frame)
    rec.release()

    names = sorted(os.listdir(tmp_path))
    assert names[0] == "segment_00000.mp4"
    assert len(names) >= 2, f"分割されていない: {names}"


def test_cv2経路は保持数ぶんの名前を循環させる(tmp_path):
    """splitmuxsinkのmax-filesがリングバッファとして動くため、そちらへ揃えている。
    連番を増やして古いものを消す方式だと、エンコーダを切り替えた時点で
    ディレクトリの構成が変わってしまう。"""
    pattern = str(tmp_path / SEGMENT_PATTERN)
    rec = Cv2SegmentedRecorder(pattern, width=64, height=48, fps=12.0,
                               segment_bytes=1, max_segments=2)
    frame = np.zeros((48, 64, 3), np.uint8)
    for _ in range(5):
        rec.write(frame)
    rec.release()

    names = sorted(os.listdir(tmp_path))
    assert names == ["segment_00000.mp4", "segment_00001.mp4"]


def test_保持数0なら消さない(tmp_path):
    """既定を無制限にしているのは、事後分析用の証跡を黙って消さないため。"""
    pattern = str(tmp_path / SEGMENT_PATTERN)
    rec = Cv2SegmentedRecorder(pattern, width=64, height=48, fps=12.0,
                               segment_bytes=1, max_segments=0)
    frame = np.zeros((48, 64, 3), np.uint8)
    for _ in range(4):
        rec.write(frame)
    rec.release()

    assert len(os.listdir(tmp_path)) >= 3


def test_セグメント名の書式():
    """NVENC側とcv2側で同じ名前になること（エンコーダを変えても中身の構成が変わらない）。"""
    assert SEGMENT_PATTERN % 0 == "segment_00000.mp4"
    assert SEGMENT_PATTERN % 42 == "segment_00042.mp4"


def test_保持数なしなら番号は増え続ける(tmp_path):
    """時系列が名前から読めるのはこちらの場合だけ。既定を無制限にしている
    理由のひとつでもある。"""
    pattern = str(tmp_path / SEGMENT_PATTERN)
    rec = Cv2SegmentedRecorder(pattern, width=64, height=48, fps=12.0,
                               segment_bytes=1, max_segments=0)
    frame = np.zeros((48, 64, 3), np.uint8)
    for _ in range(3):
        rec.write(frame)
    rec.release()

    names = sorted(os.listdir(tmp_path))
    assert names[:2] == ["segment_00000.mp4", "segment_00001.mp4"]
    assert len(names) >= 3
