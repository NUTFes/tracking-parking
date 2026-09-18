"""フレームへ焼き込む文字列がASCIIに収まっていることのテスト。

cv2.putTextが使うHersheyフォントはASCIIしか持たず、非ASCIIは1文字ずつ'?'として
描かれる（"Line1 (入口側)" → "Line1 (???)"）。この環境のOpenCVはfreetypeを
含まないためTTF描画へ逃げられない。日本語のラベルを足しても例外は出ず、動画に
'?'が並ぶだけなので気づきにくい。ここで気づけるようにする。
"""
import ast
from pathlib import Path

import pytest

import setup_lines
from tracking_parking.output.video_writer import LINE1_LABEL, LINE2_LABEL

REPO_ROOT = Path(__file__).resolve().parents[2]

# フレームへ描画するコードを持つファイル。
DRAWING_SOURCES = (
    REPO_ROOT / "src" / "tracking_parking" / "output" / "video_writer.py",
    REPO_ROOT / "scripts" / "visualize_lines.py",
    REPO_ROOT / "scripts" / "setup_lines.py",
)


def drawn_string_literals(path: Path):
    """cv2.putText / _draw_text_with_background へ直接渡している文字列リテラルを集める。

    変数経由で渡す値までは追えないので、リテラルで書かれた分だけを対象にする
    （ラベルの追加はほぼリテラルで入るため、これで実用上は足りる）。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.attr if isinstance(func, ast.Attribute)
            else func.id if isinstance(func, ast.Name)
            else ""
        )
        if name not in ("putText", "_draw_text_with_background", "getTextSize"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.append(arg.value)
    return found


@pytest.mark.parametrize("path", DRAWING_SOURCES, ids=lambda p: p.name)
def test_描画へ直接渡す文字列はASCIIのみ(path):
    non_ascii = [s for s in drawn_string_literals(path) if not s.isascii()]
    assert non_ascii == [], f"{path.name} が非ASCIIを描画しようとしている: {non_ascii}"


def test_ライン名はASCII():
    assert LINE1_LABEL.isascii()
    assert LINE2_LABEL.isascii()


def test_setup_linesのオーバーレイ用ラベルはASCII():
    gui = setup_lines.LineSetupGUI("dummy.mp4", "dummy.env")
    assert all(label.isascii() for label in gui.overlay_labels)


def test_端末用ラベルとオーバーレイ用ラベルは1対1で対応する():
    """順序がずれると、クリックすべき点と画面の表示が食い違う。"""
    gui = setup_lines.LineSetupGUI("dummy.mp4", "dummy.env")
    assert len(gui.labels) == len(gui.overlay_labels)


def test_端末用ラベルは日本語のまま():
    """端末は日本語を正しく出せる。ASCII化は描画側だけの制約なので、
    案内文まで英語に倒さない。"""
    gui = setup_lines.LineSetupGUI("dummy.mp4", "dummy.env")
    assert any(not label.isascii() for label in gui.labels)
