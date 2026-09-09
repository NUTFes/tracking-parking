"""時間窓（秒）の設定読み込みに関するテスト。

フレーム基準から秒基準へ移行したため、旧env varが残った.envを黙って
無視しないことと、既定値が旧既定の30fps換算と一致することを確認する。
"""
import pytest

from detection.config import Config

# from_env が必須とする最小限のenv。
REQUIRED = {
    "HOME_DIR": "/tmp/line-detection-test",
    "MODEL_PATH": "yolov8s.pt",
    "LINE1_X1": "0", "LINE1_Y1": "0", "LINE1_X2": "100", "LINE1_Y2": "0",
    "LINE2_X1": "0", "LINE2_Y1": "50", "LINE2_X2": "100", "LINE2_Y2": "50",
    "PARKING_REF_X": "50", "PARKING_REF_Y": "100",
}

TIME_WINDOW_VARS = (
    "MAX_FRAME_GAP", "CLEANUP_THRESHOLD",
    "MAX_FRAME_GAP_SEC", "CLEANUP_THRESHOLD_SEC",
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """.envの探索結果に左右されないよう、空の.envを明示的に読ませる。"""
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)
    for key in TIME_WINDOW_VARS:
        monkeypatch.delenv(key, raising=False)
    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")
    return lambda: Config.from_env(str(empty_env))


def test_既定値は旧既定の30fps換算と一致する(env):
    """MAX_FRAME_GAP=90 / CLEANUP_THRESHOLD=150 は30fpsで3秒 / 5秒だった。"""
    config = env()
    assert config.max_frame_gap_sec == 3.0
    assert config.cleanup_threshold_sec == 5.0


def test_秒指定を読み込む(env, monkeypatch):
    monkeypatch.setenv("MAX_FRAME_GAP_SEC", "2.5")
    monkeypatch.setenv("CLEANUP_THRESHOLD_SEC", "7.5")
    config = env()
    assert config.max_frame_gap_sec == 2.5
    assert config.cleanup_threshold_sec == 7.5


@pytest.mark.parametrize(
    "old_name, new_name",
    [("MAX_FRAME_GAP", "MAX_FRAME_GAP_SEC"),
     ("CLEANUP_THRESHOLD", "CLEANUP_THRESHOLD_SEC")],
)
def test_旧env_varが残っていたら移行を促して停止する(env, monkeypatch, old_name, new_name):
    """フレーム数の設定を黙って無視すると、窓の長さが意図せず既定値へ戻る。"""
    monkeypatch.setenv(old_name, "90")
    with pytest.raises(ValueError, match=new_name):
        env()


@pytest.mark.parametrize(
    "old_name, new_name",
    [("MAX_FRAME_GAP", "MAX_FRAME_GAP_SEC"),
     ("CLEANUP_THRESHOLD", "CLEANUP_THRESHOLD_SEC")],
)
def test_新旧が併記されていれば新のみを使う(env, monkeypatch, old_name, new_name):
    """移行途中の.envを許容する（新が書いてあれば旧は無視してよい）。"""
    monkeypatch.setenv(old_name, "90")
    monkeypatch.setenv(new_name, "4.0")
    config = env()
    assert getattr(config, new_name.lower()) == 4.0
