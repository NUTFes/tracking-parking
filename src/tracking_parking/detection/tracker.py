"""
車両トラッキングと状態管理モジュール
ハイブリッド方式による入出庫判定を実装

時間窓（Line1とLine2の対応付け、trackのクリーンアップ）は秒で扱い、判定には
呼び出し側が与える「ストリーム時刻」を使う。フレーム番号の差で判定していた頃は、
秒指定を開いた時点のfpsでフレーム数へ換算していたが、これは処理が撮影レートに
追いつく前提に立っていた。ライブカメラでは処理が追いつかず古いフレームが捨て
られるため、30fps宣言のカメラを実測14fpsで処理すると「3秒」の窓が実時間で
6秒以上に伸びる。動画ファイルでは frame_id / fps が厳密にストリーム時刻なので、
この変更で挙動は変わらない。
"""

from dataclasses import dataclass, field
from typing import Dict, Literal, Optional, Tuple, List

from tracking_parking.detection.line_crossing import LineTransitionState


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
    line1_time: Optional[float] = None  # 通過したストリーム時刻(秒)

    # Line2状態(補助ライン)
    line2_direction: Optional[str] = None  # "IN" or "OUT"
    line2_time: Optional[float] = None  # 通過したストリーム時刻(秒)

    # イベント追跡
    passed_order: List[str] = field(default_factory=list)  # ["line1", "line2"] など
    counted: bool = False
    confidence: Optional[Confidence] = None
    pending_event_id: Optional[str] = None

    # 更新追跡
    last_update_time: float = 0.0  # 最後に位置が入ったストリーム時刻(秒)

    def update_position(self, point: Tuple[float, float], stream_time_sec: float):
        """
        車両位置を更新

        Args:
            point: 新しい車両位置
            stream_time_sec: ストリーム時刻(秒)
        """
        self.prev_point = self.curr_point
        self.curr_point = point
        self.last_update_time = stream_time_sec

    def record_line1_crossing(self, direction: str, stream_time_sec: float):
        """
        Line1交差を記録

        Args:
            direction: "IN" or "OUT"
            stream_time_sec: ストリーム時刻(秒)
        """
        self.line1_direction = direction
        self.line1_time = stream_time_sec
        self.passed_order.append("line1")

    def record_line2_crossing(self, direction: str, stream_time_sec: float):
        """
        Line2交差を記録

        Args:
            direction: "IN" or "OUT"
            stream_time_sec: ストリーム時刻(秒)
        """
        self.line2_direction = direction
        self.line2_time = stream_time_sec
        self.passed_order.append("line2")

    def resolve_confidence(
        self,
        current_time_sec: float,
        max_gap_sec: float,
    ) -> Optional[Confidence]:
        """
        pendingの信頼度を、現在までのライン通過履歴から解決する。

        Args:
            current_time_sec: 現在のストリーム時刻(秒)
            max_gap_sec: Line1とLine2の通過を対応付ける最大の時間差(秒)

        Returns:
            Optional[Confidence]: "pending"、"high"、"normal"、またはNone
        """
        if not self.counted or self.line1_time is None:
            return None

        if self.confidence in ("high", "normal"):
            return self.confidence

        if self.line1_direction == "IN" and self.line2_direction is None:
            if current_time_sec - self.line1_time > max_gap_sec:
                self.confidence = "normal"
            else:
                self.confidence = "pending"
            return self.confidence

        # OUTでLine2が未通過なら、期待順序 line2→line1 はすでに成立しない。
        if self.line2_direction is None or self.line2_time is None:
            self.confidence = "normal"
            return self.confidence

        if self.line1_direction == "IN":
            expected_order = ["line1", "line2"]
        elif self.line1_direction == "OUT":
            expected_order = ["line2", "line1"]
        else:
            self.confidence = "normal"
            return self.confidence

        time_diff = abs(self.line1_time - self.line2_time)
        valid_pair = (
            self.line1_direction == self.line2_direction
            and time_diff <= max_gap_sec
            and self.passed_order == expected_order
        )
        self.confidence = "high" if valid_pair else "normal"
        return self.confidence


class VehicleTracker:
    """車両トラッキングクラス"""

    def __init__(self, max_gap_sec: float = 3.0, cleanup_threshold_sec: float = 5.0):
        """
        Args:
            max_gap_sec: Line1とLine2の通過を対応付ける最大の時間差(秒)
            cleanup_threshold_sec: 古い追跡をクリーンアップするまでの未更新時間(秒)
        """
        self.states: Dict[int, VehicleState] = {}
        self.max_gap_sec = max_gap_sec
        self.cleanup_threshold_sec = cleanup_threshold_sec

        # 統計情報
        self.total_in = 0
        self.total_out = 0
        self.high_confidence_count = 0
        self.normal_confidence_count = 0

    def update(
        self, track_id: int, point: Tuple[float, float], stream_time_sec: float
    ) -> VehicleState:
        """
        車両状態を更新または作成

        Args:
            track_id: トラッキングID
            point: 車両位置
            stream_time_sec: ストリーム時刻(秒)

        Returns:
            VehicleState: 更新された車両状態
        """
        if track_id not in self.states:
            # 新しい車両を追加
            self.states[track_id] = VehicleState(track_id=track_id)

        state = self.states[track_id]
        state.update_position(point, stream_time_sec)

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
        current_time_sec: float,
    ) -> List[ConfidenceUpdate]:
        """全trackのpending confidenceを評価し、新たな確定結果を返す。"""
        updates = []
        for state in self.states.values():
            if state.confidence != "pending":
                continue

            resolved = state.resolve_confidence(current_time_sec, self.max_gap_sec)
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

    def cleanup_stale_tracks(self, current_time_sec: float):
        """
        古い追跡を削除

        Args:
            current_time_sec: 現在のストリーム時刻(秒)
        """
        track_ids_to_remove = []

        for track_id, state in self.states.items():
            elapsed_since_update = current_time_sec - state.last_update_time

            if (
                elapsed_since_update > self.cleanup_threshold_sec
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
