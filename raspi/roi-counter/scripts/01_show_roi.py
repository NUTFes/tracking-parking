import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import cv2

from src.roi import get_roi_y_range
from src.visualizer import draw_band_lines, draw_grid, draw_roi

# ── パラメータ ──────────────────────────────────────────────────────────────
VIDEO_SOURCE: str | int = "data/inputs/IMG_2788_fixed.MOV"
SEEK_SEC = 5.0  # 表示するフレームの秒数

ROI_POINTS = [
    (630, 770),
    (1270, 770),
    (1530, 1000),
    (390, 1000),
]
S_LOW  = 0.15
S_HIGH = 0.60
# ────────────────────────────────────────────────────────────────────────────

OUTPUT_PATH = Path("data/outputs/roi_check.png")


def main() -> None:
    cap = cv2.VideoCapture(VIDEO_SOURCE)
    if not cap.isOpened():
        print(f"[ERROR] 動画を開けません: {VIDEO_SOURCE}")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_POS_MSEC, SEEK_SEC * 1000)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        print(f"[ERROR] {SEEK_SEC}秒地点のフレームを取得できません")
        sys.exit(1)

    draw_grid(frame)
    draw_roi(frame, ROI_POINTS)
    y_min, y_max = get_roi_y_range(ROI_POINTS)
    draw_band_lines(frame, ROI_POINTS, y_min, y_max, S_LOW, S_HIGH)
    cv2.putText(frame, f"y_min={y_min:.0f}  y_max={y_max:.0f}",
                (10, frame.shape[0] - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUTPUT_PATH), frame)
    print(f"保存: {OUTPUT_PATH}")

    cv2.imshow("ROI Check", frame)
    while True:
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
