"""
Главная страница — список заказов.
"""
import customtkinter as ctk
from tkinter import ttk
import tkinter as tk
from datetime import datetime
from db.database import get_session
from db.models import Order


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

    def _build(self):
        # Верхняя панель
        top = ctk.CTkFrame(self, corner_radius=0, height=52)
        top.pack(fill="x", side="top")
        top.pack_propagate(False)

        ctk.CTkLabel(
            top, text="ЗАКАЗЫ",
            font=("JetBrains Mono", 10),
        ).pack(side="left", padx=(20, 16), pady=14)

        ctk.CTkEntry(
            top, textvariable=self._search_var,
            placeholder_text="Поиск по номеру или названию...",
            font=("JetBrains Mono", 12),
            width=300, height=32,
        ).pack(side="left", pady=10)

        self._count_lbl = ctk.CTkLabel(
            top, text="",
            font=("JetBrains Mono", 11),
        )
        self._count_lbl.pack(side="right", padx=20)

        ctk.CTkButton(
            top, text="↺", width=32, height=32,
            font=("Arial", 16),
            command=self._reload,
        ).pack(side="right", padx=(0, 8), pady=10)

        # Таблица — адаптируем цвета под текущую тему
        table_frame = ctk.CTkFrame(self, corner_radius=0)
        table_frame.pack(fill="both", expand=True)

        is_dark = ctk.get_appearance_mode().lower() == "dark"
        bg      = "#1a1a1a" if is_dark else "#f0f0f0"
        fg      = "#e8e8e8" if is_dark else "#1a1a1a"
        sel_bg  = "#3a3a3a" if is_dark else "#c8e6c9"
        hdr_bg  = "#242424" if is_dark else "#e0e0e0"

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Orders.Treeview",
            background=bg, foreground=fg,
            rowheight=40, fieldbackground=bg,
            font=("JetBrains Mono", 12),
            borderwidth=0,
        )
        style.configure(
            "Orders.Treeview.Heading",
            background=hdr_bg, foreground=fg,
            relief="flat", font=("JetBrains Mono", 10),
        )
        style.map(
            "Orders.Treeview",
            background=[("selected", sel_bg)],
            foreground=[("selected", "#c8f135" if is_dark else "#1b5e20")],
        )
        style.map("Orders.Treeview.Heading",
                  background=[("active", sel_bg)])

        vsb = ttk.Scrollbar(table_frame, orient="vertical")
        vsb.pack(side="right", fill="y")

        cols = ("number", "name", "binding", "status", "created")
        self.tree = ttk.Treeview(
            table_frame, columns=cols, show="headings",
            style="Orders.Treeview",
            yscrollcommand=vsb.set, selectmode="browse",
        )
        vsb.configure(command=self.tree.yview)

        headers = {
            "number":  ("№",          70,  "center"),
            "name":    ("Название",   380, "w"),
            "binding": ("Скрепление", 120, "center"),
            "status":  ("Мониторинг", 120, "center"),
            "created": ("Создан",     160, "center"),
        }
        for col, (label, width, anchor) in headers.items():
            self.tree.heading(col, text=label,
                              command=lambda c=col: self._sort_by(c))
            self.tree.column(col, width=width, anchor=anchor,
                             stretch=(col == "name"))

        danger = "#ff5555" if is_dark else "#c62828"
        even   = "#1e1e1e" if is_dark else "#fafafa"
        odd    = "#1a1a1a" if is_dark else "#f0f0f0"
        self.tree.tag_configure("monitoring", foreground=danger)
        self.tree.tag_configure("even", background=even)
        self.tree.tag_configure("odd",  background=odd)

        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Return>",   self._on_double_click)

        # Статус-бар
        self._status_bar = ctk.CTkLabel(
            self, text="", font=("JetBrains Mono", 10),
            anchor="w", corner_radius=0, height=22,
        )
        self._status_bar.pack(fill="x", side="bottom")

    def _reload(self, *_):
        query = self._search_var.get().strip().lower()
        session = get_session()
        try:
            orders = session.query(Order).all()
        finally:
            session.close()

        if query:
            orders = [o for o in orders
                      if query in str(o.number)
                      or query in (o.name or "").lower()]

        rev = not self._sort_asc
        if self._sort_col == "number":
            orders.sort(key=lambda o: o.number, reverse=rev)
        elif self._sort_col == "name":
            orders.sort(key=lambda o: (o.name or "").lower(), reverse=rev)
        elif self._sort_col == "created":
            orders.sort(key=lambda o: o.created or datetime.min, reverse=rev)
        elif self._sort_col == "status":
            orders.sort(key=lambda o: o.monitoring, reverse=rev)

        self.tree.delete(*self.tree.get_children())
        for i, o in enumerate(orders):
            if o.monitoring:
                tag = ("monitoring",)
            else:
                tag = ("even",) if i % 2 == 0 else ("odd",)

            created = o.created.strftime("%d.%m.%Y %H:%M") if o.created else "—"
            self.tree.insert(
                "", "end", iid=str(o.id),
                values=(
                    f"{o.number:04d}",
                    o.name or "",
                    o.binding or "—",
                    "● ВКЛ" if o.monitoring else "—",
                    created,
                ),
                tags=tag,
            )

        n = len(orders)
        self._count_lbl.configure(text=f"{n} заказов")
        self._status_bar.configure(text=f"  Загружено: {n}")

    def _sort_by(self, col: str):
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        self._reload()

    def _on_double_click(self, event=None):
        sel = self.tree.selection()
        print("%$#@!", Order)
        if sel:
            self.app.show_order(order_id=int(sel[0]), order_number=int(Order.number))
