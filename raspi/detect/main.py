# yoloで物体認識したものを、日付と車数に変換して送信する

import cv2
from sahi import AutoDetectionModel
from sahi.utils.yolov8 import download_yolov8s_model
from dbcontrol import send_mongo,connect_mongo
from detect import detect
import os
from dotenv import load_dotenv

load_dotenv()
USER = os.environ["USER_NAME"]
PASS = os.environ["PASS"]
HOST = os.environ["HOST"]
PORT = os.environ["PORT"]
DB_NAME = os.environ["DB_NAME"]
COLLECTION_NAME = os.environ["COLLECTION_NAME"]
COLUMN_NAME = os.environ["COLUMN_NAME"]

# 人なら0、車なら2
count_class = 0

def main():
    # モデルをダウンロード
    yolov8_model_path = "models/yolov8s.pt"
    download_yolov8s_model(yolov8_model_path)

    # mongoDBと接続
    collection,_ = connect_mongo(USER,PASS,HOST,PORT,DB_NAME,COLLECTION_NAME,COLUMN_NAME)


    # 画像パスまたはnumpy画像を用いて標準的な推論を行う。
    # YOLOv8 、このようにオブジェクト検出用のモデルをインスタンス化することができる：
    detection_model = AutoDetectionModel.from_pretrained(
        model_type="yolov8",
        model_path=yolov8_model_path,
        confidence_threshold=0.3,
        device="cpu",  # or 'cuda:0'
    )

    # カメラデバイスを開く
    cap = cv2.VideoCapture(0)

    while True:
        ret, frame = cap.read()
        print("isCap",ret)
        if not ret:
            break
        
        # detect.pyでカウントした数を取り出す
        count = detect(detection_model,frame,count_class)

        # データを送信する
        send_mongo(count,collection)


if __name__ == "__main__": 
    main() 
