"""カメラ入力の解像度設定に関するテスト。

指定しないとデバイス既定（Logitech C270は640x480）で開くため、ライン座標を
1280x720のクリップで設定していると座標が全てずれる。実機で必ず踏む問題なので、
「未設定」と「明示指定」が区別されることと、中途半端な指定が通らないことを固定する。
"""
import pytest

from tracking_parking.config import Config, Line

REQUIRED = {
    "HOME_DIR": "/tmp/line-detection-test",
    "MODEL_PATH": "yolov8s.pt",
    "LINE1_X1": "0", "LINE1_Y1": "0", "LINE1_X2": "100", "LINE1_Y2": "0",
    "LINE2_X1": "0", "LINE2_Y1": "50", "LINE2_X2": "100", "LINE2_Y2": "50",
    "PARKING_REF_X": "50", "PARKING_REF_Y": "100",
}

CAMERA_VARS = ("CAMERA_WIDTH", "CAMERA_HEIGHT", "CAMERA_FOURCC")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """.envの探索結果に左右されないよう、空の.envを明示的に読ませる。"""
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)
    for key in CAMERA_VARS:
        monkeypatch.delenv(key, raising=False)
    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")
    return lambda: Config.from_env(str(empty_env))


def make_config(**overrides) -> Config:
    """validate()のカメラ検査だけを見るための最小Config。"""
    base = dict(
        home_dir="/tmp/line-detection-test",
        model_path="yolov8s.pt",
        confidence_threshold=0.25,
        vehicle_classes=[2, 7],
        line1=Line(start=(0, 0), end=(100, 0)),
        line2=Line(start=(0, 50), end=(100, 50)),
        parking_ref_point=(50.0, 100.0),
        margin_px=5.0,
        endpoint_margin_px=0.0,
        max_frame_gap_sec=3.0,
        cleanup_threshold_sec=5.0,
        iou_threshold=0.7,
        method="hybrid",
        save_video=False,
        save_logs=True,
        show_display=False,
        video_encoder="auto",
        video_segment_mb=256,
        video_max_segments=0,
        camera_width=None,
        camera_height=None,
        camera_fourcc=None,
    )
    base.update(overrides)
    return Config(**base)


def test_未設定ならNoneのままでデバイス既定に任せる(env):
    """0やデフォルト値で埋めると「既定に任せる」意思を表現できなくなる。"""
    config = env()
    assert config.camera_width is None
    assert config.camera_height is None
    assert config.camera_fourcc is None


def test_解像度とFOURCCを読み込む(env, monkeypatch):
    monkeypatch.setenv("CAMERA_WIDTH", "1280")
    monkeypatch.setenv("CAMERA_HEIGHT", "720")
    monkeypatch.setenv("CAMERA_FOURCC", "MJPG")
    config = env()
    assert (config.camera_width, config.camera_height) == (1280, 720)
    assert config.camera_fourcc == "MJPG"


def test_空文字は未設定として扱う(env, monkeypatch):
    """.envでキーだけ残して値を消した状態を「既定に任せる」と読む。"""
    monkeypatch.setenv("CAMERA_WIDTH", "")
    monkeypatch.setenv("CAMERA_FOURCC", "")
    config = env()
    assert config.camera_width is None
    assert config.camera_fourcc is None


def test_整数でない解像度は読み込み時に弾く(env, monkeypatch):
    monkeypatch.setenv("CAMERA_WIDTH", "1280.5")
    with pytest.raises(ValueError, match="CAMERA_WIDTH"):
        env()


def test_片方だけの指定は弾く():
    """幅だけ指定してもドライバが対応する組み合わせへ勝手に丸めるため、
    意図した画角にならないまま気づけない。"""
    with pytest.raises(ValueError, match="CAMERA_WIDTHとCAMERA_HEIGHT"):
        make_config(camera_width=1280, camera_height=None).validate()


@pytest.mark.parametrize("width, height", [(0, 720), (1280, -1)])
def test_非正の解像度は弾く(width, height):
    with pytest.raises(ValueError, match="正の整数"):
        make_config(camera_width=width, camera_height=height).validate()


def test_FOURCCが4文字でなければ弾く():
    """cv2.VideoWriter_fourccは4文字前提で、短い値を渡すと静かに別の値になる。"""
    with pytest.raises(ValueError, match="CAMERA_FOURCC"):
        make_config(camera_fourcc="MJP").validate()
