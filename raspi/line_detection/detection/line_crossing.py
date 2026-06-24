"""
ライン交差検知モジュール
外積法を使用してライン交差を判定する
"""

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
    """
    # 外積: (B-A) × (P-A)
    # = (x2-x1) * (py-y1) - (y2-y1) * (px-x1)
    return (line_end[0] - line_start[0]) * (point[1] - line_start[1]) - \
           (line_end[1] - line_start[1]) * (point[0] - line_start[0])


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
    """ライン交差検知クラス"""

    def __init__(self,
                 line1: Line,
                 line2: Line,
                 parking_ref_point: Tuple[float, float],
                 margin: float = 1000.0):
        """
        Args:
            line1: Line1(入口側ライン)
            line2: Line2(駐車場側ライン)
            parking_ref_point: 駐車場基準点
            margin: ライン交差判定のマージン
        """
        self.line1 = line1
        self.line2 = line2
        self.parking_ref_point = parking_ref_point
        self.margin = margin

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

    def detect_line1_crossing(self,
                              prev_point: Tuple[float, float],
                              curr_point: Tuple[float, float]) -> Optional[str]:
        """
        Line1(入口側)の交差を検知

        Args:
            prev_point: 前フレームの車両位置
            curr_point: 現フレームの車両位置

        Returns:
            Optional[str]:
                "IN": 入庫方向に交差
                "OUT": 出庫方向に交差
                None: 交差なし
        """
        return self._detect_crossing(
            prev_point,
            curr_point,
            self.line1,
            self.parking_side_line1
        )

    def detect_line2_crossing(self,
                              prev_point: Tuple[float, float],
                              curr_point: Tuple[float, float]) -> bool:
        """
        Line2(駐車場側)の交差を検知

        Args:
            prev_point: 前フレームの車両位置
            curr_point: 現フレームの車両位置

        Returns:
            bool: 交差した場合True、そうでない場合False
        """
        result = self._detect_crossing(
            prev_point,
            curr_point,
            self.line2,
            self.parking_side_line2
        )
        return result is not None

    def _detect_crossing(self,
                        prev_point: Tuple[float, float],
                        curr_point: Tuple[float, float],
                        line: Line,
                        parking_side: float) -> Optional[str]:
        """
        ライン交差を検知(内部実装)

        Args:
            prev_point: 前フレームの車両位置
            curr_point: 現フレームの車両位置
            line: 判定するライン
            parking_side: 駐車場側の符号

        Returns:
            Optional[str]:
                "IN": 入庫方向に交差
                "OUT": 出庫方向に交差
                None: 交差なし
        """
        # 前フレームと現フレームの側を計算
        prev_side = side_of_line(prev_point, line.start, line.end)
        curr_side = side_of_line(curr_point, line.start, line.end)

        # マージン処理: 微小な揺れを無視
        if abs(prev_side) < self.margin or abs(curr_side) < self.margin:
            return None

        # 符号が変化 = ライン交差
        if prev_side * curr_side < 0:
            # 駐車場基準点でIN/OUT判定
            # curr_sideとparking_sideの符号が同じ = 駐車場側に移動 = IN
            # curr_sideとparking_sideの符号が異なる = 道路側に移動 = OUT
            if curr_side * parking_side > 0:
                return "IN"
            else:
                return "OUT"

        return None

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
