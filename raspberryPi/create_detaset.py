"""
ナンバープレートを生成しアフィン変換して背景と合成することでGround Truth形式のデータセットを作成する
"""
import json
import glob
import random
import os
import shutil
import math
import numpy as np
import cv2
from PIL import Image
from number_plate import NumberPlate

from dotenv import load_dotenv

MAX = 30000  # 生成する画像数

load_dotenv()
HOME_DIR = os.environ['HOME_DIR']

CLASS_NAME = [
    "PRIVATE_STANDARD",
    "BUS_STANDAR",
    "PRIVATE_LIGHT_VEHICLE",
    "BUS_LIGHT_VEHICLE",
]

COLORS = [(0, 0, 175), (175, 0, 0), (0, 175, 0), (175, 0, 175)]

BACKGROUND_IMAGE_PATH = HOME_DIR + "/raspberryPi/resorces/dataset/background_images"
TARGET_IMAGE_PATH = HOME_DIR + "/raspberryPi/resorces/dataset/output_png"
OUTPUT_PATH = HOME_DIR + "/raspberryPi/resorces/dataset/output_ground_truth"

S3Bucket = "s3://ground_truth_dataset"
manifestFile = "output.manifest"


BASE_WIDTH = 440  # ナンバープレートの基本サイズは、背景画像とのバランスより、横幅を440を基準とする
BACK_WIDTH = 1280  # 背景画像ファイルのサイズを合わせる必要がある
BACK_HEIGHT = 960  # 背景画像ファイルのサイズを合わせる必要がある


# 背景画像取得クラス
class Background:
    def __init__(self, backPath):
        self.__backPath = backPath

    def get(self):
        print(glob.glob(self.__backPath + "/*.png"))
        imagePath = random.choice(glob.glob(self.__backPath + "/*.png"))
        return cv2.imread(imagePath, cv2.IMREAD_UNCHANGED)


# 検出対象取得クラス (base_widthで指定された横幅を基準にリサイズされる)
class Target:
    def __init__(self, target_path, base_width, class_name):
        self.__target_path = target_path
        self.__base_width = base_width
        self.__class_name = class_name
        self.__number_plate = NumberPlate()

    def get(self, class_id):
        # 対象画像
        class_name = self.__class_name[class_id]
        target_image = number_plate = self.__number_plate.generate(class_id)

        # 透過PNGへの変換
        # Point 1: 白色部分に対応するマスク画像を生成
        mask = np.all(target_image[:, :, :] == [255, 255, 255], axis=-1)
        # Point 2: 元画像をBGR形式からBGRA形式に変換
        target_image = cv2.cvtColor(target_image, cv2.COLOR_BGR2BGRA)
        # Point3: マスク画像をもとに、白色部分を透明化
        target_image[mask, 3] = 0

        # 基準（横）サイズに基づきリサイズ
        h, w, _ = target_image.shape
        aspect = h / w
        target_image = cv2.resize(
            target_image, (int(self.__base_width * aspect), self.__base_width)
        )

        return target_image


# 変換クラス
class Transformer:
    def __init__(self, width, height):
        self.__width = width
        self.__height = height
        self.__min_scale = 0.1
        self.__max_scale = 1

    # distonation UP:0,DOWN;1,LEFT:2,RIGHT:3
    # ratio: UP/DOWN 0 〜 0.1
    # ratio: LEFT/RIGHT 0 〜 0.3
    def __affine(self, target_image, ratio, distnatoin):
        # アフィン変換（上下、左右から見た傾き）
        h, w, _ = target_image.shape
        if distnatoin == 0:
            distortion_w = int(ratio * w)
            x1 = 0
            x2 = 0 - distortion_w
            x3 = w
            x4 = w - distortion_w
            y1 = h
            y2 = 0
            y3 = 0
            y4 = h
            # 変換後のイメージのサイズ
            ww = w + distortion_w
            hh = h
        elif distnatoin == 1:
            distortion_w = int(ratio * w)
            x1 = 0 - distortion_w
            x2 = 0
            x3 = w - distortion_w
            x4 = w
            y1 = h
            y2 = 0
            y3 = 0
            y4 = h
            # 変換後のイメージのサイズ
            ww = w + distortion_w
            hh = h
        elif distnatoin == 2:
            distortion_h = int(ratio * h)
            x1 = 0
            x2 = 0
            x3 = w
            x4 = w
            y1 = h
            y2 = 0 - int(distortion_h * 0.6)
            y3 = 0
            y4 = h - distortion_h
            # 変換後のイメージのサイズ
            ww = w
            hh = h + int(distortion_h * 1.3)
        elif distnatoin == 3:
            distortion_h = int(ratio * h)
            x1 = 0
            x2 = 0
            x3 = w
            x4 = w
            y1 = h - int(distortion_h * 0.6)
            y2 = 0
            y3 = 0 - distortion_h
            y4 = h
            # 変換後のイメージのサイズ
            ww = w
            hh = h + int(distortion_h * 1.3)

        pts2 = [(x2, y2), (x1, y1), (x4, y4), (x3, y3)]
        w2 = max(pts2, key=lambda x: x[0])[0]
        h2 = max(pts2, key=lambda x: x[1])[1]
        h, w, _ = target_image.shape
        pts1 = np.float32([(0, 0), (0, h), (w, h), (w, 0)])
        pts2 = np.float32(pts2)

        M = cv2.getPerspectiveTransform(pts2, pts1)
        target_image = cv2.warpPerspective(
            target_image, M, (w2 + 100, h2 + 100), borderValue=(255, 255, 255)
        )
        return (target_image, ww, hh)

    def warp(self, target_image):
        # サイズ変更
        target_image = self.__resize(target_image)

        # アフィン変換
        # distonation UP:0,DOWN;1,LEFT:2,RIGHT:3
        # ratio: UP/DOWN max:0.1
        # ratio: LEFT/RIGHT max:0.3
        ratio = random.uniform(0, 0.1)
        distonation = random.randint(0, 3)
        if distonation == 2 or distonation == 3:
            ratio = random.uniform(0, 0.3)
        (target_image, w, h) = self.__affine(target_image, ratio, distonation)

        # 配置位置決定
        left = random.randint(0, self.__width - w)
        top = random.randint(0, self.__height - h)
        rect = ((left, top), (left + w, top + h))

        # 背景面との合成
        new_image = self.__synthesize(target_image, left, top)
        return (new_image, rect)

    def __resize(self, img):
        scale = random.uniform(self.__min_scale, self.__max_scale)
        w, h, _ = img.shape
        return cv2.resize(img, (int(w * scale), int(h * scale)))

    def __rote(self, target_image, angle):
        h, w, _ = target_image.shape
        rate = h / w
        scale = 1
        if rate < 0.9 or 1.1 < rate:
            scale = 0.9
        elif rate < 0.8 or 1.2 < rate:
            scale = 0.6
        center = (int(w / 2), int(h / 2))
        trans = cv2.getRotationMatrix2D(center, angle, scale)
        return cv2.warpAffine(target_image, trans, (w, h))

    def __synthesize(self, target_image, left, top):
        background_image = np.zeros((self.__height, self.__width, 4), np.uint8)
        back_pil = Image.fromarray(background_image)
        front_pil = Image.fromarray(target_image)
        back_pil.paste(front_pil, (left, top), front_pil)
        return np.array(back_pil)


class Effecter:
    # Gauss
    def gauss(self, img, level):
        return cv2.blur(img, (level * 2 + 1, level * 2 + 1))

    # Noise
    def noise(self, img):
        img = img.astype("float64")
        img[:, :, 0] = self.__single_channel_noise(img[:, :, 0])
        img[:, :, 1] = self.__single_channel_noise(img[:, :, 1])
        img[:, :, 2] = self.__single_channel_noise(img[:, :, 2])
        return img.astype("uint8")

    def __single_channel_noise(self, single):
        diff = 255 - single.max()
        noise = np.random.normal(0, random.randint(1, 100), single.shape)
        noise = (noise - noise.min()) / (noise.max() - noise.min())
        noise = diff * noise
        noise = noise.astype(np.uint8)
        dst = single + noise
        return dst


# バウンディングボックス描画
def box(frame, rect, class_id):
    ((x1, y1), (x2, y2)) = rect
    label = "{}".format(CLASS_NAME[class_id])
    img = cv2.rectangle(frame, (x1, y1), (x2, y2), COLORS[class_id], 2)
    img = cv2.rectangle(img, (x1, y1), (x1 + 150, y1 - 20), COLORS[class_id], -1)
    cv2.putText(
        img,
        label,
        (x1 + 2, y1 - 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return img


# 背景と商品の合成
def marge_image(background_image, front_image):
    back_pil = Image.fromarray(background_image)
    front_pil = Image.fromarray(front_image)
    back_pil.paste(front_pil, (0, 0), front_pil)
    return np.array(back_pil)


# Manifest生成クラス
class Manifest:
    def __init__(self, class_name):
        self.__lines = ""
        self.__class_map = {}
        for i in range(len(class_name)):
            self.__class_map[str(i)] = class_name[i]

    def appned(self, fileName, data, height, width):
        date = "0000-00-00T00:00:00.000000"
        line = {
            "source-ref": "{}/{}".format(S3Bucket, fileName),
            "boxlabel": {
                "image_size": [{"width": width, "height": height, "depth": 3}],
                "annotations": [],
            },
            "boxlabel-metadata": {
                "job-name": "xxxxxxx",
                "class-map": self.__class_map,
                "human-annotated": "yes",
                "objects": {"confidence": 1},
                "creation-date": date,
                "type": "groundtruth/object-detection",
            },
        }
        for i in range(data.max()):
            (_, rect, class_id) = data.get(i)
            ((x1, y1), (x2, y2)) = rect
            line["boxlabel"]["annotations"].append(
                {
                    "class_id": class_id,
                    "width": x2 - x1,
                    "top": y1,
                    "height": y2 - y1,
                    "left": x1,
                }
            )
        self.__lines += json.dumps(line) + "\n"

    def get(self):
        return self.__lines


# 1画像分のデータを保持するクラス
class Data:
    def __init__(self, rate):
        self.__rects = []
        self.__images = []
        self.__class_ids = []
        self.__rate = rate

    def get_class_ids(self):
        return self.__class_ids

    def max(self):
        return len(self.__rects)

    def get(self, i):
        return (self.__images[i], self.__rects[i], self.__class_ids[i])

    # 追加（重複率が指定値以上の場合は失敗する）
    def append(self, target_image, rect, class_id):
        conflict = False
        for i in range(len(self.__rects)):
            iou = self.__multiplicity(self.__rects[i], rect)
            if iou > self.__rate:
                conflict = True
                break
        if conflict == False:
            self.__rects.append(rect)
            self.__images.append(target_image)
            self.__class_ids.append(class_id)
            return True
        return False

    # 重複率
    def __multiplicity(self, a, b):
        (ax_mn, ay_mn) = a[0]
        (ax_mx, ay_mx) = a[1]
        (bx_mn, by_mn) = b[0]
        (bx_mx, by_mx) = b[1]
        a_area = (ax_mx - ax_mn + 1) * (ay_mx - ay_mn + 1)
        b_area = (bx_mx - bx_mn + 1) * (by_mx - by_mn + 1)
        abx_mn = max(ax_mn, bx_mn)
        aby_mn = max(ay_mn, by_mn)
        abx_mx = min(ax_mx, bx_mx)
        aby_mx = min(ay_mx, by_mx)
        w = max(0, abx_mx - abx_mn + 1)
        h = max(0, aby_mx - aby_mn + 1)
        intersect = w * h
        return intersect / (a_area + b_area - intersect)


# 各クラスのデータ数が同一になるようにカウントする
class Counter:
    def __init__(self, max):
        self.__counter = np.zeros(max)

    def get(self):
        n = np.argmin(self.__counter)
        return int(n)

    def inc(self, index):
        self.__counter[index] += 1

    def print(self):
        print(self.__counter)


def main():
    # 出力先の初期化
    if os.path.exists(OUTPUT_PATH):
        shutil.rmtree(OUTPUT_PATH)
    os.mkdir(OUTPUT_PATH)

    target = Target(TARGET_IMAGE_PATH, BASE_WIDTH, CLASS_NAME)
    background = Background(BACKGROUND_IMAGE_PATH)

    transformer = Transformer(BACK_WIDTH, BACK_HEIGHT)
    manifest = Manifest(CLASS_NAME)
    counter = Counter(len(CLASS_NAME))
    effecter = Effecter()

    no = 0

    while True:
        # 背景画像の取得
        background_image = background.get()

        # 商品データ

        # 重なり率（これを超える場合は、配置されない）
        # rate = 0.1
        rate = 0  # ナンバープレートの重なりは、対象画となるため、重なりを排除する
        data = Data(rate)
        # for _ in range(20):
        for _ in range(10):
            # 現時点で作成数の少ないクラスIDを取得
            class_id = counter.get()
            # 商品画像の取得
            target_image = target.get(class_id)
            # 変換
            (transform_image, rect) = transformer.warp(target_image)
            frame = marge_image(background_image, transform_image)
            # 商品の追加（重複した場合は、失敗する）
            ret = data.append(transform_image, rect, class_id)
            if ret:
                counter.inc(class_id)

        print("max:{}".format(data.max()))
        frame = background_image
        for index in range(data.max()):
            (target_image, _, _) = data.get(index)
            # 合成
            frame = marge_image(frame, target_image)

        # アルファチャンネル削除
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

        # エフェクト
        frame = effecter.gauss(frame, random.randint(0, 2))
        frame = effecter.noise(frame)

        # 画像名
        fileName = "{:05d}.png".format(no)
        no += 1

        # 画像保存
        cv2.imwrite("{}/{}".format(OUTPUT_PATH, fileName), frame)
        # manifest追加
        manifest.appned(fileName, data, frame.shape[0], frame.shape[1])

        for i in range(data.max()):
            (_, rect, class_id) = data.get(i)
            # バウンディングボックス描画（確認用）
            frame = box(frame, rect, class_id)

        counter.print()
        print("no:{}".format(no))
        if MAX <= no:
            break

        # 表示（確認用）
        cv2.imshow("frame", frame)
        cv2.waitKey(1)

    # manifest 保存
    with open("{}/{}".format(OUTPUT_PATH, manifestFile), "w") as f:
        f.write(manifest.get())


main()