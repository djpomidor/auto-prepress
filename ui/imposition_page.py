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
import config
from db.database import get_session, get_imposition, save_imposition
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


def _scan_preps_templates(order) -> list:
    """
    Ищет .tpl шаблоны Preps в папках config.preps_templates,
    подходящие под обрезной формат и тип скрепления заказа.
    Возвращает список словарей, отсортированный по имени.
    """
    if not order or not order.width or not order.height:
        return []

    dirs = config.CFG.get("preps_templates", [])
    trim_pair = {int(order.width), int(order.height)}
    binding_code  = order.binding or ""
    binding_label = binding_code_to_label(order.binding) if order.binding else ""

    results = []
    seen_paths = set()
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d)
        except Exception:
            continue
        for fname in entries:
            if not fname.lower().endswith(".tpl"):
                continue
            m = _TEMPLATE_RE.match(fname)
            if not m:
                continue
            try:
                tw, th = int(m.group("trim_w")), int(m.group("trim_h"))
            except ValueError:
                continue
            if {tw, th} != trim_pair:
                continue
            if binding_code and not _binding_matches(binding_code, binding_label, m.group("binding")):
                continue

            path = os.path.join(d, fname)
            if path in seen_paths:
                continue
            seen_paths.add(path)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = 0
            results.append({
                "fname": fname,
                "path": path,
                "source_dir": d,
                "order_num": m.group("order"),
                "name": m.group("name"),
                "trim": f"{tw}x{th}",
                "paper": f"{m.group('paper_w')}x{m.group('paper_h')}",
                "binding": m.group("binding"),
                "mtime": mtime,
                "year": datetime.fromtimestamp(mtime).year if mtime else None,
            })

    # Сначала новые — по дате изменения файла шаблона (убывание)
    results.sort(key=lambda r: r["mtime"], reverse=True)
    return results


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
            command=self._refresh_templates,
        ).pack(side="right", padx=10, pady=6)

        self._templates_criteria_lbl = ctk.CTkLabel(
            frame, text="", font=("JetBrains Mono", 10),
            text_color=("gray25","gray80"), justify="left", anchor="w", wraplength=280,
        )
        self._templates_criteria_lbl.grid(row=1, column=0, sticky="ew", padx=14, pady=(10, 4))

        self.templates_list = ctk.CTkScrollableFrame(
            frame, fg_color="transparent",
            scrollbar_button_color=DARK_BD,
        )
        self.templates_list.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
        self.templates_list.grid_columnconfigure(0, weight=1)

    def _refresh_templates(self):
        if not hasattr(self, "templates_list"):
            return

        for w in self.templates_list.winfo_children():
            w.destroy()

        if not self.order:
            self._templates_criteria_lbl.configure(text="Заказ не найден.")
            return

        o = self.order
        fmt = f"{o.width}×{o.height} мм" if o.width and o.height else "формат не указан"
        binding = binding_code_to_label(o.binding) if o.binding else "скрепление не указано"
        self._templates_criteria_lbl.configure(
            text=f"Заказ №{o.number:04d}\nФормат: {fmt}\nСкрепление: {binding}"
        )

        if not o.width or not o.height:
            ctk.CTkLabel(
                self.templates_list,
                text="У заказа не указан обрезной формат —\nнечего сопоставлять с шаблонами.",
                font=("JetBrains Mono", 11), text_color=("gray25","gray80"), justify="left",
            ).pack(anchor="w", padx=12, pady=12)
            return

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

            card = ctk.CTkFrame(self.templates_list, fg_color=("gray85","gray20"),
                                 corner_radius=6, cursor="hand2")
            card.pack(fill="x", padx=8, pady=5)

            name_lbl = ctk.CTkLabel(
                card, text=tpl["fname"], font=("JetBrains Mono", 12, "bold"),
                text_color=ACCENT, anchor="w", justify="left", wraplength=270,
                cursor="hand2",
            )
            name_lbl.pack(fill="x", padx=10, pady=(10, 2), anchor="w")

            meta_lbl = ctk.CTkLabel(
                card,
                text=f"№{tpl['order_num']} · {tpl['trim']} мм · бумага {tpl['paper']} · {tpl['binding']}",
                font=("JetBrains Mono", 11), text_color=("gray30","gray75"), anchor="w",
            )
            meta_lbl.pack(fill="x", padx=10, pady=(0, 10), anchor="w")

            for widget in (card, name_lbl, meta_lbl):
                widget.bind("<Button-1>", lambda e, p=tpl["path"]: self._open_template(p))

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
            text=f"✓ {os.path.basename(saved_path)}", text_color=ACCENT
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
        self._status_lbl.configure(text="✓ Спуск сохранён", text_color=ACCENT)

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