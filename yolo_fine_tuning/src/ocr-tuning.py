import cv2
import os
from dotenv import load_dotenv
from ultralytics import YOLO
import easyocr
import Levenshtein

def preprocessing(image, ):
    x1 = y1 = 0
    x2, y2, _ = image.shape
    lx = x2-x1
    ly = y2-y1
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    print('xyxy:', x1, y1, x2, y2)
    return 0

def main():
    # パス設定
    load_dotenv()
    HOME_DIR = os.environ["HOME_DIR"]
    image_path = "/Users/ycn/Workspace/NUTMEG/tracking-parking/detected_images/detected_object_25.jpg"
    # Yoloモデルのロードとビデオキャプチャのセットアップ
    image = cv2.imread(image_path)
    
    # 画像を保存するディレクトリを作成
    save_dir = os.path.join(HOME_DIR, "detected_images")
    os.makedirs(save_dir, exist_ok=True)
    
    

if __name__ == "__main__":
    main()


# その他の初期化
id_list = []
reader = easyocr.Reader(["ja", "en"])
first_time = True
found_similar = False
before_prosess = True
before_resize = False
ocr_results = []
division = 5/12

x1 = y1 = 0
x2, y2, _ = image.shape
lx = x2-x1
ly = y2-y1
x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
print('xyxy:', x1, y1, x2, y2)

# グレースケール化
g_cropped_frame = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

# エッジ検出
# edges_cropped_frame = cv2.Canny(g_cropped_frame, 100, 200)

# 大津の手法による2値化
# _, binary_cropped_frame = cv2.threshold(edges_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

# バイキュービック補間
resized_frame = cv2.resize(g_cropped_frame, None, fx=10, fy=10, interpolation=cv2.INTER_CUBIC)

# 前処理後フレーム変数
result_frame = resized_frame

# # 物体検出後画像処理
# # ナンバープレート上部と下部で分割
# t_cropped_frame = image[y1:int(y1+ly*division), x1:x2]
# b_cropped_frame = image[int(y1+ly*division):y2, x1:x2]

# # グレースケール化
# t_g_cropped_frame = cv2.cvtColor(t_cropped_frame, cv2.COLOR_BGR2GRAY)
# b_g_cropped_frame = cv2.cvtColor(b_cropped_frame, cv2.COLOR_BGR2GRAY)

# # エッジ検出 (Canny)
# t_edges_cropped_frame = cv2.Canny(t_g_cropped_frame, 100, 200)
# b_edges_cropped_frame = cv2.Canny(b_g_cropped_frame, 100, 200)

# # 大津の手法による2値化
# # _, t_binary_cropped_frame = cv2.threshold(t_edges_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
# # _, b_binary_cropped_frame = cv2.threshold(b_edges_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

# if not before_prosess:
#     # # グレースケール化
#     # t_g_cropped_frame = cv2.cvtColor(t_cropped_frame, cv2.COLOR_BGR2GRAY)
#     # b_g_cropped_frame = cv2.cvtColor(b_cropped_frame, cv2.COLOR_BGR2GRAY)
    
#     # エッジ検出 (Canny)
#     t_edges_cropped_frame = cv2.Canny(t_binary_cropped_frame, 100, 200)
#     b_edges_cropped_frame = cv2.Canny(b_binary_cropped_frame, 100, 200)
    
#     # 大津の手法による2値化
#     _, t_binary_cropped_frame = cv2.threshold(t_edges_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
#     _, b_binary_cropped_frame = cv2.threshold(b_edges_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
#     # _, t_binary_cropped_frame = cv2.threshold(t_denoised_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
#     # _, b_binary_cropped_frame = cv2.threshold(b_denoised_cropped_frame, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
#     # _, t_binary_cropped_frame = cv2.threshold(t_denoised_cropped_frame, 0, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C + cv2.THRESH_OTSU)
#     # _, b_binary_cropped_frame = cv2.threshold(b_denoised_cropped_frame, 0, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C + cv2.THRESH_OTSU)
    
#     # # バイキュービック補間
#     # t_resized_cropped_frame = cv2.resize(t_binary_cropped_frame, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
#     # b_resized_cropped_frame = cv2.resize(b_binary_cropped_frame, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    
#     # 前処理後フレーム変数
#     t_result_frame = t_binary_cropped_frame
#     b_result_frame = b_binary_cropped_frame
# else:
#     # # バイキュービック補間
#     # t_resized_frame = cv2.resize(t_binary_cropped_frame, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
#     # b_resized_frame = cv2.resize(t_binary_cropped_frame, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
#     # バイキュービック補間
#     t_resized_frame = cv2.resize(t_edges_cropped_frame, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
#     b_resized_frame = cv2.resize(b_edges_cropped_frame, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    
#     # 前処理後フレーム変数
#     t_result_frame = t_resized_frame
#     b_result_frame = b_resized_frame
    
        
# 前処理後の状態をフレームに表示
# cv2.imwrite('ProcessedTopFrame.jpg', t_result_frame)
# cv2.imwrite('ProcessedBottomFrame.jpg', b_result_frame)
cv2.imwrite('ProcessedFrame.jpg', resized_frame)

# t_result_text = reader.readtext(t_result_frame, detail=0)
# b_result_text = reader.readtext(b_result_frame, detail=0)
result_text = reader.readtext(result_frame, detail=0)
# result_list = t_result_text + b_result_text
# result_text = " ".join(result_list)
print("OCR:", result_text)

# リソースの解放
cv2.destroyAllWindows()
