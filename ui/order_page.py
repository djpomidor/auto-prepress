"""
Страница заказа: создание / просмотр / редактирование.
"""
import os
import shutil
import threading
import tkinter as tk
import customtkinter as ctk
from tkinter import filedialog, messagebox
from datetime import datetime
from db.database import get_session
from db.models import Order
import config

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


def _label(parent, text, **kw):
    return ctk.CTkLabel(
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

        # Переменные формы
        self.v_number   = tk.StringVar()
        self.v_name     = tk.StringVar()
        self.v_type     = tk.StringVar()
        self.v_circ     = tk.StringVar()
        self.v_binding  = tk.StringVar()
        self.v_width    = tk.StringVar()
        self.v_height   = tk.StringVar()
        self.v_delivery = tk.StringVar()
        self.v_submit   = tk.StringVar()
        self.v_due      = tk.StringVar()

        self._build()

        if order_id:
            self._load_order(order_id)

    # ── BUILD ─────────────────────────────────────────────────────
    def _build(self):
        # Два столбца: левый (форма) + правый (статус / файлы)
        self.grid_columnconfigure(0, weight=2, minsize=520)
        self.grid_columnconfigure(1, weight=3)
        self.grid_rowconfigure(0, weight=1)

        # ── Левая колонка ─────────────────────────────────────────
        left = ctk.CTkScrollableFrame(
            self, fg_color=("gray90","gray17"), corner_radius=0,
            scrollbar_button_color=DARK_BD,
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 1))

        # Drag-and-drop зона спецификации
        self._build_drop_zone(left)

        ctk.CTkFrame(left, fg_color=("gray80","gray25"), height=1).pack(fill="x", pady=12)

        # Форма заказа
        self._build_form(left)

        # Кнопки
        self._build_action_buttons(left)

        # ── Правая колонка ────────────────────────────────────────
        right = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # Панель статуса PitStop
        self._build_pitstop_panel(right)

        # Панель файлов в папке заказа
        self._build_files_panel(right)

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
        sec.grid_columnconfigure(1, weight=1)

        fields = [
            ("Номер заказа",   self.v_number,   "Например: 0641"),
            ("Название",       self.v_name,     "До 32 символов"),
            ("Тип",            self.v_type,     "Напр. KBS, SKR"),
            ("Тираж",          self.v_circ,     ""),
            ("Скрепление",     self.v_binding,  "КБС / СКР / ШВП"),
            ("Ширина (мм)",    self.v_width,    ""),
            ("Высота (мм)",    self.v_height,   ""),
            ("Дата выхода",    self.v_delivery, "ДД.ММ.ГГГГ"),
            ("Сдача файлов",   self.v_submit,   "ДД.ММ.ГГГГ"),
            ("Дата в печать",  self.v_due,      "ДД.ММ.ГГГГ"),
        ]

        for row, (label, var, hint) in enumerate(fields):
            _label(sec, label).grid(row=row, column=0, sticky="w",
                                    pady=5, padx=(0, 16))
            e = ctk.CTkEntry(
                sec, textvariable=var,
                placeholder_text=hint,
                font=("JetBrains Mono", 13),
                fg_color=("gray85","gray20"),  border_width=1,
                
            )
            e.grid(row=row, column=1, sticky="ew", pady=5)

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

        self.pitstop_text = ctk.CTkTextbox(
            frame, fg_color="transparent", 
            font=("JetBrains Mono", 11),
            corner_radius=0, border_width=0,
            state="disabled",
        )
        self.pitstop_text.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)

        self._set_pitstop_text("Ожидание файлов...\n\nПосле появления PDF в папке in\nрезультаты проверки отобразятся здесь.")

    def _build_files_panel(self, parent):
        pass  # TODO в следующей итерации

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
        self.v_type.set(o.type or "")
        self.v_circ.set(str(o.circulation) if o.circulation else "")
        self.v_binding.set(o.binding or "")
        self.v_width.set(str(o.width) if o.width else "")
        self.v_height.set(str(o.height) if o.height else "")

        def _fmt(dt): return dt.strftime("%d.%m.%Y") if dt else ""
        self.v_delivery.set(_fmt(o.delivery_date))
        self.v_submit.set(_fmt(o.submiting_files))
        self.v_due.set(_fmt(o.due_date))

        self.btn_create.configure(text="💾  Сохранить изменения")
        self._show_order_buttons()

        # Автозапуск мониторинга если был включён
        if o.monitoring and o.folder_path:
            self._start_monitoring(o)

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

    def _process_spec(self, path: str):
        self.drop_lbl.configure(
            text=f"📄  {os.path.basename(path)}\nРаспознаю...",
            text_color=WARNING
        )
        self._ocr_progress.pack(fill="x", padx=0, pady=(4, 0))
        self._ocr_progress.start()
        self._ocr_status.configure(text="OCR в процессе...")

        def worker():
            from services.spec_reader import read_spec
            try:
                data = read_spec(path)
                self.after(0, lambda d=data, p=path: self._apply_spec_data(d, p))
            except Exception as e:
                msg = str(e)
                self.after(0, lambda m=msg: self._ocr_error(m))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_spec_data(self, data: dict, path: str):
        self._ocr_progress.stop()
        self._ocr_progress.pack_forget()

        if data.get("number"):   self.v_number.set(str(data["number"]))
        if data.get("name"):     self.v_name.set(data["name"])
        if data.get("binding"):  self.v_binding.set(data["binding"])
        if data.get("width"):    self.v_width.set(str(data["width"]))
        if data.get("height"):   self.v_height.set(str(data["height"]))
        if data.get("circ"):     self.v_circ.set(str(data["circ"]))
        if data.get("due_date"): self.v_due.set(data["due_date"])

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
            o.type          = self.v_type.get().strip()
            o.binding       = self.v_binding.get().strip()
            o.created       = o.created or datetime.now()
            o.delivery_date = parse_date(self.v_delivery.get())
            o.submiting_files = parse_date(self.v_submit.get())
            o.due_date      = parse_date(self.v_due.get())

            try:
                o.circulation = int(self.v_circ.get()) if self.v_circ.get() else None
                o.width       = int(self.v_width.get()) if self.v_width.get() else None
                o.height      = int(self.v_height.get()) if self.v_height.get() else None
            except ValueError:
                pass

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

        # XML
        xml_path = os.path.join(in_path, f"{folder_name}.xml")
        try:
            root_el = ET.Element("order")
            for tag, val in [
                ("number", str(o.number)),
                ("name",   o.name),
                ("binding", o.binding),
                ("width",  str(o.width or "")),
                ("height", str(o.height or "")),
                ("circulation", str(o.circulation or "")),
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
        from services.pitstop_parser import parse_pitstop_log
        folder_name = os.path.basename(self.order.folder_path)
        log_dir = os.path.join(cfg.CFG["pitstop_log"], folder_name)
        result = parse_pitstop_log(log_dir)
        self._set_pitstop_text(result)

    def _set_pitstop_text(self, text: str):
        try:
            if not self.winfo_exists():
                return
            if not hasattr(self, "pitstop_text"):
                return
            self.pitstop_text.configure(state="normal")
            self.pitstop_text.delete("1.0", "end")
            self.pitstop_text.insert("1.0", text)
            self.pitstop_text.configure(state="disabled")
        except Exception:
            pass

    # ── IMPOSITION ────────────────────────────────────────────────
    def _open_imposition(self):
        if self.order_id:
            self.app.show_imposition(self.order_id)