import cv2
import os
from dotenv import load_dotenv
from ultralytics import YOLO
import easyocr
import Levenshtein

# パス設定
load_dotenv()
HOME_DIR = os.environ["HOME_DIR"]
PATH = os.path.join(HOME_DIR, "yolo_fine_tuning/runs/detect/train14/weights/best.pt")
# PATH = "/Users/ycn/Workspace/NUTMEG/tracking-parking/yolo_fine_tuning/test/yolov8l.pt"
# video_path = os.path.join(HOME_DIR, "yolo_fine_tuning/src/testVideo/ocr_test2.mp4")
video_path = os.path.join(HOME_DIR, "yolo_fine_tuning/src/testVideo/tra-pa_motion_test_multi.mp4")
camera_path = 0


# Yoloモデルのロードとビデオキャプチャのセットアップ
model = YOLO(PATH)
cap = cv2.VideoCapture(camera_path)
# cap = cv2.VideoCapture(video_path)

# fps値設定
cap.set(cv2.CAP_PROP_FPS, 60)

# 出力動画の設定
# output_path = os.path.join(HOME_DIR, 'yolo_fine_tuning/src/testVideo/output.mp4')
# fourcc = cv2.VideoWriter_fourcc(*'mp4v')
# out = cv2.VideoWriter(output_path, fourcc, 30.0, (int(cap.get(3)), int(cap.get(4))))

# その他の初期化
id_list = []
reader = easyocr.Reader(["ja", "en"])
first_time = True
found_similar = False
before_prosess = True
ocr_results = []
division = 5/12

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    # 物体認識前処理
    if before_prosess:
        # ノイズ除去
        denoised_frame = cv2.medianBlur(frame, 1)
        
        # グレースケール化
        g_frame = cv2.cvtColor(denoised_frame, cv2.COLOR_BGR2GRAY)
        
        # エッジ検出 (Canny)
        # edges_frame = cv2.Canny(g_frame, 200, 400)
        # edges_frame = cv2.Canny(denoised_frame, 100, 200)
        
        # 大津の手法による2値化
        # _, binary_frame = cv2.threshold(g_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # _, binary_frame = cv2.threshold(ch_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # バイキュービック補間
        # resized_frame = cv2.resize(g_frame, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        
        # 前処理後フレーム変数
        # results_frame = resized_frame
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
        print('xyxy:', x1, y1, x2, y2)
        
        
        # 物体検出後画像処理
        # ナンバープレート上部と下部で分割
        t_cropped_frame = results_frame[y1:int(y1+(y2-y1)*division), x1:x2]
        b_cropped_frame = results_frame[int(y1+(y2-y1)*division):y2, x1:x2]
        
        if not before_prosess:
            # グレースケール化
            t_g_cropped_frame = cv2.cvtColor(t_cropped_frame, cv2.COLOR_BGR2GRAY)
            b_g_cropped_frame = cv2.cvtColor(b_cropped_frame, cv2.COLOR_BGR2GRAY)
            
            # ノイズ除去
            # t_denoised_cropped_frame = cv2.medianBlur(t_g_cropped_frame, 1)
            # b_denoised_cropped_frame = cv2.medianBlur(b_g_cropped_frame, 1)
            
            # エッジ検出 (Canny)
            # t_edges_cropped_frame = cv2.Canny(t_denoised_cropped_frame, 100, 200)
            # b_edges_cropped_frame = cv2.Canny(b_denoised_cropped_frame, 100, 200)
            
            # 大津の手法による2値化
            _, t_binary_cropped_frame = cv2.threshold(t_g_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            _, b_binary_cropped_frame = cv2.threshold(b_g_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # _, t_binary_cropped_frame = cv2.threshold(t_denoised_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            # _, b_binary_cropped_frame = cv2.threshold(b_denoised_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # _, t_binary_cropped_frame = cv2.threshold(t_denoised_cropped_frame, 0, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C + cv2.THRESH_OTSU)
            # _, b_binary_cropped_frame = cv2.threshold(b_denoised_cropped_frame, 0, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C + cv2.THRESH_OTSU)
            
            # # バイキュービック補間
            # t_resized_cropped_frame = cv2.resize(t_binary_cropped_frame, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            # b_resized_cropped_frame = cv2.resize(b_binary_cropped_frame, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            
            # 前処理後フレーム変数
            t_result_frame = t_binary_cropped_frame
            b_result_frame = b_binary_cropped_frame
        else:
            t_resized_frame = cv2.resize(t_cropped_frame, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            b_resized_frame = cv2.resize(b_cropped_frame, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            
            # 前処理後フレーム変数
            t_result_frame = t_resized_frame
            b_result_frame = b_resized_frame
        
        
        # 前処理後の状態をフレームに表示
        cv2.imshow('Processed Top Frame', t_result_frame)
        cv2.imshow('Processed Bottom Frame', b_result_frame)
        
        t_result_text = reader.readtext(t_result_frame, detail=0)
        b_result_text = reader.readtext(b_result_frame, detail=0)
        result_list = t_result_text + b_result_text
        result_text = " ".join(result_list)
        print("OCR:", result_text)
        
        # OCR結果からすでに駐車場に入った車かどうかを判定
        found_similar = False
        count = 0
        print("len of ocr_results:", len(ocr_results))
        print("len of id_list:", len(id_list))
        for parked in ocr_results:
            similarity = Levenshtein.ratio(result_text, parked)
            print("類似度比較：", similarity)
            print("count:", count)
            if similarity >= 0.8:
                found_similar = True
                break
            count+=1
            
        if found_similar:
            del ocr_results[count]
        else:
            ocr_results.append(result_text)

    # IDのセットを更新
    if not found_similar:
        id_list.extend(new_ids)
    
    print("id:", id_list)
    print("parked", len(ocr_results))

    # 出力動画にフレームを書き込む
    # out.write(annotated_frame)
    
    # フレームを表示
    cv2.imshow('Frame', annotated_frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# ocrの結果
print(ocr_results)

# リソースの解放
cap.release()
# out.release()
cv2.destroyAllWindows()
