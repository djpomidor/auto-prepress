"""
Страница заказа: создание / просмотр / редактирование.
"""
import os
import shutil
import tempfile
import threading
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
from tkinter import filedialog, messagebox
from datetime import datetime
from db.database import get_session
from db.models import Order
import config

# Куда сохраняется JPG превью распознанной спецификации ДО того, как
# заказ создан (папки на P: ещё нет) — переживает переключение между
# страницами приложения (но не предназначено для долгого хранения).
_PENDING_PREVIEW_DIR  = os.path.join(tempfile.gettempdir(), "ImpoReader")
_PENDING_PREVIEW_PATH = os.path.join(_PENDING_PREVIEW_DIR, "pending_preview.jpg")

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
WARNING  = "#ffaa33"


def _poppler_kwargs() -> dict:
    """Путь к Poppler (pdftoppm/pdfinfo), если он не в системном PATH —
    берётся из config.json (ключ poppler_path)."""
    p = config.CFG.get("poppler_path") or ""
    return {"poppler_path": p} if p else {}


def _label(parent, text, **kw):    return ctk.CTkLabel(
        parent, text=text,
        font=("JetBrains Mono", 10), text_color=("gray40","gray60"),
        anchor="w", **kw
    )

def _entry(parent, var, width=200, **kw):
    return ctk.CTkEntry(
        parent, textvariable=var,
        font=("JetBrains Mono", 13),
        fg_color=("gray85","gray20"),  border_width=1,
         width=width, **kw
    )


class OrderPage(ctk.CTkFrame):
    def __init__(self, parent, app, order_id=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self.order_id = order_id
        self.order = None  # type: Optional[Order]
        self._monitor_thread = None

        # Путь к файлу спецификации, который ещё не перенесён в папку
        # заказа (заказ пока не создан — папки не существует)
        self._pending_spec_path = None

        # Переменные формы
        self.v_number      = tk.StringVar()
        self.v_name        = tk.StringVar()
        self.v_description = tk.StringVar()
        self.v_format      = tk.StringVar()   # "Ширина x Высота", напр. "150x225"
        self.v_circ        = tk.StringVar()
        self.v_binding      = tk.StringVar()
        self.v_pages_block  = tk.StringVar()
        self.v_pages_cover  = tk.StringVar()
        self.v_pages_insert = tk.StringVar()
        self.v_color_block  = tk.StringVar()
        self.v_color_cover  = tk.StringVar()
        self.v_color_insert = tk.StringVar()
        self.v_delivery = tk.StringVar()
        self.v_submit   = tk.StringVar()
        self.v_due      = tk.StringVar()
        # Многострочные поля — свои Textbox-виджеты (создаются в _build_form)
        self.txt_postprocessing = None
        self.txt_tech_notes     = None

        self._build()

        if order_id:
            self._load_order(order_id)
        else:
            self._load_pending_preview_temp()

    # ── BUILD ─────────────────────────────────────────────────────
    def _build(self):
        # Три панели в PanedWindow — форма / превью спецификации /
        # результаты PitStop. Границы можно перетаскивать мышью.
        # По умолчанию: форма 1/4, превью 2/4, PitStop 1/4 ширины окна.
        self.pack_propagate(False)
        try:
            win_w = self.app.cfg.get("window_width", 1400)
        except Exception:
            win_w = 1400
        left_default_w  = max(320, int(win_w * 0.25))
        right_default_w = max(320, int(win_w * 0.25))

        is_dark = ctk.get_appearance_mode().lower() == "dark"
        sash_bg = "#242424" if is_dark else "#d5d5d5"

        self._paned = tk.PanedWindow(
            self, orient="horizontal", sashwidth=6, sashrelief="flat",
            bg=sash_bg, bd=0,
        )
        self._paned.pack(fill="both", expand=True)

        # ── Левая панель — форма ────────────────────────────────
        # ВАЖНО: tk.PanedWindow.add() требует, чтобы добавляемый виджет
        # был прямым потомком panedwindow на уровне Tcl. У CTkScrollableFrame
        # сложная внутренняя структура (canvas + внутренний frame), поэтому
        # напрямую добавлять его в PanedWindow нельзя — сначала оборачиваем
        # в обычный CTkFrame-контейнер, который и добавляем в панель.
        left_container = ctk.CTkFrame(
            self._paned, fg_color=("gray90","gray17"), corner_radius=0,
        )
        self._paned.add(left_container, width=left_default_w, minsize=280, stretch="never")

        left = ctk.CTkScrollableFrame(
            left_container, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=DARK_BD,
        )
        left.pack(fill="both", expand=True)

        self._build_drop_zone(left)
        ctk.CTkFrame(left, fg_color=("gray80","gray25"), height=1).pack(fill="x", pady=12)
        self._build_form(left)
        self._build_action_buttons(left)

        # ── Центральная панель — превью спецификации ────────────
        center = ctk.CTkFrame(self._paned, fg_color=("gray88","gray14"), corner_radius=0)
        center.grid_rowconfigure(1, weight=1)
        center.grid_columnconfigure(0, weight=1)
        self._paned.add(center, minsize=300, stretch="always")
        self._build_preview_panel(center)

        # ── Правая панель — результаты PitStop ───────────────────
        right = ctk.CTkFrame(self._paned, fg_color="transparent", corner_radius=0)
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)
        self._paned.add(right, width=right_default_w, minsize=280, stretch="never")
        self._build_pitstop_panel(right)

    # ── PREVIEW PANEL (центр) ────────────────────────────────────
    def _build_preview_panel(self, parent):
        hdr = ctk.CTkFrame(parent, fg_color=("gray85","gray20"), height=36, corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        _label(hdr, "ПРЕВЬЮ СПЕЦИФИКАЦИИ").pack(side="left", padx=16, pady=8)

        # ── Управление зумом ─────────────────────────────────────
        zoom_box = ctk.CTkFrame(hdr, fg_color="transparent")
        zoom_box.pack(side="right", padx=10, pady=4)

        ctk.CTkButton(
            zoom_box, text="−", width=26, height=24, font=("JetBrains Mono", 13, "bold"),
            fg_color=("gray80","gray25"), hover_color=DARK_BD2,
            command=self._zoom_out,
        ).pack(side="left", padx=2)

        self._zoom_lbl = ctk.CTkLabel(
            zoom_box, text="—", font=("JetBrains Mono", 10), width=42,
        )
        self._zoom_lbl.pack(side="left", padx=2)

        ctk.CTkButton(
            zoom_box, text="+", width=26, height=24, font=("JetBrains Mono", 13, "bold"),
            fg_color=("gray80","gray25"), hover_color=DARK_BD2,
            command=self._zoom_in,
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            zoom_box, text="⤢ 100%", width=56, height=24, font=("JetBrains Mono", 10),
            fg_color=("gray80","gray25"), hover_color=DARK_BD2,
            command=self._zoom_reset,
        ).pack(side="left", padx=(6, 0))

        # ── Холст превью (с прокруткой при увеличении) ────────────
        self._preview_area = ctk.CTkFrame(parent, fg_color="transparent")
        self._preview_area.grid(row=1, column=0, sticky="nsew")
        self._preview_area.grid_rowconfigure(0, weight=1)
        self._preview_area.grid_columnconfigure(0, weight=1)

        is_dark = ctk.get_appearance_mode().lower() == "dark"
        canvas_bg = "#161616" if is_dark else "#dcdcdc"

        self._preview_canvas = tk.Canvas(
            self._preview_area, bg=canvas_bg, highlightthickness=0, bd=0,
        )
        self._preview_canvas.grid(row=0, column=0, sticky="nsew")

        vsb = ttk.Scrollbar(self._preview_area, orient="vertical",
                             command=self._preview_canvas.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb = ttk.Scrollbar(self._preview_area, orient="horizontal",
                             command=self._preview_canvas.xview)
        hsb.grid(row=1, column=0, sticky="ew")
        self._preview_canvas.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._preview_pil_image = None   # оригинал (полное разрешение)
        self._preview_tk_image  = None   # текущая отрисованная картинка (ссылка для GC)
        self._preview_zoom      = 1.0    # множитель поверх масштаба "вписать в окно"

        self._preview_canvas.bind("<Configure>", lambda e: self._render_preview())
        # Зум колесом мыши
        self._preview_canvas.bind("<MouseWheel>", self._on_preview_wheel)        # Windows/macOS
        self._preview_canvas.bind("<Button-4>", lambda e: self._zoom_step(1))    # Linux — вверх
        self._preview_canvas.bind("<Button-5>", lambda e: self._zoom_step(-1))   # Linux — вниз
        # Перетаскивание (панорамирование) зажатой левой кнопкой мыши
        self._preview_canvas.bind("<ButtonPress-1>", lambda e: self._preview_canvas.scan_mark(e.x, e.y))
        self._preview_canvas.bind("<B1-Motion>", lambda e: self._preview_canvas.scan_dragto(e.x, e.y, gain=1))

        # ── Полоса несовпадений (формат / кол-во полос) ──────────
        self._mismatch_bar = ctk.CTkFrame(parent, fg_color=WARNING, corner_radius=0, height=0)
        self._mismatch_bar.grid(row=2, column=0, sticky="ew")
        self._mismatch_bar.grid_propagate(False)
        self._mismatch_lbl = ctk.CTkLabel(
            self._mismatch_bar, text="", font=("JetBrains Mono", 11, "bold"),
            text_color="#1a1a1a", justify="left", anchor="w",
        )
        self._mismatch_lbl.pack(fill="x", padx=14, pady=6)
        self._mismatch_bar.grid_remove()  # скрыт пока нет предупреждений

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

    def _render_preview(self):
        """Перерисовывает превью на холсте с учётом текущего зума."""
        if not hasattr(self, "_preview_canvas"):
            return
        canvas = self._preview_canvas
        cw = max(1, canvas.winfo_width())
        ch = max(1, canvas.winfo_height())

        if not self._preview_pil_image:
            canvas.delete("all")
            canvas.create_text(
                cw // 2, ch // 2,
                text="Спецификация ещё не загружена.\nПеретащите PDF/JPG в левую панель.",
                fill=TEXT3, font=("JetBrains Mono", 12), justify="center",
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
        # Если картинка меньше холста — центрируем, иначе — от угла
        # (и разрешаем скроллить/перетаскивать)
        x0 = max(0, (cw - new_w) // 2)
        y0 = max(0, (ch - new_h) // 2)
        canvas.create_image(x0, y0, anchor="nw", image=self._preview_tk_image)
        region_w = max(cw, new_w)
        region_h = max(ch, new_h)
        canvas.configure(scrollregion=(0, 0, region_w, region_h))

        self._zoom_lbl.configure(text=f"{int(self._preview_zoom * 100)}%")

    def _update_preview_display(self, path: str):
        """Загружает (или рендерит из PDF) картинку в центральную панель."""
        ext = os.path.splitext(path)[1].lower()
        try:
            from PIL import Image
            if ext == ".pdf":
                from pdf2image import convert_from_path
                pages = convert_from_path(
                    path, dpi=150, first_page=1, last_page=1,
                    **_poppler_kwargs()
                )
                if not pages:
                    return
                img = pages[0]
            else:
                img = Image.open(path)
                img.load()
            self._preview_pil_image = img
            self._preview_zoom = 1.0
            # Пока заказ не создан (папки на P: нет) — сохраняем превью
            # во временную папку, чтобы не потерять его при переходе
            # между страницами приложения.
            if not (self.order and self.order.folder_path):
                self._save_pending_preview_temp(img)
            self.after(0, self._render_preview)
        except Exception as e:
            self._preview_pil_image = None
            err = str(e)
            self.after(0, lambda: self._preview_canvas.create_text(
                self._preview_canvas.winfo_width() // 2,
                self._preview_canvas.winfo_height() // 2,
                text=f"Не удалось построить превью:\n{err}",
                fill=DANGER, font=("JetBrains Mono", 12), justify="center",
            ))

    def _save_pending_preview_temp(self, img):
        """Сохраняет превью во временную папку (пока заказ не создан)."""
        try:
            os.makedirs(_PENDING_PREVIEW_DIR, exist_ok=True)
            img.convert("RGB").save(_PENDING_PREVIEW_PATH, "JPEG", quality=90)
        except Exception:
            pass

    def _load_pending_preview_temp(self):
        """При открытии страницы НОВОГО заказа — подхватываем превью,
        сохранённое во временной папке при предыдущем распознавании
        (если пользователь успел уйти со страницы, не создав заказ)."""
        if self.order_id or not os.path.isfile(_PENDING_PREVIEW_PATH):
            return
        threading.Thread(
            target=self._update_preview_display,
            args=(_PENDING_PREVIEW_PATH,), daemon=True
        ).start()

    def _clear_pending_preview_temp(self):
        """Удаляет временное превью — вызывается после того, как
        спецификация и её JPG-превью уже сохранены в папке заказа."""
        try:
            if os.path.isfile(_PENDING_PREVIEW_PATH):
                os.remove(_PENDING_PREVIEW_PATH)
        except Exception:
            pass

    def _save_preview_jpg(self, pdf_path: str, folder_path: str):
        """Сохраняет JPG превью первой страницы PDF-спецификации в
        папку заказа на диске P: (рядом со спецификацией в in/)."""
        if not folder_path or os.path.splitext(pdf_path)[1].lower() != ".pdf":
            return None
        try:
            from pdf2image import convert_from_path
            pages = convert_from_path(
                pdf_path, dpi=150, first_page=1, last_page=1,
                **_poppler_kwargs()
            )
            if not pages:
                return None
            stem = os.path.splitext(os.path.basename(pdf_path))[0]
            dst_dir = os.path.dirname(pdf_path) if os.path.dirname(pdf_path) else folder_path
            dst = os.path.join(dst_dir, f"{stem}_preview.jpg")
            pages[0].save(dst, "JPEG", quality=90)
            return dst
        except Exception:
            return None



    # ── DROP ZONE ─────────────────────────────────────────────────
    def _build_drop_zone(self, parent):
        sec = ctk.CTkFrame(parent, fg_color="transparent")
        sec.pack(fill="x", padx=20, pady=(20, 0))

        _label(sec, "СПЕЦИФИКАЦИЯ ЗАКАЗА").pack(anchor="w", pady=(0, 6))

        self.drop_zone = ctk.CTkFrame(
            sec, fg_color=("gray85","gray20"), corner_radius=6,
            border_width=1,  height=90
        )
        self.drop_zone.pack(fill="x")
        self.drop_zone.pack_propagate(False)

        self.drop_lbl = ctk.CTkLabel(
            self.drop_zone,
            text="Перетащите PDF или JPG спецификации сюда\n"
                 "или нажмите для выбора файла",
            font=("JetBrains Mono", 11),
            text_color=("gray40","gray60"), justify="center"
        )
        self.drop_lbl.place(relx=0.5, rely=0.5, anchor="center")

        # Кнопка выбора файла
        self.drop_zone.bind("<Button-1>", lambda _: self._pick_spec_file())
        self.drop_lbl.bind("<Button-1>", lambda _: self._pick_spec_file())

        # Drag-and-drop через tkinterdnd2
        self._setup_dnd()

        # Прогресс OCR
        self._ocr_progress = ctk.CTkProgressBar(
            sec, mode="indeterminate",
            fg_color=("gray80","gray25"), progress_color=ACCENT,
        )

        self._ocr_status = ctk.CTkLabel(
            sec, text="", font=("JetBrains Mono", 10), text_color=TEXT3
        )
        self._ocr_status.pack(anchor="w", pady=(4, 0))

    # ── FORM ──────────────────────────────────────────────────────
    def _build_form(self, parent):
        sec = ctk.CTkFrame(parent, fg_color="transparent")
        sec.pack(fill="x", padx=20)
        sec.grid_columnconfigure(0, weight=1, uniform="col")
        sec.grid_columnconfigure(1, weight=1, uniform="col")

        # Поля спецификации — размещаются в две колонки, по одному
        # блоку label+entry на ячейку. "если есть" (Скрепление, Объём
        # обл./вкл., Красочность обл./вклейки) — эти поля можно
        # оставить пустыми, они не обязательны для сохранения заказа.
        fields = [
            ("Номер заказа",        self.v_number,       "Например: 0641"),
            ("Название",            self.v_name,         "До 32 символов"),
            ("Описание заказа",     self.v_description,  "книга / брошюра / газета..."),
            ("Формат",              self.v_format,        "Ширина x Высота, напр. 150x225"),
            ("Тираж",                self.v_circ,          ""),
            ("Скрепление",           self.v_binding,       "Термоклей / Скрепка / Тв. переплёт"),
            ("Объём блок",           self.v_pages_block,   "кол-во полос"),
            ("Объём обл.",           self.v_pages_cover,   "кол-во полос"),
            ("Объём вкл.",           self.v_pages_insert,  "кол-во полос"),
            ("Красочность блока",    self.v_color_block,   "напр. 4+4"),
            ("Красочность обложки",  self.v_color_cover,   "напр. 4+0"),
            ("Красочность вклейки",  self.v_color_insert,  "напр. 4+4"),
        ]

        for i, (label, var, hint) in enumerate(fields):
            row, col = divmod(i, 2)
            cell = ctk.CTkFrame(sec, fg_color="transparent")
            cell.grid(row=row, column=col, sticky="ew",
                      padx=(0, 12) if col == 0 else (0, 0), pady=5)
            _label(cell, label).pack(anchor="w")
            ctk.CTkEntry(
                cell, textvariable=var,
                placeholder_text=hint,
                font=("JetBrains Mono", 13),
                fg_color=("gray85","gray20"), border_width=1,
            ).pack(fill="x", pady=(2, 0))

        # ── Постпечатная обработка / Технические пояснения ────────
        # Многострочные поля, во всю ширину сайдбара
        multiline_sec = ctk.CTkFrame(parent, fg_color="transparent")
        multiline_sec.pack(fill="x", padx=20, pady=(10, 0))

        _label(multiline_sec, "Постпечатная обработка").pack(anchor="w", pady=(0, 2))
        self.txt_postprocessing = ctk.CTkTextbox(
            multiline_sec, height=54, font=("JetBrains Mono", 12),
            fg_color=("gray85","gray20"), border_width=1, wrap="word",
        )
        self.txt_postprocessing.pack(fill="x", pady=(0, 10))

        _label(multiline_sec, "Технические пояснения").pack(anchor="w", pady=(0, 2))
        self.txt_tech_notes = ctk.CTkTextbox(
            multiline_sec, height=80, font=("JetBrains Mono", 12),
            fg_color=("gray85","gray20"), border_width=1, wrap="word",
        )
        self.txt_tech_notes.pack(fill="x", pady=(0, 4))

        # ── Даты ────────────────────────────────────────────────────
        dates_sec = ctk.CTkFrame(parent, fg_color="transparent")
        dates_sec.pack(fill="x", padx=20, pady=(10, 0))
        dates_sec.grid_columnconfigure(1, weight=1)

        date_fields = [
            ("Дата выхода",    self.v_delivery, "ДД.ММ.ГГГГ"),
            ("Сдача файлов",   self.v_submit,   "ДД.ММ.ГГГГ"),
            ("Дата в печать",  self.v_due,      "ДД.ММ.ГГГГ"),
        ]
        for row, (label, var, hint) in enumerate(date_fields):
            _label(dates_sec, label).grid(row=row, column=0, sticky="w",
                                          pady=5, padx=(0, 16))
            ctk.CTkEntry(
                dates_sec, textvariable=var,
                placeholder_text=hint,
                font=("JetBrains Mono", 13),
                fg_color=("gray85","gray20"), border_width=1,
            ).grid(row=row, column=1, sticky="ew", pady=5)

    # ── ACTION BUTTONS ────────────────────────────────────────────
    def _build_action_buttons(self, parent):
        btn_frame = ctk.CTkFrame(parent, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=20)

        # Кнопка "Создать" / "Сохранить"
        self.btn_create = ctk.CTkButton(
            btn_frame,
            text="✓  Создать заказ",
            font=("JetBrains Mono", 13, "bold"),
            fg_color=SUCCESS, hover_color="#29a855",
            text_color=DARK_BG, height=40,
            command=self._create_or_save,
        )
        self.btn_create.pack(fill="x", pady=(0, 8))

        # Кнопка мониторинга (появляется после создания)
        self.btn_monitor = ctk.CTkButton(
            btn_frame,
            text="",
            font=("JetBrains Mono", 12),
            height=36, command=self._toggle_monitor
        )

        # Кнопка спуска полос (появляется после создания)
        self.btn_imposition = ctk.CTkButton(
            btn_frame,
            text="⊞  Сделать спуск полос",
            font=("JetBrains Mono", 12),
            fg_color=("gray85","gray20"), hover_color=DARK_BD2,
             border_width=1,
             height=36,
            command=self._open_imposition,
        )

    # ── PITSTOP PANEL ─────────────────────────────────────────────
    def _build_pitstop_panel(self, parent):
        frame = ctk.CTkFrame(parent, fg_color=("gray90","gray17"), corner_radius=0)
        frame.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(frame, fg_color=("gray85","gray20"), height=36, corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)

        _label(hdr, "РЕЗУЛЬТАТЫ PREFLIGHT (PitStop)").pack(
            side="left", padx=16, pady=8
        )

        ctk.CTkButton(
            hdr, text="↺ Обновить", width=90, height=24,
            font=("JetBrains Mono", 10),
            fg_color=("gray80","gray25"), hover_color=DARK_BD2,
             command=self._refresh_pitstop
        ).pack(side="right", padx=10, pady=6)

        self.pitstop_list = ctk.CTkScrollableFrame(
            frame, fg_color="transparent",
            scrollbar_button_color=DARK_BD,
        )
        self.pitstop_list.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.pitstop_list.grid_columnconfigure(0, weight=1)

        self._set_pitstop_placeholder(
            "Ожидание файлов...\n\nПосле появления PDF в папке in\nрезультаты проверки отобразятся здесь."
        )

    def _set_pitstop_placeholder(self, text: str):
        for w in self.pitstop_list.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.pitstop_list, text=text, font=("JetBrains Mono", 11),
            text_color=TEXT3, justify="left",
        ).pack(anchor="w", padx=12, pady=12)

    def _render_pitstop_reports(self, reports: list):
        """Отрисовывает список отчётов, от новых к старым."""
        for w in self.pitstop_list.winfo_children():
            w.destroy()

        if not reports:
            self._set_pitstop_placeholder(
                "XML лог PitStop не найден.\nОжидание проверки файлов..."
            )
            return

        for rep in reports:
            block = ctk.CTkFrame(self.pitstop_list, fg_color=("gray85","gray20"),
                                  corner_radius=6)
            block.pack(fill="x", padx=8, pady=6)

            top = ctk.CTkFrame(block, fg_color="transparent")
            top.pack(fill="x", padx=10, pady=(8, 2))

            status_color = DANGER if rep["errors"] else (WARNING if rep["warnings"] else SUCCESS)
            ctk.CTkLabel(
                top, text=rep["dt"].strftime("%d.%m.%Y  %H:%M:%S"),
                font=("JetBrains Mono", 12, "bold"), text_color=status_color,
                anchor="w",
            ).pack(side="left")

            ctk.CTkLabel(
                top, text=rep["fname"], font=("JetBrains Mono", 9),
                text_color=TEXT3,
            ).pack(side="right")

            if rep["pdf_path"]:
                link = ctk.CTkLabel(
                    block, text="🔗 Открыть PDF лога в Acrobat",
                    font=("JetBrains Mono", 10, "underline"),
                    text_color=ACCENT, cursor="hand2", anchor="w",
                )
                link.pack(anchor="w", padx=10, pady=(0, 4))
                link.bind("<Button-1>", lambda e, p=rep["pdf_path"]: self._open_in_acrobat(p))

            body = ctk.CTkLabel(
                block, text=rep["text"], font=("JetBrains Mono", 10),
                text_color=TEXT2, justify="left", anchor="w", wraplength=280,
            )
            body.pack(fill="x", padx=10, pady=(0, 10))

    def _open_in_acrobat(self, pdf_path: str):
        import subprocess
        acrobat = config.CFG.get("acrobat_path", "")
        try:
            if acrobat and os.path.isfile(acrobat):
                subprocess.Popen([acrobat, pdf_path])
            else:
                os.startfile(pdf_path)  # fallback — приложение по умолчанию
        except Exception as e:
            messagebox.showerror("Acrobat", f"Не удалось открыть PDF:\n{e}")


    # ── LOAD ORDER ────────────────────────────────────────────────
    def _load_order(self, order_id: int):
        session = get_session()
        try:
            self.order = session.get(Order, order_id)
        finally:
            session.close()

        if not self.order:
            return

        o = self.order
        self.v_number.set(str(o.number))
        self.v_name.set(o.name or "")
        self.v_description.set(o.description or "")
        self.v_circ.set(str(o.circulation) if o.circulation else "")
        self.v_binding.set(o.binding or "")
        if o.width and o.height:
            self.v_format.set(f"{o.width}x{o.height}")
        else:
            self.v_format.set("")
        self.v_pages_block.set(str(o.pages_block) if o.pages_block else "")
        self.v_pages_cover.set(str(o.pages_cover) if o.pages_cover else "")
        self.v_pages_insert.set(str(o.pages_insert) if o.pages_insert else "")
        self.v_color_block.set(o.color_block or "")
        self.v_color_cover.set(o.color_cover or "")
        self.v_color_insert.set(o.color_insert or "")

        self.txt_postprocessing.delete("1.0", "end")
        self.txt_postprocessing.insert("1.0", o.postprocessing or "")
        self.txt_tech_notes.delete("1.0", "end")
        self.txt_tech_notes.insert("1.0", o.tech_notes or "")

        def _fmt(dt): return dt.strftime("%d.%m.%Y") if dt else ""
        self.v_delivery.set(_fmt(o.delivery_date))
        self.v_submit.set(_fmt(o.submiting_files))
        self.v_due.set(_fmt(o.due_date))

        self.btn_create.configure(text="💾  Сохранить изменения")
        self._show_order_buttons()

        # Подтягиваем историю PitStop и превью существующей спецификации
        self._refresh_pitstop()
        self._load_existing_preview()

        # Автозапуск мониторинга если был включён
        if o.monitoring and o.folder_path:
            self._start_monitoring(o)

    def _load_existing_preview(self):
        """При открытии существующего заказа — показываем превью уже
        сохранённой спецификации (PDF/JPG)."""
        if not self.order or not self.order.folder_path:
            return

        path = self.order.spec_path
        if not path or not os.path.isfile(path):
            # Заказ создан до появления поля spec_path — ищем в корне
            # папки заказа (старое поведение, best-effort)
            root = self.order.folder_path
            if not os.path.isdir(root):
                return
            candidates = [
                f for f in os.listdir(root)
                if f.lower().endswith((".pdf", ".jpg", ".jpeg", ".png"))
                and not f.endswith("_preview.jpg")
            ]
            if not candidates:
                return
            candidates.sort(key=lambda f: os.path.getmtime(os.path.join(root, f)), reverse=True)
            path = os.path.join(root, candidates[0])

        threading.Thread(target=self._update_preview_display, args=(path,), daemon=True).start()

    # ── SPEC FILE ─────────────────────────────────────────────────
    def _pick_spec_file(self):
        path = filedialog.askopenfilename(
            title="Выберите спецификацию",
            filetypes=[
                ("PDF / изображения", "*.pdf *.jpg *.jpeg *.png"),
                ("Все файлы", "*.*"),
            ]
        )
        if path:
            self._process_spec(path)

    def _on_drop(self, event):
        """Обработка drop события от tkinterdnd2."""
        raw = event.data.strip()
        # Windows возвращает пути в фигурных скобках если есть пробелы
        # Несколько файлов разделены пробелами — берём первый
        if raw.startswith("{"):
            # Парсим путь в скобках: {C:/path with spaces/file.pdf}
            import re
            paths = re.findall(r"\{([^}]+)\}", raw)
            if not paths:
                paths = [raw.strip("{}")]
        else:
            paths = raw.split()
        path = paths[0] if paths else ""
        path = path.strip()
        if os.path.isfile(path):
            self._process_spec(path)


    def _setup_dnd(self):
        """Настройка drag-and-drop если tkinterdnd2 доступен."""
        try:
            self.drop_zone.drop_target_register("DND_Files")
            self.drop_zone.dnd_bind("<<Drop>>", self._on_drop)
            self.drop_lbl.drop_target_register("DND_Files")
            self.drop_lbl.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass  # tkinterdnd2 не установлен — работаем только через кнопку

    def _stage_spec_file(self, path: str) -> str:
        """
        Переносит файл спецификации в КОРЕНЬ папки заказа на диске P:
        (не в in\\ — там теперь лежат файлы заказчика для Prinergy
        Refine) ДО распознавания. Если заказ ещё не создан (папки не
        существует), запоминает путь — файл будет скопирован в папку
        заказа сразу после её создания.
        Возвращает путь, с которого нужно распознавать (копия в
        папке заказа, либо исходный путь, если папки ещё нет).
        """
        folder_path = self.order.folder_path if self.order else None
        if not folder_path:
            self._pending_spec_path = path
            return path

        try:
            os.makedirs(folder_path, exist_ok=True)
            dst = os.path.join(folder_path, os.path.basename(path))
            if os.path.abspath(dst) != os.path.abspath(path):
                shutil.copy2(path, dst)
            self._pending_spec_path = None
            self._save_spec_path(dst)
            return dst
        except Exception as e:
            # Диск P: недоступен — распознаём с исходного пути,
            # но предупреждаем пользователя
            self._ocr_status.configure(
                text=f"⚠ Не удалось скопировать на P: ({e}) — распознаю с исходного файла"
            )
            self._pending_spec_path = path
            return path

    def _save_spec_path(self, path: str):
        """Сохраняет путь к файлу спецификации в БД, чтобы потом
        безошибочно находить его для превью (в корне заказа могут
        появиться и другие PDF — отрефайненные файлы заказчика)."""
        if not self.order or not self.order.id:
            return
        self.order.spec_path = path
        session = get_session()
        try:
            o = session.get(Order, self.order.id)
            if o:
                o.spec_path = path
                session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    def _process_spec(self, path: str):
        # Сначала переносим файл в папку заказа на P: (если она уже
        # есть), и только потом распознаём.
        staged_path = self._stage_spec_file(path)

        self.drop_lbl.configure(
            text=f"📄  {os.path.basename(staged_path)}\nРаспознаю...",
            text_color=WARNING
        )
        self._ocr_progress.pack(fill="x", padx=0, pady=(4, 0))
        self._ocr_progress.start()
        self._ocr_status.configure(text="OCR в процессе...")

        # Превью в центральной панели (в фоне — pdf2image может быть медленным)
        threading.Thread(
            target=self._update_preview_display, args=(staged_path,), daemon=True
        ).start()
        # Для PDF, если папка заказа уже существует — сразу сохраняем
        # JPG превью на диск P: рядом со спецификацией.
        if self.order and self.order.folder_path:
            threading.Thread(
                target=self._save_preview_jpg,
                args=(staged_path, self.order.folder_path), daemon=True
            ).start()

        def worker():
            from services.spec_reader import read_spec
            try:
                data = read_spec(staged_path)
                self.after(0, lambda d=data, p=staged_path: self._apply_spec_data(d, p))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda m=msg: self._ocr_error(m))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_spec_data(self, data: dict, path: str):
        self._ocr_progress.stop()
        self._ocr_progress.pack_forget()

        if data.get("number"):      self.v_number.set(str(data["number"]))
        if data.get("name"):        self.v_name.set(data["name"])
        if data.get("description"): self.v_description.set(data["description"])
        if data.get("binding"):     self.v_binding.set(data["binding"])
        if data.get("width") and data.get("height"):
            self.v_format.set(f"{data['width']}x{data['height']}")
        # ключ в spec_reader называется "circulation", а не "circ"
        circ = data.get("circulation") or data.get("circ")
        if circ:                    self.v_circ.set(str(circ))
        if data.get("pages_block"):  self.v_pages_block.set(str(data["pages_block"]))
        if data.get("pages_cover"):  self.v_pages_cover.set(str(data["pages_cover"]))
        if data.get("pages_insert"): self.v_pages_insert.set(str(data["pages_insert"]))
        if data.get("color_block"):  self.v_color_block.set(data["color_block"])
        if data.get("color_cover"):  self.v_color_cover.set(data["color_cover"])
        if data.get("color_insert"): self.v_color_insert.set(data["color_insert"])
        if data.get("postprocessing"):
            self.txt_postprocessing.delete("1.0", "end")
            self.txt_postprocessing.insert("1.0", data["postprocessing"])
        if data.get("tech_notes"):
            self.txt_tech_notes.delete("1.0", "end")
            self.txt_tech_notes.insert("1.0", data["tech_notes"])
        if data.get("due_date"): self.v_due.set(data["due_date"])
        if data.get("delivery_date"): self.v_delivery.set(data["delivery_date"])
        if data.get("submit_date"): self.v_submit.set(data["submit_date"])

        self.drop_lbl.configure(
            text=f"✓  {os.path.basename(path)}\nРаспознано. Проверьте данные.",
            text_color=ACCENT
        )
        self._ocr_status.configure(text=f"Источник: {path}")

    def _ocr_error(self, msg: str):
        self._ocr_progress.stop()
        self._ocr_progress.pack_forget()
        self.drop_lbl.configure(
            text=f"✗  Ошибка OCR: {msg}", text_color=DANGER
        )

    # ── CREATE / SAVE ─────────────────────────────────────────────
    def _create_or_save(self):
        try:
            number = int(self.v_number.get())
        except ValueError:
            messagebox.showerror("Ошибка", "Номер заказа должен быть числом")
            return

        name = self.v_name.get().strip()
        if not name:
            messagebox.showerror("Ошибка", "Укажите название заказа")
            return

        def parse_date(s):
            s = s.strip()
            if not s:
                return None
            for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(s, fmt)
                except ValueError:
                    pass
            return None

        session = get_session()
        try:
            if self.order_id:
                o = session.get(Order, self.order_id)
            else:
                o = Order()
                session.add(o)

            o.number        = number
            o.name          = name
            o.description   = self.v_description.get().strip() or None
            o.binding       = self.v_binding.get().strip()
            o.created       = o.created or datetime.now()
            o.delivery_date = parse_date(self.v_delivery.get())
            o.submiting_files = parse_date(self.v_submit.get())
            o.due_date      = parse_date(self.v_due.get())

            # "Формат" вводится одним полем "ШxВ", напр. "150x225"
            import re as _re
            fmt_m = _re.match(
                r"\s*(\d+)\s*[xхХx]\s*(\d+)",
                self.v_format.get()
            )
            o.width  = int(fmt_m.group(1)) if fmt_m else None
            o.height = int(fmt_m.group(2)) if fmt_m else None

            def _int_or_none(v):
                v = v.strip()
                return int(v) if v.isdigit() else None

            try:
                o.circulation = int(self.v_circ.get()) if self.v_circ.get() else None
            except ValueError:
                o.circulation = None

            o.pages_block  = _int_or_none(self.v_pages_block.get())
            o.pages_cover  = _int_or_none(self.v_pages_cover.get())
            o.pages_insert = _int_or_none(self.v_pages_insert.get())
            o.color_block  = self.v_color_block.get().strip() or None
            o.color_cover  = self.v_color_cover.get().strip() or None
            o.color_insert = self.v_color_insert.get().strip() or None
            o.postprocessing = self.txt_postprocessing.get("1.0", "end").strip() or None
            o.tech_notes     = self.txt_tech_notes.get("1.0", "end").strip() or None

            session.commit()
            self.order_id = o.id
            self.order = o

            # Создаём папку и XML
            self._create_order_folder(o)
            self._show_order_buttons()
            self.btn_create.configure(text="💾  Сохранить изменения")

            messagebox.showinfo(
                "Готово",
                f"Заказ {number:04d} сохранён.\nПапка: {o.folder_path or '—'}"
            )
        except Exception as e:
            session.rollback()
            messagebox.showerror("Ошибка БД", str(e))
        finally:
            session.close()

    # ── FOLDER ────────────────────────────────────────────────────
    def _create_order_folder(self, o: Order):
        import re, xml.etree.ElementTree as ET

        # Транслитерация для имени папки
        def translit(s):
            trans_dict = {
                'а': 'a',  'б': 'b',  'в': 'v',  'г': 'g',  'д': 'd',
                'е': 'e',  'ё': 'e',  'ж': 'zh', 'з': 'z',  'и': 'i',
                'й': 'i',  'к': 'k',  'л': 'l',  'м': 'm',  'н': 'n',
                'о': 'o',  'п': 'p',  'р': 'r',  'с': 's',  'т': 't',
                'у': 'u',  'ф': 'f',  'х': 'kh', 'ц': 'ts', 'ч': 'ch',
                'ш': 'sh', 'щ': 'shch','ъ': '',   'ы': 'y',  'ь': '',
                'э': 'e',  'ю': 'yu', 'я': 'ya',
                'А': 'A',  'Б': 'B',  'В': 'V',  'Г': 'G',  'Д': 'D',
                'Е': 'E',  'Ё': 'E',  'Ж': 'Zh', 'З': 'Z',  'И': 'I',
                'Й': 'I',  'К': 'K',  'Л': 'L',  'М': 'M',  'Н': 'N',
                'О': 'O',  'П': 'P',  'Р': 'R',  'С': 'S',  'Т': 'T',
                'У': 'U',  'Ф': 'F',  'Х': 'Kh', 'Ц': 'Ts', 'Ч': 'Ch',
                'Ш': 'Sh', 'Щ': 'Shch','Ъ': '',  'Ы': 'Y',  'Ь': '',
                'Э': 'E',  'Ю': 'Yu', 'Я': 'Ya',
            }
            table = str.maketrans(trans_dict)
            s = s.translate(table)
            s = re.sub(r"[^A-Za-z0-9_]", "_", s)
            s = re.sub(r"_+", "_", s)
            return s[:30].strip("_")

        short = translit(o.name)
        folder_name = f"{o.number:04d}_{short}"
        root = config.CFG["orders_root"]
        folder_path = os.path.join(root, folder_name)
        in_path = os.path.join(folder_path, "in")

        try:
            os.makedirs(in_path, exist_ok=True)
        except Exception:
            pass  # Сетевой диск может быть недоступен

        # Если спецификация была распознана ДО создания заказа (папки
        # ещё не было) — переносим её в КОРЕНЬ папки заказа сейчас, и
        # заодно сохраняем JPG превью (для PDF) на диск P:.
        if self._pending_spec_path and os.path.isfile(self._pending_spec_path):
            try:
                dst = os.path.join(folder_path, os.path.basename(self._pending_spec_path))
                if os.path.abspath(dst) != os.path.abspath(self._pending_spec_path):
                    shutil.copy2(self._pending_spec_path, dst)
                self._pending_spec_path = None
                o.spec_path = dst
                self._save_preview_jpg(dst, folder_path)
                self._clear_pending_preview_temp()
            except Exception:
                pass  # Диск P: недоступен — попробуем при следующем сохранении

        # XML
        xml_path = os.path.join(in_path, f"{folder_name}.xml")
        try:
            root_el = ET.Element("order")
            for tag, val in [
                ("number", str(o.number)),
                ("name",   o.name),
                ("description", o.description or ""),
                ("binding", o.binding),
                ("width",  str(o.width or "")),
                ("height", str(o.height or "")),
                ("circulation", str(o.circulation or "")),
                ("pages_block",  str(o.pages_block or "")),
                ("pages_cover",  str(o.pages_cover or "")),
                ("pages_insert", str(o.pages_insert or "")),
                ("color_block",  o.color_block or ""),
                ("color_cover",  o.color_cover or ""),
                ("color_insert", o.color_insert or ""),
                ("postprocessing", o.postprocessing or ""),
                ("tech_notes",     o.tech_notes or ""),
            ]:
                el = ET.SubElement(root_el, tag)
                el.text = val
            ET.ElementTree(root_el).write(xml_path, encoding="utf-8", xml_declaration=True)
        except Exception:
            pass

        # Сохраняем путь в БД
        session = get_session()
        try:
            order = session.get(Order, o.id)
            order.folder_path = folder_path
            if o.spec_path:
                order.spec_path = o.spec_path
            session.commit()
        finally:
            session.close()

        o.folder_path = folder_path

    # ── MONITORING ────────────────────────────────────────────────
    def _show_order_buttons(self):
        if not self.order:
            return
        monitoring = self.order.monitoring
        if monitoring:
            self.btn_monitor.configure(
                text="⬤  Мониторинг ВКЛ  (нажать — выключить)",
                fg_color=DANGER, hover_color="#cc3333", text_color="white"
            )
        else:
            self.btn_monitor.configure(
                text="○  Мониторинг ВЫКЛ  (нажать — включить)",
                fg_color=("gray85","gray20"), hover_color=DARK_BD2,
                 border_width=1,
                text_color=TEXT2
            )
        self.btn_monitor.pack(fill="x", pady=(0, 8))
        self.btn_imposition.pack(fill="x")

    def _toggle_monitor(self):
        if not self.order:
            return
        session = get_session()
        try:
            o = session.get(Order, self.order.id)
            o.monitoring = not o.monitoring
            session.commit()
            self.order.monitoring = o.monitoring

            if o.monitoring:
                self._start_monitoring(o)
            else:
                self._stop_monitoring()
            self._show_order_buttons()
        finally:
            session.close()

    def _start_monitoring(self, order):
        from services.monitor_manager import MonitorManager

        folder_path = order.folder_path or ""
        in_path     = os.path.join(folder_path, "in")

        if not folder_path:
            from tkinter import messagebox
            messagebox.showerror("Мониторинг",
                "folder_path пустой — сохраните заказ заново")
            return
        if not os.path.isdir(in_path):
            from tkinter import messagebox
            messagebox.showerror("Мониторинг",
                f"Папка не найдена:\n{in_path}\n\nПроверьте что диск P: доступен")
            return

        MonitorManager().start_order(
            order_id=order.id,
            folder_path=folder_path,
            callback=self._on_new_file,
        )


    def _stop_monitoring(self):
        from services.monitor_manager import MonitorManager
        if self.order:
            MonitorManager().stop_order(self.order.id)

    def _on_new_file(self, path: str):
        # Проверяем что виджет ещё существует перед обновлением
        try:
            if self.winfo_exists():
                self.after(0, self._refresh_pitstop)
        except Exception:
            pass

    # ── PITSTOP ───────────────────────────────────────────────────
    def _refresh_pitstop(self):
        if not self.order or not self.order.folder_path:
            return
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        import config as cfg
        from services.pitstop_parser import list_pitstop_reports, check_mismatch
        folder_name = os.path.basename(self.order.folder_path)
        log_dir = os.path.join(cfg.CFG["pitstop_log"], folder_name)
        reports = list_pitstop_reports(log_dir)
        self._render_pitstop_reports(reports)
        self._update_mismatch_bar(reports[0] if reports else None)

    def _update_mismatch_bar(self, latest_report):
        """Показывает (если есть) несовпадение формата/полос между
        заказом и последним отчётом PitStop, внизу центральной панели."""
        from services.pitstop_parser import check_mismatch
        if not latest_report or not self.order:
            self._mismatch_bar.grid_remove()
            return
        problems = check_mismatch(latest_report, self.order)
        if not problems:
            self._mismatch_bar.grid_remove()
            return
        self._mismatch_lbl.configure(text="\n".join(problems))
        self._mismatch_bar.configure(height=24 * len(problems) + 16)
        self._mismatch_bar.grid()

    # ── IMPOSITION ────────────────────────────────────────────────
    def _open_imposition(self):
        if self.order_id:
            self.app.show_imposition(self.order_id)