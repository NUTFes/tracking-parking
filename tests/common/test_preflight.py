"""本番実行の事前チェックに関するテスト。

ここで見ているのは「起動はするが結果が静かにおかしくなる」条件。特にライン座標が
画角の外に出ているケースは、一度も交差せずイベントがゼロのまま動き続けるため、
実行してもエラーにならない。実機のjetson-newcam.envが実際にこの状態だった
（1920x1080で設定した座標のまま、カメラは1280x720）。
"""
from types import SimpleNamespace

from tracking_parking.common.preflight import (
    check_disk_space,
    check_line_bounds,
    describe_frame_mismatch,
)


def make_config(line1=((100, 300), (600, 300)), line2=((150, 200), (550, 200)),
                ref=(350.0, 150.0)):
    return SimpleNamespace(
        line1=SimpleNamespace(start=line1[0], end=line1[1]),
        line2=SimpleNamespace(start=line2[0], end=line2[1]),
        parking_ref_point=ref,
    )


def test_画角の内側なら問題なし():
    assert check_line_bounds(make_config(), 1280, 720) == []


def test_画角の外に出ている座標を指摘する():
    """xだけが外に出ているケース。どの点がどの値で外れたかを出す。"""
    config = make_config(line1=((1591, 300), (600, 300)))
    problems = check_line_bounds(config, 1280, 720)
    assert len(problems) == 1
    assert "LINE1 始点" in problems[0]
    assert "1591" in problems[0] and "1280x720" in problems[0]


def test_高さだけが外に出ていても指摘する():
    """1920x1080で設定した座標を1280x720で使うと、yも720を超える。
    xだけ見ていると見落とす。"""
    config = make_config(line1=((600, 879), (600, 300)))
    problems = check_line_bounds(config, 1280, 720)
    assert len(problems) == 1
    assert "879" in problems[0]


def test_複数の座標が外に出ていれば全部挙げる():
    """1つ直して再実行、を繰り返さずに済むように。"""
    config = make_config(
        line1=((1591, 879), (225, 863)),
        line2=((1527, 792), (1288, 900)),
        ref=(1492.0, 820.0),
    )
    problems = check_line_bounds(config, 1280, 720)
    # 実機のjetson-newcam.envそのままの値。x・yの両方が超えるため5点すべてが外。
    assert len(problems) == 5


def test_負の座標も外とみなす():
    config = make_config(ref=(-1.0, 100.0))
    assert any("駐車場基準点" in p for p in check_line_bounds(config, 1280, 720))


def test_境界はフレーム内の最後の画素まで():
    """width=1280 のとき有効なxは0..1279。1280は外。"""
    assert check_line_bounds(make_config(ref=(1279.0, 719.0)), 1280, 720) == []
    assert check_line_bounds(make_config(ref=(1280.0, 719.0)), 1280, 720) != []


def test_解像度が一致していれば問題なし():
    assert describe_frame_mismatch((1280, 720), (1280, 720)) == []


def test_解像度が丸められたら指摘する():
    problems = describe_frame_mismatch((1920, 1080), (1280, 960))
    assert len(problems) == 1
    assert "1920x1080" in problems[0] and "1280x960" in problems[0]


def test_解像度が未設定なら指摘する():
    """未設定だとデバイス既定で開くため、ライン座標を設定した画角と一致する
    保証がない。"""
    problems = describe_frame_mismatch((None, None), (640, 480))
    assert len(problems) == 1
    assert "CAMERA_WIDTH" in problems[0]


def test_空き容量が足りていれば問題なし():
    assert check_disk_space(200 * 1024**3, need_bytes=100 * 1024**3) == []


def test_空き容量が足りなければ指摘する():
    problems = check_disk_space(10 * 1024**3, need_bytes=100 * 1024**3)
    assert len(problems) == 1
    assert "10.0GB" in problems[0] and "100.0GB" in problems[0]
