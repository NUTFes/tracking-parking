from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class VehicleState(Enum):
    UNKNOWN       = "UNKNOWN"
    IN_CANDIDATE  = "IN_CANDIDATE"
    OUT_CANDIDATE = "OUT_CANDIDATE"
    COUNTED       = "COUNTED"


@dataclass(frozen=True)
class CountedEvent:
    """COUNTED trackから履歴を除いて保持する軽量イベント。"""

    track_id: int
    event_id: Optional[str]
    counted_as: Optional[str]
    counted_frame: Optional[int]
    first_seen_frame: Optional[int]
    candidate_started_frame: Optional[int]
    last_seen_frame: Optional[int]
    s_min: Optional[float]
    s_max: Optional[float]
    s_first: Optional[float]
    s_last: Optional[float]
    n_samples: int


@dataclass
class VehicleTrack:
    track_id: int
    state: VehicleState = VehicleState.UNKNOWN
    s_history: List[float] = field(default_factory=list)
    counted_as: Optional[str] = None  # "IN" | "OUT"
    counted_frame: Optional[int] = None  # COUNTED へ遷移したフレーム番号
    event_id: Optional[str] = None
    first_seen_frame: Optional[int] = None
    candidate_started_frame: Optional[int] = None
    last_seen_frame: Optional[int] = None
    s_min: Optional[float] = None
    s_max: Optional[float] = None
    s_first: Optional[float] = None
    s_last: Optional[float] = None
    n_samples: int = 0
