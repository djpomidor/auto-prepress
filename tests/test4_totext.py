import cv2
import pytesseract

# Укажите путь, если Tesseract не добавлен в PATH
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# 1. Загрузка изображения
img = cv2.imread('spec/804.jpg')

# 2. Удаление синих рукописных чернил (используем синий канал)
# b, g, r = cv2.split(img)
# gray = b 

# 3. Увеличение контраста и бинаризация (сделай бумагу белой, а текст черным)
# thresh = cv2.adaptiveThreshold(
#     gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 15
# )

# 4. Распознавание очищенного изображения
my_config = r'-l rus --psm 3'
text = pytesseract.image_to_string(img, config=my_config)

# 5. Сохранение распознанного текста в файл
with open('result2.txt', 'w', encoding='utf-8') as f:
    f.write(text)

# (Опционально) Сохранить очищенный файл для проверки глазами
cv2.imwrite('cleaned_document.png', img)

print("Готово! Текст успешно сохранен в файл result.txt")
