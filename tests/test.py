import pytesseract
from PIL import Image

# Укажите путь, если Tesseract не добавлен в PATH
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# Откройте изображение
img = Image.open('804.jpg')

# Настройки: режим PSM 6 (блок текста), OEM 1 (LSTM), белый список для цифр и точки
my_config = r'--oem 1 --psm 3 tsv'

# Распознайте текст (укажите нужный язык)
text = pytesseract.image_to_string(img, lang='rus', config=my_config)

# print(text)

with open('result4.txt', 'w', encoding='utf-8') as f:
    f.write(text)