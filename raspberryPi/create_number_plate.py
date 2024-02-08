from number_plate import NumberPlate
import cv2

category=0 # 0:普通車（自家用） 1:普通車（事業用） 2:軽自動車（自家用） 3:軽自動車（事業用）

number_plate = NumberPlate()
img = number_plate.generate(category)
print(img)

# imgに画像のデータがはいっているから、これを保存すると画像になる
# 実行するとtest.pngが生成されるからやってみて
cv2.imwrite('./test.jpg', img)
