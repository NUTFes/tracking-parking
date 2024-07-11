import glob
import os

import cv2
import ocr
from ultralytics import YOLO

confidence = 0.8
imgsz = 1280
class_names = [
    "普通自動車（自家用）",
    "普通自動車（業務用）",
    "軽自動車（自家用）",
    "普通自動車（業務用）",
]
color = [(0, 0, 255), (255, 0, 255), (255, 0, 0), (255, 255, 0)]
face = ["🐹", "🐰", "🐲", "🐻"]


def main():
    model = YOLO(
        "/home/ichinose/workspace/tracking-parking/yolo_fine_tuning/runs/detect/train14/weights/best.pt"
    )

    files = glob.glob(
        "/home/ichinose/workspace/tracking-parking/yolo_fine_tuning/test_number_data/test_number_plate.jpg"
    )
    for file in files:
        print(file)
        name = os.path.basename(file).split(".")[0]
        img = cv2.imread(file)

        results = model.predict(file, conf=confidence, imgsz=imgsz)

        for result in results:
            boxes = result.boxes.cpu().numpy()
            ids = result.boxes.cls.cpu().numpy().astype(int)
            confs = result.boxes.conf.cpu().numpy()

            if len(boxes) > 0:
                box = boxes[0]
                cls_id = ids[0]
                conf = confs[0]

                # ナンバープレート画像（OCRでの読み取りに使用する）
                r = box.xyxy[0].astype(int)
                number_plate_image = img[r[1] : r[3], r[0] : r[2]]
                verify_image = ocr.detect(
                    name, number_plate_image, cls_id, class_names[cls_id], conf
                )

                img = cv2.rectangle(img, (r[0], r[1]), (r[2], r[3]), color[cls_id], 7)
                print(
                    "\n{} {} conf:{:.2f}  ({},{}), ({},{})".format(
                        face[cls_id], class_names[cls_id], conf, r[0], r[1], r[2], r[3]
                    )
                )

        # 画像の表示
        img = cv2.resize(img, None, fx=0.5, fy=0.5)
        cv2.imshow("image", img)

        cv2.imshow("verify", verify_image)
        cv2.waitKey(1)

        # キー入力待機
        input("Please enter key. ")


if __name__ == "__main__":
    main()
