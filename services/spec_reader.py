"""
Распознавание спецификации заказа.
Поддерживает PDF (текстовый слой) и JPG/PNG (Tesseract OCR).
"""
import re
import os
import shutil
import tempfile


def _poppler_kwargs() -> dict:
    """Путь к Poppler (pdftoppm/pdfinfo), если он не в системном PATH —
    берётся из config.json (ключ poppler_path)."""
    try:
        import config
        p = config.CFG.get("poppler_path") or ""
        return {"poppler_path": p} if p else {}
    except Exception:
        return {}


def _convert_pdf_first_page(path: str, dpi: int):
    """Рендерит первую страницу PDF в картинку через pdf2image/Poppler.

    На Windows pdfinfo/pdftoppm, запущенные из Python через subprocess,
    нередко не могут открыть файл, если в пути есть кириллица, пробелы
    или другие не-ASCII символы. Поэтому при первой неудаче делаем
    копию PDF во временную папку с "безопасным" ASCII-именем и
    пробуем ещё раз с ней.
    """
    from pdf2image import convert_from_path
    kwargs = dict(dpi=dpi, first_page=1, last_page=1, **_poppler_kwargs())
    try:
        return convert_from_path(path, **kwargs)
    except Exception as first_err:
        tmp_dir = tempfile.mkdtemp(prefix="imporeader_")
        try:
            tmp_pdf = os.path.join(tmp_dir, "source.pdf")
            shutil.copy2(path, tmp_pdf)
            return convert_from_path(tmp_pdf, **kwargs)
        except Exception:
            raise first_err
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ─── PUBLIC API ──────────────────────────────────────────────────

def read_spec(path: str) -> dict:
    ext = os.path.splitext(path)[1].lower()
    text = _extract_text(path)
    is_pdf = (ext == ".pdf") and len(text.strip()) > 50
    cleaned = _clean(text, is_pdf=is_pdf)

    if _is_eksmo_aip_format(cleaned):
        data = _parse_eksmo_aip(cleaned)
    else:
        data = _parse(cleaned)

    data["raw_text"] = text
    return data


def _is_eksmo_aip_format(text: str) -> bool:
    """Новый тип бланка — 'СПЕЦИФИКАЦИЯ ДЛЯ ПЕЧАТИ' от ЭКСМО в типографию
    (не 'Спецификация заказа №', как в стандартном бланке типографии).
    Определяем по паре характерных фраз, которые в стандартном бланке
    не встречаются."""
    has_title  = re.search(r"специфи[кк]аци[яи]\s+для\s+печати", text, re.I)
    has_typog  = re.search(r"в\s+типографию\s+\S", text, re.I)
    return bool(has_title and has_typog)


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

    # Обрезаем лишний фон вокруг листа (стол, тени и т.п.) — актуально
    # прежде всего для фото с телефона (не для чистых сканов), но не
    # вредит и им.
    img = _autocrop(img)

    # Быстрый пробный OCR всего листа целиком — нужен ТОЛЬКО чтобы
    # понять, с каким именно типом бланка имеем дело, до того как
    # решать, как именно резать картинку под конкретные поля (разметка
    # полей у бланков разная, см. _ocr_image_standard/_eksmo_aip).
    probe_cfg = r"--oem 3 --psm 6"
    probe_text = pytesseract.image_to_string(img, lang="rus+eng", config=probe_cfg)

    if _is_eksmo_aip_format(probe_text):
        return _ocr_image_eksmo_aip(img, path)
    return _ocr_image_standard(img, path)


def _ocr_image_eksmo_aip(img, path: str) -> str:
    """OCR нового бланка 'СПЕЦИФИКАЦИЯ ДЛЯ ПЕЧАТИ' (ЭКСМО → типография).

    В отличие от старого бланка тут НЕ нужно вырезать отдельную ячейку
    с номером заказа под пристальным прицелом — в этом бланке поле
    '№ Заказа в типографии' изначально пустое и не распознаётся (см.
    _parse_eksmo_aip — заполняется вручную), поэтому просто чистим
    линии таблиц и распознаём лист целиком одним проходом."""
    import pytesseract
    ocr_cfg = r"--oem 3 --psm 6"
    clean_img = remove_table_borders(img)
    text = pytesseract.image_to_string(clean_img, lang="rus+eng", config=ocr_cfg)
    _save_debug(clean_img, path)
    print(f"[OCR] Бланк ЭКСМО-АИП, тело (первые 300):\n{text[:300]}\n---")
    return text


def _ocr_image_standard(img, path: str) -> str:
    """OCR обычного (стандартного) бланка типографии — 'Спецификация
    заказа №'. Требует точечной вырезки ячейки с номером заказа, т.к.
    рядом с ней в шапке находится логотип, мешающий распознаванию."""
    import pytesseract
    from PIL import Image

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
        import pdf2image  # noqa: F401 — проверяем, что библиотека установлена
    except ImportError:
        raise RuntimeError("pip install pdf2image + poppler")
    pages = _convert_pdf_first_page(path, dpi=250)
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
    # Кириллический х → латинский, но ТОЛЬКО между цифрами
    # ("83х97" → "83x97", "4х4" → "4x4") — раньше заменялось ВЕЗДЕ в
    # тексте, что ломало обычные русские слова с буквой "х" (например,
    # "Технические" превращалось в "Теxнические", и регулярка для
    # "Технические пояснения" переставала находить это поле).
    text = re.sub(r"(?<=\d)\s*[хХ]\s*(?=\d)", "x", text)

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
    client = m.group(1).strip().split("\n")[0][:80] if m else None
    if client:
        # Убираем прилипший цифровой код клиента в конце строки,
        # напр. 'ООО "АВА-ПЕТЕР" 00000948' → 'ООО "АВА-ПЕТЕР"'
        client = re.sub(r"\s+\d{4,}\s*$", "", client).strip()
    d["client"] = client[:64] if client else None

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
    # Реальная строка формы: "Скрепление скрепка Толщина корешка"
    # (значение "Толщина корешка" на этой же строке — обрезаем перед
    # ним). Дальше приводим к одному из 5 канонических вариантов
    # ("скрепка", "термоклей", "твердый переплет", "резка в формат",
    # "на пружину") через binding_types.normalize_binding_label —
    # именно так текст и должен отображаться в интерфейсе.
    from binding_types import normalize_binding_label
    m = re.search(
        r"скрепление[^\S\n]*(.+?)(?=[^\S\n]+толщина\s+корешка|\n|$)",
        text, re.I
    )
    raw_binding = m.group(1).strip() if m else ""
    d["binding"] = normalize_binding_label(raw_binding) if raw_binding else None

    # ── Толщина корешка ──────────────────────────────────────────
    # Та же строка, что и "Скрепление" — значение (если есть) идёт
    # сразу после метки "Толщина корешка".
    m = re.search(r"толщина\s+корешка[^\S\n]*(.+?)(?=\n|$)", text, re.I)
    spine = m.group(1).strip() if m else ""
    d["spine_thickness"] = spine[:16] if spine else None

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

    # ── Бумага (тип + плотность, одной строкой: "мат. 130") ─────────
    def _paper_after_label(label_pattern: str):
        # [^\S\n] = пробелы/табы, но НЕ перевод строки — не даём
        # захватить данные со следующей строки таблицы.
        m = re.search(
            label_pattern + r"[^\S\n]+([^\d\n]+?)[^\S\n]+(\d+)",
            text, re.I
        )
        if not m:
            return None
        ptype = m.group(1).strip(" .\t")
        density = m.group(2)
        return f"{ptype}. {density}" if ptype else density

    d["paper_block"]  = _paper_after_label(r"бумага\s+бло[кк]\.?")
    d["paper_cover"]  = _paper_after_label(r"бумага\s+обл\.?(?:\+\s*подл\.?)?")
    d["paper_insert"] = _paper_after_label(r"бумага\s+вкл\.?")

    # ── Лак ──────────────────────────────────────────────────────
    m = re.search(r"\bлак[^\S\n]+(.*?)(?=[^\S\n]*ламинат\b|\n|$)", text, re.I)
    lak = m.group(1).strip(" .\t") if m else ""
    d["lak"] = lak[:32] if lak else None

    # ── Технические пояснения ────────────────────────────────────
    # Значение может занимать НЕСКОЛЬКО строк, поэтому вместо
    # regex-lookahead (ненадёжно ведёт себя на границах строк) режем
    # текст явно: от конца метки до ближайшей следующей метки формы.
    label_m = re.search(
        r"техническ(?:ие|ое)\s+поясн(?:ения|ение)[^\S\n]*[:\-]?",
        text, re.I
    )
    if label_m:
        start = label_m.end()
        rest = text[start:]

        boundary_pos = None

        # "Вид упаковки": перед этой меткой в PDF часто "выныривает"
        # значение упаковки (напр. "коробки"), отрисованное крупным
        # шрифтом и попадающее в извлечённый текст на строку ВЫШЕ
        # самой метки — поэтому обрезаем от начала этой строки, а не
        # от самой метки.
        m_vu = re.search(r"\n[^\n]*\n[^\S\n]*вид\s+упаковки\b", rest, re.I)
        if m_vu:
            boundary_pos = m_vu.start()

        for pat in (r"\bдата\s+сдачи\b", r"\bдата\s+заполнения\b",
                    r"\bдата\s+в\s+печать\b", r"\bрезультаты\s+проверки\b"):
            m2 = re.search(pat, rest, re.I)
            if m2 and (boundary_pos is None or m2.start() < boundary_pos):
                boundary_pos = m2.start()

        end = start + boundary_pos if boundary_pos is not None else len(text)
        note = text[start:end].strip()
        d["tech_notes"] = note[:500] if note else None
    else:
        d["tech_notes"] = None

    # ── Даты ─────────────────────────────────────────────────────
    d["due_date"]      = _find_date(text, r"дата\s+в\s+печать")
    d["delivery_date"] = _find_date(text, r"дата\s+сдачи\s+тиража")
    d["submit_date"]   = _find_date(text, r"дата\s+сдачи\s+материалов")

    return d


def _parse_eksmo_aip(text: str) -> dict:
    """
    Парсер нового типа бланка — 'СПЕЦИФИКАЦИЯ ДЛЯ ПЕЧАТИ' (ЭКСМО → типография,
    напр. РостБалт). Структура принципиально другая: это не заказ клиента
    типографии, а задание от издательства ЭКСМО в типографию, поэтому многие
    поля этого бланка не совпадают по смыслу с обычным ("Заказчик",
    "Описание заказа" и т.п. тут просто нет).

    Решения по неоднозначным полям (см. чат):
      • "number" (№ заказа) намеренно НЕ заполняется — в бланке этого поля
        нет ("№ Заказа в типографии" оставлено пустым для типографии),
        пользователь вводит его вручную после распознавания.
      • "client" — жёстко "ЭКСМО" (само слово есть только в логотипе-
        картинке, распознать из текстового слоя нельзя).
      • "description" — берём из поля "Серия".
      • Всё, что не влезает в текущие поля формы (Особые условия, Каптал,
        Тип корешка, Автор, Серия, код ITD, ISBN, Технолог, дата бланка) —
        сводится одним блоком в "tech_notes", чтобы не терять информацию.
    """
    from binding_types import normalize_binding_label

    d = {}

    d["client"] = "ЭКСМО"

    # ── Серия / Автор / Название ─────────────────────────────────
    m = re.search(r"Серия\s+(.+?)(?:\n|$)", text, re.I)
    series = m.group(1).strip() if m else None
    d["description"] = series[:64] if series else None

    # [^\S\n] (не \s!) — иначе при ПУСТОМ поле "Автор" (бывает, если автор
    # не указан) regex перепрыгивает через перевод строки и захватывает
    # содержимое следующего поля ("Название ...") как имя автора.
    m = re.search(r"Автор[^\S\n]*(\S.*?)(?:\n|$)", text, re.I)
    author = m.group(1).strip() if m else None

    m = re.search(r"Название[^\S\n]*(\S.*?)(?:\n|$)", text, re.I)
    d["name"] = m.group(1).strip()[:120] if m else None

    # ── Объём в печатных листах / Тираж / Переплёт ───────────────
    m = re.search(r"Объ[её]м\s+в\s+печатных\s+листах\s+([\d.,]+)", text, re.I)
    sheets = m.group(1).strip() if m else None

    m = re.search(r"Тираж\s+([\d\s]+)\s*экз", text, re.I)
    d["circulation"] = int(re.sub(r"\s", "", m.group(1))) if m else None

    m = re.search(r"Переплет\s+(.+?)(?:\n|$)", text, re.I)
    raw_binding = m.group(1).strip() if m else ""
    d["binding"] = normalize_binding_label(raw_binding) if raw_binding else None

    # ── Формат (реальный размер после обрезки, НЕ "Формат издания",
    #    который является долей бумажного листа, напр. 72x104/16) ──
    m = re.search(r"Блок\s+(\d{2,4})x(\d{2,4})\s*мм", text, re.I)
    if m:
        d["width"], d["height"] = int(m.group(1)), int(m.group(2))
    else:
        d["width"] = d["height"] = None

    # ── Красочность блока ─────────────────────────────────────────
    m = re.search(r"Блок\s+текста\s+(\d\s*\+\s*\d)(?!\s*\()", text, re.I)
    d["color_block"] = re.sub(r"\s", "", m.group(1)) if m else None

    # ── Бумага блока (строка "п/о ... мм, бумага <тип> <плотность>") ─
    m = re.search(r"п/о[^\n]*?,\s*бумага\s+(.+?)\s+(\d{2,3})\b", text, re.I)
    d["paper_block"] = f"{m.group(1).strip()}. {m.group(2)}" if m else None

    # ── Обложка: красочность + отделка (целлофанирование и т.п.) ──
    m = re.search(r"Обложка\s+(\d\s*\+\s*\d)\s*;\s*(.+?)(?:\n|$)", text, re.I)
    finishing = None
    if m:
        d["color_cover"] = re.sub(r"\s", "", m.group(1))
        finishing = m.group(2).strip()
    else:
        d["color_cover"] = None
    d["lak"] = finishing[:32] if finishing else None

    # ── Бумага/картон обложки — следующая строка после "Обложка ..;.." ─
    d["paper_cover"] = None
    if m:
        rest = text[m.end():]
        m2 = re.search(r"^\s*(.+?)(?:\n|$)", rest)
        if m2:
            cover_material = m2.group(1).strip()
            cover_material = re.sub(r"^бумага\s+", "", cover_material, flags=re.I)
            d["paper_cover"] = cover_material[:64]

    d["color_insert"] = None
    d["paper_insert"] = None
    d["pages_insert"] = None

    # ── Каптал / Тип корешка ────────────────────────────────────────
    m = re.search(r"Каптал\s+(.+?)\s+Тип\s+корешка\s+(.+?)(?:\n|$)", text, re.I)
    captal = spine_type = None
    if m:
        captal, spine_type = m.group(1).strip(), m.group(2).strip()
    d["spine_thickness"] = None  # в этом бланке толщина корешка не указывается

    # ── Объём блока (кол-во страниц) — "Блок текста (56 стр.)" ──────
    m = re.search(r"Блок\s+текста\s*\((\d+)\s*стр", text, re.I)
    d["pages_block"] = int(m.group(1)) if m else None
    d["pages_cover"] = None  # явно не указано в бланке

    # ── Особые условия (многострочный блок до "МАТЕРИАЛЫ") ─────────
    # Ищем границы отдельно (а не одним regex с "\nМАТЕРИАЛЫ") — при OCR
    # со скана/фото перед словом "МАТЕРИАЛЫ" часто прилипает мусор
    # (напр. "___ МАТЕРИАЛЫ"), из-за чего "\n" сразу перед ним не находится.
    special = None
    m_start = re.search(r"Особые\s+условия[^\S\n]*", text, re.I)
    if m_start:
        start = m_start.end()
        m_end = re.search(r"МАТЕРИАЛЫ", text[start:], re.I)
        end = start + m_end.start() if m_end else len(text)
        special = re.sub(r"\s*\n\s*", " ", text[start:end]).strip()
        special = special or None

    # ── Служебные идентификаторы (ITD-код, ISBN) ────────────────────
    m = re.search(r"\b(ITD\d+)\b", text)
    itd_code = m.group(1) if m else None

    m = re.search(r"\b(97[89][\d\-]{10,20}\d)\b", text)
    isbn = m.group(1) if m else None

    # ── Типография-получатель ────────────────────────────────────
    m = re.search(r"В\s+типографию\s+(.+?)(?:\n|$)", text, re.I)
    typography = m.group(1).strip() if m else None

    # ── Технолог ──────────────────────────────────────────────────
    m = re.search(r"Технолог\s+(.+?)(?:\n|$)", text, re.I)
    technologist = m.group(1).strip() if m else None

    # ── Даты ─────────────────────────────────────────────────────
    d["due_date"] = _find_date(text, r"Просьба\s+изготовить\s+к")
    d["delivery_date"] = None
    d["submit_date"] = None
    m = re.search(r"Просьба\s+изготовить\s+к\s+\d{1,2}[./]\d{1,2}[./]\d{2,4}\s+Дата\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})", text, re.I)
    spec_date = _norm_date(m.group(1)) if m else None

    # ── Собираем "Технические пояснения" ─────────────────────────
    notes_parts = []
    if typography:      notes_parts.append(f"В типографию: {typography}")
    if series:           notes_parts.append(f"Серия: {series}")
    if author:            notes_parts.append(f"Автор: {author}")
    if sheets:            notes_parts.append(f"Объём в печ. листах: {sheets}")
    if captal:            notes_parts.append(f"Каптал: {captal}")
    if spine_type:        notes_parts.append(f"Тип корешка: {spine_type}")
    if special:           notes_parts.append(f"Особые условия: {special}")
    if itd_code:          notes_parts.append(itd_code)
    if isbn:              notes_parts.append(f"ISBN {isbn}")
    if technologist:      notes_parts.append(f"Технолог: {technologist}")
    if spec_date:         notes_parts.append(f"Дата составления спецификации: {spec_date}")

    d["tech_notes"] = "\n".join(notes_parts)[:1000] if notes_parts else None

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