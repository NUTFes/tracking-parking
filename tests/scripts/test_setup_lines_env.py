"""setup_lines.py が .env へ書き戻す際の契約テスト。

以前はファイル全体をハードコードのテンプレートで上書きしており、比較条件のために
手で入れた値（CONFIDENCE_THRESHOLD、VEHICLE_CLASSES など）が消えていた。さらに
テンプレートが廃止済みの CLEANUP_THRESHOLD を書き出すため、GUI実行後の .env では
Config.from_env が移行エラーで停止する状態だった。

roi-counter の roi_config.py と同じ契約（書き込むのは対象キーだけ、他は保持）に
揃えたことを確認する。
"""
import pytest

from setup_lines import (
    LINE_ENV_KEYS,
    apply_line_values,
    build_line_env_values,
)

POINTS = [(10, 20), (30, 40), (50, 60), (70, 80), (90, 100)]


def test_5点をライン座標のキーへ順に割り当てる():
    v = build_line_env_values(POINTS)
    assert list(v) == list(LINE_ENV_KEYS)
    assert v["LINE1_START_X"] == 10 and v["LINE1_START_Y"] == 20
    assert v["LINE2_END_X"] == 70 and v["LINE2_END_Y"] == 80
    assert v["PARKING_REF_X"] == 90 and v["PARKING_REF_Y"] == 100


@pytest.mark.parametrize("n", [0, 4, 6])
def test_5点でなければ拒否する(n):
    with pytest.raises(ValueError, match="5点"):
        build_line_env_values([(1, 1)] * n)


def test_既存キーは行ごと差し替える():
    before = "LINE1_START_X=999\nLINE1_START_Y=888\n"
    after = apply_line_values(before, build_line_env_values(POINTS))
    assert "LINE1_START_X=10" in after
    assert "LINE1_START_Y=20" in after
    assert "999" not in after and "888" not in after


def test_他のキーとコメントを保持する():
    """比較条件のために手で入れた値が消えないこと。"""
    before = (
        "# 比較条件（ROI方式と揃える）\n"
        "MODEL_PATH=yolov8s.pt\n"
        "CONFIDENCE_THRESHOLD=0.25\n"
        "VEHICLE_CLASSES=2,7\n"
        "IOU_THRESHOLD=0.7\n"
        "CLEANUP_THRESHOLD_SEC=5.0\n"
    )
    after = apply_line_values(before, build_line_env_values(POINTS))
    for kept in ("# 比較条件（ROI方式と揃える）", "MODEL_PATH=yolov8s.pt",
                 "CONFIDENCE_THRESHOLD=0.25", "VEHICLE_CLASSES=2,7",
                 "IOU_THRESHOLD=0.7", "CLEANUP_THRESHOLD_SEC=5.0"):
        assert kept in after


def test_廃止済みのCLEANUP_THRESHOLDを書き出さない():
    """GUI実行後の.envでConfig.from_envが起動できること。"""
    after = apply_line_values("", build_line_env_values(POINTS))
    assert "CLEANUP_THRESHOLD=" not in after
    assert "MAX_FRAME_GAP=" not in after


def test_キーが無い場合は末尾へ追記する():
    after = apply_line_values("MODEL_PATH=yolov8s.pt\n", build_line_env_values(POINTS))
    assert "MODEL_PATH=yolov8s.pt" in after
    for key in LINE_ENV_KEYS:
        assert f"{key}=" in after


def test_空の入力でも全キーを書き出す():
    after = apply_line_values("", build_line_env_values(POINTS))
    for key in LINE_ENV_KEYS:
        assert f"{key}=" in after
    assert after.endswith("\n")


def test_二重適用しても重複しない():
    v = build_line_env_values(POINTS)
    once = apply_line_values("MODEL_PATH=yolov8s.pt\n", v)
    twice = apply_line_values(once, v)
    for key in LINE_ENV_KEYS:
        assert twice.count(f"{key}=") == 1
