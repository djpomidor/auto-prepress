"""
ImpoReader Desktop v1.0
Запуск: python main.py
Зависимости: pip install customtkinter pillow watchdog sqlalchemy requests
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import customtkinter as ctk
from ui.app import App


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("green")
    app = App()
    app.mainloop()
