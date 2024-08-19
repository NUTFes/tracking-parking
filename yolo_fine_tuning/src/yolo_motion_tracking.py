import cv2
import os
from dotenv import load_dotenv
from ultralytics import YOLO

# 動画ファイルのパス
video_path = 'testVideo/tra-pa_motion_test.mp4'

# パス設定
load_dotenv()
HOME_DIR = os.environ["HOME_DIR"]
PATH = HOME_DIR + "/yolo_fine_tuning/runs/detect/train14/weights/best.pt"

# Yoloモデルのロード
model = YOLO(PATH)

# 動画ファイルの読み込み
cap = cv2.VideoCapture(video_path)

# 出力動画の設定
output_path = '/testVideo'
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
out = cv2.VideoWriter(output_path, fourcc, 30.0, (int(cap.get(3)), int(cap.get(4))))

while(cap.isOpened()):
    ret, frame = cap.read()
    if ret:
        # フレームごとに物体検知を行う
        results = model(frame)
        
        # 検知結果を描画
        annotated_frame = results[0].plot()
        
        # 出力動画にフレームを書き込む
        out.write(annotated_frame)
        
        # フレームを表示
        cv2.imshow('Frame', annotated_frame)
        
        # 'q'キーが押されたら終了
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    else:
        break

# リソースの解放
cap.release()
out.release()
cv2.destroyAllWindows()

