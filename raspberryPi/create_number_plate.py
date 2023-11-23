from number_plate import NumberPlate

category=0 # 0:普通車（自家用） 1:普通車（事業用） 2:軽自動車（自家用） 3:軽自動車（事業用）

number_plate = NumberPlate()
img = number_plate.generate(category)