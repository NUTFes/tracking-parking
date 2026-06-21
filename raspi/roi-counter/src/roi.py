import cv2
import numpy as np
from typing import List, Tuple


def is_in_roi(point: Tuple[float, float], roi_points: List[Tuple[int, int]]) -> bool:
    contour = np.array(roi_points, dtype=np.float32)
    return cv2.pointPolygonTest(contour, point, False) >= 0


def get_roi_y_range(roi_points: List[Tuple[int, int]]) -> Tuple[float, float]:
    ys = [p[1] for p in roi_points]
    return float(min(ys)), float(max(ys))
