import json
import os
import shutil

from dotenv import load_dotenv

load_dotenv()
HOME_DIR = os.environ["HOME_DIR"]

# 定義
inputPath = HOME_DIR + "/yolo_fine_tuning/resorces/dataset/output_ground_truth"
# outputPath = "./dataset/yolo"
outputPath = HOME_DIR + "/yolo_fine_tuning/yolo"
manifest = "output.manifest"
# 学習用と検証用の分割比率
ratio = 0.8  # 8対2に分割する


# 1件のJデータを表現するクラス
class Data:
    def __init__(self, src):
        # プロジェクト名の取得
        for key in src.keys():
            index = key.rfind("-metadata")
            if index != -1:
                projectName = key[0:index]

        # メタデータの取得
        metadata = src[projectName + "-metadata"]
        class_map = metadata["class-map"]

        # 画像名の取得
        self.imgFileName = os.path.basename(src["source-ref"])
        self.baseName = self.imgFileName.split(".")[0]
        # 画像サイズの取得
        project = src[projectName]
        image_size = project["image_size"]
        self.img_width = image_size[0]["width"]
        self.img_height = image_size[0]["height"]

        self.annotations = []
        # アノテーションの取得
        for annotation in project["annotations"]:
            class_id = annotation["class_id"]
            top = annotation["top"]
            left = annotation["left"]
            width = annotation["width"]
            height = annotation["height"]

            self.annotations.append(
                {
                    "label": class_map[str(class_id)],
                    "width": width,
                    "top": top,
                    "height": height,
                    "left": left,
                }
            )

    # 指定されたラベルを含むかどうか
    def exsists(self, label):
        for annotation in self.annotations:
            if annotation["label"] == label:
                return True
        return False

    def store(self, imagePath, labelPath, inputPath, labels):
        cls_list = []
        for label in labels:
            cls_list.append(label[0])

        text = ""
        for annotation in self.annotations:
            cls_id = cls_list.index(annotation["label"])
            top = annotation["top"]
            left = annotation["left"]
            width = annotation["width"]
            height = annotation["height"]

            yolo_x = (left + width / 2) / self.img_width
            yolo_y = (top + height / 2) / self.img_height
            yolo_w = width / self.img_width
            yolo_h = height / self.img_height

            text += "{} {:.6f} {:.6f} {:.6f} {:.6f}\n".format(
                cls_id, yolo_x, yolo_y, yolo_w, yolo_h
            )
        # txtの保存
        with open("{}/{}.txt".format(labelPath, self.baseName), mode="w") as f:
            f.write(text)
        # 画像のコピー
        shutil.copyfile(
            "{}/{}".format(inputPath, self.imgFileName),
            "{}/{}".format(imagePath, self.imgFileName),
        )


# dataListをラベルを含むものと、含まないものに分割する
def deviedDataList(dataList, label):
    targetList = []
    unTargetList = []
    for data in dataList:
        if data.exsists(label):
            targetList.append(data)
        else:
            unTargetList.append(data)
    return (targetList, unTargetList)


# ラベルの件数の少ない順に並べ替える(配列のインデックスが、クラスIDとなる)
def getLabel(dataList):
    labels = {}
    for data in dataList:
        for annotation in data.annotations:
            label = annotation["label"]
            if label in labels:
                labels[label] += 1
            else:
                labels[label] = 1
    # ラベルの件数の少ない順に並べ替える(配列のインデックスが、クラスIDとなる)
    labels = sorted(labels.items(), key=lambda x: x[1])
    return labels


# 全てのJSONデータを読み込む
def getDataList(inputPath, manifest):
    dataList = []
    with open("{}/{}".format(inputPath, manifest), "r") as f:
        srcList = f.read().split("\n")
        for src in srcList:
            if src != "":
                json_src = json.loads(src)
                dataList.append(Data(json.loads(src)))
    return dataList


def main():
    # 出力先フォルダ生成
    train_images = "{}/train/images".format(outputPath)
    validation_images = "{}/valid/images".format(outputPath)
    train_labels = "{}/train/labels".format(outputPath)
    validation_labels = "{}/valid/labels".format(outputPath)

    os.makedirs(outputPath, exist_ok=True)
    os.makedirs(train_images, exist_ok=True)
    os.makedirs(validation_images, exist_ok=True)
    os.makedirs(train_labels, exist_ok=True)
    os.makedirs(validation_labels, exist_ok=True)

    # 全てのJSONデータを読み込む
    dataList = getDataList(inputPath, manifest)
    log = "全データ: {}件 ".format(len(dataList))

    # ラベルの件数の少ない順に並べ替える(配列のインデックスが、クラスIDとなる)
    labels = getLabel(dataList)
    for i, label in enumerate(labels):
        log += "[{}]{}: {}件 ".format(i, label[0], label[1])
    print(log)

    # 保存済みリスト
    storedList = []
    log = ""
    # ラベルの数の少ないものから優先して分割する
    for i, label in enumerate(labels):
        log = ""
        log += "{} => ".format(label[0])
        # dataListをラベルが含まれるものと、含まないものに分割する
        (targetList, unTargetList) = deviedDataList(dataList, label[0])
        # 保存済みリストから、当該ラベルで既に保存済の件数をカウントする
        (include, notInclude) = deviedDataList(storedList, label[0])
        storedCounst = len(include)
        # train用に必要な件数
        # count = int(label[1] * ratio) - storedCounst
        count = int((len(dataList) * ratio))
        log += "{}:".format(count)
        # train側への保存
        for i in range(count):
            data = targetList.pop()
            data.store(train_images, train_labels, inputPath, labels)
            storedList.append(data)
        # validation側への保存
        log += "{} ".format(len(targetList))
        for data in targetList:
            data.store(validation_images, validation_labels, inputPath, labels)
            storedList.append(data)

        dataList = unTargetList
        log += "残り:{}件".format(len(dataList))
        print(log)


main()
