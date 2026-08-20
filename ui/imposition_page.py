"""
Страница спуска полос.
"""
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
from tkinter import filedialog, messagebox
from datetime import datetime
import threading
import base64
import json
import os
import re
import shutil
import subprocess
import time
import config
from db.database import (
    get_session, get_imposition, save_imposition,
    get_preps_template_cache, replace_preps_template_cache,
)
from db.models import Order
from binding_types import binding_code_to_label

# Масштаб превью фото спуска по умолчанию — «вписать в окно»
# (множитель поверх масштаба fit; см. _render_preview)
_DEFAULT_PREVIEW_ZOOM = 1.0

DARK_BG  = "#0f0f0f"
DARK_SF  = "#1a1a1a"
DARK_SF2 = "#242424"
DARK_BD  = "#2e2e2e"
DARK_BD2 = "#3a3a3a"
ACCENT   = "#c8f135"
ACCENT2  = "#9bc429"
# Для текста-акцента (подзаголовки, статусы) на сером фоне: чистый
# лайм ACCENT нечитаем на светлом фоне светлой темы, поэтому для
# текста используем адаптивную пару (тёмно-оливковый на светлой теме
# / лайм на тёмной) вместо одноцветного ACCENT. Для ФОНА кнопок
# (fg_color=ACCENT) сам ACCENT остаётся как есть — там всегда тёмный
# текст поверх, контраст в порядке.
ACCENT_TEXT = ("#5c7a00", "#c8f135")
TEXT     = "#e8e8e8"
TEXT2    = "#888888"
TEXT3    = "#555555"
DANGER   = "#ff5555"
SUCCESS  = "#33cc66"
INFO     = "#55aaff"
WARNING  = "#ffaa33"

# ── Разбор имён файлов шаблонов Preps ────────────────────────────────
# Пример: 0055_MadBombers_173x260_64x90_Skrepka.tpl
#         номер_название_обрезнойформат_форматбумаги_скрепление.tpl
_TEMPLATE_RE = re.compile(
    r'^(?P<order>\d+)_(?P<name>.+?)_(?P<trim_w>\d+)[xхX](?P<trim_h>\d+)_'
    r'(?P<paper_w>\d+)[xхX](?P<paper_h>\d+)_(?P<binding>[^_.]+)\.tpl$',
    re.IGNORECASE,
)

_TRANSLIT = {
    'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z',
    'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
    'с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sch',
    'ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
}


def _norm_token(text: str) -> str:
    """Транслитерация кириллицы в латиницу + приведение к нижнему
    регистру, только буквы/цифры — чтобы сравнивать "скрепка" (из
    заказа) с "Skrepka" (из имени файла шаблона), не завися от
    конкретной транслитерации/регистра."""
    if not text:
        return ""
    out = []
    for ch in text:
        low = ch.lower()
        if low in _TRANSLIT:
            out.append(_TRANSLIT[low])
        elif low.isalnum():
            out.append(low)
    return "".join(out)


# Соответствие КОДА скрепления заказа (как он хранится в БД —
# printery_order.binding, см. binding_types.py: SKR/KBS/HARD/SHT/SHK/
# REZ/PRU/FALC) токенам скрепления в именах файлов шаблонов Preps. У
# одного типа скрепления может быть несколько вариантов написания
# токена в имени файла (напр. и "shitie", и "nitki" — шитьё/твёрдый
# переплёт, это один и тот же процесс/шаблон).
_BINDING_CODE_TEMPLATE_TOKENS = {
    "SHT":  {"shitie", "nitki"},            # шитьё
    "HARD": {"shitie", "nitki"},            # твердый переплет — те же шаблоны, что и шитьё
    "SHK":  {"shitie", "nitki", "tkley"},   # шитье+термоклей — оба процесса
    "KBS":  {"tkley"},                       # термоклей
    "SKR":  {"skrepka"},                     # скрепка
}


def _binding_matches(order_binding_code: str, order_binding_label: str, template_binding: str) -> bool:
    """Сравнивает скрепление заказа с токеном скрепления из имени
    файла шаблона Preps (обычно транслит, напр. "Skrepka").

    В первую очередь сравниваем по КОДУ скрепления заказа (точный,
    берётся из БД — см. _BINDING_CODE_TEMPLATE_TOKENS) — это надёжный
    способ, не зависящий от формулировок. Если код неизвестен/не
    входит в таблицу (напр. "резка в формат", "на пружину",
    "фальцовка" — под них шаблонов спуска нет) — используем текстовую
    метку скрепления как запасной вариант (нечёткое сравнение
    транслитерированных строк по подстроке/префиксу)."""
    b = _norm_token(template_binding)
    if not b:
        return False

    code = (order_binding_code or "").strip().upper()
    if code in _BINDING_CODE_TEMPLATE_TOKENS:
        return b in _BINDING_CODE_TEMPLATE_TOKENS[code]

    a = _norm_token(order_binding_label)
    if not a:
        return False
    if a == b:
        return True
    # частичное совпадение по началу слова (запасной вариант для
    # кодов/меток, которых нет в таблице выше)
    prefix_len = min(5, len(a), len(b))
    return a[:prefix_len] == b[:prefix_len] or a in b or b in a


# Кэш "сырого" списка .tpl шаблонов из БЫСТРЫХ (локальных) папок
# config.preps_templates — сканируется заново при каждом поиске (эти
# папки меняются часто — туда сохраняются новые шаблоны), но всё
# равно кэшируется на короткое время (TTL), чтобы не пересканировать
# диск при каждой перерисовке списка за одно открытие страницы.
# МЕДЛЕННЫЕ архивные папки (config.preps_templates_archive, сетевые)
# сюда не входят — они кэшируются в БД, см. _get_archive_templates.
_TEMPLATES_CACHE = {"data": None, "timestamp": 0.0, "dirs": None, "all_tpl_paths": []}
_TEMPLATES_CACHE_TTL = 600  # секунд (10 минут)


def _parse_template_record(path: str, fname: str, source_dir: str = None) -> dict:
    """Разбирает имя файла шаблона по _TEMPLATE_RE и возвращает запись
    в едином формате, общем и для "быстрого" скана, и для архивного
    кэша из БД — чтобы дальнейшая фильтрация (_scan_preps_templates)
    не зависела от источника. Возвращает None, если имя не подходит
    под схему "номер_название_формат_бумага_скрепление.tpl"."""
    m = _TEMPLATE_RE.match(fname)
    if not m:
        return None
    try:
        tw, th = int(m.group("trim_w")), int(m.group("trim_h"))
    except ValueError:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0
    return {
        "fname": fname,
        "path": path,
        "source_dir": source_dir or os.path.dirname(path),
        "order_num": m.group("order"),
        "name": m.group("name"),
        "trim_w": tw,
        "trim_h": th,
        "paper": f"{m.group('paper_w')}x{m.group('paper_h')}",
        "binding": m.group("binding"),
        "mtime": mtime,
        "year": datetime.fromtimestamp(mtime).year if mtime else None,
    }


def _scan_all_templates(dirs, force: bool = False) -> list:
    """
    Рекурсивно сканирует БЫСТРЫЕ (локальные) папки шаблонов из dirs
    (включая вложенные подпапки) и возвращает список ВСЕХ .tpl-файлов
    с разобранными из имени параметрами — без фильтрации под
    конкретный заказ. Результат кэшируется на _TEMPLATES_CACHE_TTL
    секунд; force=True заставляет пересканировать сейчас же
    (используется кнопкой ↺ "Обновить").

    Заодно (в том же проходе по диску) запоминает пути ВСЕХ .tpl
    файлов, включая те, что не подходят под формат имени — например,
    пустые шаблоны-заготовки ("пустой шаблон Saddle Stitched.tpl" и
    т.п.), используемые как основа при создании нового шаблона (см.
    _find_base_template).

    ВАЖНО: сюда передаются только "быстрые" папки (config.preps_
    templates) — медленный сетевой архив (config.preps_templates_
    archive) сканируется отдельно и вручную, см. _rescan_archive_to_db.
    """
    now = time.monotonic()
    dirs_key = tuple(dirs)
    cached = _TEMPLATES_CACHE
    if (not force
            and cached["data"] is not None
            and cached["dirs"] == dirs_key
            and now - cached["timestamp"] < _TEMPLATES_CACHE_TTL):
        return cached["data"]

    all_templates = []
    all_tpl_paths = []
    seen_paths = set()
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        # Рекурсивно обходим все вложенные подпапки — шаблоны могут
        # быть разложены по годам/заказчикам/типам и т.п., а не
        # только лежать прямо в корне указанной папки.
        try:
            walker = os.walk(d)
        except Exception:
            continue
        for root, _subdirs, files in walker:
            for fname in files:
                if not fname.lower().endswith(".tpl"):
                    continue
                path = os.path.join(root, fname)
                all_tpl_paths.append(path)

                if path in seen_paths:
                    continue
                seen_paths.add(path)

                record = _parse_template_record(path, fname, source_dir=d)
                if record:
                    all_templates.append(record)

    # Сначала новые — по дате изменения файла шаблона (убывание)
    all_templates.sort(key=lambda r: r["mtime"], reverse=True)

    cached["data"] = all_templates
    cached["timestamp"] = now
    cached["dirs"] = dirs_key
    cached["all_tpl_paths"] = all_tpl_paths
    return all_templates


def _rescan_archive_to_db(dirs) -> int:
    """
    Полностью пересканирует МЕДЛЕННЫЕ (сетевые) архивные папки
    шаблонов (config.preps_templates_archive) и заменяет содержимое
    таблицы preps_template_cache в БД новым списком. Вызывается
    ТОЛЬКО вручную (кнопка "Обновить архив шаблонов") — не при
    обычном поиске, т.к. это может быть медленно (сеть). Возвращает
    количество найденных шаблонов.
    """
    records = []
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        try:
            walker = os.walk(d)
        except Exception:
            continue
        for root, _subdirs, files in walker:
            for fname in files:
                if not fname.lower().endswith(".tpl"):
                    continue
                path = os.path.join(root, fname)
                record = _parse_template_record(path, fname, source_dir=d)
                if record:
                    records.append(record)

    db_records = [
        {
            "path": r["path"], "fname": r["fname"],
            "order_num": r["order_num"], "name": r["name"],
            "trim_w": r["trim_w"], "trim_h": r["trim_h"],
            "paper": r["paper"], "binding": r["binding"],
            "mtime": r["mtime"],
        }
        for r in records
    ]
    replace_preps_template_cache(db_records)
    return len(records)


def _get_archive_templates() -> list:
    """
    Возвращает список шаблонов из архивного кэша в БД (см.
    PrepsTemplateCache / _rescan_archive_to_db), в ТОМ ЖЕ формате,
    что и _scan_all_templates — чтобы фильтрация под заказ
    (_scan_preps_templates) не зависела от источника. НЕ обращается
    к диску/сети — только к БД, поэтому быстро всегда.
    """
    rows = get_preps_template_cache()
    result = []
    for row in rows:
        year = None
        if row.mtime:
            try:
                year = datetime.fromtimestamp(row.mtime).year
            except (OSError, OverflowError, ValueError):
                year = None
        result.append({
            "fname": row.fname,
            "path": row.path,
            "source_dir": os.path.dirname(row.path),
            "order_num": row.order_num,
            "name": row.name,
            "trim_w": row.trim_w,
            "trim_h": row.trim_h,
            "paper": row.paper,
            "binding": row.binding,
            "mtime": row.mtime or 0,
            "year": year,
            "from_archive": True,
        })
    return result


def _scan_preps_templates(order, force: bool = False) -> list:
    """
    Ищет .tpl-шаблоны Preps, подходящие под обрезной формат и тип
    скрепления заказа — из двух источников:
      • "быстрые" папки (config.preps_templates) — сканируются с
        диска напрямую (см. _scan_all_templates), force=True
        пересканирует сейчас же (кнопка ↺);
      • "архивные" папки (config.preps_templates_archive) — берутся
        из кэша в БД (см. _get_archive_templates), диск/сеть НЕ
        трогаются (обновляется отдельной кнопкой "Обновить архив").

    Если с учётом скрепления ничего не нашлось — повторяем поиск
    только по обрезному формату (без учёта скрепления), чтобы не
    оставлять пользователя совсем без вариантов.
    """
    if not order or not order.width or not order.height:
        return []

    live_dirs = config.CFG.get("preps_templates", [])
    trim_pair = {int(order.width), int(order.height)}
    binding_code  = order.binding or ""
    binding_label = binding_code_to_label(order.binding) if order.binding else ""

    live_templates = _scan_all_templates(live_dirs, force=force)
    archive_templates = _get_archive_templates()

    seen_paths = set()

    def _filter(require_binding: bool) -> list:
        out = []
        for tpl in (live_templates + archive_templates):
            if {tpl["trim_w"], tpl["trim_h"]} != trim_pair:
                continue
            if require_binding and binding_code and not _binding_matches(binding_code, binding_label, tpl["binding"]):
                continue
            path = tpl["path"]
            if path in seen_paths:
                continue
            seen_paths.add(path)
            item = dict(tpl)
            item["trim"] = f"{tpl['trim_w']}x{tpl['trim_h']}"
            out.append(item)
        return out

    results = _filter(require_binding=True)
    if not results:
        # Запасной вариант — искать только по обрезному формату,
        # без учёта скрепления (см. описание метода).
        seen_paths.clear()
        results = _filter(require_binding=False)

    results.sort(key=lambda r: r["mtime"], reverse=True)
    return results


def _find_base_template(kind: str) -> str:
    """
    Ищет пустой шаблон-заготовку Preps (без номера заказа в имени),
    используемую как основа при создании нового шаблона (заголовок
    + пустой лист, без сигнатур). kind: "saddle" (Saddle Stitched —
    для скрепки) или "perfect" (Perfect Bound — для всего
    остального).

    Приоритет: явный путь в config.json → preps_empty_templates →
    {saddle|perfect}. Если не задан или файл не найден — ищем в
    папках preps_templates файл, в имени которого есть оба ключевых
    слова ("saddle"+"stitch" или "perfect"+"bound"), регистр не
    важен — под это подходят присланные "пустой шаблон Saddle
    Stitched.tpl" / "пустой шаблон Perfect Bound.tpl".
    """
    override = (config.CFG.get("preps_empty_templates", {}) or {}).get(kind)
    if override and os.path.isfile(override):
        return override

    dirs = config.CFG.get("preps_templates", [])
    _scan_all_templates(dirs)  # обеспечиваем свежий кэш (без force)
    keywords = {
        "saddle":  ("saddle", "stitch"),
        "perfect": ("perfect", "bound"),
    }.get(kind, ())
    if not keywords:
        return None

    for path in _TEMPLATES_CACHE.get("all_tpl_paths") or []:
        low = os.path.basename(path).lower()
        if all(k in low for k in keywords):
            return path
    return None


# ── Разбор содержимого .tpl (сигнатуры) ──────────────────────────────
# Формат .tpl Preps официально не документирован — разбор ниже основан
# на анализе реальных файлов (Preps 5.3.3) и сверен с тем, что Preps
# показывает в диалогах "Margin Widths"/"Gutter Widths" для примера
# (клапан 15 мм, Gutter Top/Bottom Half по 3 мм = 6 мм):
#   • формат листа и ориентация сигнатуры — из строки %SSiPressSheet,
#     идущей сразу за %SSiSignature: (ширина/высота листа);
#   • клапан (Bottom margin при горизонтальном листе / Left margin при
#     вертикальном) — это отступ (X или Y) первой реальной страницы
#     от края листа, из первой строки %SSiPrshPage: внутри сигнатуры
#     с ненулевыми шириной/высотой (т.е. это уже размещённая страница,
#     а не "дефолтная" нулевая заготовка);
#   • Gutter Widths (расстояние между страницами в голове) — считается
#     напрямую из фактического зазора между соседними рядами/
#     колонками страниц этой же сигнатуры (см. _parse_tpl_file); если
#     в сигнатуре только один ряд/колонка — используется запасной
#     вариант: общее значение из %SSiPressSheet в шапке файла (единое
#     на весь шаблон). Делится пополам на "Top Half"/"Bottom Half".
# Если для нестандартного/старого файла что-то из этого не находится —
# показываем "—"; на копирование сигнатуры это не влияет (копируется
# исходный текст блока как есть).
_PT_PER_MM = 72 / 25.4

_SIG_LINE_RE = re.compile(
    r"^%SSiSignature:\s*\|(?P<name>[^|]*)\|\s+(?P<pages>\d+)", re.IGNORECASE
)
_PRESSSHEET_RE = re.compile(
    r"^%SSiPressSheet:\s+([\d.]+)\s+([\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+"
    r"(\d+)\s+([\d.]+)\s+(\d+)\s+([\d.]+)\s+(\d+)"
)
_PRSHPAGE_RE = re.compile(
    r"^%SSiPrshPage:\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)"
)
_PRSHMATRIX_RE = re.compile(
    r"^%SSiPrshMatrix:\s+(\d+)\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)"
)


def _mm(pt: float) -> float:
    return round(pt / _PT_PER_MM, 1)


def _find_gutter_half_pt(raw_lines: list) -> float:
    """
    Ищет в блоке сигнатуры половину Gutter Widths (то, что Preps
    показывает как "Top Half"/"Bottom Half" или "Left Half"/"Right
    Half" — ось зависит от раскладки конкретной сигнатуры, поэтому в
    интерфейсе показываем значение без указания стороны).

    Источник — строка "%SSiPrshMatrix: 4 <X> <X> <флаг>" с ОДИНАКОВЫМИ
    двумя значениями (это и есть половина зазора, повторённая дважды
    для симметрии). Подтверждено на реальных примерах:
      • обычная сеточная сигнатура (несколько рядов/колонок страниц)
        — нужная строка оканчивается флагом "0";
      • разворотная обложка "голова к голове" (2 страницы, флага "0"
        с одинаковыми X X нет вовсе) — нужная строка оканчивается
        флагом "1".
    Поэтому: сначала ищем первую подходящую строку с флагом "0";
    если её нет — берём первую с флагом "1". Возвращает половину в pt
    или None, если такой строки нет вовсе (тогда в интерфейсе будет
    показано "—", а не гадание).
    """
    candidates_0, candidates_1 = [], []
    for line in raw_lines:
        m = _PRSHMATRIX_RE.match(line)
        if not m:
            continue
        idx, a, b, flag = m.groups()
        if idx != "4":
            continue
        a, b = float(a), float(b)
        if a <= 0 or abs(a - b) > 0.01:
            continue  # не пара одинаковых значений — не то поле
        if flag == "0":
            candidates_0.append(a)
        elif flag == "1":
            candidates_1.append(a)
    if candidates_0:
        return candidates_0[0]
    if candidates_1:
        return candidates_1[0]
    return None


_TPL_PARSE_CACHE = {}  # path -> (mtime, header_lines, signatures)


def _parse_tpl_file(path: str, force: bool = False) -> tuple:
    """
    Разбирает .tpl файл на "шапку" (всё до первой %SSiSignature:) и
    список сигнатур. Каждая сигнатура — от своей строки %SSiSignature:
    до строки перед следующей %SSiSignature: (или до конца файла),
    включительно, с сохранением исходных строк как есть (raw_lines) —
    именно этот кусок текста копируется в новый шаблон при нажатии
    "Добавить в шаблон".

    Кэшируется по (путь, mtime файла) — повторное открытие того же
    шаблона в интерфейсе не читает файл с диска заново, пока он не
    изменился.
    """
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0

    cached = _TPL_PARSE_CACHE.get(path)
    if not force and cached and cached[0] == mtime:
        return cached[1], cached[2]

    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            lines = f.readlines()
    except Exception:
        return [], []

    header_lines = []
    signatures = []
    current = None

    for line in lines:
        if line.startswith("%SSiSignature:"):
            if current is not None:
                signatures.append(current)
            current = {"raw_lines": [line], "header_line": line}
        elif current is not None:
            current["raw_lines"].append(line)
        else:
            header_lines.append(line)
    if current is not None:
        signatures.append(current)

    parsed_sigs = []
    for sig in signatures:
        info = {
            "name": None,
            "pages": None,
            "press_format": None,
            "orientation": None,     # "horizontal" | "vertical"
            "clapan_mm": None,
            "clapan_side": None,     # "Bottom" | "Left"
            "gutter_half_mm": None,
            "gutter_total_mm": None,
            "raw_lines": sig["raw_lines"],
        }
        m = _SIG_LINE_RE.match(sig["header_line"])
        if m:
            info["name"] = m.group("name") or "(без имени)"
            try:
                info["pages"] = int(m.group("pages"))
            except ValueError:
                pass

        # Формат печатного листа и ориентация — из первой строки
        # %SSiPressSheet: внутри блока сигнатуры.
        horizontal = None
        for line in sig["raw_lines"][1:]:
            pm = _PRESSSHEET_RE.match(line)
            if pm:
                w_mm, h_mm = _mm(float(pm.group(1))), _mm(float(pm.group(2)))
                # Формат листа в имени шаблонов задаётся в см
                # (72x52 = 720x520 мм) — округляем до см для показа.
                info["press_format"] = f"{round(w_mm / 10)}x{round(h_mm / 10)}"
                horizontal = w_mm >= h_mm
                info["orientation"] = "horizontal" if horizontal else "vertical"
                info["clapan_side"] = "Bottom" if horizontal else "Left"
                break

        # Клапан — на основе первой реально размещённой страницы
        # сигнатуры (не "нулевой" заготовки) из строк %SSiPrshPage:.
        # Клапан (Bottom margin при горизонтальном листе / Left margin
        # при вертикальном) — отступ первой страницы (Y или X) от края
        # листа. Подтверждено верным на всех 15 сигнатурах реального
        # шаблона (и обычных сеточных, и разворотных обложках).
        real_pages = []
        for line in sig["raw_lines"][1:]:
            ppm = _PRSHPAGE_RE.match(line)
            if not ppm:
                continue
            x, y, w, h = (float(v) for v in ppm.groups())
            if w > 0 and h > 0:
                real_pages.append((x, y, w, h))

        if real_pages and horizontal is not None:
            first_x, first_y, first_w, first_h = real_pages[0]
            offset = first_y if horizontal else first_x
            info["clapan_mm"] = round(offset / _PT_PER_MM, 1)

        # Gutter Widths (расстояние между страницами в голове) — см.
        # _find_gutter_half_pt: подтверждено верным и на обычной
        # сеточной сигнатуре, и на разворотной обложке "голова к
        # голове" (где страницы стоят "лицом друг к другу" без общего
        # ряда/колонки — там зазор геометрией не вычислить).
        gutter_half_pt = _find_gutter_half_pt(sig["raw_lines"])
        if gutter_half_pt is not None:
            half_mm = round(gutter_half_pt / _PT_PER_MM, 1)
            info["gutter_half_mm"] = half_mm
            info["gutter_total_mm"] = round(half_mm * 2, 1)

        parsed_sigs.append(info)

    _TPL_PARSE_CACHE[path] = (mtime, header_lines, parsed_sigs)
    return header_lines, parsed_sigs


def _sanitize_name_for_filename(name: str) -> str:
    """Убирает из названия заказа символы, недопустимые в имени файла
    (и подчёркивания-разделители самого имени шаблона)."""
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    name = re.sub(r"\s+", "", name)
    return name or "Order"


def order_folder_name_part(order) -> str:
    """
    Название для имени файла нового шаблона — ТО ЖЕ САМОЕ, что
    используется в реальном имени папки заказа на диске (папка
    создаётся в order_page.py с транслитерацией кириллицы и
    очисткой имени — см. функцию translit() там же). Берём его прямо
    из фактического пути order.folder_path (обрезая номерной префикс
    "NNNN_"), чтобы имя в шаблоне гарантированно совпадало с папкой,
    а не дублировало логику транслитерации отдельно.
    """
    folder_path = getattr(order, "folder_path", None) if order else None
    if folder_path:
        # Разбираем путь вручную по обоим вариантам разделителя
        # (\ и /) — os.path.basename зависит от ОС, на которой
        # выполняется код, а order.folder_path всегда в формате
        # Windows-пути (сеть/диск P:), даже если сам код когда-то
        # запускается для тестов не на Windows.
        parts = [p for p in re.split(r"[\\/]+", str(folder_path)) if p]
        base = parts[-1] if parts else ""
        m = re.match(r"^\d+_(.+)$", base)
        if m and m.group(1):
            return m.group(1)
        if base:
            return base
    # Запасной вариант — папка заказа ещё не создана на диске,
    # используем упрощённую очистку "сырого" названия заказа.
    return _sanitize_name_for_filename(order.name if order else "")


def build_template_filename(order, press_format: str, binding_token: str) -> str:
    """
    Собирает имя нового шаблона по принятой схеме:
        <номер>_<название>_<обрезнойформат>_<форматбумаги>_<скрепление>.tpl
    напр. "0027_Comix_163x245_72x52_Shitie.tpl"
    Название — то же, что в имени папки заказа на диске (см.
    order_folder_name_part).
    """
    number = f"{order.number:04d}" if order and order.number else "0000"
    name = order_folder_name_part(order)
    trim = f"{int(order.width)}x{int(order.height)}" if order and order.width and order.height else "0x0"
    press = (press_format or "").strip().replace(" ", "")
    binding_token = (binding_token or "").strip()
    return f"{number}_{name}_{trim}_{press}_{binding_token}.tpl"


def build_new_template_content(base_path: str, new_name_no_ext: str, signatures_raw: list) -> list:
    """
    Собирает содержимое нового .tpl: берёт "шапку" из base_path
    (пустой шаблон-заготовка Saddle Stitched/Perfect Bound), меняет в
    ней внутреннее имя макета (строки "Template File: ...путь..." и
    "%SSiLayout: |имя| |имя| ...") на новое, и дописывает в конец
    сырые блоки выбранных сигнатур (raw_lines — как есть, без
    пересчёта координат: сигнатура просто копируется в новый файл).
    Возвращает список строк (с их исходными \\r\\n) — записывать через
    open(path, "w", encoding="utf-8", newline="").
    """
    header_lines, _sigs = _parse_tpl_file(base_path)
    if not header_lines:
        with open(base_path, "r", encoding="utf-8", errors="replace", newline="") as f:
            header_lines = f.readlines()

    out_lines = []
    for line in header_lines:
        stripped = line.rstrip("\r\n")
        if "Template File:" in stripped:
            out_lines.append(f"% This: Template File: {new_name_no_ext}.tpl\r\n")
        elif stripped.startswith("%SSiLayout:"):
            m = re.match(r"^(%SSiLayout:\s*\|)[^|]*(\|\s*\|)[^|]*(\|.*)$", stripped)
            if m:
                out_lines.append(f"{m.group(1)}{new_name_no_ext}{m.group(2)}{new_name_no_ext}{m.group(3)}\r\n")
            else:
                out_lines.append(line)
        else:
            out_lines.append(line)

    for raw_lines in signatures_raw:
        out_lines.extend(raw_lines)

    return out_lines


class ImpositionPage(ctk.CTkFrame):
    def __init__(self, parent, app, order_id: int = None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self.order_id = order_id
        self.order = None
        self._img_path = None
        self._sheets = []

        # Превью фото спуска (в центральной панели, с зумом)
        self._preview_pil_image = None
        self._preview_tk_image  = None
        self._preview_zoom      = _DEFAULT_PREVIEW_ZOOM

        # Сохранённая ранее (в БД) запись спуска полос для этого
        # заказа, если она есть — подхватываем фото и сетку.
        self.imposition = None

        # "Черновик" нового шаблона Preps, который собирается из
        # сигнатур, добавляемых из уже существующих шаблонов (см.
        # _open_create_template_dialog / _add_signature_to_draft).
        # None — черновика нет, показываем кнопку "Создать шаблон".
        self._tpl_draft = None
        # path -> bool, какие карточки шаблонов сейчас развёрнуты
        # (показывают список своих сигнатур)
        self._tpl_expanded = {}

        if order_id:
            session = get_session()
            try:
                self.order = session.get(Order, order_id)
            finally:
                session.close()
            self.imposition = get_imposition(order_id)

        self._build()
        self._refresh_templates()
        self._load_existing_imposition()

    # ── LAYOUT ────────────────────────────────────────────────────
    def _build(self):
        # Три панели, как на странице заказа: левая (контролы) —
        # центр (фото/сетка спуска) — правая (шаблоны Preps). Границы
        # можно перетаскивать. Левая панель по умолчанию СКРЫТА —
        # открывается кнопкой в верхней панели инструментов.
        self.pack_propagate(False)
        try:
            win_w = self.app.cfg.get("window_width", 1400)
        except Exception:
            win_w = 1400
        left_default_w  = 320
        right_default_w = max(320, int(win_w * 0.25))
        self._left_default_w = left_default_w

        is_dark = ctk.get_appearance_mode().lower() == "dark"
        sash_bg = "#242424" if is_dark else "#d5d5d5"

        # ── Верхняя панель инструментов — переключатель сайдбара ──
        toolbar = ctk.CTkFrame(self, fg_color=("gray85","gray20"), height=32, corner_radius=0)
        toolbar.pack(fill="x", side="top")
        toolbar.pack_propagate(False)

        self._sidebar_btn = ctk.CTkButton(
            toolbar, text="☰  Показать панель", width=180, height=24,
            font=("JetBrains Mono", 10),
            fg_color=("gray80","gray25"), hover_color=DARK_BD2,
            border_width=1,
            command=self._toggle_sidebar,
        )
        self._sidebar_btn.pack(side="left", padx=10, pady=4)

        self._paned = tk.PanedWindow(
            self, orient="horizontal", sashwidth=6, sashrelief="flat",
            bg=sash_bg, bd=0,
        )
        self._paned.pack(fill="both", expand=True)

        # ── Левая панель — контролы ──────────────────────────────
        # ВАЖНО: CTkScrollableFrame нельзя добавлять в PanedWindow
        # напрямую (сложная внутренняя структура canvas/frame) —
        # оборачиваем в обычный CTkFrame-контейнер. Панель по
        # умолчанию НЕ добавляется в paned window (скрыта) — см.
        # _toggle_sidebar.
        left_container = ctk.CTkFrame(
            self._paned, fg_color=("gray90","gray17"), corner_radius=0,
        )
        self._left_container = left_container
        self._sidebar_visible = False

        left = ctk.CTkScrollableFrame(
            left_container, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=DARK_BD,
        )
        left.pack(fill="both", expand=True)

        def lbl(t):
            return ctk.CTkLabel(
                left, text=t,
                font=("JetBrains Mono", 9), text_color=("gray40","gray60"), anchor="w"
            )

        # ── Фото ──────────────────────────────────────────────────
        # Сама загрузка/просмотр фото спуска (с зумом) теперь живёт
        # в центральной панели — как у спецификации на странице
        # заказа. Здесь, в сайдбаре, оставляем только компактный
        # статус.
        lbl("ФОТО СПУСКА").pack(anchor="w", padx=16, pady=(16, 6))
        self._photo_status_lbl = ctk.CTkLabel(
            left,
            text="Перетащите или кликните превью,\nчтобы выбрать фото",
            font=("JetBrains Mono", 10), text_color=TEXT3,
            justify="left", anchor="w", wraplength=270,
        )
        self._photo_status_lbl.pack(anchor="w", padx=16, fill="x")

        ctk.CTkFrame(left, fg_color=("gray80","gray25"), height=1).pack(fill="x", pady=10)

        # ── Сетка ─────────────────────────────────────────────────
        lbl("ПАРАМЕТРЫ СЕТКИ").pack(anchor="w", padx=16, pady=(0, 6))
        grid_f = ctk.CTkFrame(left, fg_color="transparent")
        grid_f.pack(fill="x", padx=16)
        grid_f.columnconfigure(1, weight=1)

        self.v_rows = tk.StringVar(value=str(self.imposition.rows) if self.imposition and self.imposition.rows else "4")
        self.v_cols = tk.StringVar(value=str(self.imposition.cols) if self.imposition and self.imposition.cols else "4")
        self.v_two  = tk.BooleanVar(value=self.imposition.two_sided if self.imposition and self.imposition.two_sided is not None else True)

        for row, (label, var) in enumerate([
            ("Рядов",   self.v_rows),
            ("Колонок", self.v_cols),
        ]):
            ctk.CTkLabel(
                grid_f, text=label,
                font=("JetBrains Mono", 10), text_color=TEXT3
            ).grid(row=row, column=0, sticky="w", pady=4)
            ctk.CTkEntry(
                grid_f, textvariable=var, width=80,
                font=("JetBrains Mono", 12),
                fg_color=("gray85","gray20"),  text_color=TEXT
            ).grid(row=row, column=1, sticky="e", pady=4)

        ctk.CTkCheckBox(
            left, text="Два спуска (лицо + оборот)",
            variable=self.v_two,
            font=("JetBrains Mono", 11), 
            fg_color=ACCENT2, checkmark_color=DARK_BG,
        ).pack(anchor="w", padx=16, pady=(6, 0))

        ctk.CTkFrame(left, fg_color=("gray80","gray25"), height=1).pack(fill="x", pady=10)

        # ── AI движок ─────────────────────────────────────────────
        lbl("AI ДВИЖОК").pack(anchor="w", padx=16, pady=(0, 6))

        self.v_engine = tk.StringVar(value="ollama")
        ctk.CTkSegmentedButton(
            left, values=["ollama", "claude"],
            variable=self.v_engine,
            font=("JetBrains Mono", 10),
            selected_color=ACCENT2,
            unselected_color=DARK_SF2,
            
            command=self._on_engine_change,
        ).pack(fill="x", padx=16)

        # ── Ollama настройки ──────────────────────────────────────
        self.ollama_frame = ctk.CTkFrame(left, fg_color="transparent")
        self.ollama_frame.pack(fill="x", padx=16, pady=(8, 0))

        lbl2 = lambda t: ctk.CTkLabel(
            self.ollama_frame, text=t,
            font=("JetBrains Mono", 9), text_color=("gray40","gray60"), anchor="w"
        )

        lbl2("URL прокси / Ollama").pack(anchor="w", pady=(0, 2))
        self.v_ollama_url = tk.StringVar(value="http://localhost:11434/api/generate")
        ctk.CTkEntry(
            self.ollama_frame, textvariable=self.v_ollama_url,
            font=("JetBrains Mono", 11),
            fg_color=("gray85","gray20"),  
        ).pack(fill="x", pady=(0, 6))

        lbl2("Модель").pack(anchor="w", pady=(0, 2))
        self.v_ollama_model = tk.StringVar(value="qwen2-vl:7b")
        
        # Заменяем CTkEntry на CTkComboBox
        ctk.CTkComboBox(
            self.ollama_frame, 
            variable=self.v_ollama_model,               # Передает и принимает значение
            values=["qwen2-vl:7b", "qwen2.5vl:7b", "qwen2:latest", "llava:7b"], # Список вариантов
            font=("JetBrains Mono", 11),
            dropdown_font=("JetBrains Mono", 11),       # Шрифт для выпадающего списка
            fg_color=("gray85","gray20"),
        ).pack(fill="x", pady=(0, 6))

        # Кнопка ping + статус
        ping_row = ctk.CTkFrame(self.ollama_frame, fg_color="transparent")
        ping_row.pack(fill="x", pady=(0, 4))

        ctk.CTkButton(
            ping_row, text="⟳ Проверить соединение",
            font=("JetBrains Mono", 10),
            fg_color=("gray85","gray20"), hover_color=DARK_BD2,
             border_width=1,
             height=28,
            command=self._ping_ollama,
        ).pack(side="left", fill="x", expand=True)

        self._ping_dot = ctk.CTkLabel(
            ping_row, text="●", width=20,
            font=("Arial", 14), text_color=TEXT3
        )
        self._ping_dot.pack(side="left", padx=(6, 0))

        self._ping_status = ctk.CTkLabel(
            self.ollama_frame, text="Не проверено",
            font=("JetBrains Mono", 9), text_color=("gray40","gray60"), anchor="w"
        )
        self._ping_status.pack(anchor="w")

        ctk.CTkFrame(left, fg_color=("gray80","gray25"), height=1).pack(fill="x", pady=10)

        # ── Кнопка распознать ─────────────────────────────────────
        self.btn_analyze = ctk.CTkButton(
            left,
            text="▶  Распознать",
            font=("JetBrains Mono", 13, "bold"),
            fg_color=ACCENT, hover_color=ACCENT2,
            text_color="black", height=38,
            command=self._analyze,
            state="disabled",
        )
        self.btn_analyze.pack(fill="x", padx=16, pady=(0, 6))

        self._status_lbl = ctk.CTkLabel(
            left, text="Загрузите фото спуска",
            font=("JetBrains Mono", 10), text_color=("gray40","gray60"), wraplength=270
        )
        self._status_lbl.pack(padx=16, pady=(0, 10))

        ctk.CTkFrame(left, fg_color=("gray80","gray25"), height=1).pack(fill="x", pady=4)

        # ── Экспорт ───────────────────────────────────────────────
        lbl("ЭКСПОРТ").pack(anchor="w", padx=16, pady=(8, 6))
        for label, cmd in [
            ("⬇  Скачать TPL + JOB", self._export_both),
            ("↓  Только .tpl",        self._export_tpl),
            ("↓  Только .job",        self._export_job),
        ]:
            ctk.CTkButton(
                left, text=label,
                font=("JetBrains Mono", 11),
                fg_color=("gray85","gray20"), hover_color=DARK_BD2,
                 border_width=1,
                 height=30,
                command=cmd,
            ).pack(fill="x", padx=16, pady=2)

        ctk.CTkButton(
            left, text="💾  Сохранить спуск",
            font=("JetBrains Mono", 11, "bold"),
            fg_color=("gray85","gray20"), hover_color=DARK_BD2,
            border_width=1, height=30,
            command=self._save_imposition_to_db,
        ).pack(fill="x", padx=16, pady=(8, 16))

        # ── Центральная панель — фото / сетка спуска ─────────────
        center = ctk.CTkFrame(self._paned, fg_color="transparent", corner_radius=0)
        self._paned.add(center, minsize=300, stretch="always")
        self._build_center(center)

        # ── Правая панель — шаблоны Preps ────────────────────────
        right_container = ctk.CTkFrame(self._paned, fg_color="transparent", corner_radius=0)
        right_container.grid_rowconfigure(0, weight=1)
        right_container.grid_columnconfigure(0, weight=1)
        self._paned.add(right_container, width=right_default_w, minsize=280, stretch="never")
        self._build_templates_panel(right_container)

    # ── SIDEBAR TOGGLE ───────────────────────────────────────────
    def _toggle_sidebar(self):
        if self._sidebar_visible:
            self._paned.forget(self._left_container)
            self._sidebar_visible = False
            self._sidebar_btn.configure(text="☰  Показать панель")
        else:
            first_pane = self._paned.panes()[0] if self._paned.panes() else None
            if first_pane:
                self._paned.add(
                    self._left_container, width=self._left_default_w,
                    minsize=280, stretch="never", before=first_pane,
                )
            else:
                self._paned.add(
                    self._left_container, width=self._left_default_w,
                    minsize=280, stretch="never",
                )
            self._sidebar_visible = True
            self._sidebar_btn.configure(text="☰  Скрыть панель")

    # ── ЦЕНТРАЛЬНАЯ ПАНЕЛЬ (фото / сетка) ────────────────────────
    def _build_center(self, parent):
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        # Верхняя мини-панель — переключатель "Фото / Сетка" + зум
        nav = ctk.CTkFrame(parent, fg_color=("gray85","gray20"), height=36, corner_radius=0)
        nav.grid(row=0, column=0, sticky="ew")
        nav.grid_propagate(False)

        self._view_seg = ctk.CTkSegmentedButton(
            nav, values=["📷 Фото", "▦ Сетка"],
            font=("JetBrains Mono", 10),
            selected_color=ACCENT2, unselected_color=DARK_SF2,
            command=self._on_view_change,
        )
        self._view_seg.set("📷 Фото")
        self._view_seg.pack(side="left", padx=10, pady=4)

        # Управление зумом (актуально только для вида "Фото")
        self._zoom_box = ctk.CTkFrame(nav, fg_color="transparent")
        self._zoom_box.pack(side="right", padx=10, pady=4)

        ctk.CTkButton(
            self._zoom_box, text="−", width=26, height=24, font=("JetBrains Mono", 13, "bold"),
            fg_color=("gray80","gray25"), hover_color=DARK_BD2,
            command=self._zoom_out,
        ).pack(side="left", padx=2)

        self._zoom_lbl = ctk.CTkLabel(
            self._zoom_box, text="—", font=("JetBrains Mono", 10), width=42,
        )
        self._zoom_lbl.pack(side="left", padx=2)

        ctk.CTkButton(
            self._zoom_box, text="+", width=26, height=24, font=("JetBrains Mono", 13, "bold"),
            fg_color=("gray80","gray25"), hover_color=DARK_BD2,
            command=self._zoom_in,
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            self._zoom_box, text="⤢ 100%", width=56, height=24, font=("JetBrains Mono", 10),
            fg_color=("gray80","gray25"), hover_color=DARK_BD2,
            command=self._zoom_reset,
        ).pack(side="left", padx=(6, 0))

        # Область содержимого — фото и сетка лежат друг на друге,
        # переключение через tkraise() (см. _on_view_change)
        content = ctk.CTkFrame(parent, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self._photo_frame = ctk.CTkFrame(content, fg_color=("gray88","gray14"), corner_radius=0)
        self._photo_frame.grid(row=0, column=0, sticky="nsew")
        self._grid_frame = ctk.CTkFrame(content, fg_color="transparent")
        self._grid_frame.grid(row=0, column=0, sticky="nsew")

        self._build_photo_canvas(self._photo_frame)
        self._build_empty_state()

        self._view_mode = "photo"
        self._photo_frame.tkraise()

    def _on_view_change(self, value: str):
        if value.startswith("📷"):
            self._view_mode = "photo"
            self._photo_frame.tkraise()
            self._zoom_box.pack(side="right", padx=10, pady=4)
        else:
            self._view_mode = "grid"
            self._grid_frame.tkraise()
            self._zoom_box.pack_forget()

    # ── ФОТО — превью с зумом (как на странице заказа) ──────────
    def _build_photo_canvas(self, parent):
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        canvas_bg = "#161616" if is_dark else "#dcdcdc"

        self._preview_canvas = tk.Canvas(
            parent, bg=canvas_bg, highlightthickness=0, bd=0,
        )
        self._preview_canvas.pack(fill="both", expand=True)

        self._preview_canvas.bind("<Configure>", lambda e: self._render_preview())
        # Зум колесом мыши
        self._preview_canvas.bind("<MouseWheel>", self._on_preview_wheel)        # Windows/macOS
        self._preview_canvas.bind("<Button-4>", lambda e: self._zoom_step(1))    # Linux — вверх
        self._preview_canvas.bind("<Button-5>", lambda e: self._zoom_step(-1))   # Linux — вниз
        # Клик по пустому превью — выбор файла; если фото уже
        # загружено — то же нажатие панорамирует (двигает) его.
        self._preview_canvas.bind("<ButtonPress-1>", self._on_preview_click)
        self._preview_canvas.bind("<B1-Motion>", self._on_preview_drag)

        # Drag-and-drop фото спуска — прямо на превью
        try:
            self._preview_canvas.drop_target_register("DND_Files")
            self._preview_canvas.dnd_bind("<<Drop>>", self._on_photo_drop)
        except Exception:
            pass

        self._render_preview()

    # ── ZOOM ──────────────────────────────────────────────────────
    def _on_preview_wheel(self, event):
        direction = 1 if event.delta > 0 else -1
        self._zoom_step(direction)

    def _zoom_step(self, direction: int):
        if not self._preview_pil_image:
            return
        factor = 1.15 if direction > 0 else (1 / 1.15)
        self._preview_zoom = max(0.15, min(8.0, self._preview_zoom * factor))
        self._render_preview()

    def _zoom_in(self):
        self._zoom_step(1)

    def _zoom_out(self):
        self._zoom_step(-1)

    def _zoom_reset(self):
        """Возврат к масштабу «вписать в окно»."""
        self._preview_zoom = 1.0
        self._render_preview()

    def _on_preview_click(self, event):
        """Клик по превью: если фото ещё нет — открываем диалог
        выбора файла; если уже загружено — начинаем панорамирование."""
        if self._preview_pil_image is None:
            self._pick_photo()
        else:
            self._preview_canvas.scan_mark(event.x, event.y)

    def _on_preview_drag(self, event):
        if self._preview_pil_image is not None:
            self._preview_canvas.scan_dragto(event.x, event.y, gain=1)

    def _render_preview(self):
        """Перерисовывает превью фото спуска на холсте с учётом
        текущего зума."""
        if not hasattr(self, "_preview_canvas"):
            return
        canvas = self._preview_canvas
        cw = max(1, canvas.winfo_width())
        ch = max(1, canvas.winfo_height())

        if not self._preview_pil_image:
            canvas.delete("all")
            canvas.create_text(
                cw // 2, ch // 2,
                text="📷\n\nПеретащите фото спуска сюда\nили нажмите для выбора файла",
                fill=TEXT3, font=("JetBrains Mono", 20), justify="center",
            )
            canvas.configure(scrollregion=(0, 0, cw, ch))
            if hasattr(self, "_zoom_lbl"):
                self._zoom_lbl.configure(text="—")
            return

        try:
            from PIL import Image, ImageTk
        except ImportError:
            return

        img = self._preview_pil_image
        iw, ih = img.size
        fit_scale = min(cw / iw, ch / ih) if iw and ih else 1.0
        fit_scale = max(fit_scale, 0.01)
        scale = max(0.02, fit_scale * self._preview_zoom)

        new_w = max(1, int(iw * scale))
        new_h = max(1, int(ih * scale))
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        self._preview_tk_image = ImageTk.PhotoImage(resized)

        canvas.delete("all")
        x0 = max(0, (cw - new_w) // 2)
        y0 = max(0, (ch - new_h) // 2)
        canvas.create_image(x0, y0, anchor="nw", image=self._preview_tk_image)
        region_w = max(cw, new_w)
        region_h = max(ch, new_h)
        canvas.configure(scrollregion=(0, 0, region_w, region_h))

        self._zoom_lbl.configure(text=f"{int(self._preview_zoom * 100)}%")

    # ── ШАБЛОНЫ PREPS ────────────────────────────────────────────
    def _build_templates_panel(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=("gray90","gray17"), corner_radius=0)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_rowconfigure(2, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(frame, fg_color=("gray85","gray20"), height=36, corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        ctk.CTkLabel(
            hdr, text="ШАБЛОНЫ PREPS",
            font=("JetBrains Mono", 12, "bold"), text_color=("gray15","gray90"),
            anchor="w",
        ).pack(side="left", padx=16, pady=8)
        ctk.CTkButton(
            hdr, text="↺", width=28, height=24,
            font=("JetBrains Mono", 12),
            fg_color=("gray80","gray25"), hover_color=DARK_BD2,
            command=lambda: self._refresh_templates(force=True),
        ).pack(side="right", padx=(4, 10), pady=6)
        ctk.CTkButton(
            hdr, text="🗄 Архив", width=76, height=24,
            font=("JetBrains Mono", 10),
            fg_color=("gray80","gray25"), hover_color=DARK_BD2,
            command=self._refresh_archive_cache,
        ).pack(side="right", padx=(4, 0), pady=6)

        # ── "Создать шаблон" / панель активного черновика — включает
        # название нового шаблона и (под ним) инфо о заказе, по
        # которому шаблон собирается (см. _render_draft_bar).
        self._draft_frame = ctk.CTkFrame(frame, fg_color=("gray88","gray15"), corner_radius=0)
        self._draft_frame.grid(row=1, column=0, sticky="ew")
        self._render_draft_bar()

        self.templates_list = ctk.CTkScrollableFrame(
            frame, fg_color="transparent",
            scrollbar_button_color=DARK_BD,
        )
        self.templates_list.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
        self.templates_list.grid_columnconfigure(0, weight=1)

    def _order_criteria_text(self) -> str:
        """Заказ №/Формат/Скрепление — контекст, по которому подбираются
        и называются шаблоны. Показывается под названием в панели
        "Создать шаблон" (см. _render_draft_bar)."""
        if not self.order:
            return "Заказ не найден."
        o = self.order
        fmt = f"{o.width}×{o.height} мм" if o.width and o.height else "формат не указан"
        binding = binding_code_to_label(o.binding) if o.binding else "скрепление не указано"
        return f"Заказ № {o.number:04d}\nФормат: {fmt}\nСкрепление: {binding}"

    # ── ЧЕРНОВИК НОВОГО ШАБЛОНА ("Создать шаблон") ──────────────────
    def _render_draft_bar(self):
        for w in self._draft_frame.winfo_children():
            w.destroy()

        if self._tpl_draft is None:
            ctk.CTkButton(
                self._draft_frame, text="➕  Создать шаблон",
                font=("JetBrains Mono", 12, "bold"),
                fg_color=ACCENT, hover_color=ACCENT2, text_color="black",
                height=32,
                command=self._open_create_template_dialog,
            ).pack(fill="x", padx=10, pady=(10, 6))
            ctk.CTkLabel(
                self._draft_frame, text=self._order_criteria_text(),
                font=("JetBrains Mono", 10), text_color=("gray25","gray80"),
                justify="left", anchor="w", wraplength=280,
            ).pack(fill="x", padx=10, pady=(0, 10))
            return

        draft = self._tpl_draft
        is_editing = bool(draft.get("editing_existing_path"))
        ctk.CTkLabel(
            self._draft_frame, text=("РЕДАКТИРОВАНИЕ ШАБЛОНА" if is_editing else "ЧЕРНОВИК ШАБЛОНА"),
            font=("JetBrains Mono", 9, "bold"), text_color=("gray25","gray80"), anchor="w",
        ).pack(fill="x", padx=10, pady=(10, 0))
        ctk.CTkLabel(
            self._draft_frame, text=draft["filename"],
            font=("JetBrains Mono", 12, "bold"), text_color=ACCENT_TEXT, anchor="w",
            wraplength=270, justify="left",
        ).pack(fill="x", padx=10, pady=(2, 6))
        ctk.CTkLabel(
            self._draft_frame, text=self._order_criteria_text(),
            font=("JetBrains Mono", 10), text_color=("gray25","gray80"),
            justify="left", anchor="w", wraplength=280,
        ).pack(fill="x", padx=10, pady=(0, 8))

        if not draft["signatures"]:
            ctk.CTkLabel(
                self._draft_frame,
                text="Пока пусто. Разверните шаблон в списке ниже\nи нажмите «+ Добавить в шаблон» на нужной\nсигнатуре.",
                font=("JetBrains Mono", 10), text_color=("gray30","gray70"),
                justify="left", anchor="w",
            ).pack(fill="x", padx=10, pady=(0, 6))
        else:
            for i, item in enumerate(draft["signatures"]):
                row = ctk.CTkFrame(self._draft_frame, fg_color=("gray82","gray22"), corner_radius=4)
                row.pack(fill="x", padx=10, pady=2)
                ctk.CTkLabel(
                    row, text=f"{item['sig']['name'] or '?'}  ·  {item['source_fname']}",
                    font=("JetBrains Mono", 10), text_color=("gray20","gray85"),
                    anchor="w", justify="left", wraplength=210,
                ).pack(side="left", padx=(8, 4), pady=4, fill="x", expand=True)
                ctk.CTkButton(
                    row, text="✕", width=22, height=22,
                    font=("JetBrains Mono", 10),
                    fg_color="transparent", hover_color=DANGER, text_color=("gray30","gray80"),
                    command=lambda idx=i: self._remove_signature_from_draft(idx),
                ).pack(side="right", padx=6, pady=4)

        btns = ctk.CTkFrame(self._draft_frame, fg_color="transparent")
        btns.pack(fill="x", padx=10, pady=(4, 10))
        ctk.CTkButton(
            btns, text="💾  Сохранить",
            font=("JetBrains Mono", 11, "bold"),
            fg_color=ACCENT, hover_color=ACCENT2, text_color="black",
            text_color_disabled=("gray30", "gray40"),
            height=30,
            state="normal" if draft["signatures"] else "disabled",
            command=self._save_template_draft,
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(
            btns, text="Отмена",
            font=("JetBrains Mono", 11),
            fg_color=("gray80","gray25"), hover_color=DARK_BD2,
            height=30,
            command=self._cancel_template_draft,
        ).pack(side="right", fill="x", expand=True, padx=(4, 0))

    def _open_create_template_dialog(self):
        if not self.order:
            messagebox.showwarning("Создать шаблон", "Заказ не найден.")
            return
        if not self.order.width or not self.order.height:
            messagebox.showwarning(
                "Создать шаблон",
                "У заказа не указан обрезной формат — без него нельзя\n"
                "собрать корректное имя файла шаблона."
            )
            return

        code = (self.order.binding or "").strip().upper()
        binding_options = sorted(_BINDING_CODE_TEMPLATE_TOKENS.get(code, {"shitie", "nitki", "tkley", "skrepka"}))
        binding_titles = [t.capitalize() for t in binding_options]
        base_kind_default = "saddle" if code == "SKR" else "perfect"

        dlg = ctk.CTkToplevel(self)
        dlg.title("Создать шаблон")
        dlg.geometry("420x360")
        dlg.transient(self)
        dlg.grab_set()

        pad = {"padx": 16, "pady": (10, 0)}

        ctk.CTkLabel(dlg, text=f"Заказ № {self.order.number:04d} · {self.order.width}x{self.order.height} мм",
                     font=("JetBrains Mono", 11, "bold")).pack(anchor="w", **pad)

        ctk.CTkLabel(dlg, text="Название (для имени файла):", font=("JetBrains Mono", 10)).pack(anchor="w", **pad)
        v_name = tk.StringVar(value=order_folder_name_part(self.order))
        ctk.CTkEntry(dlg, textvariable=v_name, font=("JetBrains Mono", 11)).pack(fill="x", padx=16, pady=(2, 0))

        ctk.CTkLabel(dlg, text="Формат печатной машины (см), напр. 72x52:",
                     font=("JetBrains Mono", 10)).pack(anchor="w", **pad)
        v_press = ctk.CTkComboBox(
            dlg, values=["65x47", "72x52", "64x45", "64x90", "70x100"],
            font=("JetBrains Mono", 11),
        )
        v_press.set("72x52")
        v_press.pack(fill="x", padx=16, pady=(2, 0))

        ctk.CTkLabel(dlg, text="Тип скрепления (в имени файла):",
                     font=("JetBrains Mono", 10)).pack(anchor="w", **pad)
        v_binding = ctk.CTkComboBox(dlg, values=binding_titles, font=("JetBrains Mono", 11))
        v_binding.set(binding_titles[0] if binding_titles else "Shitie")
        v_binding.pack(fill="x", padx=16, pady=(2, 0))

        preview_lbl = ctk.CTkLabel(dlg, text="", font=("JetBrains Mono", 10, "bold"), text_color=ACCENT_TEXT,
                                    wraplength=380, justify="left")
        preview_lbl.pack(anchor="w", padx=16, pady=(10, 0))

        def update_preview(*_a):
            fname = build_template_filename(self.order, v_press.get(), v_binding.get())
            preview_lbl.configure(text=f"Имя файла: {fname}")

        v_name.trace_add("write", update_preview)
        v_press.configure(command=lambda _v: update_preview())
        v_binding.configure(command=lambda _v: update_preview())
        update_preview()

        err_lbl = ctk.CTkLabel(dlg, text="", font=("JetBrains Mono", 10), text_color=DANGER,
                                wraplength=380, justify="left")
        err_lbl.pack(anchor="w", padx=16, pady=(4, 0))

        def on_create():
            press = v_press.get().strip()
            if not re.match(r"^\d+[xхX]\d+$", press):
                err_lbl.configure(text="Формат печатной машины укажите как ЧИСЛОxЧИСЛО, напр. 72x52.")
                return
            binding_token = v_binding.get().strip().lower()
            base_path = _find_base_template(base_kind_default)
            if not base_path:
                err_lbl.configure(
                    text=f"Не найден пустой шаблон-заготовка "
                         f"({'Saddle Stitched' if base_kind_default == 'saddle' else 'Perfect Bound'}). "
                         f"Проверьте config.json → preps_empty_templates."
                )
                return

            fname = build_template_filename(self.order, press, v_binding.get().strip())
            self._start_new_template_draft(fname, base_path)
            dlg.destroy()

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=16, side="bottom")
        ctk.CTkButton(
            btn_row, text="Создать", font=("JetBrains Mono", 12, "bold"),
            fg_color=ACCENT, hover_color=ACCENT2, text_color="black",
            command=on_create,
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(
            btn_row, text="Отмена", font=("JetBrains Mono", 12),
            fg_color=("gray80","gray25"), hover_color=DARK_BD2,
            command=dlg.destroy,
        ).pack(side="right", fill="x", expand=True, padx=(6, 0))

    def _start_new_template_draft(self, filename: str, base_path: str):
        self._tpl_draft = {
            "filename": filename, "base_path": base_path, "signatures": [],
            "editing_existing_path": None,
        }
        self._render_draft_bar()

    def _edit_existing_template(self, path: str):
        """
        Загружает СУЩЕСТВУЮЩИЙ шаблон целиком в черновик — все его
        сигнатуры появляются в панели черновика, их можно удалить
        (✕), можно добавить чужие сигнатуры из других шаблонов
        (кнопка "+"), а по "💾 Сохранить" по умолчанию перезаписывается
        тот же файл (можно сохранить и в другое место — диалог
        сохранения это позволяет). См. п.5.
        """
        if self._tpl_draft and self._tpl_draft["signatures"]:
            if not messagebox.askyesno(
                "Редактировать шаблон",
                "Текущий черновик будет заменён содержимым выбранного\n"
                "шаблона. Продолжить?"
            ):
                return

        _header, sigs = _parse_tpl_file(path, force=True)
        if not sigs:
            messagebox.showwarning(
                "Редактировать шаблон",
                "Не удалось прочитать сигнатуры этого файла — возможно,\n"
                "формат не распознан."
            )
            return

        fname = os.path.basename(path)
        self._tpl_draft = {
            "filename": fname,
            "base_path": path,
            "signatures": [{"sig": s, "source_fname": fname} for s in sigs],
            "editing_existing_path": path,
        }
        self._render_draft_bar()
        self._status_lbl.configure(text=f"Редактирование: {fname}", text_color=ACCENT_TEXT)

    def _add_signature_to_draft(self, sig: dict, source_fname: str):
        if self._tpl_draft is None:
            messagebox.showinfo(
                "Добавить в шаблон",
                "Сначала нажмите «➕ Создать шаблон» вверху панели —\n"
                "туда и будут добавляться выбранные сигнатуры."
            )
            return
        self._tpl_draft["signatures"].append({"sig": sig, "source_fname": source_fname})
        self._render_draft_bar()

    def _remove_signature_from_draft(self, index: int):
        if self._tpl_draft is None:
            return
        try:
            self._tpl_draft["signatures"].pop(index)
        except IndexError:
            pass
        self._render_draft_bar()

    def _cancel_template_draft(self):
        if self._tpl_draft and self._tpl_draft["signatures"]:
            if not messagebox.askyesno("Отменить черновик", "Отменить черновик? Несохранённые изменения будут потеряны."):
                return
        self._tpl_draft = None
        self._render_draft_bar()

    def _save_template_draft(self):
        draft = self._tpl_draft
        if not draft or not draft["signatures"]:
            return

        editing_path = draft.get("editing_existing_path")
        if editing_path:
            # Редактирование существующего шаблона — по умолчанию
            # сохраняем поверх того же файла (можно выбрать другое
            # место через тот же диалог "Сохранить как").
            default_dir = os.path.dirname(editing_path)
            default_fname = os.path.basename(editing_path)
            title = "Сохранить отредактированный шаблон Preps"
        else:
            dirs = [d for d in config.CFG.get("preps_templates", []) if d and os.path.isdir(d)]
            default_dir = dirs[0] if dirs else os.path.dirname(draft["base_path"])
            default_fname = draft["filename"]
            title = "Сохранить новый шаблон Preps"

        save_path = filedialog.asksaveasfilename(
            title=title,
            initialdir=default_dir,
            initialfile=default_fname,
            defaultextension=".tpl",
            filetypes=[("Шаблоны Preps", "*.tpl")],
        )
        if not save_path:
            return

        new_name_no_ext = os.path.splitext(os.path.basename(save_path))[0]
        raw_blocks = [item["sig"]["raw_lines"] for item in draft["signatures"]]
        content_lines = build_new_template_content(draft["base_path"], new_name_no_ext, raw_blocks)

        try:
            with open(save_path, "w", encoding="utf-8", newline="") as f:
                f.writelines(content_lines)
        except Exception as e:
            messagebox.showerror("Сохранить шаблон", f"Не удалось сохранить файл:\n{e}")
            return

        self._tpl_draft = None
        self._render_draft_bar()
        verb = "обновлён" if editing_path else "сохранён"
        self._status_lbl.configure(text=f"✓ Шаблон {verb}: {os.path.basename(save_path)}", text_color=ACCENT_TEXT)
        # Новый/изменённый файл на диске — обновляем список (форс,
        # чтобы попал в кэш и в список, если формат/скрепление заказа
        # совпадают). Если файл был в архиве — его придётся отдельно
        # пересканировать кнопкой "🗄 Архив" (кэш архива не трогаем
        # автоматически).
        self._refresh_templates(force=True)

    def _render_template_signatures(self, container, path: str):
        ctk.CTkLabel(
            container, text="Загружаю сигнатуры…", font=("JetBrains Mono", 10),
            text_color=("gray30","gray70"),
        ).pack(anchor="w", padx=10, pady=6)
        container.update_idletasks()

        _header, signatures = _parse_tpl_file(path)

        for w in container.winfo_children():
            w.destroy()

        # "Редактировать этот шаблон" — загружает ВСЕ сигнатуры этого
        # файла в черновик (можно убрать ненужные, добавить чужие, и
        # сохранить — по умолчанию поверх того же файла). См. п.5.
        edit_row = ctk.CTkFrame(container, fg_color="transparent")
        edit_row.pack(fill="x", padx=8, pady=(6, 2))
        ctk.CTkButton(
            edit_row, text="✎  Редактировать этот шаблон", font=("JetBrains Mono", 10, "bold"),
            fg_color=("gray75","gray28"), hover_color=DARK_BD2, text_color=("gray10","white"),
            height=26,
            command=lambda p=path: self._edit_existing_template(p),
        ).pack(fill="x")

        if not signatures:
            ctk.CTkLabel(
                container, text="Сигнатур не найдено (или не удалось разобрать файл).",
                font=("JetBrains Mono", 10), text_color=("gray30","gray70"), justify="left",
            ).pack(anchor="w", padx=10, pady=6)
            return

        source_fname = os.path.basename(path)
        for sig in signatures:
            row = ctk.CTkFrame(container, fg_color=("gray80","gray23"), corner_radius=4)
            row.pack(fill="x", padx=8, pady=3)

            # Кнопку пакуем ПЕРВОЙ (side="right"), чтобы она гарантированно
            # получала своё место и не пропадала за правым краем, если
            # строка с текстом не помещается по ширине.
            add_btn = ctk.CTkButton(
                row, text="+", font=("JetBrains Mono", 20, "bold"),
                fg_color=("gray70","gray30"), hover_color=ACCENT2, text_color=("gray10","white"),
                height=34, width=34,
                command=lambda s=sig, fn=source_fname: self._add_signature_to_draft(s, fn),
            )
            add_btn.pack(side="right", padx=8, pady=6)

            text_col = ctk.CTkFrame(row, fg_color="transparent")
            text_col.pack(side="left", padx=(8, 4), pady=6, fill="x", expand=True)

            ctk.CTkLabel(
                text_col, text=f"▪ {sig['name'] or '(без имени)'}",
                font=("JetBrains Mono", 10, "bold"),
                text_color=("gray10","white"), justify="left", anchor="w",
            ).pack(fill="x", anchor="w")

            details = []
            if sig["pages"] is not None:
                details.append(f"{sig['pages']} стр.")
            details.append(f"Клапан: {sig['clapan_mm']} мм" if sig["clapan_mm"] is not None else "Клапан: —")
            details.append(f"В голове: {sig['gutter_total_mm']} мм" if sig["gutter_total_mm"] is not None else "В голове: —")
            ctk.CTkLabel(
                text_col, text="  " + " · ".join(details), font=("JetBrains Mono", 10),
                text_color=("gray20","gray85"), justify="left", anchor="w",
            ).pack(fill="x", anchor="w")

    def _refresh_archive_cache(self):
        """
        Кнопка "🗄 Архив" — пересканирует МЕДЛЕННУЮ сетевую папку(и)
        из config.preps_templates_archive и обновляет кэш в БД (см.
        _rescan_archive_to_db). Архив обновляется примерно раз в
        полгода, поэтому это отдельное явное действие, а не часть
        обычного обновления списка (кнопка ↺).
        """
        archive_dirs = [d for d in config.CFG.get("preps_templates_archive", []) if d]
        if not archive_dirs:
            messagebox.showinfo(
                "Обновить архив шаблонов",
                "В config.json не заданы папки preps_templates_archive — обновлять нечего."
            )
            return

        missing = [d for d in archive_dirs if not os.path.isdir(d)]
        if missing:
            messagebox.showwarning(
                "Обновить архив шаблонов",
                "Недоступны папки архива:\n" + "\n".join(missing)
            )
            return

        if not messagebox.askyesno(
            "Обновить архив шаблонов",
            "Пересканировать архив шаблонов Preps на сервере?\n"
            "Это сетевая папка — может занять некоторое время."
        ):
            return

        for w in self.templates_list.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.templates_list, text="Сканирую архив шаблонов на сервере…\nЭто может занять некоторое время.",
            font=("JetBrains Mono", 11), text_color=("gray25","gray80"), justify="left",
        ).pack(anchor="w", padx=12, pady=12)

        def worker():
            try:
                count = _rescan_archive_to_db(archive_dirs)
                error = None
            except Exception as e:
                count = 0
                error = str(e)
            self.after(0, lambda: self._on_archive_rescanned(count, error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_archive_rescanned(self, count: int, error: str):
        if error:
            messagebox.showerror("Обновить архив шаблонов", f"Не удалось обновить архив:\n{error}")
        else:
            self._status_lbl.configure(
                text=f"✓ Архив шаблонов обновлён: найдено {count}", text_color=ACCENT_TEXT
            )
        self._refresh_templates(force=False)

    def _refresh_templates(self, force: bool = False):
        if not hasattr(self, "templates_list"):
            return

        if force:
            # Принудительное обновление (кнопка ↺) пересканирует
            # быстрые локальные папки (config.preps_templates) —
            # делаем это в фоновом потоке на случай временных
            # задержек диска, и показываем статус, пока идёт
            # сканирование. Архивные (сетевые) папки сюда не входят —
            # они берутся из кэша в БД, см. "🗄 Архив" / _refresh_archive_cache.
            for w in self.templates_list.winfo_children():
                w.destroy()
            ctk.CTkLabel(
                self.templates_list, text="Обновляю список шаблонов…",
                font=("JetBrains Mono", 11), text_color=("gray25","gray80"),
            ).pack(anchor="w", padx=12, pady=12)

            order = self.order

            def worker():
                if order and order.width and order.height:
                    _scan_preps_templates(order, force=True)
                self.after(0, lambda: self._refresh_templates(force=False))

            threading.Thread(target=worker, daemon=True).start()
            return

        for w in self.templates_list.winfo_children():
            w.destroy()

        if not self.order:
            ctk.CTkLabel(
                self.templates_list, text="Заказ не найден.",
                font=("JetBrains Mono", 11), text_color=("gray25","gray80"), justify="left",
            ).pack(anchor="w", padx=12, pady=12)
            return

        o = self.order

        if not o.width or not o.height:
            ctk.CTkLabel(
                self.templates_list,
                text="У заказа не указан обрезной формат —\nнечего сопоставлять с шаблонами.",
                font=("JetBrains Mono", 11), text_color=("gray25","gray80"), justify="left",
            ).pack(anchor="w", padx=12, pady=12)
            return

        # force=False — сканирование папок (в т.ч. сетевой NAS) идёт
        # только если кэш пуст/устарел, см. _scan_all_templates
        templates = _scan_preps_templates(o)

        if not templates:
            dirs = [d for d in config.CFG.get("preps_templates", []) if d]
            missing = [d for d in dirs if not os.path.isdir(d)]
            msg = "Подходящих шаблонов не найдено."
            if missing:
                msg += "\n\n⚠ Недоступны папки:\n" + "\n".join(missing)
            ctk.CTkLabel(
                self.templates_list, text=msg,
                font=("JetBrains Mono", 11), text_color=("gray25","gray80"), justify="left",
            ).pack(anchor="w", padx=12, pady=12)
            return

        # Список уже отсортирован по дате изменения файла (новые
        # сверху, см. _scan_preps_templates) — группируем по году,
        # вставляя заголовок года перед первой карточкой этого года.
        last_year = None
        for tpl in templates:
            year = tpl.get("year")
            if year != last_year:
                ctk.CTkLabel(
                    self.templates_list, text=str(year) if year else "Дата неизвестна",
                    font=("JetBrains Mono", 11, "bold"), text_color=("gray20","gray85"),
                    anchor="w",
                ).pack(fill="x", padx=10, pady=(14 if last_year is not None else 6, 4))
                last_year = year

            card = ctk.CTkFrame(self.templates_list, fg_color=("gray85","gray20"), corner_radius=6)
            card.pack(fill="x", padx=8, pady=5)

            header_row = ctk.CTkFrame(card, fg_color="transparent", cursor="hand2")
            header_row.pack(fill="x")

            text_col = ctk.CTkFrame(header_row, fg_color="transparent", cursor="hand2")
            text_col.pack(side="left", fill="x", expand=True)

            name_lbl = ctk.CTkLabel(
                text_col, text=("🗄 " if tpl.get("from_archive") else "") + tpl["fname"],
                font=("JetBrains Mono", 12, "bold"),
                text_color=ACCENT_TEXT, anchor="w", justify="left", wraplength=230,
                cursor="hand2",
            )
            name_lbl.pack(fill="x", padx=10, pady=(10, 2), anchor="w")

            meta_lbl = ctk.CTkLabel(
                text_col,
                text=f"№{tpl['order_num']} · {tpl['trim']} мм · бумага {tpl['paper']} · {tpl['binding']}",
                font=("JetBrains Mono", 11), text_color=("gray30","gray75"), anchor="w",
            )
            meta_lbl.pack(fill="x", padx=10, pady=(0, 10), anchor="w")

            for widget in (header_row, text_col, name_lbl, meta_lbl):
                widget.bind("<Button-1>", lambda e, p=tpl["path"]: self._open_template(p))

            sig_container = ctk.CTkFrame(card, fg_color=("gray82","gray18"), corner_radius=0)

            is_expanded = self._tpl_expanded.get(tpl["path"], False)
            expand_btn = ctk.CTkButton(
                header_row, text=("▾" if is_expanded else "▸"), width=34, height=34,
                font=("JetBrains Mono", 20, "bold"),
                fg_color="transparent", hover_color=DARK_BD2, text_color=("gray30","gray80"),
                command=lambda p=tpl["path"], c=sig_container, b=None: self._on_expand_click(p, c),
            )
            expand_btn.pack(side="right", padx=8, pady=8)

            if is_expanded:
                sig_container.pack(fill="x", pady=(0, 6))
                self._render_template_signatures(sig_container, tpl["path"])

    def _on_expand_click(self, path: str, container):
        expanded = not self._tpl_expanded.get(path, False)
        self._tpl_expanded[path] = expanded
        for w in container.winfo_children():
            w.destroy()
        if expanded:
            container.pack(fill="x", pady=(0, 6))
            self._render_template_signatures(container, path)
        else:
            container.pack_forget()

    def _open_template(self, path: str):
        """Открывает .tpl шаблон в программе Preps."""
        if not os.path.isfile(path):
            messagebox.showerror("Preps", f"Файл не найден:\n{path}")
            return
        preps_exe = (config.CFG.get("preps_path") or "").strip()
        try:
            if preps_exe and os.path.isfile(preps_exe):
                subprocess.Popen([preps_exe, path])
            else:
                # Открываем через ассоциацию файлов Windows (.tpl → Preps)
                os.startfile(path)
        except Exception as e:
            messagebox.showerror("Preps", f"Не удалось открыть шаблон:\n{e}")

    def _on_engine_change(self, value):
        if value == "ollama":
            self.ollama_frame.pack(fill="x", padx=16, pady=(8, 0))
        else:
            self.ollama_frame.pack_forget()

    # ── PING OLLAMA ───────────────────────────────────────────────
    def _ping_ollama(self):
        self._ping_dot.configure(text_color=WARNING)
        self._ping_status.configure(text="Проверяю...")

        def worker():
            import requests
            url = self.v_ollama_url.get().strip()
            model = self.v_ollama_model.get().strip()

            # Ollama API: GET /api/tags — проверяем что сервер жив
            # Определяем базовый URL
            base = url.replace("/api/generate", "").replace("/api/chat", "").rstrip("/")
            try:
                resp = requests.get(f"{base}/api/tags", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                    if model in models:
                        msg = f"✓ Ollama работает · {model} найдена"
                        color = ACCENT
                    elif models:
                        msg = f"⚠ {model} не найдена\nДоступны: {', '.join(models[:3])}"
                        color = WARNING
                    else:
                        msg = "⚠ Модели не установлены\nВыполните: ollama pull " + model
                        color = WARNING
                else:
                    msg = f"✗ HTTP {resp.status_code}"
                    color = DANGER
            except requests.exceptions.ConnectionError:
                msg = "✗ Ollama не запущена\nВыполните: ollama serve"
                color = DANGER
            except Exception as e:
                msg = f"✗ Ошибка: {e}"
                color = DANGER

            self.after(0, lambda m=msg, c=color: self._set_ping_status(m, c))

        threading.Thread(target=worker, daemon=True).start()

    def _set_ping_status(self, msg: str, color: str):
        self._ping_dot.configure(text_color=color)
        self._ping_status.configure(text=msg, text_color=color)

    # ── PHOTO ─────────────────────────────────────────────────────
    def _build_empty_state(self):
        for w in self._grid_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self._grid_frame,
            text="⊟\n\nЗагрузите фото спуска\nи нажмите Распознать",
            font=("JetBrains Mono", 14), text_color=("gray40","gray60"), justify="center"
        ).place(relx=0.5, rely=0.5, anchor="center")

    def _pick_photo(self):
        path = filedialog.askopenfilename(
            filetypes=[("Изображения", "*.jpg *.jpeg *.png"), ("Все", "*.*")]
        )
        if path:
            self._load_photo(path)

    def _spusk_dst_path(self, src_path: str) -> str:
        """Путь, по которому фото спуска должно лежать в корне папки
        заказа на диске P: — с припиской "_spusk" к имени заказа."""
        if not self.order or not self.order.folder_path:
            return None
        ext = os.path.splitext(src_path)[1].lower() or ".jpg"
        name = f"{self.order.folder_name}_spusk{ext}"
        return os.path.join(self.order.folder_path, name)

    def _load_photo(self, path: str, copy_to_disk: bool = True):
        """Загружает фото спуска в превью. Если copy_to_disk — копирует
        файл в корень папки заказа на диске P: (с припиской "_spusk")
        и запоминает путь в БД, чтобы при следующем открытии страницы
        подхватить фото автоматически."""
        from PIL import Image

        saved_path = path
        if copy_to_disk:
            dst = self._spusk_dst_path(path)
            if dst:
                try:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    if os.path.abspath(dst) != os.path.abspath(path):
                        shutil.copy2(path, dst)
                    saved_path = dst
                except Exception as e:
                    messagebox.showwarning(
                        "Спуск полос",
                        f"Не удалось скопировать фото на диск P::\n{e}\n\n"
                        f"Работаю с исходным файлом."
                    )

        self._img_path = saved_path

        img = Image.open(saved_path)
        img.load()
        self._preview_pil_image = img
        self._preview_zoom = _DEFAULT_PREVIEW_ZOOM
        self._render_preview()
        self._view_seg.set("📷 Фото")
        self._on_view_change("📷 Фото")

        self._photo_status_lbl.configure(
            text=f"✓ {os.path.basename(saved_path)}", text_color=ACCENT_TEXT
        )
        self.btn_analyze.configure(state="normal")
        self._status_lbl.configure(text="Фото загружено")

        # Запоминаем путь к фото в БД (для последующих открытий
        # страницы), только если файл реально лежит в папке заказа
        if self.order and self.order.id and saved_path == self._spusk_dst_path(path):
            save_imposition(self.order.id, photo_path=saved_path)

    def _on_photo_drop(self, event):
        raw = (event.data or "").strip()
        if raw.startswith("{"):
            paths = re.findall(r"\{([^}]+)\}", raw)
            if not paths:
                paths = [raw.strip("{}")]
        else:
            paths = raw.split()
        path = (paths[0] if paths else "").strip()
        if path and os.path.isfile(path):
            self._load_photo(path)

    def _load_existing_imposition(self):
        """При открытии страницы уже существующего заказа — подхватывает
        сохранённое ранее фото спуска (с диска P:) и сетку из БД, если
        они есть, без повторного копирования файла."""
        if not self.imposition:
            return

        photo_path = self.imposition.photo_path
        if photo_path and os.path.isfile(photo_path):
            self._load_photo(photo_path, copy_to_disk=False)
        elif self.order and self.order.folder_path and os.path.isdir(self.order.folder_path):
            # Запись в БД есть, но путь не найден (файл могли
            # переименовать/перенести) — ищем "*_spusk.*" в корне
            # папки заказа как запасной вариант.
            root = self.order.folder_path
            candidates = [
                f for f in os.listdir(root)
                if "_spusk" in f.lower()
                and f.lower().endswith((".jpg", ".jpeg", ".png"))
            ]
            if candidates:
                candidates.sort(key=lambda f: os.path.getmtime(os.path.join(root, f)), reverse=True)
                self._load_photo(os.path.join(root, candidates[0]), copy_to_disk=False)

        if self.imposition.sheets_json:
            try:
                sheets = json.loads(self.imposition.sheets_json)
            except Exception:
                sheets = []
            if sheets:
                self._sheets = sheets
                self._render_grid()
                self._view_seg.set("▦ Сетка")
                self._on_view_change("▦ Сетка")
                self._status_lbl.configure(text="Загружен сохранённый спуск")

    def _save_imposition_to_db(self):
        """Сохраняет текущее состояние спуска (сетку/параметры/фото)
        в БД для последующего редактирования."""
        if not self.order or not self.order.id:
            messagebox.showwarning("Спуск полос", "Заказ не найден — сохранение недоступно.")
            return
        sheets = self._collect_sheets() if self._sheets else []
        try:
            rows = int(self.v_rows.get() or 4)
        except ValueError:
            rows = None
        try:
            cols = int(self.v_cols.get() or 4)
        except ValueError:
            cols = None

        save_imposition(
            self.order.id,
            photo_path=self._img_path,
            rows=rows, cols=cols,
            two_sided=self.v_two.get(),
            sheets_json=json.dumps(sheets, ensure_ascii=False) if sheets else None,
        )
        self._status_lbl.configure(text="✓ Спуск сохранён", text_color=ACCENT_TEXT)

    # ── ANALYZE ───────────────────────────────────────────────────
    def _analyze(self):
        if not self._img_path:
            return
        self.btn_analyze.configure(state="disabled", text="⟳  Анализирую...")
        self._status_lbl.configure(text="Отправляю в AI...")

        def worker():
            try:
                result = self._call_ai()
                self.after(0, lambda r=result: self._apply_result(r))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda m=msg: self._on_error(m))
            finally:
                self.after(0, lambda: self.btn_analyze.configure(
                    state="normal", text="↺  Распознать снова"
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _call_ai(self) -> dict:
        import requests
        rows = int(self.v_rows.get() or 4)
        cols = int(self.v_cols.get() or 4)
        two  = self.v_two.get()

        with open(self._img_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

        prompt = (
            f"You are a prepress specialist. This is a handwritten imposition layout for offset printing. "
            f"Grid: {rows} rows x {cols} columns ({rows*cols} positions). "
            f"{'Find TWO impositions: face side and back side.' if two else 'One imposition.'} "
            f"Rows top to bottom (row 0=top). Columns left to right (col 0=left). "
            f"Page numbers are handwritten integers. rotated=true if page is upside down. "
            f"Return ONLY valid JSON, no markdown:\n"
            f'{{"overall_confidence":0.5,"issues":[],"sheets":['
            f'{{"side":"face","label":"Лицо","rows":{rows},"cols":{cols},'
            f'"cells":[{{"row":0,"col":0,"page":null,"rotated":false,"confident":true}}]}}'
            f'{"," + chr(123) + chr(34) + "side" + chr(34) + ":" + chr(34) + "back" + chr(34) + "," + chr(34) + "label" + chr(34) + ":" + chr(34) + "Оборот" + chr(34) + "," + chr(34) + "rows" + chr(34) + ":" + str(rows) + "," + chr(34) + "cols" + chr(34) + ":" + str(cols) + "," + chr(34) + "cells" + chr(34) + ":[...]" + chr(125) if two else ""}'
            f']}}'
        )

        engine = self.v_engine.get()

        if engine == "ollama":
            url   = self.v_ollama_url.get().strip()
            model = self.v_ollama_model.get().strip()

            # Ollama /api/generate
            payload = {
                "model":  model,
                "prompt": prompt,
                "images": [img_b64],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 1200},
            }
            resp = requests.post(url, json=payload, timeout=180)
            resp.raise_for_status()
            raw = resp.json().get("response", "")

        else:
            # Claude API
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 1000,
                    "messages": [{"role": "user", "content": [
                        {"type": "image", "source": {
                            "type": "base64", "media_type": "image/jpeg", "data": img_b64
                        }},
                        {"type": "text", "text": prompt},
                    ]}],
                },
                headers={"Content-Type": "application/json"},
                timeout=60,
            )
            resp.raise_for_status()
            raw = resp.json()["content"][0]["text"]

        raw = raw.strip().replace("```json", "").replace("```", "").strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            raise ValueError("JSON не найден в ответе модели")
        return json.loads(m.group(0))

    def _apply_result(self, result: dict):
        self._sheets = result.get("sheets", [])
        conf   = result.get("overall_confidence", 0)
        issues = result.get("issues", [])
        issue_txt = f"  ⚠ {issues[0]}" if issues else ""
        self._status_lbl.configure(
            text=f"Уверенность: {int(conf * 100)}%{issue_txt}"
        )
        self._render_grid()
        self._save_imposition_to_db()

    def _on_error(self, msg: str):
        self._status_lbl.configure(
            text=f"Ошибка:\n{msg}", text_color=DANGER
        )

    # ── GRID RENDER ───────────────────────────────────────────────
    def _render_grid(self):
        for w in self._grid_frame.winfo_children():
            w.destroy()

        scroll = ctk.CTkScrollableFrame(self._grid_frame, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=20)

        if hasattr(self, "_view_seg"):
            self._view_seg.set("▦ Сетка")
            self._on_view_change("▦ Сетка")

        for si, sheet in enumerate(self._sheets):
            # Заголовок листа
            hdr = ctk.CTkFrame(scroll, fg_color="transparent")
            hdr.pack(anchor="w", pady=(0 if si == 0 else 18, 6))

            ctk.CTkLabel(
                hdr, text=f"ЛИСТ {si + 1}",
                font=("JetBrains Mono", 11), text_color=TEXT2
            ).pack(side="left")
            ctk.CTkLabel(
                hdr,
                text=f"  {sheet['label']}",
                font=("JetBrains Mono", 10),
                text_color=ACCENT_TEXT if sheet["side"] == "face" else INFO
            ).pack(side="left")
            ctk.CTkLabel(
                hdr,
                text=f"  {sheet['rows']}×{sheet['cols']}",
                font=("JetBrains Mono", 10), text_color=TEXT3
            ).pack(side="left")

            # Сетка
            grid_frame = ctk.CTkFrame(scroll, fg_color=("gray85","gray20"), corner_radius=4)
            grid_frame.pack(anchor="w")

            rows  = sheet["rows"]
            cols  = sheet["cols"]
            cells = {(c["row"], c["col"]): c for c in sheet.get("cells", [])}

            for r in range(rows):
                for c in range(cols):
                    cd        = cells.get((r, c), {})
                    page      = cd.get("page")
                    confident = cd.get("confident", True)
                    rotated   = cd.get("rotated", False)

                    cell = ctk.CTkFrame(
                        grid_frame, width=70, height=52,
                        fg_color=("gray90","gray17"),
                        border_color=WARNING if not confident else DARK_BD2,
                        border_width=1, corner_radius=2
                    )
                    cell.grid(row=r, column=c, padx=2, pady=2)
                    cell.grid_propagate(False)

                    var = tk.StringVar(value=str(page) if page is not None else "")
                    entry = ctk.CTkEntry(
                        cell, textvariable=var, width=60,
                        font=("JetBrains Mono", 17, "bold"),
                        fg_color="transparent", border_width=0,
                        text_color=TEXT if confident else WARNING,
                        justify="center",
                    )
                    entry.place(relx=0.5, rely=0.5, anchor="center")

                    if rotated:
                        ctk.CTkLabel(
                            cell, text="↻", font=("Arial", 9),
                            text_color=WARNING
                        ).place(relx=1.0, rely=0.0, anchor="ne", x=-2, y=2)

                    cd["_var"] = var
                    cells[(r, c)] = cd

            sheet["_cells_vars"] = cells

    # ── EXPORT ────────────────────────────────────────────────────
    def _collect_sheets(self):
        result = []
        for sheet in self._sheets:
            cells = []
            for (r, c), cd in sheet.get("_cells_vars", {}).items():
                val = cd.get("_var", tk.StringVar()).get().strip()
                cells.append({
                    "row": r, "col": c,
                    "page": int(val) if val.isdigit() else None,
                    "rotated": cd.get("rotated", False),
                    "confident": cd.get("confident", True),
                })
            result.append({**sheet, "cells": cells})
        return result

    def _export_tpl(self):
        from services.tpl_generator import generate_tpl
        sheets = self._collect_sheets()
        path = filedialog.asksaveasfilename(
            defaultextension=".tpl",
            filetypes=[("Preps Template", "*.tpl")],
            initialfile="NewTemplate.tpl",
        )
        if path:
            content = generate_tpl(sheets)
            with open(path, "w", encoding="cp1251", errors="replace") as f:
                f.write(content)

    def _export_job(self):
        from services.tpl_generator import generate_job
        sheets = self._collect_sheets()
        path = filedialog.asksaveasfilename(
            defaultextension=".job",
            filetypes=[("Preps Job", "*.job")],
        )
        if path:
            content = generate_job(sheets, {})
            with open(path, "w", encoding="cp1251", errors="replace") as f:
                f.write(content)

    def _export_both(self):
        self._export_tpl()
        self._export_job()
