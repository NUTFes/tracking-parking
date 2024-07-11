import codecs
import json
import os
import time

import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont


def readApi(im_file_name):
    with open(im_file_name, "rb") as f:
        data = f.read()

    subscription_key = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    endpoint = "https://japaneast.api.cognitive.microsoft.com/"
    model_version = "2022-04-30"
    # model_version = "2022-01-30-preview"
    # model_version = "2021-04-12"
    language = "ja"

    text_recognition_url = endpoint + "vision/v3.2/read/analyze"
    headers = {
        "Ocp-Apim-Subscription-Key": subscription_key,
        "Content-Type": "application/octet-stream",
    }
    params = {"language ": language, "model-version": model_version}

    response = requests.post(
        text_recognition_url, headers=headers, params=params, json=None, data=data
    )
    response.raise_for_status()

    operation_url = response.headers["Operation-Location"]
    analysis = {}
    poll = True

    while poll:
        response_final = requests.get(
            response.headers["Operation-Location"], headers=headers
        )
        analysis = response_final.json()

        print(json.dumps(analysis, indent=4, ensure_ascii=False))

        time.sleep(1)
        if "analyzeResult" in analysis:
            poll = False
        if "status" in analysis and analysis["status"] == "failed":
            poll = False
    return analysis


def putText(img, text, point, size, color):
    fontFace = "gosic.ttc"
    stroke_width = 1

    # cv2 -> PIL
    imgPIL = Image.fromarray(cv2.cvtColor(img.copy(), cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(imgPIL)
    fontPIL = ImageFont.truetype(font=fontFace, size=size)
    draw.text(xy=point, text=text, fill=color, font=fontPIL, stroke_width=stroke_width)
    # PIL -> cv2
    return cv2.cvtColor(np.array(imgPIL, dtype=np.uint8), cv2.COLOR_RGB2BGR)


def convert_to_gray(image):
    image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)


def detect(name, image, cls_id, class_name, conf):
    work_dir = "./ocr"
    if not os.path.exists(work_dir):
        os.mkdir(work_dir)

    # 定形のサイズに変換する
    img_all = cv2.resize(image, (440, 220))
    # 業務車の場合は反転する
    if cls_id == 1 or cls_id == 3:
        img_all = cv2.bitwise_not(img_all)
    # グレースケール
    img_all = convert_to_gray(img_all)

    # 部分切り取り
    img_parts = []
    text_parts = ["", "", ""]
    # 上段
    img_parts.append(img_all[0:100, 0:440])
    # ひらがな
    img_parts.append(img_all[100:200, 20:100])
    # 4桁の数字
    img_parts.append(img_all[80:220, 80:440])

    text = ""

    for index in range(len(img_parts)):
        im_file_name = "{}/number_{}_{}.png".format(work_dir, name, index)
        json_file_name = "{}/analysis_{}_{}.json".format(work_dir, name, index)

        if not os.path.isfile(json_file_name):
            # 画像保存
            cv2.imwrite(im_file_name, img_parts[index])
            analysis = readApi(im_file_name)
            with codecs.open(json_file_name, "w+", "utf-8") as fp:
                json.dump(analysis, fp, ensure_ascii=False, indent=2)

        else:
            with open(json_file_name) as f:
                analysis = json.load(f)

        if "analyzeResult" in analysis:
            analyzeResult = analysis["analyzeResult"]

            if "readResults" in analyzeResult:
                readResults = analyzeResult["readResults"]
                readResult = readResults[0]
                if "lines" in readResult:
                    lines = readResult["lines"]
                    for line in lines:
                        x1, y1, _, _, x3, y3, _, _ = line["boundingBox"]
                        img_parts[index] = cv2.rectangle(
                            img_parts[index],
                            (x1, y1),
                            (x3, y3),
                            (0, 0, 255),
                            2,
                            cv2.LINE_4,
                        )
                        # ゴミの排除
                        text = (
                            line["text"]
                            .replace("*", "")
                            .replace("°", "")
                            .replace("-", "")
                        )
                        text_parts[index] = text.replace("*", "")

            # text = text.replace("*", "")

    # 白バックの画像生成
    verify_image = np.zeros((700, 500, 3), dtype=np.uint8) + 255
    h, w = image.shape[:2]

    # 元イメージ
    margin_x = 10
    margin_y = 50
    verify_image[margin_y : h + margin_y, margin_x : w + margin_x, :] = image

    margin_y = 230

    for img in img_parts:
        h2, w2 = img.shape[:2]
        verify_image[margin_y : h2 + margin_y, margin_x : w2 + margin_x, :] = img
        margin_y += h2 + 10

    margin_y = 600
    verify_image = putText(
        verify_image,
        "confidence: {:.2f}".format(conf),
        (margin_x, margin_y),
        15,
        (0, 0, 0),
    )

    margin_y += 25
    verify_image = putText(
        verify_image, class_name, (margin_x, margin_y), 15, (0, 0, 0)
    )
    margin_y += 30
    verify_image = putText(
        verify_image, text_parts[0], (margin_x, margin_y), 25, (0, 0, 0)
    )
    margin_x += 110
    verify_image = putText(
        verify_image, text_parts[1], (margin_x, margin_y), 25, (0, 0, 0)
    )
    margin_x += 50
    verify_image = putText(
        verify_image, text_parts[2], (margin_x, margin_y), 25, (0, 0, 0)
    )

    return verify_image
