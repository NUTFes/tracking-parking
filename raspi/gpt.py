import cv2
from sahi import AutoDetectionModel
from sahi.predict import get_prediction
from sahi.utils.yolov8 import download_yolov8s_model

# Download YOLOv8 model
yolov8_model_path = "models/yolov8s.pt"
download_yolov8s_model(yolov8_model_path)

# YOLOv8 、このようにオブジェクト検出用のモデルをインスタンス化することができる：
detection_model = AutoDetectionModel.from_pretrained(
    model_type="yolov8",
    model_path=yolov8_model_path,
    confidence_threshold=0.3,
    device="cpu",  # or 'cuda:0'
)

# カメラデバイスを開く
cap = cv2.VideoCapture(0)  # 通常、0はデフォルトのカメラを指します

try:
    while True:
        # カメラから画像を読み込む
        ret, frame = cap.read()
        print(ret)
        if not ret:
            break

        # SAHIを使用して物体検出を行う
        result = get_prediction(frame, detection_model)

        # 結果を可視化し、表示する
        result.export_visuals(export_dir="demo_data/")
        cv2.imshow(
            "YOLOv8 Object Detection", cv2.imread("demo_data/prediction_visual.png")
        )
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
finally:
    cap.release()
    cv2.destroyAllWindows()
