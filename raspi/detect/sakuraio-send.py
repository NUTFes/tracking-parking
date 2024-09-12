from dbcontrol import get_mongo,connect_mongo
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
COLUMN_NAME = os.environ["COLUMN_NAME"]
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
collection,_ = connect_mongo(USER,PASS,HOST,PORT,DB_NAME,COLLECTION_NAME,COLUMN_NAME)

channel = 1
sakuraio = SakuraIOSMBus()
parked_num = get_mongo(collection)
field_value = parked_num.get(COLUMN_NAME)
sakuraio.enqueue_tx(channel, int(field_value))
sakuraio.send()