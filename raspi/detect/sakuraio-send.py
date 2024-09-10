from dbcontrol import get_mongo
import cv2
from sahi import AutoDetectionModel
from sahi.utils.yolov8 import download_yolov8s_model
from send import send_mongo,connect_mongo
from detect import detect
import os
from dotenv import load_dotenv

load_dotenv()
USER = os.environ["USER_NAME"]
PASS = os.environ["PASS"]
HOST = os.environ["HOST"]
PORT = os.environ["PORT"]
DB_NAME = os.environ["DB_NAME"]
COLLECTION_NAME = os.environ["COLLECTION_NAME"]
# sakuraio-send.py
# sakura.ioのデータ送信テストプログラム
# (Raspberry Piでsakura.ioを接続して実行)
# 使い方:
# % python3でインタラクティブシェルを起動し、
# >>> が出てきたら1行ずつ入力してENTER
# もしくは
# % python3 sakuraio-send.py
#
# 参考:
# sakuraio.enqueue_tx(0, 1)の1を任意の値に変えると
# sakura.ioに送信される値が変わる


from sakuraio.hardware.rpi import SakuraIOSMBus
collection,_ = connect_mongo(USER,PASS,HOST,PORT,DB_NAME,COLLECTION_NAME)

sakuraio = SakuraIOSMBus()
parked_num = get_mongo(collection)
sakuraio.enqueue_tx(0, parked_num)
sakuraio.send()
