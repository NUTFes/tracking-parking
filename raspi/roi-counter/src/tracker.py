from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class VehicleState(Enum):
    UNKNOWN       = "UNKNOWN"
    IN_CANDIDATE  = "IN_CANDIDATE"
    OUT_CANDIDATE = "OUT_CANDIDATE"
    COUNTED       = "COUNTED"


@dataclass
class VehicleTrack:
    track_id: int
    state: VehicleState = VehicleState.UNKNOWN
    s_history: List[float] = field(default_factory=list)
    counted_as: Optional[str] = None  # "IN" | "OUT"
