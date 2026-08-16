from typing import Dict, List, Optional

from .tracker import CountedEvent, VehicleState, VehicleTrack


class Counter:
    def __init__(
        self,
        s_low: float = 0.25,
        s_high: float = 0.75,
        *,
        cleanup_threshold: int = 150,
        max_candidate_age: int = 300,
        s_history_limit: int = 300,
    ):
        if cleanup_threshold < 0:
            raise ValueError("cleanup_thresholdは0以上である必要があります")
        if max_candidate_age < 0:
            raise ValueError("max_candidate_ageは0以上である必要があります")
        if s_history_limit < 0:
            raise ValueError("s_history_limitは0以上である必要があります")

        self.s_low = s_low
        self.s_high = s_high
        self.cleanup_threshold = cleanup_threshold
        self.max_candidate_age = max_candidate_age
        self.s_history_limit = s_history_limit
        self.tracks: Dict[int, VehicleTrack] = {}
        self.archive: List[CountedEvent] = []
        self.count_in = 0
        self.count_out = 0
        # cleanup後のID再利用も別track instanceとして診断できるようにする。
        self.total_track_instances = 0

    def update(self, track_id: int, s: float, frame_idx: Optional[int] = None) -> None:
        if track_id not in self.tracks:
            self.tracks[track_id] = VehicleTrack(track_id=track_id)
            self.total_track_instances += 1

        track = self.tracks[track_id]
        if frame_idx is not None:
            if track.first_seen_frame is None:
                track.first_seen_frame = frame_idx
            track.last_seen_frame = frame_idx

        track.s_first = s if track.n_samples == 0 else track.s_first
        track.s_last = s
        track.s_min = s if track.s_min is None else min(track.s_min, s)
        track.s_max = s if track.s_max is None else max(track.s_max, s)
        track.n_samples += 1
        if self.s_history_limit == 0:
            track.s_history.append(s)
        else:
            track.s_history.append(s)
            if len(track.s_history) > self.s_history_limit:
                del track.s_history[:-self.s_history_limit]

        if track.state == VehicleState.UNKNOWN:
            if s < self.s_low:
                track.state = VehicleState.IN_CANDIDATE
                track.candidate_started_frame = frame_idx
            elif s > self.s_high:
                track.state = VehicleState.OUT_CANDIDATE
                track.candidate_started_frame = frame_idx

        elif track.state == VehicleState.IN_CANDIDATE:
            if s > self.s_high:
                track.state = VehicleState.COUNTED
                track.counted_as = "IN"
                track.counted_frame = frame_idx
                self.count_in += 1

        elif track.state == VehicleState.OUT_CANDIDATE:
            if s < self.s_low:
                track.state = VehicleState.COUNTED
                track.counted_as = "OUT"
                track.counted_frame = frame_idx
                self.count_out += 1

    def get_all_tracks(self) -> List[VehicleTrack]:
        return list(self.tracks.values())

    def get_archived_events(self) -> List[CountedEvent]:
        """archiveの内容を外部から変更できない形で返す。"""
        return list(self.archive)

    def cleanup(self, current_frame: int) -> None:
        """古いtrackを削除し、確定済みイベントをarchiveへ移す。"""
        stale_track_ids: List[int] = []

        for track_id, track in self.tracks.items():
            if (
                track.state in (VehicleState.IN_CANDIDATE, VehicleState.OUT_CANDIDATE)
                and track.candidate_started_frame is not None
                and current_frame - track.candidate_started_frame > self.max_candidate_age
            ):
                track.state = VehicleState.UNKNOWN
                track.candidate_started_frame = None

            if track.last_seen_frame is None:
                continue
            if current_frame - track.last_seen_frame <= self.cleanup_threshold:
                continue

            if track.state == VehicleState.COUNTED:
                self.archive.append(
                    CountedEvent(
                        track_id=track.track_id,
                        counted_as=track.counted_as,
                        counted_frame=track.counted_frame,
                        first_seen_frame=track.first_seen_frame,
                        candidate_started_frame=track.candidate_started_frame,
                        last_seen_frame=track.last_seen_frame,
                        s_min=track.s_min,
                        s_max=track.s_max,
                        s_first=track.s_first,
                        s_last=track.s_last,
                        n_samples=track.n_samples,
                    )
                )
            stale_track_ids.append(track_id)

        for track_id in stale_track_ids:
            del self.tracks[track_id]
