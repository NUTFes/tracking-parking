from typing import List, Tuple

import cv2
import numpy as np

from .tracker import VehicleState

_STATE_COLORS = {
    VehicleState.UNKNOWN:       (128, 128, 128),
    VehicleState.IN_CANDIDATE:  (0, 255, 0),
    VehicleState.OUT_CANDIDATE: (0, 0, 255),
    VehicleState.COUNTED:       (255, 165, 0),
}


def draw_roi(frame, roi_points: List[Tuple[int, int]],
             color=(0, 255, 0), thickness: int = 2) -> None:
    pts = np.array(roi_points, dtype=np.int32)
    cv2.polylines(frame, [pts], isClosed=True, color=color, thickness=thickness)
    for i, (x, y) in enumerate(roi_points):
        cv2.circle(frame, (x, y), 5, color, -1)
        cv2.putText(frame, str(i), (x + 8, y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def draw_bbox_with_info(frame, bbox: Tuple[int, int, int, int],
                        track_id: int, s: float, state: VehicleState) -> None:
    x1, y1, x2, y2 = bbox
    color = _STATE_COLORS.get(state, (255, 255, 255))
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    label = f"ID:{track_id} s:{s:.2f} {state.value}"
    cv2.putText(frame, label, (x1, y1 - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)


def draw_band_lines(frame, roi_points: List[Tuple[int, int]],
                    y_min: float, y_max: float,
                    s_low: float, s_high: float) -> None:
    """ROI内に s_low・s_high の横ラインを描画する．"""
    def _x_at_y(p1, p2, y):
        x1, y1 = p1; x2, y2 = p2
        if y1 == y2:
            return None
        t = (y - y1) / (y2 - y1)
        return x1 + t * (x2 - x1) if 0 <= t <= 1 else None

    n = len(roi_points)
    for s, color, label in [
        (s_low,  (0, 200, 0),   f"s_low={s_low}"),
        (s_high, (0, 0, 200),   f"s_high={s_high}"),
    ]:
        y = y_max - s * (y_max - y_min)
        xs = [x for i in range(n)
              if (x := _x_at_y(roi_points[i], roi_points[(i + 1) % n], y)) is not None]
        if len(xs) >= 2:
            x_left, x_right = int(min(xs)), int(max(xs))
            y_int = int(y)
            cv2.line(frame, (x_left, y_int), (x_right, y_int), color, 2)
            cv2.putText(frame, label, (x_left + 5, y_int - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)


def draw_counts(frame, count_in: int, count_out: int) -> None:
    cv2.putText(frame, f"IN:  {count_in}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
    cv2.putText(frame, f"OUT: {count_out}", (10, 70),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
