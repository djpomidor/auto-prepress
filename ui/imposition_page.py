"""
Страница спуска полос.
Перенесена логика из impo_reader.html.
"""
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog
import threading
import base64
import json

DARK_BG  = "#0f0f0f"
DARK_SF  = "#1a1a1a"
DARK_SF2 = "#242424"
DARK_BD  = "#2e2e2e"
DARK_BD2 = "#3a3a3a"
ACCENT   = "#c8f135"
ACCENT2  = "#9bc429"
TEXT     = "#e8e8e8"
TEXT2    = "#888888"
TEXT3    = "#555555"
DANGER   = "#ff5555"
INFO     = "#55aaff"
WARNING  = "#ffaa33"


class ImpositionPage(ctk.CTkFrame):
    def __init__(self, parent, app, order_id: int, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self.order_id = order_id
        self._img_path = None
        self._sheets = []

        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=0, minsize=300)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Левая панель ──────────────────────────────────────────
        left = ctk.CTkScrollableFrame(
            self, fg_color=DARK_SF, corner_radius=0, width=300
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 1))

        # Загрузка фото
        _lbl = lambda t: ctk.CTkLabel(
            left, text=t, font=("JetBrains Mono", 9),
            text_color=TEXT3, anchor="w"
        )
        _lbl("ФОТО СПУСКА").pack(anchor="w", padx=16, pady=(16, 6))

        self.photo_zone = ctk.CTkFrame(
            left, fg_color=DARK_SF2, corner_radius=6,
            border_width=1, border_color=DARK_BD2, height=80
        )
        self.photo_zone.pack(fill="x", padx=16)
        self.photo_zone.pack_propagate(False)
        ctk.CTkLabel(
            self.photo_zone,
            text="Нажмите или перетащите JPG",
            font=("JetBrains Mono", 11), text_color=TEXT3
        ).place(relx=0.5, rely=0.5, anchor="center")
        self.photo_zone.bind("<Button-1>", lambda _: self._pick_photo())

        # Превью фото
        self.photo_lbl = ctk.CTkLabel(left, text="", image=None)
        self.photo_lbl.pack(padx=16, pady=(8, 0))

        ctk.CTkFrame(left, fg_color=DARK_BD, height=1).pack(fill="x", pady=12)

        # Параметры сетки
        _lbl("ПАРАМЕТРЫ СЕТКИ").pack(anchor="w", padx=16, pady=(0, 6))
        grid_f = ctk.CTkFrame(left, fg_color="transparent")
        grid_f.pack(fill="x", padx=16)
        grid_f.columnconfigure(1, weight=1)

        self.v_rows = tk.StringVar(value="4")
        self.v_cols = tk.StringVar(value="4")
        self.v_two  = tk.BooleanVar(value=True)

        for row, (label, var) in enumerate([("Рядов", self.v_rows), ("Колонок", self.v_cols)]):
            ctk.CTkLabel(grid_f, text=label, font=("JetBrains Mono", 10), text_color=TEXT3).grid(
                row=row, column=0, sticky="w", pady=4
            )
            ctk.CTkEntry(
                grid_f, textvariable=var, width=80,
                font=("JetBrains Mono", 12),
                fg_color=DARK_SF2, border_color=DARK_BD2,
                text_color=TEXT
            ).grid(row=row, column=1, sticky="e", pady=4)

        ctk.CTkCheckBox(
            left, text="Два спуска (лицо + оборот)",
            variable=self.v_two,
            font=("JetBrains Mono", 11), text_color=TEXT2,
            fg_color=ACCENT2, checkmark_color=DARK_BG,
        ).pack(anchor="w", padx=16, pady=8)

        ctk.CTkFrame(left, fg_color=DARK_BD, height=1).pack(fill="x", pady=4)

        # Движок AI
        _lbl("AI ДВИЖОК").pack(anchor="w", padx=16, pady=(8, 6))
        self.v_engine = tk.StringVar(value="ollama")
        ctk.CTkSegmentedButton(
            left, values=["ollama", "claude"],
            variable=self.v_engine,
            font=("JetBrains Mono", 10),
            selected_color=ACCENT2,
            unselected_color=DARK_SF2,
            text_color=TEXT,
        ).pack(fill="x", padx=16)

        ctk.CTkFrame(left, fg_color=DARK_BD, height=1).pack(fill="x", pady=10)

        # Кнопка распознать
        self.btn_analyze = ctk.CTkButton(
            left,
            text="▶  Распознать",
            font=("JetBrains Mono", 13, "bold"),
            fg_color=ACCENT, hover_color=ACCENT2,
            text_color=DARK_BG, height=38,
            command=self._analyze,
            state="disabled",
        )
        self.btn_analyze.pack(fill="x", padx=16, pady=(0, 8))

        self._status_lbl = ctk.CTkLabel(
            left, text="Загрузите фото спуска",
            font=("JetBrains Mono", 10), text_color=TEXT3
        )
        self._status_lbl.pack(padx=16, pady=(0, 12))

        ctk.CTkFrame(left, fg_color=DARK_BD, height=1).pack(fill="x", pady=4)

        # Кнопки экспорта
        _lbl("ЭКСПОРТ").pack(anchor="w", padx=16, pady=(8, 6))
        for label, cmd in [
            ("⬇  Скачать TPL + JOB", self._export_both),
            ("↓  Только .tpl",        self._export_tpl),
            ("↓  Только .job",        self._export_job),
        ]:
            ctk.CTkButton(
                left, text=label,
                font=("JetBrains Mono", 11),
                fg_color=DARK_SF2, hover_color=DARK_BD2,
                border_color=DARK_BD2, border_width=1,
                text_color=TEXT2, height=32,
                command=cmd,
            ).pack(fill="x", padx=16, pady=3)

        # ── Правая панель (редактор сетки) ───────────────────────
        self.right = ctk.CTkFrame(self, fg_color=DARK_BG, corner_radius=0)
        self.right.grid(row=0, column=1, sticky="nsew")

        self._build_empty_state()

    def _build_empty_state(self):
        for w in self.right.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.right,
            text="⊟\n\nЗагрузите фото спуска\nи нажмите Распознать",
            font=("JetBrains Mono", 14), text_color=TEXT3,
            justify="center"
        ).place(relx=0.5, rely=0.5, anchor="center")

    def _pick_photo(self):
        path = filedialog.askopenfilename(
            filetypes=[("Изображения", "*.jpg *.jpeg *.png"), ("Все", "*.*")]
        )
        if path:
            self._load_photo(path)

    def _load_photo(self, path: str):
        from PIL import Image, ImageTk
        self._img_path = path
        img = Image.open(path)
        img.thumbnail((260, 200))
        photo = ImageTk.PhotoImage(img)
        self.photo_lbl.configure(image=photo, text="")
        self.photo_lbl.image = photo
        self.btn_analyze.configure(state="normal")
        self._status_lbl.configure(text="Фото загружено")

    def _analyze(self):
        if not self._img_path:
            return
        self.btn_analyze.configure(state="disabled", text="⟳  Анализирую...")
        self._status_lbl.configure(text="Отправляю в AI...")

        def worker():
            try:
                result = self._call_ai()
                self.after(0, lambda: self._apply_result(result))
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
            f"You are a prepress specialist. This is a handwritten imposition layout. "
            f"Grid: {rows} rows x {cols} columns. "
            f"{'Find TWO impositions (face and back).' if two else ''} "
            f"Return ONLY valid JSON:\n"
            f'{{"overall_confidence":0.5,"issues":[],"sheets":['
            f'{{"side":"face","label":"Лицо","rows":{rows},"cols":{cols},'
            f'"cells":[{{"row":0,"col":0,"page":null,"rotated":false,"confident":true}}]}}'
            f'{"," + chr(123) + chr(34) + "side" + chr(34) + ":" + chr(34) + "back" + chr(34) + "," + chr(34) + "label" + chr(34) + ":" + chr(34) + "Оборот" + chr(34) + "," + chr(34) + "rows" + chr(34) + ":" + str(rows) + "," + chr(34) + "cols" + chr(34) + ":" + str(cols) + "," + chr(34) + "cells" + chr(34) + ":[...]" + chr(125) if two else ""}'
            f']}}'
        )

        if self.v_engine.get() == "ollama":
            import config as cfg
            resp = requests.post(
                cfg.CFG["ollama_url"],
                json={"model": cfg.CFG["ollama_model"], "prompt": prompt,
                      "images": [img_b64], "stream": False,
                      "options": {"temperature": 0.1}},
                timeout=120
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")
        else:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                json={"model": "claude-sonnet-4-20250514", "max_tokens": 1000,
                      "messages": [{"role": "user", "content": [
                          {"type": "image", "source": {"type": "base64",
                           "media_type": "image/jpeg", "data": img_b64}},
                          {"type": "text", "text": prompt}
                      ]}]},
                headers={"Content-Type": "application/json"},
                timeout=60
            )
            resp.raise_for_status()
            raw = resp.json()["content"][0]["text"]

        raw = raw.strip().replace("```json", "").replace("```", "").strip()
        m = __import__("re").search(r"\{[\s\S]*\}", raw)
        if not m:
            raise ValueError("JSON не найден в ответе")
        return json.loads(m.group(0))

    def _apply_result(self, result: dict):
        self._sheets = result.get("sheets", [])
        conf = result.get("overall_confidence", 0)
        issues = result.get("issues", [])
        self._status_lbl.configure(
            text=f"Уверенность: {int(conf*100)}%"
                 + (f"  ⚠ {issues[0]}" if issues else "")
        )
        self._render_grid()

    def _on_error(self, msg: str):
        self._status_lbl.configure(text=f"Ошибка: {msg}")

    def _render_grid(self):
        for w in self.right.winfo_children():
            w.destroy()

        scroll = ctk.CTkScrollableFrame(
            self.right, fg_color="transparent"
        )
        scroll.pack(fill="both", expand=True, padx=20, pady=20)

        for si, sheet in enumerate(self._sheets):
            sc = "lf" if sheet["side"] == "face" else "lb"
            hdr = ctk.CTkFrame(scroll, fg_color="transparent")
            hdr.pack(anchor="w", pady=(0 if si == 0 else 16, 6))

            ctk.CTkLabel(
                hdr, text=f"ЛИСТ {si+1}",
                font=("JetBrains Mono", 11), text_color=TEXT2
            ).pack(side="left")
            ctk.CTkLabel(
                hdr, text=f"  {sheet['label']}",
                font=("JetBrains Mono", 10), text_color=ACCENT if sheet["side"]=="face" else INFO
            ).pack(side="left")
            ctk.CTkLabel(
                hdr, text=f"  {sheet['rows']}×{sheet['cols']}",
                font=("JetBrains Mono", 10), text_color=TEXT3
            ).pack(side="left")

            grid_frame = ctk.CTkFrame(scroll, fg_color=DARK_SF2, corner_radius=4)
            grid_frame.pack(anchor="w")

            rows, cols = sheet["rows"], sheet["cols"]
            cells = {(c["row"], c["col"]): c for c in sheet.get("cells", [])}

            for r in range(rows):
                for c in range(cols):
                    cd = cells.get((r, c), {})
                    page = cd.get("page")
                    confident = cd.get("confident", True)
                    rotated = cd.get("rotated", False)

                    cell = ctk.CTkFrame(
                        grid_frame, width=70, height=52,
                        fg_color=DARK_SF,
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
                        justify="center"
                    )
                    entry.place(relx=0.5, rely=0.5, anchor="center")

                    # Сохраняем var для экспорта
                    cd["_var"] = var
                    cells[(r, c)] = cd

                    if rotated:
                        ctk.CTkLabel(
                            cell, text="↻", font=("Arial", 8),
                            text_color=WARNING
                        ).place(relx=1.0, rely=0.0, anchor="ne", x=-2, y=2)

            sheet["_cells_vars"] = cells

    # ── EXPORT ────────────────────────────────────────────────────
    def _collect_sheets(self):
        """Собираем актуальные данные из UI полей."""
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
            initialfile="NewTemplate.tpl"
        )
        if path:
            content = generate_tpl(sheets)
            with open(path, "w", encoding="cp1251") as f:
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
            with open(path, "w", encoding="cp1251") as f:
                f.write(content)

    def _export_both(self):
        self._export_tpl()
        self._export_job()
