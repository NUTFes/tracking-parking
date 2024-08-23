import cv2
import os
from dotenv import load_dotenv
from ultralytics import YOLO
import easyocr

# パス設定
load_dotenv()
HOME_DIR = os.environ["HOME_DIR"]
PATH = os.path.join(HOME_DIR, "yolo_fine_tuning/runs/detect/train14/weights/best.pt")
video_path = os.path.join(HOME_DIR, "yolo_fine_tuning/src/testVideo/tra-pa_motion_test_multi.mp4")

# Yoloモデルのロードとビデオキャプチャのセットアップ
model = YOLO(PATH)
cap = cv2.VideoCapture(video_path)

# 出力動画の設定
output_path = os.path.join(HOME_DIR, 'yolo_fine_tuning/src/testVideo/output.mp4')
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
out = cv2.VideoWriter(output_path, fourcc, 30.0, (int(cap.get(3)), int(cap.get(4))))

# その他の初期化
id_set = set()
reader = easyocr.Reader(["ja", "en"])
first_time = True

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    # 物体検知
    results = model.track(frame, persist=True)
    annotated_frame = results[0].plot()
    id_list = list(map(int, results[0].boxes.id)) if results[0].boxes.id is not None else []

    if first_time and results[0].boxes.xyxy.tolist():
        first_time = False

    # 新しいIDの検出とOCR実行
    new_ids = [i for i in id_list if i not in id_set and results[0].boxes.xyxy.tolist()]
    for i in new_ids:
        x1, y1, x2, y2 = results[0].boxes.xyxy[0].tolist()
        print('xyxy:', x1, y1, x2, y2)
        result_text = reader.readtext(frame, detail=0)
        print("OCR:", result_text)

    # IDのセットを更新
    id_set.update(new_ids)
    print("id:", id_set)

    # 出力動画にフレームを書き込む
    out.write(annotated_frame)
    
    # フレームを表示
    cv2.imshow('Frame', annotated_frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# リソースの解放
cap.release()
out.release()
cv2.destroyAllWindows()
