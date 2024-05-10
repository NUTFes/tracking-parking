# 入力：カメラで得た画像
# 出力：検出台数

from sahi.predict import get_sliced_prediction

def detect(model,data,count_class):
    count = 0

    # 入力データから検出を行う
    print("detect start...")
    result = get_sliced_prediction(
    data,
    model,
    slice_height=256,
    slice_width=256,
    overlap_height_ratio=0.2,
    overlap_width_ratio=0.2,
    )

    print("detect finish")

    # 検出した結果を画像にする
    result.export_visuals(export_dir="result/")

    # 検出結果を辞書型のリストに変換
    detect_list = result.to_coco_predictions()
    
    # 指定のカテゴリをカウント
    for detect_object in detect_list:
        if detect_object["category_id"] == count_class:
            count += 1

    print(f'{count_class} is the number of {count}')

    return count



