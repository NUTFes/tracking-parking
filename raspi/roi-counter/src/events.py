from typing import Iterable, List, Optional

from .tracker import VehicleTrack

EVENT_COLUMNS = ("track_id", "event_type", "frame_index", "timestamp_sec", "is_warmup")


def build_event_rows(
    tracks: Iterable[VehicleTrack], fps: float, warmup_frames: int
) -> List[dict]:
    """カウント確定済みトラックからイベント列を生成する。

    warmup中に確定したイベントも除外しない(件数 = count_in + count_out を保つため)。
    ``is_warmup`` 列で明示する。
    """

    counted = [track for track in tracks if track.counted_as is not None]
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
        })
    return rows
