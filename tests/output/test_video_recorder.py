"""録画先の選択と、NVENC経路のパイプラインに関するテスト。

実際のエンコードはハードウェア依存なので、ここで固定するのは選択の規則と
パイプラインの形。パイプの形が崩れると、映像が壊れるのは実行してから分かる
（バイト列の位置でフレームを区切るため、サイズや色形式がずれると以降すべてが
ずれる）ので、形そのものをテストで押さえる。
"""
import numpy as np
import pytest

from tracking_parking.output import video_recorder
from tracking_parking.output.video_recorder import (
    ENCODER_CHOICES,
    Cv2Recorder,
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


def test_autoはNVENCが使えればNVENCを選ぶ(has_nvenc, tmp_path):
    rec = open_recorder(str(tmp_path / "a.mp4"), width=1280, height=720,
                        fps=12.0, encoder="auto")
    assert isinstance(rec, NvencRecorder)
    assert rec.name == "nvenc"


def test_autoはNVENCが無ければcv2へ落ちる(no_nvenc, tmp_path):
    rec = open_recorder(str(tmp_path / "a.mp4"), width=320, height=240,
                        fps=12.0, encoder="auto")
    assert isinstance(rec, Cv2Recorder)
    assert rec.name == "cv2"
    rec.release()


def test_cv2指定はNVENCがあってもcv2を使う(has_nvenc, tmp_path):
    """速度より再現性を採る場合のために、明示指定が効くこと。"""
    rec = open_recorder(str(tmp_path / "a.mp4"), width=320, height=240,
                        fps=12.0, encoder="cv2")
    assert isinstance(rec, Cv2Recorder)
    rec.release()


def test_nvenc指定でNVENCが無ければ黙って落とさない(no_nvenc, tmp_path):
    """cv2へ勝手に落ちると、速いつもりで遅い経路で走り続けることになる。"""
    with pytest.raises(ValueError, match="nvenc"):
        open_recorder(str(tmp_path / "a.mp4"), width=1280, height=720,
                      fps=12.0, encoder="nvenc")


def test_未知のエンコーダ名は弾く(tmp_path):
    with pytest.raises(ValueError, match="VIDEO_ENCODER"):
        open_recorder(str(tmp_path / "a.mp4"), width=1280, height=720,
                      fps=12.0, encoder="h265")


@pytest.mark.parametrize("width, height", [(1281, 720), (1280, 721)])
def test_奇数サイズはNVENCへ渡さない(has_nvenc, tmp_path, width, height):
    """H.264は幅・高さが偶数である必要がある。"""
    rec = open_recorder(str(tmp_path / "a.mp4"), width=width, height=height,
                        fps=12.0, encoder="auto")
    assert isinstance(rec, Cv2Recorder)
    rec.release()


def test_パイプラインの形(has_nvenc, tmp_path):
    path = str(tmp_path / "a.mp4")
    open_recorder(path, width=1280, height=720, fps=12.0, encoder="nvenc")
    argv = has_nvenc["argv"]

    assert argv[0] == "gst-launch-1.0"
    joined = " ".join(argv)
    # 生BGRを受け取り、NVENCでH.264にしてmp4へ入れる
    assert "fdsrc" in joined and "format=bgr" in joined
    assert "nvv4l2h264enc" in joined
    assert f"location={path}" in joined
    # 下流の詰まりがstdin.write()へ伝わらないようにqueueを挟む
    assert "queue" in joined
    # queueの暗黙のバイト上限(既定10MB)は外す。生BGRは1280x720で2.7MB/フレーム
    # なので、外さないと枚数指定が効かないまま約3.8枚で間引かれる。
    assert "max-size-bytes=0" in argv
    assert "max-size-time=0" in argv
    # 下流が止まったとき（ディスク満杯など）にカウント処理まで止めない
    assert "leaky=downstream" in argv
    # 解像度はパイプの区切りそのものなので、必ず渡っていること
    assert "width=1280" in argv and "height=720" in argv


def test_fpsは分数で渡す(has_nvenc, tmp_path):
    """GStreamerのframerateは分数。小数fpsを落とさないこと。"""
    open_recorder(str(tmp_path / "a.mp4"), width=640, height=480,
                  fps=11.5, encoder="nvenc")
    assert "framerate=11500/1000" in has_nvenc["argv"]


def test_エンコーダ名の選択肢():
    assert ENCODER_CHOICES == ("auto", "nvenc", "cv2")


def test_サイズの違うフレームは受け取らない(monkeypatch):
    """パイプはバイト列の位置でフレームを区切るため、1枚ずれると以降すべてが崩れる。"""
    written = []

    class FakeStdin:
        def write(self, data):
            written.append(len(data))

    class FakeProc:
        def __init__(self, *a, **kw):
            self.stdin = FakeStdin()
            self.stderr = None

        def poll(self):
            return None

    monkeypatch.setattr(video_recorder.subprocess, "Popen", FakeProc)
    rec = NvencRecorder("x.mp4", width=64, height=48, fps=12.0)

    rec.write(np.zeros((48, 64, 3), np.uint8))
    assert written == [64 * 48 * 3]

    with pytest.raises(ValueError, match="大きさ"):
        rec.write(np.zeros((49, 64, 3), np.uint8))
