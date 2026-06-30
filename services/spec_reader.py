"""
Распознавание спецификации заказа.
Поддерживает PDF (текстовый слой) и JPG/PNG (Tesseract OCR).
"""
import re
import os


# ─── PUBLIC API ──────────────────────────────────────────────────

def read_spec(path: str) -> dict:
    ext = os.path.splitext(path)[1].lower()
    text = _extract_text(path)
    is_pdf = (ext == ".pdf") and len(text.strip()) > 50
    cleaned = _clean(text, is_pdf=is_pdf)
    print(f"[Spec] Cleaned (первые 200):\n{cleaned[:200]}")
    data = _parse(cleaned)
    data["raw_text"] = text
    return data


# ─── ИЗВЛЕЧЕНИЕ ТЕКСТА ───────────────────────────────────────────

def _extract_text(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        text = _read_pdf_text(path)
        if text and len(text.strip()) > 50:
            return text
        return _ocr_pdf_scan(path)
    return _ocr_image(path)


def _read_pdf_text(path: str) -> str:
    import logging
    # Глушим подробные логи pdfminer/pdfplumber
    for noisy in ["pdfminer", "pdfplumber", "pdfminer.psparser",
                  "pdfminer.pdfinterp", "pdfminer.cmapdb",
                  "pdfminer.pdfdocument", "pdfminer.pdfpage"]:
        logging.getLogger(noisy).setLevel(logging.ERROR)

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
    try:
        import fitz
        doc = fitz.open(path)
        parts = [page.get_text() for i, page in enumerate(doc) if i < 2]
        doc.close()
        return "\n".join(parts)
    except ImportError:
        pass
    return ""


def remove_table_borders(img_pil):
    """
    Убирает линии таблицы перед OCR.
    Использует более мягкие параметры чтобы не трогать текст в шапке.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return img_pil

    img = np.array(img_pil.convert("RGB"))
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

    # Бинаризация
    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY_INV,
        15, 10
    )

    # Горизонтальные линии — минимальная длина 1/15 ширины
    # (длиннее чтобы не цеплять подчёркивания в тексте)
    h_len = max(60, img.shape[1] // 15)
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (h_len, 1))
    h_lines  = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)

    # Вертикальные линии — минимальная высота 1/15
    v_len = max(60, img.shape[0] // 15)
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_len))
    v_lines  = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)

    mask = cv2.add(h_lines, v_lines)

    # Небольшое расширение — убираем остатки линий
    k    = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    mask = cv2.dilate(mask, k, iterations=1)

    result = cv2.inpaint(img, mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)

    from PIL import Image as PILImage
    return PILImage.fromarray(result)


def _ocr_image(path: str) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise RuntimeError(
            "pip install pytesseract pillow\n"
            "+ Tesseract: https://github.com/UB-Mannheim/tesseract/wiki"
        )
    img = Image.open(path)

    # Масштабируем
    w, h = img.size
    if w < 1800:
        scale = 1800 / w
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    ocr_cfg = r"--oem 3 --psm 6"

    iw, ih = img.width, img.height

    # ШАГ 1: Вырезаем ТОЛЬКО ячейку с номером заказа.
    # Структура шапки бланка по горизонтали:
    #   0%──28%  "Спецификация заказа №"  (курсив, слева)
    #   28%─55%  [ 883 ]                  (номер в ячейке, по центру-левее)
    #   55%─100% ЛОГОТИП                  (мешает OCR — не читаем)
    #
    # Читаем всю левую часть шапки (0–55%), логотип отрезаем
    header_crop = img.crop((0, 0, int(iw * 0.55), int(ih * 0.10)))
    # Увеличиваем х2 для лучшего распознавания мелкого текста
    hw, hh = header_crop.size
    header_big = header_crop.resize((hw * 2, hh * 2), Image.LANCZOS)
    header_text = pytesseract.image_to_string(
        header_big, lang="rus+eng", config=ocr_cfg
    )

    # ШАГ 2: Отдельно читаем только ячейку номера (28–55%, верхние 10%)
    # psm 8 = single word, whitelist только цифры
    num_crop = img.crop((int(iw * 0.28), 0, int(iw * 0.55), int(ih * 0.10)))
    nw, nh = num_crop.size
    num_big = num_crop.resize((nw * 3, nh * 3), Image.LANCZOS)
    # Сохраняем для отладки (оригинальный кроп без изменений)
    _save_crop(num_big,    "num_cell.jpg")
    _save_crop(header_big, "header_left.jpg")

    # Читаем ТОЛЬКО верхнюю половину кропа — там ячейка с номером.
    # Нижняя половина кропа может захватить строку "Заказчик" → "00001940".
    nw2, nh2 = num_big.size
    num_top = num_big.crop((0, 0, nw2, nh2 // 2))

    num_raw = ""
    for psm in [7, 8, 6]:
        cfg = f"--oem 3 --psm {psm} -c tessedit_char_whitelist=0123456789"
        for src in [num_top, num_big]:
            result = pytesseract.image_to_string(
                src, lang="eng", config=cfg
            ).strip().replace(" ", "").replace("\n", "")
            if re.fullmatch(r"\d{3,6}", result):
                num_raw = result
                print(f"[OCR] Ячейка номера: '{num_raw}' (psm {psm})")
                break
        if num_raw:
            break

    if not num_raw:
        # Fallback — ищем первое 3-6 значное число в тексте шапки
        nm = re.search(r"(?<![\d])([1-9]\d{2,5})(?![\d])", header_text)
        if nm:
            num_raw = nm.group(1)
            print(f"[OCR] Номер из шапки: '{num_raw}'")
        else:
            print("[OCR] Номер не найден — см. debug/num_cell.jpg")

    # ШАГ 3: Тело документа с удалением рамок
    body_crop  = img.crop((0, int(ih * 0.08), iw, ih))
    body_clean = remove_table_borders(body_crop)
    body_text  = pytesseract.image_to_string(
        body_clean, lang="rus+eng", config=ocr_cfg
    )

    # Собираем финальный текст
    # Если число из ячейки прочиталось — подставляем явно в начало
    import re as _re
    if _re.fullmatch(r"\d{3,6}", num_raw):
        number_line = f"Спецификация заказа № {num_raw}"
    else:
        # Fallback — ищем число в header_text
        nm = _re.search(r"(\d{3,6})", header_text)
        number_line = f"Спецификация заказа № {nm.group(1)}" if nm else ""

    text = number_line + "\n" + header_text + "\n" + body_text
    _save_debug(body_clean, path)

    print(f"[OCR] Шапка:\n{header_text[:200]}")
    print(f"[OCR] Тело (первые 300):\n{body_text[:300]}\n---")
    return text


def _ocr_pdf_scan(path: str) -> str:
    try:
        from pdf2image import convert_from_path
    except ImportError:
        raise RuntimeError("pip install pdf2image + poppler")
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


def _debug_dir():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "debug")
    os.makedirs(d, exist_ok=True)
    return d

def _save_debug(img, source_path: str = ""):
    try:
        img.save(os.path.join(_debug_dir(), "ocr_input.jpg"))
    except Exception:
        pass

def _save_crop(img, filename: str):
    try:
        img.save(os.path.join(_debug_dir(), filename))
    except Exception:
        pass

def _autocrop(img):
    """Обрезает пустые белые поля вокруг контента."""
    try:
        import numpy as np
        import cv2
        arr = np.array(img.convert("RGB"))
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        # Бинаризация — находим пиксели темнее 200
        _, mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
        coords = cv2.findNonZero(mask)
        if coords is None:
            return img
        x, y, w, h = cv2.boundingRect(coords)
        # Добавляем небольшой отступ
        pad = 10
        x = max(0, x - pad)
        y = max(0, y - pad)
        w = min(arr.shape[1] - x, w + pad * 2)
        h = min(arr.shape[0] - y, h + pad * 2)
        from PIL import Image as PILImage
        return PILImage.fromarray(arr[y:y+h, x:x+w])
    except Exception:
        return img


# ─── ОЧИСТКА ТЕКСТА OCR ──────────────────────────────────────────

def _clean(text: str, is_pdf: bool = False) -> str:
    """
    Нормализует текст.
    is_pdf=True — мягкая очистка (нет артефактов рамок).
    is_pdf=False — полная очистка OCR артефактов.
    """
    # Кириллический х → латинский (для "83х97", "4х4")
    text = text.replace("х", "x").replace("Х", "x")

    if not is_pdf:
        # Убираем артефакты рамок ячеек характерные для OCR
        text = re.sub(r"\|", " ", text)
        text = re.sub(r"\[([^\]]*)\]", r"\1", text)
        text = re.sub(r"\[", " ", text)
        text = re.sub(r"\]", " ", text)
        text = re.sub(r"<>", " ", text)

    # Множественные пробелы → один
    text = re.sub(r"[ \t]+", " ", text)

    # Убираем пустые строки
    lines = [l.strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    return "\n".join(lines)


# ─── ПАРСЕР ──────────────────────────────────────────────────────

def _parse(text: str) -> dict:
    # Обрезаем до "Дата в печать"
    cut = re.search(r"дата\s+в\s+печать", text, re.I)
    if cut:
        text = text[: cut.end() + 40]

    d = {}

    # ── Номер заказа ─────────────────────────────────────────────
    # Ищем в нескольких вариантах — OCR может разбить на строки
    # или вставить артефакты между "Спецификация заказа №" и числом

    # Вариант 1: "Спецификация заказа № 878" (всё в одной строке)
    m = re.search(
        r"спецификаци[яи]\s+заказа\s*[№#NnОо]?\s*\.?\s*(\d{3,6})",
        text, re.I
    )
    if not m:
        # Вариант 2: число в той же строке через любые символы
        # "Спецификация заказа №  | 883 |" → после _clean → "Спецификация заказа №  883"
        m = re.search(
            r"спецификаци[яи]\s+заказа[^\n]{0,30}?(\d{3,6})",
            text, re.I
        )
    if not m:
        # Вариант 3: число на следующей строке сразу после заголовка
        m = re.search(
            r"спецификаци[яи]\s+заказа[^\d]{0,40}(\d{3,6})",
            text, re.I | re.DOTALL
        )
    if not m:
        # Вариант 4: "заказ № 878"
        m = re.search(r"заказ\s*[№#]?\s*(\d{3,6})", text, re.I)
    if not m:
        # Вариант 5: одиночное число в первых 5 строках
        for line in text.splitlines()[:5]:
            line = line.strip()
            if re.fullmatch(r"\d{3,6}", line):
                m = re.match(r"(\d{3,6})", line)
                break
    d["number"] = int(m.group(1)) if m else None

    # ── Наименование заказа ──────────────────────────────────────
    m = re.search(r"наименование\s+заказа\s+(.+)", text, re.I)
    d["name"] = m.group(1).strip().split("\n")[0].strip()[:64] if m else None

    # ── Описание ─────────────────────────────────────────────────
    m = re.search(r"описание\s+заказа\s+(.+)", text, re.I)
    d["description"] = m.group(1).strip().split("\n")[0][:32] if m else None

    # ── Заказчик ─────────────────────────────────────────────────
    m = re.search(r"заказчик[^)]*\)\s+(.+)", text, re.I)
    if not m:
        m = re.search(r"заказчик\s*\(организация\)\s+(.+)", text, re.I)
    d["client"] = m.group(1).strip().split("\n")[0][:64] if m else None

    # ── Тираж ────────────────────────────────────────────────────
    m = re.search(r"тираж\s+(\d[\d\s]*)", text, re.I)
    d["circulation"] = int(re.sub(r"\s", "", m.group(1))) if m else None

    # ── Формат изделия ───────────────────────────────────────────
    m = re.search(r"формат\s+(\d{2,4})\s*x\s*(\d{2,4})", text, re.I)
    if m:
        d["width"]  = int(m.group(1))
        d["height"] = int(m.group(2))
    else:
        d["width"] = d["height"] = None

    # ── Объёмы ───────────────────────────────────────────────────
    m = re.search(r"объ[её]м\s+бло[кк]\s+(\d+)", text, re.I)
    d["pages_block"] = int(m.group(1)) if m else None

    m = re.search(r"объ[её]м\s+обл\.?\s+(\d+)", text, re.I)
    d["pages_cover"] = int(m.group(1)) if m else None

    m = re.search(r"объ[её]м\s+вкл\.?\s+(\d+)", text, re.I)
    d["pages_insert"] = int(m.group(1)) if m else None

    # ── Красочность ──────────────────────────────────────────────
    m = re.search(r"красочность\s+блока?\s+(\d+\s*[x+]\s*\d+)", text, re.I)
    d["color_block"] = _norm_color(m.group(1)) if m else None

    m = re.search(r"красочность\s+обло[жщ]ки\s+(\d+\s*[x+]\s*\d+)", text, re.I)
    d["color_cover"] = _norm_color(m.group(1)) if m else None

    m = re.search(r"красочность\s+вкле[йй]ки\s+(\d+\s*[x+]\s*\d+)", text, re.I)
    d["color_insert"] = _norm_color(m.group(1)) if m else None

    # ── Скрепление ───────────────────────────────────────────────
    binding_map = [
        (r"термо\s*кле[йй]|кбс",  "КБС"),
        (r"скреп",                  "СКР"),
        (r"ши[тт]ь|шитьё|швп",     "ШВП"),
        (r"евро",                   "ЕВР"),
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

    # ── Ламинат ──────────────────────────────────────────────────
    m = re.search(r"ламинат\s+(?!двух)([^\n]+)", text, re.I)
    if m:
        lam = m.group(1).strip()
        if re.search(r"матов", lam, re.I):
            d["laminate"] = "мат"
        elif re.search(r"глянц", lam, re.I):
            d["laminate"] = "глянц"
        elif lam and not re.search(r"^\s*$", lam):
            d["laminate"] = lam[:16]
        else:
            d["laminate"] = None
    else:
        d["laminate"] = None

    m = re.search(r"вид\s+ламината\s+(.+)", text, re.I)
    d["laminate_type"] = m.group(1).strip().split("\n")[0][:32] if m else None

    # ── Бумага ───────────────────────────────────────────────────
    m = re.search(r"бумага\s+бло[кк]\s+(\S+)\s+(\d+)", text, re.I)
    if m:
        d["paper_block_type"]    = m.group(1).strip(".").strip()
        d["paper_block_density"] = int(m.group(2))
    else:
        d["paper_block_type"] = d["paper_block_density"] = None

    m = re.search(r"бумага\s+обл[^.]*\s+(\S+)\s+(\d+)", text, re.I)
    if m:
        d["paper_cover_type"]    = m.group(1).strip(".").strip()
        d["paper_cover_density"] = int(m.group(2))
    else:
        d["paper_cover_type"] = d["paper_cover_density"] = None

    # ── Даты ─────────────────────────────────────────────────────
    d["due_date"]      = _find_date(text, r"дата\s+в\s+печать")
    d["delivery_date"] = _find_date(text, r"дата\s+сдачи\s+тиража")
    d["submit_date"]   = _find_date(text, r"дата\s+сдачи\s+материалов")

    return d


# ─── ВСПОМОГАТЕЛЬНЫЕ ─────────────────────────────────────────────

def _find_date(text: str, label_pattern: str):
    m = re.search(
        label_pattern + r"\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
        text, re.I
    )
    return _norm_date(m.group(1)) if m else None


def _norm_color(s: str) -> str:
    s = re.sub(r"\s", "", s)
    return s.replace("x", "+")


def _norm_date(s: str) -> str:
    s = s.replace("/", ".").replace("-", ".")
    parts = s.split(".")
    if len(parts) == 3:
        d, mo, y = parts
        if len(y) == 2:
            y = "20" + y
        return f"{d.zfill(2)}.{mo.zfill(2)}.{y}"
    return s
