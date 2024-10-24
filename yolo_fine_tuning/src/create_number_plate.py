import os

import cv2
from dotenv import load_dotenv
from yolo_fine_tuning.src.number_plate import NumberPlate

load_dotenv()
HOME_DIR = os.environ["HOME_DIR"]

category = (
    0  # 0:普通車（自家用） 1:普通車（事業用） 2:軽自動車（自家用） 3:軽自動車（事業用）
)

number_plate = NumberPlate()
img = number_plate.generate(category)
print(img)

# imgに画像のデータがはいっているから、これを保存すると画像になる
# 実行するとtest.pngが生成されるからやってみて
# cv2.imwrite('./test.jpg', img)

for i in range(3):
    category = i
    for j in range(10000):
        img = number_plate.generate(category)
        # print(HOME_DIR +'/yolo_fine_tuning/resorces/create_nuber_plates/img{i}.{j}.jpg')
        cv2.imwrite(
            HOME_DIR
            + "/yolo_fine_tuning/resorces/create_nuber_plates/img"
            + str(i)
            + "_"
            + str(j)
            + ".jpg",
            img,
        )
