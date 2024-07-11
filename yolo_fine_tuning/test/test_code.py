import cv2
from ultralytics import YOLO

PATH = "/home/ichinose/workspace/tracking-parking/yolo_fine_tuning/runs/detect/train14/weights/best.pt"
TEST_FILE = "/home/ichinose/workspace/tracking-parking/yolo_fine_tuning/test/test_number_plate.jpg"

confidence = 0.8
imgsz = 1980
class_names = [
    "普通自動車（自家用）",
    "普通自動車（業務用）",
    "軽自動車（自家用）",
    "普通自動車（業務用）",
]


model = YOLO(PATH)

img = cv2.imread(TEST_FILE)

results = model.predict(TEST_FILE, conf=confidence, imgsz=imgsz)

print(results)
