# 検出数と時刻を送信
from pymongo import MongoClient
import time
import os
from dotenv import load_dotenv

def connect_mongo(user,password,host,port,db_name,collection_name):
    client = MongoClient(f"mongodb://{user}:{password}@{host}:{port}")
    db = client[db_name]
    collection = db[collection_name]
    return collection,client

def get_time():
    ut = time.time() * 1000
    return ut

def make_doc(num,time):
    num_int = f"{num}"
    document = {"count": int(num_int), "time": time }
    return document

def send_mongo(num,mongo_col):
    print("send mongo")
    ut = get_time()
    doc = make_doc(num,ut)
    mongo_col.insert_one(doc)
    print("send finish")
    #mongo_cl.close()
    return

# print(get_time())

if __name__ == "__main__": 
    load_dotenv()
    USER = os.environ["USER_NAME"]
    PASS = os.environ["PASS"]
    HOST = os.environ["HOST"]
    PORT = os.environ["PORT"]
    DB_NAME = os.environ["DB_NAME"]
    COLLECTION_NAME = os.environ["COLLECTION_NAME"]
    collection,client = connect_mongo(USER,PASS,HOST,PORT,DB_NAME,COLLECTION_NAME)
    send_mongo("20")
    print(collection)

