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
        except Exception:
            pass
    return dict(DEFAULTS)


def save(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


CFG = load()
