# 入力：カメラで得た画像
# 出力：検出台数

from IPython.display import Image
from sahi import AutoDetectionModel
from sahi.predict import get_prediction, get_sliced_prediction
from sahi.utils.cv import read_image
from sahi.utils.file import download_from_url
from sahi.utils.yolov8 import download_yolov8s_model

# Download YOLOv8 model
yolov8_model_path = "models/yolov8s.pt"
download_yolov8s_model(yolov8_model_path)

# Download test images
download_from_url(
    "https://raw.githubusercontent.com/obss/sahi/main/demo/demo_data/small-vehicles1.jpeg",
    "demo_data/small-vehicles1.jpeg",
)
download_from_url(
    "https://raw.githubusercontent.com/obss/sahi/main/demo/demo_data/terrain2.png",
    "demo_data/terrain2.png",
)

# 画像パスまたはnumpy画像を用いて標準的な推論を行う。
# YOLOv8 、このようにオブジェクト検出用のモデルをインスタンス化することができる：
detection_model = AutoDetectionModel.from_pretrained(
    model_type="yolov8",
    model_path=yolov8_model_path,
    confidence_threshold=0.3,
    device="cpu",  # or 'cuda:0'
)


# With an image path
result = get_prediction("demo_data/small-vehicles1.jpeg", detection_model)

# With a numpy image
result = get_prediction(read_image("demo_data/small-vehicles1.jpeg"), detection_model)

# 結果を可視化する
result.export_visuals(export_dir="demo_data/")
Image("demo_data/prediction_visual.png")

# スライス推論YOLOv8
result = get_sliced_prediction(
    "demo_data/small-vehicles1.jpeg",
    detection_model,
    slice_height=256,
    slice_width=256,
    overlap_height_ratio=0.2,
    overlap_width_ratio=0.2,
)


# 予測結果の取り扱い
# SAHIが提供するのは PredictionResult オブジェクトに変換することができる：

# Access the object prediction list
object_prediction_list = result.object_prediction_list
# print(object_prediction_list)
print(type(result.object_prediction_list))

# Convert to COCO annotation, COCO prediction, imantics, and fiftyone formats
result.to_coco_annotations()[:3]
result.to_coco_predictions(image_id=1)[:3]
result.to_imantics_annotations()[:3]
result.to_fiftyone_detections()[:3]

print()

# 画像のディレクトリを一括予測する：
# predict(
#     model_type="yolov8",
#     model_path="path/to/yolov8n.pt",
#     model_device="cpu",  # or 'cuda:0'
#     model_confidence_threshold=0.4,
#     source="/Users/ichinose/workspace/nutmeg/tracking-parking/raspi/demo_data/small-vehicles1.jpeg",
#     slice_height=256,
#     slice_width=256,
#     overlap_height_ratio=0.2,
#     overlap_width_ratio=0.2,
# )
