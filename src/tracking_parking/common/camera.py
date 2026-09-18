"""カメラキャプチャの解像度指定（検知ループとライン設定ツールの共通処理）。

ライン座標は「ある画角のフレーム上でクリックした座標」であり、検知ループが
別の解像度でフレームを掴むと座標の意味が変わる。setup_lines.py と
run_detection.py が別々に解像度を決めると、この一致が規約頼みになるため、
両方がこのモジュールを通す。

指定しないとデバイス既定で開く。Logitech C270の既定は640x480で、1280x720を
出せるのに使われない。
"""

import cv2

__all__ = ["apply_camera_capture_settings"]


def apply_camera_capture_settings(cap, *, width, height, fourcc) -> None:
    """カメラの要求解像度をドライバへ指定する。カメラ入力のときだけ呼ぶ。

    動画ファイル入力では解像度はファイル側が決めるので呼ばない。

    FOURCCを先に設定するのは、解像度だけ指定しても対応しない組み合わせが
    あるため（C270のYUYVは640x480までで、1280x720はMJPGでしか出ない）。

    要求が通るとは限らずドライバは近い値へ丸める。呼び出し側は設定後に
    必ず実測値を読み直す必要がある（この関数は要求するだけで、保証しない）。

    Args:
        cap: cv2.VideoCapture（open済み）
        width: 要求する幅。Noneならデバイス既定に任せる。
        height: 要求する高さ。Noneならデバイス既定に任せる。
        fourcc: 要求するFOURCC（例: "MJPG"）。Noneなら指定しない。
    """
    if fourcc:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    if width is not None and height is not None:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
