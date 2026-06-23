"""
Страница спуска полос.
"""
import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog
import threading
import base64
import json
import os

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
    def __init__(self, parent, app, order_id: int = None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self.order_id = order_id
        self._img_path = None
        self._sheets = []

        self._build()

    # ── LAYOUT ────────────────────────────────────────────────────
    def _build(self):
        self.grid_columnconfigure(0, weight=0, minsize=310)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Левая панель ──────────────────────────────────────────
        left = ctk.CTkScrollableFrame(
            self, fg_color=("gray90","gray17"), corner_radius=0, width=310
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 1))

        def lbl(t):
            return ctk.CTkLabel(
                left, text=t,
                font=("JetBrains Mono", 9), text_color=("gray40","gray60"), anchor="w"
            )

        # ── Фото ──────────────────────────────────────────────────
        lbl("ФОТО СПУСКА").pack(anchor="w", padx=16, pady=(16, 6))

        self.photo_zone = ctk.CTkFrame(
            left, fg_color=("gray85","gray20"), corner_radius=6,
            border_width=1,  height=80
        )
        self.photo_zone.pack(fill="x", padx=16)
        self.photo_zone.pack_propagate(False)
        self._drop_lbl = ctk.CTkLabel(
            self.photo_zone,
            text="Нажмите или перетащите JPG",
            font=("JetBrains Mono", 11), text_color=TEXT3
        )
        self._drop_lbl.place(relx=0.5, rely=0.5, anchor="center")
        self.photo_zone.bind("<Button-1>", lambda _: self._pick_photo())
        self._drop_lbl.bind("<Button-1>", lambda _: self._pick_photo())

        # Превью фото
        self.photo_preview = ctk.CTkLabel(left, text="", image=None)
        self.photo_preview.pack(padx=16, pady=(6, 0))

        ctk.CTkFrame(left, fg_color=("gray80","gray25"), height=1).pack(fill="x", pady=10)

        # ── Сетка ─────────────────────────────────────────────────
        lbl("ПАРАМЕТРЫ СЕТКИ").pack(anchor="w", padx=16, pady=(0, 6))
        grid_f = ctk.CTkFrame(left, fg_color="transparent")
        grid_f.pack(fill="x", padx=16)
        grid_f.columnconfigure(1, weight=1)

        self.v_rows = tk.StringVar(value="4")
        self.v_cols = tk.StringVar(value="4")
        self.v_two  = tk.BooleanVar(value=True)

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

        # lbl2("Модель").pack(anchor="w", pady=(0, 2))
        # self.v_ollama_model = tk.StringVar(value="qwen2-vl:7b")
        # ctk.CTkEntry(
        #     self.ollama_frame, textvariable=self.v_ollama_model,
        #     font=("JetBrains Mono", 11),
        #     fg_color=("gray85","gray20"),  
        # ).pack(fill="x", pady=(0, 6))

#######################################################################################
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



#######################################################################################


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
            text_color=DARK_BG, height=38,
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

        # ── Правая панель ─────────────────────────────────────────
        self.right = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.right.grid(row=0, column=1, sticky="nsew")
        self._build_empty_state()

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
        for w in self.right.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.right,
            text="⊟\n\nЗагрузите фото спуска\nи нажмите Распознать",
            font=("JetBrains Mono", 14), text_color=("gray40","gray60"), justify="center"
        ).place(relx=0.5, rely=0.5, anchor="center")

    def _pick_photo(self):
        path = filedialog.askopenfilename(
            filetypes=[("Изображения", "*.jpg *.jpeg *.png"), ("Все", "*.*")]
        )
        if path:
            self._load_photo(path)

    def _load_photo(self, path: str):
        from PIL import Image
        self._img_path = path
        img = Image.open(path)
        img.thumbnail((270, 200))
        # Используем CTkImage — правильный способ для CustomTkinter
        ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
        self.photo_preview.configure(image=ctk_img, text="")
        self.photo_preview._ctk_image = ctk_img   # держим ссылку
        self._drop_lbl.configure(
            text=f"✓ {os.path.basename(path)}", text_color=ACCENT
        )
        self.btn_analyze.configure(state="normal")
        self._status_lbl.configure(text="Фото загружено")

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
        m = __import__("re").search(r"\{[\s\S]*\}", raw)
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

    def _on_error(self, msg: str):
        self._status_lbl.configure(
            text=f"Ошибка:\n{msg}", text_color=DANGER
        )

    # ── GRID RENDER ───────────────────────────────────────────────
    def _render_grid(self):
        for w in self.right.winfo_children():
            w.destroy()

        scroll = ctk.CTkScrollableFrame(self.right, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=20)

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
                text_color=ACCENT if sheet["side"] == "face" else INFO
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
