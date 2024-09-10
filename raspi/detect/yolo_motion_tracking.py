import cv2
import os
from dotenv import load_dotenv
from ultralytics import YOLO
import easyocr
import Levenshtein
from dbcontrol import send_mongo,connect_mongo

# パス設定
load_dotenv()
HOME_DIR = os.environ["HOME_DIR"]
PATH = os.path.join(HOME_DIR, "yolo_fine_tuning/runs/detect/train14/weights/best.pt")
video_path = os.path.join(HOME_DIR, "yolo_fine_tuning/src/testVideo/tra-pa_motion_test_multi.mp4")
camera_path = 0
USER = os.environ["USER_NAME"]
PASS = os.environ["PASS"]
HOST = os.environ["HOST"]
PORT = os.environ["PORT"]
DB_NAME = os.environ["DB_NAME"]
COLLECTION_NAME = os.environ["COLLECTION_NAME"]

# mongoDBと接続
collection,_ = connect_mongo(USER,PASS,HOST,PORT,DB_NAME,COLLECTION_NAME)


# Yoloモデルのロードとビデオキャプチャのセットアップ
model = YOLO(PATH)
cap = cv2.VideoCapture(camera_path)

# fps値設定
cap.set(cv2.CAP_PROP_FPS, 60)

# 画像を保存するディレクトリを作成
save_dir = os.path.join(HOME_DIR, "detected_images")
os.makedirs(save_dir, exist_ok=True)

# その他の初期化
id_list = []
reader = easyocr.Reader(["ja", "en"])
first_time = True
found_similar = False
before_process = True
small_image_flag = False
detection_failure = False
ocr_results = []
division = 5/12
ignore_number_plate_txt = "日本 111 し 42-49"
ocr_results.append(ignore_number_plate_txt)

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    # 物体認識前処理
    if before_process:
        # ノイズ除去
        denoised_frame = cv2.medianBlur(frame, 1)
        
        # グレースケール化
        g_frame = cv2.cvtColor(denoised_frame, cv2.COLOR_BGR2GRAY)
        
        # 前処理後フレーム変数
        ch_frame = cv2.cvtColor(g_frame, cv2.COLOR_GRAY2BGR)
        results_frame = ch_frame
        
    else:
        results_frame = frame
    
    
    # 物体検知
    results = model.track(results_frame, persist=True)
    # results = model.predict(source=frame, imgsz=720)
    annotated_frame = results[0].plot()
    detected_ids = list(map(int, results[0].boxes.id)) if results[0].boxes.id is not None else []

    if first_time and results[0].boxes.xyxy.tolist():
        first_time = False

    # 新しいIDの検出とOCR実行
    new_ids = [i for i in detected_ids if i not in id_list and results[0].boxes.xyxy.tolist()]
    for i in new_ids:
        x1, y1, x2, y2 = results[0].boxes.xyxy[0].tolist()
        lx = x2-x1
        ly = y2-y1
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        # print('xyxy:', x1, y1, x2, y2)
        if(lx*ly < 2000):
            small_image_flag = True
        
        # 検出した領域を保存
        # detected_object = frame[y1:y2, x1:x2]
        # image_path = os.path.join(save_dir, f"detected_object_{i}.jpg")
        # cv2.imwrite(image_path, detected_object)
        # print(f"Saved detected object to {image_path}")
        
        # 物体検出後画像処理
        
        if not small_image_flag:
            # ナンバープレート上部と下部で分割
            t_cropped_frame = results_frame[y1:int(y1+ly*division), x1:x2]
            b_cropped_frame = results_frame[int(y1+ly*division):y2, x1:x2]
        
            # エッジ検出 (Canny)
            # t_edges_cropped_frame = cv2.Canny(t_cropped_frame, 100, 200)
            # b_edges_cropped_frame = cv2.Canny(b_cropped_frame, 100, 200)
            
            # 大津の手法による2値化
            # _, t_binary_cropped_frame = cv2.threshold(t_edges_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            # _, b_binary_cropped_frame = cv2.threshold(b_edges_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # # バイキュービック補間
            t_resized_cropped_frame = cv2.resize(t_cropped_frame, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            b_resized_cropped_frame = cv2.resize(b_cropped_frame, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            
            # 前処理後フレーム変数
            t_result_frame = t_resized_cropped_frame
            b_result_frame = b_resized_cropped_frame
            
            # 前処理後の状態をフレームに表示
            cv2.imshow('Processed Top Frame', t_result_frame)
            cv2.imshow('Processed Bottom Frame', b_result_frame)
            
            t_result_text = reader.readtext(t_result_frame, detail=0)
            b_result_text = reader.readtext(b_result_frame, detail=0)
            result_list = t_result_text + b_result_text
            result_text = " ".join(result_list)
            
        else:
            cropped_frame = results_frame[y1:y2, x1:x2]
            
            # バイキュービック補間
            resized_cropped_frame = cv2.resize(cropped_frame, None, fx=10, fy=10, interpolation=cv2.INTER_CUBIC)
            
            # 前処理後フレーム変数
            result_frame = resized_cropped_frame
            
            # 前処理後の状態をフレームに表示
            cv2.imshow('Processed Frame', result_frame)
            
            result_text = reader.readtext(result_frame, detail=0)
            
            small_image_flag = False
            
        
        # print("OCR:", result_text)
        if not result_text:
            detection_failure = True
        
        # OCR結果からすでに駐車場に入った車かどうかを判定
        found_similar = False
        count = 1
        # print("len of ocr_results:", len(ocr_results))
        # print("len of id_list:", len(id_list))
        for parked in ocr_results:
            similarity = Levenshtein.ratio(result_text, parked)
            # print("類似度比較：", similarity)
            if similarity >= 0.8:
                found_similar = True
                break
            elif similarity == 0.0:
                detection_failure = True
                break
            count += 1
            
        if detection_failure:
            # OCRリストの更新を行わずにフラグを初期化
            detection_failure = False
        elif found_similar:
            del ocr_results[count]
        else:
            ocr_results.append(result_text)

    # IDのセットを更新
    if not found_similar:
        id_list.extend(new_ids)
    
    parked_num = len(ocr_results)-1
    # print("id:", id_list)
    # print("parked:", parked_num)
    # データを送信する
    send_mongo(parked_num,collection)
    
    # フレームを表示
    cv2.imshow('Frame', annotated_frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# ocrの結果
# print(ocr_results)

# リソースの解放
cap.release()
# out.release()
cv2.destroyAllWindows()
