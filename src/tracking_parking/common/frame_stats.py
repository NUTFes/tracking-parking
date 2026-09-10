"""
フレーム処理時間の統計ユーティリティ（両検出ロジック共通）

W&B の summary に入れる速度指標（p95 / effective_fps / realtime_ok 等）を
1 フレームごとの処理時間リストから算出する。
"""

from typing import Any, Dict, List, Sequence

import numpy as np


STAT_SUFFIXES = ("min", "max", "mean", "p50", "p95", "p99", "total")


def compute_series_stats(values: Sequence[float], prefix: str) -> Dict[str, float]:
    """任意のミリ秒系列を、指定した prefix の統計キーへ展開する。"""

    if not values:
        return {f"{prefix}_{suffix}": 0.0 for suffix in STAT_SUFFIXES}

    arr = np.asarray(values, dtype=float)
    return {
        f"{prefix}_min": float(arr.min()),
        f"{prefix}_max": float(arr.max()),
        f"{prefix}_mean": float(arr.mean()),
        f"{prefix}_p50": float(np.percentile(arr, 50)),
        f"{prefix}_p95": float(np.percentile(arr, 95)),
        f"{prefix}_p99": float(np.percentile(arr, 99)),
        f"{prefix}_total": float(arr.sum()),
    }


def _timing_value(record: Any, key: str) -> float:
    if isinstance(record, dict):
        return float(record[key])
    return float(getattr(record, key))


def compute_timing_stats(records: Sequence[Any], source_fps: float) -> Dict[str, Any]:
    """timing schema v2 のフェーズ別統計とリアルタイム指標を算出する。"""

    phase_names = (
        "read_ms",
        "inference_tracking_ms",
        "counting_logic_ms",
        "core_ms",
        "output_ms",
        "end_to_end_ms",
    )
    stats: Dict[str, Any] = {}
    for phase in phase_names:
        stats.update(compute_series_stats([_timing_value(r, phase) for r in records], phase))

    core_mean = stats["core_ms_mean"]
    end_to_end_mean = stats["end_to_end_ms_mean"]
    stats["core_effective_fps"] = 1000.0 / core_mean if core_mean > 0 else 0.0
    stats["end_to_end_effective_fps"] = (
        1000.0 / end_to_end_mean if end_to_end_mean > 0 else 0.0
    )

    budget_ms = 1000.0 / source_fps if source_fps > 0 else 0.0
    miss_count = (
        sum(_timing_value(r, "end_to_end_ms") > budget_ms for r in records)
        if budget_ms > 0
        else 0
    )
    stats["frame_budget_ms"] = budget_ms
    stats["deadline_miss_count"] = int(miss_count)
    stats["deadline_miss_rate"] = float(miss_count / len(records)) if records else 0.0
    stats["core_realtime_ok"] = (
        bool(stats["core_effective_fps"] >= source_fps) if source_fps > 0 else False
    )
    stats["end_to_end_realtime_ok"] = (
        bool(records and source_fps > 0 and miss_count == 0)
    )

    # timing schema v1 互換。新しい比較・リアルタイム判定には上記の明示名を使う。
    for suffix in STAT_SUFFIXES:
        stats[f"frame_ms_{suffix}"] = stats[f"core_ms_{suffix}"]
    stats["total_ms"] = stats["core_ms_total"]
    stats["effective_fps"] = stats["core_effective_fps"]
    stats["realtime_ok"] = stats["core_realtime_ok"]
    return stats


def compute_frame_stats(frame_ms_list: List[float], source_fps: float) -> Dict:
    """
    フレーム処理時間リストから速度統計を算出する。

    Args:
        frame_ms_list: 1 フレームあたりの処理時間（ミリ秒）のリスト
        source_fps: 入力動画の FPS（realtime 判定の基準）

    Returns:
        dict: 速度統計。空リスト時は全て 0 / realtime_ok=False を返し例外を出さない。
            - frame_ms_min / frame_ms_max / frame_ms_mean
            - frame_ms_p50 / frame_ms_p95 / frame_ms_p99
            - total_ms
            - effective_fps (= 1000 / frame_ms_mean)
            - realtime_ok (= effective_fps >= source_fps)
    """
    if not frame_ms_list:
        return {
            "frame_ms_min": 0.0,
            "frame_ms_max": 0.0,
            "frame_ms_mean": 0.0,
            "frame_ms_p50": 0.0,
            "frame_ms_p95": 0.0,
            "frame_ms_p99": 0.0,
            "total_ms": 0.0,
            "effective_fps": 0.0,
            "realtime_ok": False,
        }

    arr = np.asarray(frame_ms_list, dtype=float)
    mean = float(arr.mean())
    effective_fps = 1000.0 / mean if mean > 0 else 0.0

    return {
        "frame_ms_min": float(arr.min()),
        "frame_ms_max": float(arr.max()),
        "frame_ms_mean": mean,
        "frame_ms_p50": float(np.percentile(arr, 50)),
        "frame_ms_p95": float(np.percentile(arr, 95)),
        "frame_ms_p99": float(np.percentile(arr, 99)),
        "total_ms": float(arr.sum()),
        "effective_fps": effective_fps,
        "realtime_ok": bool(effective_fps >= source_fps) if source_fps > 0 else False,
    }
