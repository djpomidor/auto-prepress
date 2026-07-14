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
    "orders_root": r"P:\\",
    "preps_templates": [
        r"P:\\Preps\\Templates",
        r"\\\\NAS-PREPRESS\\Archives\\!!!_Preps_Templates",
    ],
    "pitstop_in":  r"D:\\Pitstop_\\out",
    "pitstop_log": r"D:\\Pitstop_\\Log",

    # ── Просмотр PDF лога PitStop в Acrobat ─────────────────────────
    "acrobat_path": r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",

    # ── Poppler (pdftoppm/pdfinfo) для рендера PDF → изображение ────
    # Укажите путь к папке Library\bin из архива Poppler, если она НЕ
    # добавлена в системный PATH, например:
    #   r"C:\poppler\poppler-24.08.0\Library\bin"
    # Оставьте "" если Poppler уже в PATH.
    "poppler_path": r"C:\poppler\poppler-26.02.0\Library\bin",

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
    "prinergy_refine_out": r"p:\_PrinergyRefined\Вывод",

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
