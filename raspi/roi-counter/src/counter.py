from typing import Dict, List

from .tracker import VehicleState, VehicleTrack


class Counter:
    def __init__(self, s_low: float = 0.25, s_high: float = 0.75):
        self.s_low = s_low
        self.s_high = s_high
        self.tracks: Dict[int, VehicleTrack] = {}
        self.count_in = 0
        self.count_out = 0

    def update(self, track_id: int, s: float) -> None:
        if track_id not in self.tracks:
            self.tracks[track_id] = VehicleTrack(track_id=track_id)

        track = self.tracks[track_id]
        track.s_history.append(s)

        if track.state == VehicleState.UNKNOWN:
            if s < self.s_low:
                track.state = VehicleState.IN_CANDIDATE
            elif s > self.s_high:
                track.state = VehicleState.OUT_CANDIDATE

        elif track.state == VehicleState.IN_CANDIDATE:
            if s > self.s_high:
                track.state = VehicleState.COUNTED
                track.counted_as = "IN"
                self.count_in += 1

        elif track.state == VehicleState.OUT_CANDIDATE:
            if s < self.s_low:
                track.state = VehicleState.COUNTED
                track.counted_as = "OUT"
                self.count_out += 1

    def get_all_tracks(self) -> List[VehicleTrack]:
        return list(self.tracks.values())
