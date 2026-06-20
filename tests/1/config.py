"""
Конфигурация приложения.
Все пути и настройки редактируются здесь.
"""
import os
import json

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULTS = {
    # Базы данных
    "db_path": os.path.join(os.path.dirname(__file__), "impo_reader.db"),
    "db_type": "sqlite",          # "sqlite" или "postgresql"
    "pg_dsn": "postgresql://user:pass@localhost/impo_reader",

    # Сетевые пути
    "orders_root": r"P:\\",
    "preps_templates": [
        r"P:\\Preps\\Templates",
        r"\\\\NAS-PREPRESS\\Archives\\!!!_Preps_Templates",
    ],

    # PitStop
    "pitstop_in":  r"D:\\Pitstop_\\out",
    "pitstop_log": r"D:\\Pitstop_\\Log",

    # Ollama
    "ollama_url":   "http://localhost:11434/api/generate",
    "ollama_model": "qwen2-vl:7b",

    # Тема
    "theme": "dark",

    # UI
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
