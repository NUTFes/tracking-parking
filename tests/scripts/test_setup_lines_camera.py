"""setup_lines.py のカメラ入力対応に関するテスト。

現地では設置カメラの画角でラインを引く必要がある。--videoしか無かった頃は
「クリップを録る→GUI」の二段になり、その録画と実行時でキャプチャ解像度が
違うと座標が静かにずれた。カメラから直接1枚掴むこと、その1枚を検知ループと
同じ解像度で掴むことを固定する。
"""
import cv2
import pytest

import setup_lines
from setup_lines import LineSetupGUI, main


class FakeCapture:
    """VideoCaptureの代役。set()と読み込み枚数を記録する。"""

    def __init__(self, frame, opened=True, actual=(1280, 720)):
        self.frame = frame
        self._opened = opened
        self.actual = actual
        self.calls = []
        self.reads = 0
        self.released = False

    def isOpened(self):
        return self._opened

    def set(self, prop, value):
        self.calls.append((prop, value))
        return True

    def get(self, prop):
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return self.actual[0]
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return self.actual[1]
        return 0

    def read(self):
        self.reads += 1
        return True, self.frame

    def release(self):
        self.released = True


class FakeFrame:
    """copy()だけ生やしたフレーム代役（numpyを持ち込まない）。"""

    def copy(self):
        return self


@pytest.fixture(autouse=True)
def clear_camera_env(monkeypatch):
    """load_dotenvは既存の環境変数を上書きしないため、前のテストが読み込んだ
    値がプロセスに残り、次のテストの.envを黙って上書きする。"""
    for key in ("CAMERA_WIDTH", "CAMERA_HEIGHT", "CAMERA_FOURCC"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env_file(tmp_path):
    def _write(text=""):
        path = tmp_path / "camera.env"
        path.write_text(text, encoding="utf-8")
        return str(path)
    return _write


def install_fake_capture(monkeypatch, cap):
    opened = {}

    def fake_video_capture(source):
        opened["source"] = source
        return cap

    monkeypatch.setattr(setup_lines.cv2, "VideoCapture", fake_video_capture)
    return opened


def test_カメラから1枚掴む(monkeypatch, env_file):
    cap = FakeCapture(FakeFrame())
    opened = install_fake_capture(monkeypatch, cap)

    gui = LineSetupGUI(0, env_file("CAMERA_WIDTH=1280\nCAMERA_HEIGHT=720\n"))
    assert gui.load_first_frame() is True

    assert opened["source"] == 0          # パスではなくデバイスIDで開く
    assert cap.released is True


def test_検知ループと同じ解像度を要求する(monkeypatch, env_file):
    """ここで掴んだフレーム上の座標がそのままLINE1_*になるため、
    実行時と解像度が違うと座標の意味が変わる。"""
    cap = FakeCapture(FakeFrame())
    install_fake_capture(monkeypatch, cap)

    gui = LineSetupGUI(
        0, env_file("CAMERA_WIDTH=1280\nCAMERA_HEIGHT=720\nCAMERA_FOURCC=MJPG\n")
    )
    assert gui.load_first_frame() is True

    assert (cv2.CAP_PROP_FRAME_WIDTH, 1280) in cap.calls
    assert (cv2.CAP_PROP_FRAME_HEIGHT, 720) in cap.calls
    assert cap.calls[0][0] == cv2.CAP_PROP_FOURCC


def test_露出が安定するまでフレームを捨てる(monkeypatch, env_file):
    """開いた直後の暗いフレームでラインを引くと、見えないものを避けて座標を置く。"""
    cap = FakeCapture(FakeFrame())
    install_fake_capture(monkeypatch, cap)

    gui = LineSetupGUI(0, env_file())
    assert gui.load_first_frame() is True
    assert cap.reads == setup_lines.CAMERA_WARMUP_FRAMES + 1


def test_動画ファイル入力では解像度に触らない(monkeypatch, env_file):
    """解像度はファイル側が決める。"""
    cap = FakeCapture(FakeFrame())
    install_fake_capture(monkeypatch, cap)

    gui = LineSetupGUI("clip.mp4", env_file("CAMERA_WIDTH=1280\nCAMERA_HEIGHT=720\n"))
    assert gui.load_first_frame() is True
    assert cap.calls == []
    assert cap.reads == 1


def test_カメラ設定が不正なら掴む前に止まる(monkeypatch, env_file):
    """幅だけの指定はドライバが勝手に丸めるため、意図した画角にならない。"""
    cap = FakeCapture(FakeFrame())
    install_fake_capture(monkeypatch, cap)

    gui = LineSetupGUI(0, env_file("CAMERA_WIDTH=1280\n"))
    assert gui.load_first_frame() is False
    assert cap.reads == 0


def test_videoとcameraは同時に指定できない(monkeypatch):
    monkeypatch.setattr(
        "sys.argv", ["setup_lines.py", "--video", "a.mp4", "--camera", "0"]
    )
    with pytest.raises(SystemExit):
        main()


def test_どちらも指定しなければ止まる(monkeypatch):
    monkeypatch.setattr("sys.argv", ["setup_lines.py"])
    with pytest.raises(SystemExit):
        main()
