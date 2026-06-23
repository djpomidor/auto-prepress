"""
ImpoReader Desktop v1.0
Запуск: python main.py
Зависимости: pip install customtkinter pillow watchdog sqlalchemy requests
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import customtkinter as ctk
import config

if __name__ == "__main__":
    # Читаем тему из конфига — не хардкодим "dark"
    theme = config.CFG.get("theme", "dark")
    ctk.set_appearance_mode(theme)
    ctk.set_default_color_theme("green")

    from ui.app import App
    app = App()
    app.mainloop()