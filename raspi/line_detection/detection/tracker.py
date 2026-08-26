"""
車両トラッキングと状態管理モジュール
ハイブリッド方式による入出庫判定を実装
"""

from dataclasses import dataclass, field
from typing import Dict, Literal, Optional, Tuple, List
import time

from detection.line_crossing import LineTransitionState


Confidence = Literal["pending", "high", "normal"]
FinalConfidence = Literal["high", "normal"]


@dataclass(frozen=True)
class ConfidenceUpdate:
    """イベントログへ反映する確定済みconfidence。"""

    track_id: int
    event_id: Optional[str]
    confidence: FinalConfidence
    line2_crossed: bool


@dataclass
class VehicleState:
    """車両の状態を保持するデータクラス"""

    track_id: int
    prev_point: Optional[Tuple[float, float]] = None
    curr_point: Optional[Tuple[float, float]] = None

    # ヒステリシス方式によるライン交差判定の状態(track×ラインごと)
    line1_transition: LineTransitionState = field(default_factory=LineTransitionState)
    line2_transition: LineTransitionState = field(default_factory=LineTransitionState)

    # Line1状態(主判定ライン)
    line1_direction: Optional[str] = None  # "IN" or "OUT"
    line1_frame: Optional[int] = None
    line1_timestamp: Optional[float] = None

    # Line2状態(補助ライン)
    line2_direction: Optional[str] = None  # "IN" or "OUT"
    line2_frame: Optional[int] = None
    line2_timestamp: Optional[float] = None

    # イベント追跡
    passed_order: List[str] = field(default_factory=list)  # ["line1", "line2"] など
    counted: bool = False
    confidence: Optional[Confidence] = None
    pending_event_id: Optional[str] = None

    # 更新追跡
    last_update_frame: int = 0

    def update_position(self, point: Tuple[float, float], frame_id: int):
        """
        車両位置を更新

        Args:
            point: 新しい車両位置
            frame_id: フレーム番号
        """
        self.prev_point = self.curr_point
        self.curr_point = point
        self.last_update_frame = frame_id

    def record_line1_crossing(self, direction: str, frame_id: int):
        """
        Line1交差を記録

        Args:
            direction: "IN" or "OUT"
            frame_id: フレーム番号
        """
        self.line1_direction = direction
        self.line1_frame = frame_id
        self.line1_timestamp = time.time()
        self.passed_order.append("line1")

    def record_line2_crossing(self, direction: str, frame_id: int):
        """
        Line2交差を記録

        Args:
            direction: "IN" or "OUT"
            frame_id: フレーム番号
        """
        self.line2_direction = direction
        self.line2_frame = frame_id
        self.line2_timestamp = time.time()
        self.passed_order.append("line2")

    def resolve_confidence(
        self,
        current_frame: int,
        max_frame_gap: int,
    ) -> Optional[Confidence]:
        """
        pendingの信頼度を、現在までのライン通過履歴から解決する。

        Args:
            current_frame: 現在のフレーム番号
            max_frame_gap: Line1とLine2の最大フレーム差

        Returns:
            Optional[Confidence]: "pending"、"high"、"normal"、またはNone
        """
        if not self.counted or self.line1_frame is None:
            return None

        if self.confidence in ("high", "normal"):
            return self.confidence

        if self.line1_direction == "IN" and self.line2_direction is None:
            if current_frame - self.line1_frame > max_frame_gap:
                self.confidence = "normal"
            else:
                self.confidence = "pending"
            return self.confidence

        # OUTでLine2が未通過なら、期待順序 line2→line1 はすでに成立しない。
        if self.line2_direction is None or self.line2_frame is None:
            self.confidence = "normal"
            return self.confidence

        if self.line1_direction == "IN":
            expected_order = ["line1", "line2"]
        elif self.line1_direction == "OUT":
            expected_order = ["line2", "line1"]
        else:
            self.confidence = "normal"
            return self.confidence

        frame_diff = abs(self.line1_frame - self.line2_frame)
        valid_pair = (
            self.line1_direction == self.line2_direction
            and frame_diff <= max_frame_gap
            and self.passed_order == expected_order
        )
        self.confidence = "high" if valid_pair else "normal"
        return self.confidence


class VehicleTracker:
    """車両トラッキングクラス"""

    def __init__(self, max_frame_gap: int = 90, cleanup_threshold: int = 150):
        """
        Args:
            max_frame_gap: Line1とLine2の最大フレーム差
            cleanup_threshold: 古い追跡をクリーンアップするフレーム数
        """
        self.states: Dict[int, VehicleState] = {}
        self.max_frame_gap = max_frame_gap
        self.cleanup_threshold = cleanup_threshold

        # 統計情報
        self.total_in = 0
        self.total_out = 0
        self.high_confidence_count = 0
        self.normal_confidence_count = 0

    def update(self, track_id: int, point: Tuple[float, float], frame_id: int) -> VehicleState:
        """
        車両状態を更新または作成

        Args:
            track_id: トラッキングID
            point: 車両位置
            frame_id: フレーム番号

        Returns:
            VehicleState: 更新された車両状態
        """
        if track_id not in self.states:
            # 新しい車両を追加
            self.states[track_id] = VehicleState(track_id=track_id)

        state = self.states[track_id]
        state.update_position(point, frame_id)

        return state

    def get_state(self, track_id: int) -> Optional[VehicleState]:
        """
        車両状態を取得

        Args:
            track_id: トラッキングID

        Returns:
            Optional[VehicleState]: 車両状態(存在しない場合はNone)
        """
        return self.states.get(track_id)

    def should_count_event(self, state: VehicleState) -> bool:
        """
        イベントをカウントすべきかハイブリッド方式で判定

        Args:
            state: 車両状態

        Returns:
            bool: カウントすべき場合True
        """
        # すでにカウント済み
        if state.counted:
            return False

        # Line1を交差していない
        if not state.line1_direction:
            return False

        # ハイブリッド方式: Line1交差でカウント
        # (Line2は信頼度にのみ影響)
        return True

    def mark_as_counted(self, track_id: int) -> Optional[str]:
        """
        イベントをカウント済みとしてマーク

        Args:
            track_id: トラッキングID

        Returns:
            Optional[str]: イベントタイプ("IN" or "OUT")、エラーの場合None
        """
        state = self.get_state(track_id)
        if not state:
            return None

        # カウント済みフラグを設定
        state.counted = True
        state.confidence = "pending"

        # 統計情報を更新
        if state.line1_direction == "IN":
            self.total_in += 1
        elif state.line1_direction == "OUT":
            self.total_out += 1

        return state.line1_direction

    def resolve_pending_confidences(
        self,
        current_frame: int,
    ) -> List[ConfidenceUpdate]:
        """全trackのpending confidenceを評価し、新たな確定結果を返す。"""
        updates = []
        for state in self.states.values():
            if state.confidence != "pending":
                continue

            resolved = state.resolve_confidence(current_frame, self.max_frame_gap)
            if resolved in ("high", "normal"):
                self._record_confidence_resolution(resolved)
                updates.append(ConfidenceUpdate(
                    track_id=state.track_id,
                    event_id=state.pending_event_id,
                    confidence=resolved,
                    line2_crossed=state.line2_direction is not None,
                ))
        return updates

    def finalize_pending_confidences(self) -> List[ConfidenceUpdate]:
        """run終了時に残ったpending confidenceをnormalへ確定する。"""
        updates = []
        for state in self.states.values():
            if state.confidence != "pending":
                continue

            state.confidence = "normal"
            self._record_confidence_resolution("normal")
            updates.append(ConfidenceUpdate(
                track_id=state.track_id,
                event_id=state.pending_event_id,
                confidence="normal",
                line2_crossed=state.line2_direction is not None,
            ))
        return updates

    def _record_confidence_resolution(self, confidence: FinalConfidence):
        """確定時に一度だけconfidence別件数を加算する。"""
        if confidence == "high":
            self.high_confidence_count += 1
        else:
            self.normal_confidence_count += 1

    def cleanup_stale_tracks(self, current_frame: int):
        """
        古い追跡を削除

        Args:
            current_frame: 現在のフレーム番号
        """
        track_ids_to_remove = []

        for track_id, state in self.states.items():
            frames_since_update = current_frame - state.last_update_frame

            if (
                frames_since_update > self.cleanup_threshold
                and state.confidence != "pending"
            ):
                track_ids_to_remove.append(track_id)

        for track_id in track_ids_to_remove:
            del self.states[track_id]

    def get_summary(self) -> Dict:
        """
        統計サマリーを取得

        Returns:
            Dict: 統計情報
        """
        return {
            "total_in": self.total_in,
            "total_out": self.total_out,
            "current_parked": self.total_in - self.total_out,
            "high_confidence_events": self.high_confidence_count,
            "normal_confidence_events": self.normal_confidence_count,
            "active_tracks": len(self.states)
        }

    def get_current_parked(self) -> int:
        """
        現在の駐車台数を取得

        Returns:
            int: 駐車台数
        """
        return self.total_in - self.total_out
