import cv2
from ultralytics import YOLO

# パス設定
PATH = "/home/ichinose/workspace/tracking-parking/yolo_fine_tuning/runs/detect/train14/weights/best.pt"
TEST_FILE = (
    "/home/ichinose/workspace/tracking-parking/yolo_fine_tuning/test/test_img_1.jpg"
)

# 設定
confidence = 0.8
imgsz = 1280
class_names = [
    "普通自動車（自家用）",
    "普通自動車（業務用）",
    "軽自動車（自家用）",
    "普通自動車（業務用）",
]

# モデル読み込み
model = YOLO(PATH)

# 画像読み込み
img = cv2.imread(TEST_FILE)

# 物体検出
results = model.predict(TEST_FILE, conf=confidence, imgsz=imgsz)

# 検出された物体の情報を取得
detected_objects = []
plate_count = 0  # ナンバープレート画像のカウント

for result in results:
    for box in result.boxes:
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        conf = box.conf[0].item()
        class_id = int(box.cls[0].item())
        label = f"{class_names[class_id]}: {conf:.2f}"

        # 検出された物体の情報をリストに追加
        detected_objects.append(
            {
                "label": class_names[class_id],
                "confidence": conf,
                "box": [x1, y1, x2, y2],
            }
        )

        # バウンディングボックス描画
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
        # ラベル描画
        cv2.putText(
            img, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2
        )

        # ナンバープレート部分を切り取って保存
        plate_img = img[y1:y2, x1:x2]
        plate_filename = f"plate_{plate_count}.jpg"
        cv2.imwrite(plate_filename, plate_img)
        plate_count += 1

# 検出された物体の情報を表示
for obj in detected_objects:
    print(
        f"Label: {obj['label']}, Confidence: {obj['confidence']:.2f}, Box: {obj['box']}"
    )

# 画像表示
cv2.imshow("Detected Image", img)
cv2.waitKey(0)
cv2.destroyAllWindows()
