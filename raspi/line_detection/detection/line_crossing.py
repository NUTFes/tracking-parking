"""
ライン交差検知モジュール
外積法とヒステリシス方式を使用してライン交差を判定する
"""

import math
from dataclasses import dataclass
from typing import Tuple, Optional, List
from detection.config import Line


def side_of_line(point: Tuple[float, float],
                 line_start: Tuple[float, float],
                 line_end: Tuple[float, float]) -> float:
    """
    外積を使用してポイントがラインのどちら側にあるか判定

    Args:
        point: 判定するポイント (x, y)
        line_start: ラインの始点 (x, y)
        line_end: ラインの終点 (x, y)

    Returns:
        float: 外積の値
            > 0: ポイントはライン の片側
            < 0: ポイントはラインの反対側
            = 0: ポイントはライン上

    Note:
        外積値は「距離 × ライン長」に等しく、単位はpxではない。
        px単位の距離が必要な場合は signed_distance() を使うこと。
    """
    # 外積: (B-A) × (P-A)
    # = (x2-x1) * (py-y1) - (y2-y1) * (px-x1)
    return (line_end[0] - line_start[0]) * (point[1] - line_start[1]) - \
           (line_end[1] - line_start[1]) * (point[0] - line_start[0])


def line_length(line: Line) -> float:
    """
    ラインの長さ(px)を計算

    Args:
        line: 対象のライン

    Returns:
        float: ラインの長さ(px)
    """
    return math.hypot(line.end[0] - line.start[0], line.end[1] - line.start[1])


def signed_distance(point: Tuple[float, float], line: Line) -> float:
    """
    ラインからの符号付き距離(px)を計算

    Args:
        point: 判定するポイント (x, y)
        line: 対象のライン

    Returns:
        float: 符号付き距離(px)。符号の向きは side_of_line() と同じ。
    """
    return side_of_line(point, line.start, line.end) / line_length(line)


def classify_side(point: Tuple[float, float], line: Line, margin_px: float) -> int:
    """
    ポイントがラインのどちら側の安定領域にあるか分類する

    Args:
        point: 判定するポイント (x, y)
        line: 対象のライン
        margin_px: 判定保留帯の半幅(px)

    Returns:
        int:
            +1: signed_distance が +margin_px を超える(安定側)
            -1: signed_distance が -margin_px を下回る(安定側)
             0: 判定保留帯の中(どちらの側かを判断しない)
    """
    d = signed_distance(point, line)
    if d > margin_px:
        return 1
    if d < -margin_px:
        return -1
    return 0


def segment_crossing_param(p_from: Tuple[float, float],
                           p_to: Tuple[float, float],
                           line: Line) -> Optional[float]:
    """
    p_from→p_to の移動線分が line の(無限直線としての)交点を、
    line 自身の長さを1とした射影係数 t として返す

    Args:
        p_from: 移動前のポイント
        p_to: 移動後のポイント
        line: 対象のライン

    Returns:
        Optional[float]:
            None: p_from と p_to が line に対して同じ側(交差なし)
            float: 射影係数 t。t∈[0,1] とは限らない
                (呼び出し側が endpoint_margin_px を加味した許容範囲で
                 成立を判定すること)
    """
    d_from = signed_distance(p_from, line)
    d_to = signed_distance(p_to, line)

    if d_from * d_to >= 0:
        return None

    denom = d_from - d_to
    if denom == 0.0:
        return None  # 防御的ガード(理論上ここには来ない: 符号が逆なら値は必ず異なる)

    u = d_from / denom
    cross_x = p_from[0] + u * (p_to[0] - p_from[0])
    cross_y = p_from[1] + u * (p_to[1] - p_from[1])

    ab_x = line.end[0] - line.start[0]
    ab_y = line.end[1] - line.start[1]
    ap_x = cross_x - line.start[0]
    ap_y = cross_y - line.start[1]
    length_sq = ab_x * ab_x + ab_y * ab_y

    return (ap_x * ab_x + ap_y * ab_y) / length_sq


@dataclass
class LineTransitionState:
    """track 1本 × ライン1本ぶんのヒステリシス状態"""
    stable_side: Optional[int] = None
    last_stable_point: Optional[Tuple[float, float]] = None


def get_vehicle_point(bbox: List[float]) -> Tuple[float, float]:
    """
    bboxから車両代表点(底面中央)を取得

    Args:
        bbox: [x1, y1, x2, y2] の形式のバウンディングボックス

    Returns:
        Tuple[float, float]: 車両代表点 (x, y)
            底面中央: ((x1 + x2) / 2, y2)
    """
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, y2)


class LineCrossingDetector:
    """ライン交差検知クラス(ヒステリシス方式)"""

    def __init__(self,
                 line1: Line,
                 line2: Line,
                 parking_ref_point: Tuple[float, float],
                 margin_px: float = 1000.0,
                 endpoint_margin_px: float = 0.0):
        """
        Args:
            line1: Line1(入口側ライン)
            line2: Line2(駐車場側ライン)
            parking_ref_point: 駐車場基準点
            margin_px: 判定保留帯の半幅(px)
            endpoint_margin_px: 有限線分判定における端点の許容量(px)
        """
        self.line1 = line1
        self.line2 = line2
        self.parking_ref_point = parking_ref_point
        self.margin_px = margin_px
        self.endpoint_margin_px = endpoint_margin_px
        self.line1_length = line_length(line1)
        self.line2_length = line_length(line2)

        # 駐車場側の符号を事前計算
        self.parking_side_line1 = side_of_line(
            parking_ref_point,
            line1.start,
            line1.end
        )
        self.parking_side_line2 = side_of_line(
            parking_ref_point,
            line2.start,
            line2.end
        )

    def update_line1_crossing(self,
                              transition_state: LineTransitionState,
                              curr_point: Tuple[float, float]) -> Optional[str]:
        """
        Line1(入口側)の交差を判定し、ヒステリシス状態を更新する

        Args:
            transition_state: このtrack×Line1のヒステリシス状態(内部で更新される)
            curr_point: 現フレームの車両位置

        Returns:
            Optional[str]:
                "IN": 入庫方向に交差
                "OUT": 出庫方向に交差
                None: 交差なし
        """
        return self._update_crossing(
            transition_state,
            curr_point,
            self.line1,
            self.parking_side_line1,
            self.line1_length
        )

    def update_line2_crossing(self,
                              transition_state: LineTransitionState,
                              curr_point: Tuple[float, float]) -> Optional[str]:
        """
        Line2(駐車場側)の交差を判定し、ヒステリシス状態を更新する

        Args:
            transition_state: このtrack×Line2のヒステリシス状態(内部で更新される)
            curr_point: 現フレームの車両位置

        Returns:
            Optional[str]:
                "IN": 入庫方向に交差
                "OUT": 出庫方向に交差
                None: 交差なし
        """
        return self._update_crossing(
            transition_state,
            curr_point,
            self.line2,
            self.parking_side_line2,
            self.line2_length
        )

    def _update_crossing(self,
                        transition_state: LineTransitionState,
                        curr_point: Tuple[float, float],
                        line: Line,
                        parking_side: float,
                        line_len: float) -> Optional[str]:
        """
        ヒステリシス方式によるライン交差判定(内部実装)

        Args:
            transition_state: ヒステリシス状態(内部で更新される)
            curr_point: 現フレームの車両位置
            line: 判定するライン
            parking_side: 駐車場側の符号
            line_len: lineの長さ(px)

        Returns:
            Optional[str]:
                "IN": 入庫方向に交差
                "OUT": 出庫方向に交差
                None: 交差なし
        """
        side = classify_side(curr_point, line, self.margin_px)

        if transition_state.stable_side is None:
            # 初回観測。判定保留帯(0)なら何もせず、次フレームまで確定を待つ
            if side != 0:
                transition_state.stable_side = side
                transition_state.last_stable_point = curr_point
            return None

        if side == 0:
            # 判定保留帯: 側もlast_stable_pointも変えない
            return None

        if side == transition_state.stable_side:
            # 同じ安定側 → 参照点を更新するだけ
            transition_state.last_stable_point = curr_point
            return None

        # side == -stable_side: 反対の安定側へ抜けた
        t = segment_crossing_param(
            transition_state.last_stable_point, curr_point, line
        )
        event = None
        if t is not None:
            e = (self.endpoint_margin_px / line_len) if line_len > 0 else 0.0
            if -e <= t <= 1.0 + e:
                # 駐車場基準点でIN/OUT判定
                # sideとparking_sideの符号が同じ = 駐車場側に移動 = IN
                # sideとparking_sideの符号が異なる = 道路側に移動 = OUT
                event = "IN" if side * parking_side > 0 else "OUT"

        # ブックキーピングは判定の成否と無関係に更新する。
        # stable_sideは「curr_pointが現在どちらの安定側にいるか」という
        # 幾何的事実であり、線分内かどうかとは独立している。ここで更新を
        # 止めると、以降のフレームが古いlast_stable_pointを基準に判定を
        # 続けてしまい、間に本物の交差があっても検出できなくなる。
        transition_state.stable_side = side
        transition_state.last_stable_point = curr_point

        return event

    def is_point_near_line(self,
                          point: Tuple[float, float],
                          line: Line,
                          threshold: float = 50.0) -> bool:
        """
        ポイントがラインの近くにあるかチェック

        Args:
            point: チェックするポイント
            line: ライン
            threshold: 距離の閾値(ピクセル)

        Returns:
            bool: ラインの近くにある場合True
        """
        # ラインまでの距離を計算(外積を使った垂線距離)
        side = abs(side_of_line(point, line.start, line.end))

        # ラインの長さ
        line_length = ((line.end[0] - line.start[0]) ** 2 +
                      (line.end[1] - line.start[1]) ** 2) ** 0.5

        # 垂線距離 = |外積| / ラインの長さ
        distance = side / line_length if line_length > 0 else float('inf')

        return distance < threshold
