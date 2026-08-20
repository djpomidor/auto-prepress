"""
Конфигурация ImpoReader.
"""
import os
import json

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULTS = {
    # ── База данных ───────────────────────────────────────────────
    "db_type": "sqlite",          # "sqlite" или "postgresql"

    # SQLite: путь к файлу БД Printery (если хотите общую БД)
    # Оставьте "" чтобы создать отдельную БД рядом с main.py
    "sqlite_path": "",

    # PostgreSQL DSN (когда db_type = "postgresql")
    # Формат: postgresql://user:password@host:5432/dbname
    "pg_dsn": "postgresql://user:pass@localhost/printery",

    # ── Пути ─────────────────────────────────────────────────────
    # ВАЖНО: в raw-строке (префикс r"...") backslash НЕ схлопывается —
    # r"P:\\" это два символа backslash, а не один. Пишем одинарный
    # backslash как есть (r"P:\Preps"), а для UNC-путей — ровно два
    # ведущих (r"\\SERVER\Share"), иначе Windows не распознает сетевой
    # путь (лишние backslash в "\\\\SERVER" ломают разбор имени сервера).
    "orders_root": "P:\\",
    # Быстрые (локальный диск) папки шаблонов Preps — сканируются
    # напрямую при каждом поиске подходящего шаблона, как и раньше.
    # Сюда обычно сохраняются НОВЫЕ шаблоны — кэшировать в БД не
    # нужно, список должен быть всегда актуальным.
    "preps_templates": [
        r"P:\Preps\Templates",
    ],
    # МЕДЛЕННЫЕ (сетевые) папки-архивы шаблонов Preps — список
    # шаблонов из них кэшируется в БД (таблица preps_template_cache) и
    # обновляется вручную, кнопкой "Обновить архив шаблонов" на
    # странице "Спуск полос" (сеть не сканируется на каждый поиск).
    # Архив обновляется редко (примерно раз в полгода) — кэш не будет
    # быстро устаревать.
    "preps_templates_archive": [
        r"\\NAS-PREPRESS\Archives\!!!_Preps_Templates",
    ],
    "pitstop_in":  r"D:\Pitstop_\out",
    "pitstop_log": r"D:\Pitstop_\Log",
    # Куда PitStop Server кладёт ОРИГИНАЛЬНЫЙ файл + XML лог, когда
    # ошибок НЕ найдено (это отдельная папка от pitstop_log, куда
    # логи об ошибках не попадают вообще).
    "pitstop_ok":  r"D:\Pitstop_\Ok",

    # ── Пустые шаблоны-заготовки Preps (для кнопки "Создать шаблон"
    # на странице "Спуск полос") ────────────────────────────────────
    # Явные пути к пустым шаблонам-заготовкам (без сигнатур) —
    # используются как основа нового шаблона. Если оставить пустыми
    # ("") — при создании шаблона автоматически ищется файл с
    # ключевыми словами "saddle"+"stitch" (скрепка) или
    # "perfect"+"bound" (остальные виды скрепления) в имени, в папках
    # preps_templates (рекурсивно; архив НЕ участвует в этом поиске).
    "preps_empty_templates": {
        "saddle":  "",
        "perfect": "",
    },

    # ── Просмотр PDF лога PitStop в Acrobat ─────────────────────────
    "acrobat_path": r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",

    # ── Открытие .tpl шаблонов в Preps ────────────────────────────
    # Если оставить "" — .tpl откроется через ассоциацию файлов
    # Windows (обычно этого достаточно, если Preps уже установлен).
    "preps_path": r"",

    # ── Poppler (pdftoppm/pdfinfo) для рендера PDF → изображение ────
    # Укажите путь к папке Library\bin из архива Poppler, если она НЕ
    # добавлена в системный PATH, например:
    #   r"C:\poppler\poppler-24.08.0\Library\bin"
    # Оставьте "" если Poppler уже в PATH.
    "poppler_path": r"",

    # ── Prinergy Evo Refine (общая hot-папка на все заказы) ──────────
    # Куда копируются "сырые" PDF заказчика для рефайна. Файл
    # отправляется с префиксом "<папка_заказа>~~" в имени — это одна
    # общая hot-папка Prinergy, настроенная на ОДИН процесс-шаблон
    # Refine to PDF с фиксированным (Direct) путём вывода результата
    # в prinergy_refine_out (тем же для всех заказов).
    "prinergy_refine_in": r"P:\_PrinergyRefined",

    # Куда Prinergy Evo кладёт отрефайненные файлы (общая для всех
    # заказов папка — задаётся как Direct output path в разделе File
    # Delivery процесс-шаблона Refine to PDF, прикреплённого к
    # prinergy_refine_in). ImpoFlow сам следит за этой папкой
    # (RefineRouter) и по префиксу "<папка_заказа>~~" в имени файла
    # раскладывает результат обратно в in\ нужного заказа.
    "prinergy_refine_out": r"P:\_PrinergyRefined\Вывод",

    # ── Ollama ────────────────────────────────────────────────────
    "ollama_url":   "http://localhost:11434/api/generate",
    "ollama_model": "qwen2-vl:7b",

    # ── UI ────────────────────────────────────────────────────────
    "theme":         "dark",
    "window_width":  1400,
    "window_height": 860,
}


def load() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            return {**DEFAULTS, **saved}
        except Exception as e:
            # Раньше ошибка молча проглатывалась и подставлялись
            # значения по умолчанию — из-за этого правки config.json
            # (например, добавленный poppler_path) как будто "не
            # работали", без единого намёка на причину. Теперь хотя
            # бы печатаем в консоль, что файл не читается.
            print(f"[config] Не удалось прочитать {CONFIG_FILE}: {e}")
            print("[config] Использую значения по умолчанию. Проверьте "
                  "config.json на опечатки (особенно двойные \\\\ в путях Windows).")
    return dict(DEFAULTS)


def save(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


CFG = load()
