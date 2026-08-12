from __future__ import annotations

from collections.abc import Iterable, Sequence
from statistics import fmean, median
from typing import Any

from .tracker import CountedEvent, VehicleState, VehicleTrack


DEFAULT_DIAGNOSTIC_THRESHOLDS = (0.75, 0.70, 0.65, 0.60)


def snapshot_in_candidate_tracks(tracks: Iterable[VehicleTrack]) -> dict[tuple[int, int | None], dict[str, Any]]:
    """現在のIN候補をtrack instance単位で軽量コピーする。"""
    snapshots: dict[tuple[int, int | None], dict[str, Any]] = {}
    for track in tracks:
        if track.state != VehicleState.IN_CANDIDATE:
            continue
        key = (track.track_id, track.first_seen_frame)
        snapshots[key] = {
            "track_id": track.track_id,
            "state": track.state.value,
            "first_seen_frame": track.first_seen_frame,
            "last_seen_frame": track.last_seen_frame,
            "s_min": track.s_min,
            "s_max": track.s_max,
            "s_first": track.s_first,
            "s_last": track.s_last,
            "n_samples": track.n_samples,
        }
    return snapshots


def build_progress_diagnostics(
    tracks: Iterable[VehicleTrack],
    archive: Iterable[CountedEvent],
    *,
    total_track_instances: int,
    count_in: int,
    count_out: int,
    thresholds: Sequence[float] = DEFAULT_DIAGNOSTIC_THRESHOLDS,
    in_candidate_tracks: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """B-2用のtrack要約値とs_max投影を作る。

    ``tracks``は動画終了時点でactiveなtrack、``archive``はcleanup済みの
    COUNTEDイベントである。候補の投影は ``s_max > threshold`` で数える。
    """
    active_tracks = list(tracks)
    archived_events = list(archive)
    counted_active = [track for track in active_tracks if track.counted_as is not None]
    counted_track_instances = len(counted_active) + len(archived_events)
    expected_counted = count_in + count_out
    if counted_track_instances != expected_counted:
        raise ValueError(
            "COUNTED track数とcount値が一致しません: "
            f"tracks={counted_track_instances}, counts={expected_counted}"
        )
    if total_track_instances < counted_track_instances:
        raise ValueError("total_track_instancesはCOUNTED track数以上である必要があります")

    if in_candidate_tracks is None:
        stuck_rows = [
            {
                "track_id": track.track_id,
                "state": track.state.value,
                "first_seen_frame": track.first_seen_frame,
                "last_seen_frame": track.last_seen_frame,
                "s_min": track.s_min,
                "s_max": track.s_max,
                "s_first": track.s_first,
                "s_last": track.s_last,
                "n_samples": track.n_samples,
            }
            for track in active_tracks
            if track.state == VehicleState.IN_CANDIDATE and track.s_max is not None
        ]
    else:
        stuck_rows = [dict(row) for row in in_candidate_tracks if row.get("s_max") is not None]
    stuck_rows.sort(key=lambda row: (row["track_id"], row.get("first_seen_frame") is None, row.get("first_seen_frame")))
    s_max_values = [float(row["s_max"]) for row in stuck_rows]
    if s_max_values:
        s_max_summary: dict[str, float | None] = {
            "min": min(s_max_values),
            "median": median(s_max_values),
            "mean": fmean(s_max_values),
            "max": max(s_max_values),
        }
    else:
        s_max_summary = {key: None for key in ("min", "median", "mean", "max")}

    threshold_projection = {
        f"{float(threshold):.2f}": sum(value > threshold for value in s_max_values)
        for threshold in thresholds
    }
    return {
        "total_track_instances": total_track_instances,
        "counted_track_instances": counted_track_instances,
        "count_in": count_in,
        "count_out": count_out,
            "in_candidate_stuck_count": len(stuck_rows),
        "in_candidate_s_max": s_max_values,
        "s_max_summary": s_max_summary,
        "threshold_projection": threshold_projection,
        "in_candidate_tracks": stuck_rows,
    }
