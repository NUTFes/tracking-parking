"""両検出方式で共有する正解台数(GT)比較の契約。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.frame_timing import sha256_file


@dataclass(frozen=True)
class GroundTruth:
    """1動画分のGT。値が無い方向は ``None``(未確認)として扱う。"""

    path: str | None
    sha256: str | None
    gt_in: int | None
    gt_out: int | None

    @property
    def is_available(self) -> bool:
        return self.gt_in is not None or self.gt_out is not None

    @classmethod
    def absent(cls) -> "GroundTruth":
        return cls(path=None, sha256=None, gt_in=None, gt_out=None)


def _coerce_count(value: Any, *, key: str, source: str) -> int | None:
    """GT の1方向分の値を検証する。``null`` は未確認として ``None`` を返す。"""

    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{source}: '{key}' は真偽値を受け付けません: {value!r}")
    if isinstance(value, int):
        count = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"{source}: '{key}' は整数である必要があります: {value!r}")
        count = int(value)
    elif isinstance(value, str):
        try:
            count = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"{source}: '{key}' が数値として解釈できません: {value!r}") from exc
    else:
        raise ValueError(f"{source}: '{key}' の型が不正です: {value!r}")
    if count < 0:
        raise ValueError(f"{source}: '{key}' は0以上である必要があります: {count}")
    return count


def _load_gt_file(path: Path, *, video_source: str | int) -> GroundTruth:
    source = str(path)
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source}: GT JSON の解析に失敗しました: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{source}: GT JSON はオブジェクトである必要があります")
    if "in" not in data and "out" not in data:
        raise ValueError(f"{source}: GT に 'in' も 'out' もありません")

    gt_in = _coerce_count(data.get("in"), key="in", source=source)
    gt_out = _coerce_count(data.get("out"), key="out", source=source)

    video_field = data.get("video")
    if isinstance(video_field, str) and isinstance(video_source, str):
        if Path(video_field).stem != Path(video_source).stem:
            print(
                f"[WARN] GTの video ('{video_field}') と入力動画 "
                f"('{video_source}') のファイル名が一致しません"
            )

    return GroundTruth(path=source, sha256=sha256_file(source), gt_in=gt_in, gt_out=gt_out)


def resolve_gt_path(video_source: str | int, explicit_path: str | None) -> tuple[Path | None, bool]:
    """GTファイルのパスを決定する。返り値は ``(path, is_explicit)``。"""

    if explicit_path:
        return Path(explicit_path), True
    if isinstance(video_source, str):
        derived = Path(video_source).parent / f"{Path(video_source).stem}_gt.json"
        return derived, False
    return None, False


def load_ground_truth(video_source: str | int, explicit_path: str | None = None) -> GroundTruth:
    """GTを読み込む。

    明示パス指定でファイルが無ければ ``FileNotFoundError``(操作者の意図を裏切らない)。
    自動導出したパスが無い場合は警告のみで ``GroundTruth.absent()`` を返す。
    """

    path, is_explicit = resolve_gt_path(video_source, explicit_path)
    if path is None:
        return GroundTruth.absent()
    if not path.exists():
        if is_explicit:
            raise FileNotFoundError(f"GT ファイルが見つかりません: {path}")
        print(f"[WARN] GT ファイルが見つかりません: {path}")
        return GroundTruth.absent()
    return _load_gt_file(path, video_source=video_source)


def compute_count_error(count_in: int, count_out: int, gt: GroundTruth) -> dict[str, Any]:
    """評価可能な方向だけを対象に台数誤差を算出する。"""

    count_error_in = abs(count_in - gt.gt_in) if gt.gt_in is not None else None
    count_error_out = abs(count_out - gt.gt_out) if gt.gt_out is not None else None

    parts = [value for value in (count_error_in, count_error_out) if value is not None]
    count_error = sum(parts) if parts else None

    return {
        "count_error": count_error,
        "count_error_in": count_error_in,
        "count_error_out": count_error_out,
    }


def build_ground_truth_config(gt: GroundTruth) -> dict[str, Any]:
    """run configへ埋め込むGT識別情報。"""

    return {
        "ground_truth_config": gt.path,
        "ground_truth_sha256": gt.sha256,
        "gt_in": gt.gt_in,
        "gt_out": gt.gt_out,
    }


def build_ground_truth_summary(count_in: int, count_out: int, gt: GroundTruth) -> dict[str, Any]:
    """W&B summaryへ埋め込むGT比較結果。"""

    return {
        "gt_in": gt.gt_in,
        "gt_out": gt.gt_out,
        **compute_count_error(count_in, count_out, gt),
    }
