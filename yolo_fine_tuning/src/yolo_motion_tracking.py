import cv2
import os
from dotenv import load_dotenv
from ultralytics import YOLO
import easyocr

# パス設定
load_dotenv()
HOME_DIR = os.environ["HOME_DIR"]
PATH = os.path.join(HOME_DIR, "yolo_fine_tuning/runs/detect/train14/weights/best.pt")
video_path = os.path.join(HOME_DIR, "yolo_fine_tuning/src/testVideo/ocr_test_video.mp4")
camera_path = 0

# Yoloモデルのロードとビデオキャプチャのセットアップ
model = YOLO(PATH)
cap = cv2.VideoCapture(video_path)
# cap = cv2.VideoCapture(0)

# 出力動画の設定
output_path = os.path.join(HOME_DIR, 'yolo_fine_tuning/src/testVideo/output.mp4')
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
out = cv2.VideoWriter(output_path, fourcc, 30.0, (int(cap.get(3)), int(cap.get(4))))

# その他の初期化
id_set = set()
reader = easyocr.Reader(["ja", "en"])
first_time = True
ocr_results = []

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
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        print('xyxy:', x1, y1, x2, y2)
        t_cropped_frame = frame[y1:(y1+100), x1:x2]
        b_cropped_frame = frame[(y1+100):y2, x1:x2]
        
        # グレースケール化
        t_g_cropped_frame = cv2.cvtColor(t_cropped_frame, cv2.COLOR_BGR2GRAY)
        b_g_cropped_frame = cv2.cvtColor(b_cropped_frame, cv2.COLOR_BGR2GRAY)
        
        
        # ノイズ除去
        t_denoised_cropped_frame = cv2.medianBlur(t_g_cropped_frame, 3)
        b_denoised_cropped_frame = cv2.medianBlur(b_g_cropped_frame, 3)
        
        # 大津の手法による2値化
        _, t_binary_cropped_frame = cv2.threshold(t_denoised_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, b_binary_cropped_frame = cv2.threshold(b_denoised_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # 前処理後の状態をフレームに表示
        cv2.imshow('Processed Top Frame', t_binary_cropped_frame)
        cv2.imshow('Processed Bottom Frame', b_binary_cropped_frame)
        
        t_result_text = reader.readtext(t_binary_cropped_frame, detail=0)
        b_result_text = reader.readtext(b_binary_cropped_frame, detail=0)
        result_text = t_result_text + b_result_text
        ocr_results.append(result_text)
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

# ocrの結果
print(ocr_results)

# リソースの解放
cap.release()
out.release()
cv2.destroyAllWindows()
