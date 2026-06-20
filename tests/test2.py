import cv2
import pytesseract

# Укажите путь, если Tesseract не добавлен в PATH
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# 1. Загрузка и очистка изображения
img = cv2.imread('0872_Progress.jpg')
b, g, r = cv2.split(img)
thresh = cv2.adaptiveThreshold(
    b, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 15
)

# 2. Получение данных в формате TSV (в виде строки)
# config='--psm 3' включает автоматический поиск блоков текста
tsv_data = pytesseract.image_to_data(thresh, lang='rus', config='--psm 3')

# 3. Сохранение данных в файл .tsv с правильной кодировкой для Excel
with open('result.tsv', 'w', encoding='utf-8') as f:
    f.write(tsv_data)

print("Готово! Данные сохранены в файл result.tsv. Теперь его можно открыть в Excel.")
