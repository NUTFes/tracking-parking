"""両検出方式で共有する正解台数(GT)比較の契約。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.frame_timing import sha256_file


@dataclass(frozen=True)
class GtEvent:
    """GTの1物理イベント(入退場1件)。"""

    event_id: str
    direction: str  # "IN" or "OUT"
    t_sec: float


DEFAULT_TOLERANCE_SEC = 10.0  # 初期既定値。2ラインとROIの確定タイミング差を吸収する目的の暫定値。


@dataclass(frozen=True)
class GroundTruth:
    """1動画分のGT。値が無い方向は None(未確認)として扱う。"""

    path: str | None
    sha256: str | None
    gt_in: int | None
    gt_out: int | None
    events: tuple["GtEvent", ...] = ()
    tolerance_sec: float = DEFAULT_TOLERANCE_SEC

    @property
    def is_available(self) -> bool:
        return self.gt_in is not None or self.gt_out is not None

    @classmethod
    def absent(cls) -> "GroundTruth":
        return cls(path=None, sha256=None, gt_in=None, gt_out=None)


def _coerce_count(value: Any, *, key: str, source: str) -> int | None:
    """GT の1方向分の値を検証する。null は未確認として None を返す。"""

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


def _coerce_event_time(value: Any, *, key: str, source: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{source}: '{key}' は有限な数値である必要があります: {value!r}")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{source}: '{key}' は有限な数値である必要があります: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"{source}: '{key}' は有限な数値である必要があります: {value!r}")
    if number < 0:
        raise ValueError(f"{source}: '{key}' は0以上である必要があります: {value!r}")
    return number


def _coerce_tolerance(value: Any, *, source: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"{source}: 'tolerance_sec' は有限な正の数値である必要があります: {value!r}"
        )
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(
            f"{source}: 'tolerance_sec' は有限な正の数値である必要があります: {value!r}"
        ) from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(
            f"{source}: 'tolerance_sec' は有限な正の数値である必要があります: {value!r}"
        )
    return number


def _parse_events(data: dict[str, Any], *, source: str) -> tuple[GtEvent, ...]:
    if "events" not in data:
        return ()
    raw_events = data["events"]
    if not isinstance(raw_events, list):
        raise ValueError(f"{source}: 'events' は配列である必要があります")

    events = []
    event_ids: set[str] = set()
    for index, raw_event in enumerate(raw_events):
        event_key = f"events[{index}]"
        if not isinstance(raw_event, dict):
            raise ValueError(f"{source}: {event_key} はオブジェクトである必要があります")

        event_id = raw_event.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError(f"{source}: {event_key} の 'event_id' は空でない文字列である必要があります")
        if event_id in event_ids:
            raise ValueError(f"{source}: 'event_id' が重複しています: {event_id!r}")
        event_ids.add(event_id)

        direction = raw_event.get("direction")
        if direction not in ("IN", "OUT"):
            raise ValueError(
                f"{source}: {event_key} の 'direction' は 'IN' または 'OUT' である必要があります: "
                f"{direction!r}"
            )

        t_sec = _coerce_event_time(raw_event.get("t_sec"), key=f"{event_key}.t_sec", source=source)
        events.append(GtEvent(event_id=event_id, direction=direction, t_sec=t_sec))
    return tuple(events)


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
    events = _parse_events(data, source=source)
    tolerance_sec = (
        _coerce_tolerance(data["tolerance_sec"], source=source)
        if "tolerance_sec" in data
        else DEFAULT_TOLERANCE_SEC
    )

    video_field = data.get("video")
    if isinstance(video_field, str) and isinstance(video_source, str):
        if Path(video_field).stem != Path(video_source).stem:
            print(
                f"[WARN] GTの video ('{video_field}') と入力動画 "
                f"('{video_source}') のファイル名が一致しません"
            )

    return GroundTruth(
        path=source,
        sha256=sha256_file(source),
        gt_in=gt_in,
        gt_out=gt_out,
        events=events,
        tolerance_sec=tolerance_sec,
    )


def resolve_gt_path(video_source: str | int, explicit_path: str | None) -> tuple[Path | None, bool]:
    """GTファイルのパスを決定する。返り値は (path, is_explicit)。"""

    if explicit_path:
        return Path(explicit_path), True
    if isinstance(video_source, str):
        derived = Path(video_source).parent / f"{Path(video_source).stem}_gt.json"
        return derived, False
    return None, False


def load_ground_truth(video_source: str | int, explicit_path: str | None = None) -> GroundTruth:
    """GTを読み込む。

    明示パス指定でファイルが無ければ FileNotFoundError(操作者の意図を裏切らない)。
    自動導出したパスが無い場合は警告のみで GroundTruth.absent() を返す。
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
