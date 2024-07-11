import os

from dotenv import load_dotenv
from ultralytics import YOLO

load_dotenv()
HOME_DIR = os.environ["HOME_DIR"]

model = YOLO("yolov8l.pt")
model.train(
    data=HOME_DIR + "/yolo_fine_tuning/yolo/dataset.yaml",
    epochs=5,
    batch=8,
    workers=4,
    degrees=90.0,
)
