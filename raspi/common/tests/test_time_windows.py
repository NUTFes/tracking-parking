import math

import pytest

from common.time_windows import frames_from_seconds


@pytest.mark.parametrize(
    "seconds, fps, expected",
    [
        # 30fpsでは、これまでフレーム単位で持っていた既定値と一致する
        # （ROI: cleanup 150 / candidate 300、2ライン: max_frame_gap 90）。
        (5.0, 30.0, 150),
        (10.0, 30.0, 300),
        (3.0, 30.0, 90),
        # 実機に近い10fpsでは、同じ秒数がフレーム数として1/3になる。
        (5.0, 10.0, 50),
        (10.0, 10.0, 100),
        (3.0, 10.0, 30),
        # 端数は四捨五入する。
        (1.0, 24.0, 24),
        (0.5, 25.0, 13),
        (2.5, 10.0, 25),
    ],
)
def test_秒とfpsからフレーム数を導出する(seconds, fps, expected):
    assert frames_from_seconds(seconds, fps) == expected


def test_ゼロ秒はゼロフレームのまま返す():
    """0は「即座に失効させる」という指定であり、1へ繰り上げてはいけない。"""
    assert frames_from_seconds(0, 30.0) == 0
    assert frames_from_seconds(0.0, 10.0) == 0


def test_正の秒数は丸めで消えず最低1フレームになる():
    """窓を指定したのに0フレーム＝無効化される事故を防ぐ。"""
    assert frames_from_seconds(0.001, 10.0) == 1
    assert frames_from_seconds(0.01, 1.0) == 1


def test_同じ秒数はfpsが変わっても同じ時間長を表す():
    seconds = 5.0
    for fps in (10.0, 15.0, 24.0, 30.0, 60.0):
        frames = frames_from_seconds(seconds, fps)
        assert math.isclose(frames / fps, seconds, rel_tol=0.05)


@pytest.mark.parametrize("seconds", [-1.0, -0.001, float("nan"), float("inf")])
def test_不正なsecondsを拒否する(seconds):
    with pytest.raises(ValueError, match="seconds"):
        frames_from_seconds(seconds, 30.0)


@pytest.mark.parametrize("fps", [0, 0.0, -30.0, float("nan"), float("inf")])
def test_不正なfpsを拒否する(fps):
    """fpsが取れないまま変換すると、窓の長さが黙って狂う。"""
    with pytest.raises(ValueError, match="fps"):
        frames_from_seconds(5.0, fps)
