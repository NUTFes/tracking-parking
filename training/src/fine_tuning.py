import matplotlib

matplotlib.use("Agg")  # GUIなしでグラフを処理するバックエンドを使用


import os

from dotenv import load_dotenv
from ultralytics import YOLO

load_dotenv()
HOME_DIR = os.environ["HOME_DIR"]

model = YOLO("yolov8m.pt")
model.train(
    data=HOME_DIR + "/yolo_fine_tuning/yolo/dataset.yaml",
    epochs=5,
    batch=8,
    workers=4,
    degrees=90.0,
    # imgsz=1920,  # 最大の幅を指定
    # rect=True,  # 縦横比を保持
)

# 現在：カラー画像、m、単一背景、画像サイズはyoloの都合の良い形に
