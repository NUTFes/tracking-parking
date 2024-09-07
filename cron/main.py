import os

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

# -----------sakuraからデータを取得------------
# TODO: あとで、send.pyの位置を変えて、importする

# URLを指定
load_dotenv()
token = os.environ["TOKEN"]
module = os.environ["MODULE"]
channel = os.environ["CHANNEL"]
url = f"https://api.sakura.io/datastore/v2/channels?token={token}&module={module}&channel={channel}"
print(url)

# GETリクエストを送信
response = requests.get(url)

# ステータスコードが200 (OK) の場合のみ処理を続ける
if response.status_code == 200:
    # JSONデータに変換
    data = response.json()
    # sakuraのデータの中のresults内のデータを抽出
    results = data["results"]
    # 最新のデータ
    recentData = results[-1]
else:
    print(f"Failed to fetch data. Status code: {response.status_code}")
# --------------------------------------------


# -----------mongoDBへデータを送信--------------
def connect_mongo(user, password, host, port, db_name, collection_name):
    client = MongoClient(f"mongodb://{user}:{password}@{host}:{port}")
    db = client[db_name]
    collection = db[collection_name]
    return collection, client


def make_doc(num):
    num_int = f"{num}"
    document = {"number": int(num_int)}
    return document


def send_mongo(num, mongo_col):
    print("send mongo")
    doc = make_doc(num)
    mongo_col.insert_one(doc)
    print("send finish")
    # mongo_cl.close()
    return


# print(get_time())

if __name__ == "__main__":
    USER = os.environ["USER_NAME"]
    PASS = os.environ["PASS"]
    HOST = os.environ["HOST"]
    PORT = os.environ["PORT"]
    DB_NAME = os.environ["DB_NAME"]
    COLLECTION_NAME = os.environ["COLLECTION_NAME"]
    collection, client = connect_mongo(USER, PASS, HOST, PORT, DB_NAME, COLLECTION_NAME)
    send_mongo(recentData["value"], collection)
    print(collection)
# --------------------------------------------
