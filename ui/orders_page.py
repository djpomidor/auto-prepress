"""
Главная страница — список заказов.
Колонки: №, Название, Дата создания, Дата обновления, Статус мониторинга.
"""
import customtkinter as ctk
from tkinter import ttk
import tkinter as tk
from datetime import datetime
from db.database import get_session
from db.models import Order

# Цвета
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


class OrdersPage(ctk.CTkFrame):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.app = app
        self._sort_col = "number"
        self._sort_asc = True
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._reload())

        self._build()
        self._reload()

    # ── LAYOUT ────────────────────────────────────────────────────
    def _build(self):
        # Верхняя панель: поиск + статистика
        top = ctk.CTkFrame(self, fg_color=DARK_SF, corner_radius=0, height=52)
        top.pack(fill="x", side="top")
        top.pack_propagate(False)

        ctk.CTkLabel(
            top, text="ЗАКАЗЫ",
            font=("JetBrains Mono", 10), text_color=TEXT3
        ).pack(side="left", padx=(20, 16), pady=14)

        # Поиск
        search_frame = ctk.CTkFrame(top, fg_color=DARK_SF2,
                                    corner_radius=4, height=32)
        search_frame.pack(side="left", pady=10)
        search_frame.pack_propagate(False)

        ctk.CTkLabel(
            search_frame, text="⌕", font=("Arial", 14), text_color=TEXT3
        ).pack(side="left", padx=(10, 4))

        ctk.CTkEntry(
            search_frame, textvariable=self._search_var,
            placeholder_text="Поиск по номеру или названию...",
            font=("JetBrains Mono", 12),
            fg_color="transparent", border_width=0,
            text_color=TEXT, placeholder_text_color=TEXT3,
            width=280, height=32,
        ).pack(side="left")

        # Счётчик
        self._count_lbl = ctk.CTkLabel(
            top, text="", font=("JetBrains Mono", 11), text_color=TEXT3
        )
        self._count_lbl.pack(side="right", padx=20)

        # Кнопка обновить
        ctk.CTkButton(
            top, text="↺", width=32, height=32,
            font=("Arial", 16),
            fg_color=DARK_SF2, hover_color=DARK_BD2,
            text_color=TEXT2, corner_radius=4,
            command=self._reload
        ).pack(side="right", padx=(0, 8), pady=10)

        # ── Таблица ───────────────────────────────────────────────
        table_frame = ctk.CTkFrame(self, fg_color=DARK_SF, corner_radius=0)
        table_frame.pack(fill="both", expand=True, padx=0, pady=0)

        # Стиль ttk.Treeview под тёмную тему
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Orders.Treeview",
            background=DARK_SF,
            foreground=TEXT,
            rowheight=40,
            fieldbackground=DARK_SF,
            bordercolor=DARK_BD,
            font=("JetBrains Mono", 12),
        )
        style.configure(
            "Orders.Treeview.Heading",
            background=DARK_SF2,
            foreground=TEXT2,
            relief="flat",
            font=("JetBrains Mono", 10),
        )
        style.map(
            "Orders.Treeview",
            background=[("selected", DARK_BD2)],
            foreground=[("selected", ACCENT)],
        )
        style.map(
            "Orders.Treeview.Heading",
            background=[("active", DARK_BD)],
        )

        # Полоса прокрутки
        vsb = ttk.Scrollbar(table_frame, orient="vertical")
        vsb.pack(side="right", fill="y")

        cols = ("number", "name", "binding", "status", "created", "updated")
        self.tree = ttk.Treeview(
            table_frame,
            columns=cols,
            show="headings",
            style="Orders.Treeview",
            yscrollcommand=vsb.set,
            selectmode="browse",
        )
        vsb.configure(command=self.tree.yview)

        # Заголовки
        headers = {
            "number":  ("№",           60,  "center"),
            "name":    ("Название",    340, "w"),
            "binding": ("Скрепление",  110, "center"),
            "status":  ("Мониторинг",  120, "center"),
            "created": ("Создан",      160, "center"),
            "updated": ("Обновлён",    160, "center"),
        }
        for col, (label, width, anchor) in headers.items():
            self.tree.heading(
                col, text=label,
                command=lambda c=col: self._sort_by(c)
            )
            self.tree.column(col, width=width, anchor=anchor, stretch=(col == "name"))

        # Теги для строк
        self.tree.tag_configure("monitoring", foreground=DANGER)
        self.tree.tag_configure("even", background="#1e1e1e")
        self.tree.tag_configure("odd",  background=DARK_SF)

        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_row_double_click)
        self.tree.bind("<Return>",   self._on_row_double_click)

        # Строка статуса внизу
        self._status_bar = ctk.CTkLabel(
            self, text="",
            font=("JetBrains Mono", 10), text_color=TEXT3,
            fg_color=DARK_SF2, anchor="w",
            corner_radius=0, height=24
        )
        self._status_bar.pack(fill="x", side="bottom")

    # ── DATA ──────────────────────────────────────────────────────
    def _reload(self, *_):
        query = self._search_var.get().strip().lower()
        session = get_session()
        try:
            orders: list[Order] = session.query(Order).all()
        finally:
            session.close()

        # Фильтрация
        if query:
            orders = [
                o for o in orders
                if query in str(o.number)
                or query in (o.name or "").lower()
            ]

        # Сортировка
        rev = not self._sort_asc
        if self._sort_col == "number":
            orders.sort(key=lambda o: o.number, reverse=rev)
        elif self._sort_col == "name":
            orders.sort(key=lambda o: (o.name or "").lower(), reverse=rev)
        elif self._sort_col == "created":
            orders.sort(key=lambda o: o.created or datetime.min, reverse=rev)
        elif self._sort_col == "status":
            orders.sort(key=lambda o: o.monitoring, reverse=rev)

        # Заполнение таблицы
        self.tree.delete(*self.tree.get_children())
        for i, o in enumerate(orders):
            tag = ("monitoring",) if o.monitoring else (("even" if i % 2 == 0 else "odd"),)
            status_txt = "● ВКЛ" if o.monitoring else "—"
            created_str = o.created.strftime("%d.%m.%Y %H:%M") if o.created else "—"
            updated_str = "—"  # TODO: поле updated_at добавить позже

            self.tree.insert(
                "", "end",
                iid=str(o.id),
                values=(
                    f"{o.number:04d}",
                    o.name or "",
                    o.binding or "—",
                    status_txt,
                    created_str,
                    updated_str,
                ),
                tags=tag,
            )

        n = len(orders)
        self._count_lbl.configure(text=f"{n} заказ{'ов' if n != 1 else ''}")
        self._status_bar.configure(
            text=f"  Загружено: {n}  |  БД: {self.app.cfg['db_path']}"
        )

    def _sort_by(self, col: str):
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        self._reload()

    def _on_row_double_click(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        order_id = int(sel[0])
        self.app.show_order(order_id=order_id)
