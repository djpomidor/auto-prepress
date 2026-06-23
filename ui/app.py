"""
Главное окно приложения.
Цвета не задаются жёстко — CustomTkinter управляет темой сам.
"""
import sys
import os
import subprocess
import customtkinter as ctk
from ui.orders_page import OrdersPage
from ui.order_page import OrderPage
from ui.imposition_page import ImpositionPage
import config


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.cfg = config.CFG

        self.title("ImpoReader")
        w, h = self.cfg["window_width"], self.cfg["window_height"]
        self.geometry(f"{w}x{h}")
        self.minsize(1100, 700)

        self._current_page = None

        self._build_header()
        self._build_breadcrumb()

        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.pack(fill="both", expand=True)
        self.content_frame.grid_rowconfigure(0, weight=1)
        self.content_frame.grid_columnconfigure(0, weight=1)

        from db.database import init_db
        init_db()
        self.show_orders()

    def _build_header(self):
        header = ctk.CTkFrame(self, corner_radius=0, height=48)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="Impo",
            font=("JetBrains Mono", 18, "bold"),
            text_color=("#2d7a00", "#c8f135"),
        ).pack(side="left", padx=(20, 0))
        ctk.CTkLabel(
            header, text="Reader",
            font=("JetBrains Mono", 18),
        ).pack(side="left")
        ctk.CTkLabel(
            header, text="v1.0",
            font=("JetBrains Mono", 10),
        ).pack(side="left", padx=(6, 0))

        right = ctk.CTkFrame(header, fg_color="transparent")
        right.pack(side="right", padx=16)

        # Переключатель темы — без жёстких цветов
        self._theme_var = ctk.StringVar(value=self.cfg.get("theme", "dark"))
        ctk.CTkSegmentedButton(
            right,
            values=["dark", "light"],
            variable=self._theme_var,
            command=self._toggle_theme,
            font=("JetBrains Mono", 10),
            width=120, height=28,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            right, text="+ Новый заказ",
            font=("JetBrains Mono", 11, "bold"),
            height=30, width=130,
            command=self.show_new_order,
        ).pack(side="right")

    def _build_breadcrumb(self):
        self.bc_frame = ctk.CTkFrame(self, corner_radius=0, height=30)
        self.bc_frame.pack(fill="x", side="top")
        self.bc_frame.pack_propagate(False)

    def _update_breadcrumb(self, crumbs: list):
        for w in self.bc_frame.winfo_children():
            w.destroy()

        ctk.CTkLabel(
            self.bc_frame, text="  ⌂",
            font=("JetBrains Mono", 12),
        ).pack(side="left", padx=(8, 0))

        for i, (label, fn) in enumerate(crumbs):
            if i > 0:
                ctk.CTkLabel(
                    self.bc_frame, text=" › ",
                    font=("JetBrains Mono", 11),
                ).pack(side="left")
            lbl = ctk.CTkLabel(
                self.bc_frame, text=label,
                font=("JetBrains Mono", 11),
                cursor="hand2" if fn else "arrow",
            )
            lbl.pack(side="left")
            if fn:
                lbl.bind("<Button-1>", lambda e, f=fn: f())

    def _show_page(self, page_class, breadcrumbs, **kwargs):
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        page = page_class(self.content_frame, app=self, **kwargs)
        page.grid(row=0, column=0, sticky="nsew")
        self._current_page = page
        self._update_breadcrumb(breadcrumbs)

    def show_orders(self):
        self._show_page(OrdersPage, [("Заказы", None)])

    def show_order(self, order_id=None, order_number=None):
        if order_number:
            label = f"Заказ №{order_number:04d}"
        elif order_id:
            label = f"Заказ #{order_id}"
        else:
            label = "Новый заказ"
        self._show_page(
            OrderPage,
            [("Заказы", self.show_orders), (label, None)],
            order_id=order_id,
        )

    def show_new_order(self):
        self.show_order(order_id=None)

    def show_imposition(self, order_id: int, order_number: int = None):
        if order_number:
            order_label = f"Заказ №{order_number:04d}"
        else:
            order_label = f"Заказ #{order_id}"
        self._show_page(
            ImpositionPage,
            [
                ("Заказы", self.show_orders),
                (order_label, lambda: self.show_order(order_id, order_number)),
                ("Спуск полос", None),
            ],
            order_id=order_id,
        )

    def _toggle_theme(self, value: str):
        self.cfg["theme"] = value
        config.save(self.cfg)
        self.destroy()
        subprocess.Popen([sys.executable] + sys.argv)
