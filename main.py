"""
ImpoReader Desktop v1.0
Запуск: python main.py
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import logging
# Глушим подробные логи сторонних библиотек
for _lib in ["pdfminer", "pdfplumber", "PIL", "watchdog",
             "pdfminer.psparser", "pdfminer.pdfinterp",
             "pdfminer.cmapdb", "pdfminer.pdfdocument"]:
    logging.getLogger(_lib).setLevel(logging.WARNING)

import config

# Применяем тему ДО создания любых окон
import customtkinter as ctk
theme = config.CFG.get("theme", "dark")
ctk.set_appearance_mode(theme)
ctk.set_default_color_theme("green")

if __name__ == "__main__":
    try:
        from tkinterdnd2 import TkinterDnD
        DND_AVAILABLE = True
    except ImportError:
        DND_AVAILABLE = False

    if DND_AVAILABLE:
        # Встраиваем DnD в CustomTkinter
        from ui.app import App

        class AppDnD(TkinterDnD.DnDWrapper, App):
            def __init__(self):
                App.__init__(self)
                self.TkdndVersion = TkinterDnD._require(self)

        try:
            app = AppDnD()
            app._dnd_available = True
        except Exception as e:
            print(f"DnD init failed: {e}, falling back")
            from ui.app import App
            app = App()
            app._dnd_available = False
    else:
        from ui.app import App
        app = App()
        app._dnd_available = False
        print("Hint: pip install tkinterdnd2  — для drag-and-drop файлов")

    app.mainloop()
