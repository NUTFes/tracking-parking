"""本番実行の前に、黙って失敗する条件を潰すための検査。

ここで見ているのは「起動はするが結果が静かにおかしくなる」種類の条件。
実機で実際に踏んだものだけを入れている。

- ライン座標が実行時の画角の外にある。座標は設定時の画角に紐づくため、
  カメラの解像度が違えば検知位置がずれる。フレーム外に出ていれば一度も
  交差せず、イベントがゼロのまま静かに動き続ける。
- CUDAが使えない。`uv sync` / `uv run` が .venv を作り直すと起こる
  （README「エッジ機」参照）。CPUへ落ちると速度が実運用に足りない。
- 録画の空き容量。1280x720で約37GB/日。

検査は「問題の説明文のリスト」を返す形にしている。呼び出し側が全部まとめて
出せるようにするため（1つ直して再実行、を繰り返さずに済む）。
"""

from typing import List

__all__ = ["check_line_bounds", "check_disk_space", "describe_frame_mismatch"]


def check_line_bounds(config, width: int, height: int) -> List[str]:
    """ライン座標と駐車場基準点が画角の内側にあるかを見る。

    Args:
        config: Config（line1 / line2 / parking_ref_point を持つもの）
        width, height: 実行時のフレームの大きさ（実測値）

    Returns:
        問題の説明文のリスト。問題が無ければ空。
    """
    errors = []
    points = [
        ("LINE1 始点", config.line1.start),
        ("LINE1 終点", config.line1.end),
        ("LINE2 始点", config.line2.start),
        ("LINE2 終点", config.line2.end),
        ("駐車場基準点", config.parking_ref_point),
    ]
    for label, (x, y) in points:
        if not (0 <= x < width and 0 <= y < height):
            errors.append(
                f"{label} ({int(x)}, {int(y)}) が画角 {width}x{height} の外にあります"
            )
    return errors


def describe_frame_mismatch(requested, actual) -> List[str]:
    """要求した解像度と実測値が食い違っていないかを見る。

    Args:
        requested: (width, height)。未指定なら (None, None)。
        actual: (width, height) の実測値。

    Returns:
        問題の説明文のリスト。
    """
    if requested[0] is None or requested[1] is None:
        return [
            "CAMERA_WIDTH / CAMERA_HEIGHT が未設定です。"
            "デバイス既定で開くため、ライン座標を設定した画角と一致する保証がありません"
        ]
    if tuple(requested) != tuple(actual):
        return [
            f"カメラが要求解像度を受理しませんでした: "
            f"要求 {requested[0]}x{requested[1]} → 実際 {actual[0]}x{actual[1]}"
        ]
    return []


def check_disk_space(free_bytes: int, *, need_bytes: int) -> List[str]:
    """録画に使える空き容量を見る。

    Args:
        free_bytes: 空き容量
        need_bytes: 最低限ほしい容量

    Returns:
        問題の説明文のリスト。
    """
    if free_bytes < need_bytes:
        return [
            f"録画先の空き容量が少ないです: "
            f"空き {free_bytes / 1024**3:.1f}GB < 目安 {need_bytes / 1024**3:.1f}GB"
        ]
    return []
