import cv2
import pytesseract

# Укажите путь, если Tesseract не добавлен в PATH
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


# 1. Загрузка и очистка изображения (как в прошлом шаге)
img = cv2.imread('spec/0872_Progress.jpg')
b, g, r = cv2.split(img)
thresh = cv2.adaptiveThreshold(
    b, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 15
)

# 2. Конвертация очищенного изображения в формат PDF байт за байтом
# Используем расширение 'pdf' в параметрах Tesseract
pdf_bytes = pytesseract.image_to_pdf_or_hocr(thresh, lang='rus', extension='pdf')

# 3. Сохранение байтов в готовый PDF файл
with open('result.pdf', 'wb') as f:
    f.write(pdf_bytes)

print("Готово! Создан поисковый PDF-документ: result.pdf")
