import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

import cv2

# ── パラメータ ──────────────────────────────────────────────────────────────
VIDEO_SOURCE = "data/inputs/IMG_2787.MOV"
TARGET_FPS = 20.0
# ────────────────────────────────────────────────────────────────────────────


def main() -> None:
    src = Path(VIDEO_SOURCE)
    out_path = src.with_name(src.stem + "_fixed" + src.suffix)

    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        print(f"[ERROR] 動画を開けません: {src}")
        sys.exit(1)

    src_fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print(f"入力: {src}  ({src_fps:.2f} fps, {w}x{h}, {total_frames}フレーム)")
    print(f"出力: {out_path}  ({TARGET_FPS} fps)")

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, TARGET_FPS, (w, h))

    # 元FPSとターゲットFPSの比率でフレームを間引く
    step = src_fps / TARGET_FPS
    next_idx = 0.0
    frame_idx = 0
    written = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx >= next_idx:
            writer.write(frame)
            next_idx += step
            written += 1
        frame_idx += 1

    cap.release()
    writer.release()
    print(f"完了: {written}フレーム書き込み")


if __name__ == "__main__":
    main()
