"""
ナンバープレート画像を生成するクラス

number_plate = NumberPlate()

img = number_plate.generate(category)

category: 分類
0:自家用普通車
1:事業用普通車
2:自家用軽自動車
3:事業用軽自動車
"""
import random
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
import os

load_dotenv()
HOME_DIR = os.environ['HOME_DIR']

class NumberPlate:
    def __init__(self):
        self.__fontFace_0 = HOME_DIR +"/raspberryPi/resorces/TrmFontJB.ttf"
        self.__fontFace_1 = HOME_DIR + "/raspberryPi/resorces/BIZ-UDGOTHICB.TTC"

        black = (0, 0, 0)
        green = (0, 60, 0)
        white = (240, 240, 240)
        yellow = (0, 240, 240)
        gray = (128, 128, 128)

        self.__height = 220
        self.__width = 440
        self.__margin = 4

        self.__back_color_list = [white, green, yellow, black]
        self.__text_color_list = [green, white, black, yellow]
        self.__gray_color = gray

    def __drawText(
        self, img, text, position, fontFace, fontScale, text_color, stroke_width
    ):
        (r, g, b) = text_color
        color = (b, g, r)
        # cv2 -> PIL
        imgPIL = Image.fromarray(cv2.cvtColor(img.copy(), cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(imgPIL)
        fontPIL = ImageFont.truetype(font=fontFace, size=fontScale)
        draw.text(
            xy=position, text=text, fill=color, font=fontPIL, stroke_width=stroke_width
        )
        # PIL -> cv2
        return cv2.cvtColor(np.array(imgPIL, dtype=np.uint8), cv2.COLOR_RGB2BGR)

    def __generate_place(self):
        list = [
            "札幌",
            "釧路",
            "山形",
            "水戸",
            "群馬",
            "長野",
            "大阪",
            "京都",
            "姫路",
            "多摩",
            "埼玉",
            "室蘭",
            "千葉",
            "釧路",
            "川崎",
        ]

        index = random.randint(0, len(list) - 1)

        return list[index]

    def __generate_classification(self):
        list = [
            "500",
            "300",
            "551",
            "512",
            "330",
            "331",
            "50",
            "30",
            "55",
            "51",
            "33",
            "31",
        ]
        index = random.randint(0, len(list) - 1)
        return list[index]

    def __generate_hiragana(self):
        list = ["あ", "き", "い", "を", "う", "く", "か"]
        index = random.randint(0, len(list) - 1)
        return list[index]

    def __generate_number(self):
        number = random.randint(1, 9999)
        isHead = True

        y = int(number / 1000)
        if isHead and y == 0:
            number_text = "・"
        else:
            isHead = False
            number_text = str(y)
        number -= y * 1000

        y = int(number / 100)
        if isHead and y == 0:
            number_text += "・"
        else:
            isHead = False
            number_text += str(y)
        number -= y * 100

        if isHead:
            number_text += " "
        else:
            if random.randint(0, 3) != 0:
                number_text += "-"
            else:
                number_text += " "

        y = int(number / 10)
        if isHead and y == 0:
            number_text += "・"
        else:
            number_text += str(y)

        number -= y * 10
        number_text += str(number)

        return number_text

    def generate(self, category):
        img = np.full((self.__height, self.__width, 3), 0, dtype=np.uint8)
        cv2.rectangle(
            img,
            (0, 0),
            (self.__width, self.__height),
            self.__back_color_list[category],
            thickness=-1,
        )
        cv2.rectangle(
            img,
            (0, 0),
            (self.__width - 2, self.__height - 2),
            self.__gray_color,
            thickness=1,
        )
        cv2.rectangle(
            img,
            (self.__margin, self.__margin),
            (self.__width - self.__margin * 2, self.__height - self.__margin * 2),
            self.__gray_color,
            thickness=1,
        )

        position = (100, 10)
        fontScale = 55
        stroke_width = 1
        img = self.__drawText(
            img,
            self.__generate_place(),
            position,
            self.__fontFace_1,
            fontScale,
            self.__text_color_list[category],
            stroke_width,
        )

        position = (230, 10)
        fontScale = 65
        stroke_width = 0
        img = self.__drawText(
            img,
            self.__generate_classification(),
            position,
            self.__fontFace_0,
            fontScale,
            self.__text_color_list[category],
            stroke_width,
        )
        position = (20, 80)
        fontScale = 150
        stroke_width = 0
        img = self.__drawText(
            img,
            self.__generate_hiragana(),
            position,
            self.__fontFace_0,
            fontScale,
            self.__text_color_list[category],
            stroke_width,
        )
        position = (80, 80)
        fontScale = 130
        stroke_width = 0
        img = self.__drawText(
            img,
            self.__generate_number(),
            position,
            self.__fontFace_0,
            fontScale,
            self.__text_color_list[category],
            stroke_width,
        )

        radius = 6
        position = (80, 30)
        img = cv2.circle(
            img, position, radius, self.__gray_color, thickness=-1, lineType=cv2.LINE_AA
        )
        position = (360, 30)
        img = cv2.circle(
            img, position, radius, self.__gray_color, thickness=-1, lineType=cv2.LINE_AA
        )
        return img