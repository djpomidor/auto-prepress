"""
Распознавание спецификации заказа.
Бланк: "Спецификация заказа №" (типография Премиум и аналогичные).

Логика:
  PDF с текстом → читаем напрямую через pdfplumber или pymupdf (быстро, точно)
  PDF-скан      → конвертируем в изображение → Tesseract OCR
  JPG/PNG       → Tesseract OCR
"""
import re
import os


# ─── PUBLIC API ──────────────────────────────────────────────────

def read_spec(path: str) -> dict:
    """
    Главная функция. Возвращает словарь:
    {
        number, name, client, circulation,
        width, height,
        pages_block, pages_cover, pages_insert,
        color_block, color_cover, color_insert,
        binding, laminate, laminate_type,
        paper_block_type, paper_block_density,
        paper_cover_type, paper_cover_density,
        due_date, submit_date, delivery_date,
        raw_text   (полный текст OCR для отладки)
    }
    Отсутствующие поля = None.
    """
    text = _extract_text(path)
    data = _parse(text)
    data["raw_text"] = text
    return data


# ─── ИЗВЛЕЧЕНИЕ ТЕКСТА ───────────────────────────────────────────

def _extract_text(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        # Сначала пробуем прочитать текстовый слой напрямую
        text = _read_pdf_text(path)
        if text and len(text.strip()) > 50:
            return text
        # Fallback: PDF является сканом — OCR
        return _ocr_pdf_scan(path)
    return _ocr_image(path)


def _read_pdf_text(path: str) -> str:
    """Читает текст напрямую из PDF без OCR. Работает если PDF не скан."""

    # Вариант 1: pdfplumber — лучше для форм и таблиц
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            parts = []
            for page in pdf.pages[:2]:
                t = page.extract_text(x_tolerance=3, y_tolerance=3)
                if t:
                    parts.append(t)
            return "\n".join(parts)
    except ImportError:
        pass

    # Вариант 2: PyMuPDF
    try:
        import fitz
        doc = fitz.open(path)
        parts = []
        for i, page in enumerate(doc):
            if i >= 2:
                break
            parts.append(page.get_text())
        doc.close()
        return "\n".join(parts)
    except ImportError:
        pass

    return ""  # ни одна библиотека не установлена — упадём в OCR


def _ocr_image(path: str) -> str:
    """OCR для JPG/PNG через Tesseract."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise RuntimeError(
            "Установите зависимости:\n"
            "  pip install pytesseract pillow\n"
            "  + Tesseract: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "  Языковые данные: rus+eng"
        )
    img = Image.open(path)
    w, h = img.size
    if w < 1500:
        scale = 1500 / w
        img = img.resize((int(w * scale), int(h * scale)))
    cfg = r"--oem 1 --psm 3"
    
     
    result = pytesseract.image_to_string(img, lang="rus+eng", config=cfg)

    with open('result4.txt', 'w', encoding='utf-8') as f:
        f.write(result)

    return result


def _ocr_pdf_scan(path: str) -> str:
    """OCR для PDF-скана: конвертируем страницу в изображение → Tesseract."""
    try:
        from pdf2image import convert_from_path
    except ImportError:
        raise RuntimeError(
            "PDF является сканом. Установите pdf2image + poppler:\n"
            "  pip install pdf2image\n"
            "  poppler: https://github.com/oschwartz10612/poppler-windows/releases"
        )
    pages = convert_from_path(path, dpi=250, first_page=1, last_page=1)
    if not pages:
        return ""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
    pages[0].save(tmp_path, "JPEG", quality=95)
    try:
        return _ocr_image(tmp_path)
    finally:
        os.unlink(tmp_path)


# ─── ПАРСЕР ──────────────────────────────────────────────────────

def _parse(text: str) -> dict:
    # Нормализуем: убираем лишние пробелы, кириллические x → латинские
    text = re.sub(r"[ \t]+", " ", text)
    text = text.replace("х", "x").replace("Х", "x")

    # Обрезаем до "Дата в печать" включительно
    cut = re.search(r"дата\s+в\s+печать", text, re.I)
    if cut:
        text = text[: cut.end() + 40]

    d = {}

    # Номер заказа
    m = re.search(r"спецификация\s+заказа\s*[№#]?\s*(\d{3,5})", text, re.I)
    if not m:
        m = re.search(r"заказ\s*[№#]\s*(\d{3,5})", text, re.I)
    d["number"] = int(m.group(1)) if m else None

    # Наименование заказа
    m = re.search(r"наименование\s+заказа\s+(.+)", text, re.I)
    d["name"] = m.group(1).strip().split("\n")[0].strip()[:64] if m else None

    # Описание (тип изделия: брошюра, книга...)
    m = re.search(r"описание\s+заказа\s+(.+)", text, re.I)
    d["description"] = m.group(1).strip().split("\n")[0][:32] if m else None

    # Заказчик
    m = re.search(r"заказчик[^)]*\)\s+(.+)", text, re.I)
    d["client"] = m.group(1).strip().split("\n")[0][:64] if m else None

    # Тираж
    m = re.search(r"тираж\s+(\d[\d\s]*)", text, re.I)
    d["circulation"] = int(re.sub(r"\s", "", m.group(1))) if m else None

    # Формат изделия: "Формат 160x240"
    m = re.search(r"формат\s+(\d{2,4})\s*x\s*(\d{2,4})", text, re.I)
    if m:
        d["width"]  = int(m.group(1))
        d["height"] = int(m.group(2))
    else:
        d["width"] = d["height"] = None

    # Объём блока
    m = re.search(r"объ[её]м\s+бло[кк]\s+(\d+)", text, re.I)
    d["pages_block"] = int(m.group(1)) if m else None

    # Объём обложки
    m = re.search(r"объ[её]м\s+обл\.?\s+(\d+)", text, re.I)
    d["pages_cover"] = int(m.group(1)) if m else None

    # Объём вклейки
    m = re.search(r"объ[её]м\s+вкл\.?\s+(\d+)", text, re.I)
    d["pages_insert"] = int(m.group(1)) if m else None

    # Красочность блока: "4x4" → "4+4"
    m = re.search(r"красочность\s+блока?\s+(\d+\s*x\s*\d+)", text, re.I)
    d["color_block"] = _norm_color(m.group(1)) if m else None

    # Красочность обложки
    m = re.search(r"красочность\s+обло[жщ]ки\s+(\d+\s*x\s*\d+)", text, re.I)
    d["color_cover"] = _norm_color(m.group(1)) if m else None

    # Красочность вклейки
    m = re.search(r"красочность\s+вкле[йй]ки\s+(\d+\s*x\s*\d+)", text, re.I)
    d["color_insert"] = _norm_color(m.group(1)) if m else None

    # Скрепление
    binding_map = [
        (r"термо\s*кле[йй]|кбс|клее", "КБС"),
        (r"скреп",                      "СКР"),
        (r"ши[тт]ь|шитьё|швп",         "ШВП"),
        (r"евро",                        "ЕВР"),
    ]
    d["binding"] = None
    for pattern, val in binding_map:
        if re.search(r"скрепление\s+" + pattern, text, re.I):
            d["binding"] = val
            break
    if not d["binding"]:
        for pattern, val in binding_map:
            if re.search(pattern, text, re.I):
                d["binding"] = val
                break

    # Ламинат
    m = re.search(r"ламинат\s+([^\n]+)", text, re.I)
    if m:
        lam = m.group(1).strip()
        if re.search(r"матов", lam, re.I):
            d["laminate"] = "мат"
        elif re.search(r"глянц", lam, re.I):
            d["laminate"] = "глянц"
        else:
            d["laminate"] = lam[:16]
    else:
        d["laminate"] = None

    m = re.search(r"вид\s+ламината\s+(.+)", text, re.I)
    d["laminate_type"] = m.group(1).strip().split("\n")[0][:32] if m else None

    # Бумага блока: "Бумага блок  глянц.  105"
    m = re.search(r"бумага\s+бло[кк]\s+(\S+)\s+(\d+)", text, re.I)
    if m:
        d["paper_block_type"]    = m.group(1).strip(".")
        d["paper_block_density"] = int(m.group(2))
    else:
        d["paper_block_type"] = d["paper_block_density"] = None

    # Бумага обложки: "Бумага обл.+подл.  мат.  250"
    m = re.search(r"бумага\s+обл[^.]*\s+(\S+)\s+(\d+)", text, re.I)
    if m:
        d["paper_cover_type"]    = m.group(1).strip(".")
        d["paper_cover_density"] = int(m.group(2))
    else:
        d["paper_cover_type"] = d["paper_cover_density"] = None

    # Даты
    d["due_date"]      = _find_date(text, r"дата\s+в\s+печать")
    d["delivery_date"] = _find_date(text, r"дата\s+сдачи\s+тиража")
    d["submit_date"]   = _find_date(text, r"дата\s+сдачи\s+материалов")

    return d


def _find_date(text: str, label_pattern: str):
    m = re.search(
        label_pattern + r"\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
        text, re.I
    )
    return _norm_date(m.group(1)) if m else None


def _norm_color(s: str) -> str:
    return re.sub(r"\s", "", s).replace("x", "+")


def _norm_date(s: str) -> str:
    s = s.replace("/", ".").replace("-", ".")
    parts = s.split(".")
    if len(parts) == 3:
        d, mo, y = parts
        if len(y) == 2:
            y = "20" + y
        return f"{d.zfill(2)}.{mo.zfill(2)}.{y}"
    return s