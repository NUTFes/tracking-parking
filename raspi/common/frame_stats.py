"""
フレーム処理時間の統計ユーティリティ（両検出ロジック共通）

W&B の summary に入れる速度指標（p95 / effective_fps / realtime_ok 等）を
1 フレームごとの処理時間リストから算出する。
"""

from typing import List, Dict

import numpy as np


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
