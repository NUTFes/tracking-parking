from typing import Iterable, List, Optional

from .tracker import CountedEvent, VehicleTrack

# s要約はVehicleTrack（active）とCountedEvent（archive）が同じ属性名で持つため、
# 両方から同じように読める。閾値の位置が車両の実際の到達点と合っているかは、
# この列が無いと確定済みイベントについて確認できない（archiveがs_historyを捨てるため）。
EVENT_COLUMNS = (
    "track_id", "event_type", "frame_index", "timestamp_sec", "is_warmup", "event_id",
    "s_min", "s_max", "s_first", "s_last", "n_samples",
)


def build_event_rows(
    tracks: Iterable[VehicleTrack],
    fps: float,
    warmup_frames: int,
    archive: Iterable[CountedEvent] = (),
) -> List[dict]:
    """active trackとarchiveからカウント確定イベント列を生成する。

    warmup中に確定したイベントも除外しない(件数 = count_in + count_out を保つため)。
    ``is_warmup`` 列で明示する。
    """

    counted = [track for track in tracks if track.counted_as is not None]
    counted.extend(archive)
    counted.sort(key=lambda track: (track.counted_frame is None, track.counted_frame, track.track_id))

    rows = []
    for track in counted:
        frame_index = track.counted_frame
        timestamp_sec: Optional[float] = None
        is_warmup: Optional[bool] = None
        if frame_index is not None:
            is_warmup = frame_index < warmup_frames
            if fps > 0:
                timestamp_sec = round(frame_index / fps, 3)
        rows.append({
            "track_id": track.track_id,
            "event_type": track.counted_as,
            "frame_index": frame_index,
            "timestamp_sec": timestamp_sec,
            "is_warmup": is_warmup,
            "event_id": track.event_id,
            "s_min": track.s_min,
            "s_max": track.s_max,
            "s_first": track.s_first,
            "s_last": track.s_last,
            "n_samples": track.n_samples,
        })
    return rows
