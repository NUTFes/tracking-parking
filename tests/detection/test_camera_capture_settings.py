"""カメラへ要求解像度を指定する配線のテスト。

実カメラを繋がずに確認したいのは2点。未設定なら何も押し付けないことと、
FOURCCを解像度より先に設定すること。後者は順序が逆だと通らない組み合わせが
あるため（C270のYUYVは640x480までで、1280x720はMJPGでしか出ない）、
順序自体をテストで固定する。
"""
from types import SimpleNamespace

import cv2

import run_detection
from tracking_parking.common.camera import apply_camera_capture_settings


class FakeCapture:
    """set()の呼び出し順序を記録するだけのVideoCapture代役。"""

    def __init__(self):
        self.calls = []

    def set(self, prop, value):
        self.calls.append((prop, value))
        return True

    def props(self):
        return [prop for prop, _ in self.calls]


def test_FOURCCを解像度より先に設定する():
    cap = FakeCapture()
    apply_camera_capture_settings(cap, width=1280, height=720, fourcc="MJPG")
    props = cap.props()
    assert props.index(cv2.CAP_PROP_FOURCC) < props.index(cv2.CAP_PROP_FRAME_WIDTH)


def test_解像度を要求する():
    cap = FakeCapture()
    apply_camera_capture_settings(cap, width=1280, height=720, fourcc=None)
    assert (cv2.CAP_PROP_FRAME_WIDTH, 1280) in cap.calls
    assert (cv2.CAP_PROP_FRAME_HEIGHT, 720) in cap.calls


def test_未設定なら何も要求しない():
    """既定に任せる指定のとき、こちらから値を押し付けない。"""
    cap = FakeCapture()
    apply_camera_capture_settings(cap, width=None, height=None, fourcc=None)
    assert cap.calls == []


def test_FOURCCだけの指定でも解像度には触らない():
    cap = FakeCapture()
    apply_camera_capture_settings(cap, width=None, height=None, fourcc="MJPG")
    assert cap.props() == [cv2.CAP_PROP_FOURCC]


def test_run_detectionはConfigの値をそのまま共通処理へ渡す():
    """検知ループとsetup_lines.pyが別の解像度で開くと、ライン座標の意味が変わる。
    薄いラッパが値を取り違えていないことを固定する。"""
    cap = FakeCapture()
    run_detection.apply_camera_capture_settings(
        cap,
        SimpleNamespace(camera_width=1280, camera_height=720, camera_fourcc="MJPG"),
    )
    assert (cv2.CAP_PROP_FRAME_WIDTH, 1280) in cap.calls
    assert (cv2.CAP_PROP_FRAME_HEIGHT, 720) in cap.calls
    assert cap.props()[0] == cv2.CAP_PROP_FOURCC
