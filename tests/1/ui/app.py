"""
Главное окно приложения. Управляет навигацией между страницами.
"""
import customtkinter as ctk
from ui.orders_page import OrdersPage
from ui.order_page import OrderPage
from ui.imposition_page import ImpositionPage
import config


DARK_BG   = "#0f0f0f"
DARK_SF   = "#1a1a1a"
DARK_SF2  = "#242424"
DARK_BD   = "#2e2e2e"
ACCENT    = "#c8f135"
ACCENT2   = "#9bc429"
TEXT      = "#e8e8e8"
TEXT2     = "#888888"
TEXT3     = "#555555"
DANGER    = "#ff5555"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.cfg = config.CFG
        self._current_page = None
        self._history: list = []   # стек навигации

        # ── Окно ──────────────────────────────────────────────────
        self.title("ImpoReader")
        w, h = self.cfg["window_width"], self.cfg["window_height"]
        self.geometry(f"{w}x{h}")
        self.minsize(1100, 700)
        self.configure(fg_color=DARK_BG)

        # Применяем тему из конфига
        mode = self.cfg.get("theme", "dark")
        ctk.set_appearance_mode(mode)

        # ── Шапка ─────────────────────────────────────────────────
        self._build_header()

        # ── Хлебные крошки ────────────────────────────────────────
        self._build_breadcrumb()

        # ── Контентная область ────────────────────────────────────
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.pack(fill="both", expand=True, padx=0, pady=0)
        self.content_frame.grid_rowconfigure(0, weight=1)
        self.content_frame.grid_columnconfigure(0, weight=1)

        # ── Инициализация БД и первый экран ───────────────────────
        from db.database import init_db
        init_db()
        self.show_orders()

    # ── HEADER ────────────────────────────────────────────────────
    def _build_header(self):
        self.header = ctk.CTkFrame(self, fg_color=DARK_SF, height=48,
                                   corner_radius=0)
        self.header.pack(fill="x", side="top")
        self.header.pack_propagate(False)

        # Логотип
        logo_lbl = ctk.CTkLabel(
            self.header, text="Impo", font=("JetBrains Mono", 18, "bold"),
            text_color=ACCENT
        )
        logo_lbl.pack(side="left", padx=(20, 0))
        ctk.CTkLabel(
            self.header, text="Reader", font=("JetBrains Mono", 18),
            text_color=TEXT2
        ).pack(side="left")

        ctk.CTkLabel(
            self.header, text="v1.0",
            font=("JetBrains Mono", 10), text_color=TEXT3
        ).pack(side="left", padx=(8, 0))

        # Правая часть шапки
        right = ctk.CTkFrame(self.header, fg_color="transparent")
        right.pack(side="right", padx=16)

        # Переключатель темы
        self._theme_var = ctk.StringVar(
            value=self.cfg.get("theme", "dark")
        )
        theme_btn = ctk.CTkSegmentedButton(
            right,
            values=["dark", "light"],
            variable=self._theme_var,
            command=self._toggle_theme,
            font=("JetBrains Mono", 10),
            width=120, height=28,
        )
        theme_btn.pack(side="right", padx=(8, 0))

        # Кнопка "Новый заказ"
        ctk.CTkButton(
            right, text="+ Новый заказ",
            font=("JetBrains Mono", 11, "bold"),
            fg_color=ACCENT, text_color=DARK_BG,
            hover_color=ACCENT2, height=30, width=130,
            command=self.show_new_order
        ).pack(side="right")

    # ── BREADCRUMB ────────────────────────────────────────────────
    def _build_breadcrumb(self):
        self.bc_frame = ctk.CTkFrame(self, fg_color=DARK_SF2, height=32,
                                     corner_radius=0)
        self.bc_frame.pack(fill="x", side="top")
        self.bc_frame.pack_propagate(False)
        self._bc_labels: list[ctk.CTkLabel] = []

    def _update_breadcrumb(self, crumbs: list):
        """crumbs = [('Заказы', fn), ('0641 Batman', fn), ('Спуск', None)]"""
        for w in self.bc_frame.winfo_children():
            w.destroy()

        ctk.CTkLabel(
            self.bc_frame, text="  ⌂",
            font=("JetBrains Mono", 12), text_color=TEXT3
        ).pack(side="left", padx=(8, 0))

        for i, (label, fn) in enumerate(crumbs):
            if i > 0:
                ctk.CTkLabel(
                    self.bc_frame, text=" › ",
                    font=("JetBrains Mono", 11), text_color=TEXT3
                ).pack(side="left")
            is_last = (i == len(crumbs) - 1)
            color = TEXT if is_last else ACCENT
            lbl = ctk.CTkLabel(
                self.bc_frame, text=label,
                font=("JetBrains Mono", 11),
                text_color=color,
                cursor="hand2" if fn else "arrow"
            )
            lbl.pack(side="left")
            if fn:
                lbl.bind("<Button-1>", lambda e, f=fn: f())

    # ── NAVIGATION ────────────────────────────────────────────────
    def _show_page(self, page_class, breadcrumbs, **kwargs):
        """Универсальный метод смены страницы."""
        # Удаляем текущую страницу
        for widget in self.content_frame.winfo_children():
            widget.destroy()

        page = page_class(self.content_frame, app=self, **kwargs)
        page.grid(row=0, column=0, sticky="nsew")
        self._current_page = page
        self._update_breadcrumb(breadcrumbs)

    def show_orders(self):
        self._history = []
        self._show_page(
            OrdersPage,
            [("Заказы", None)]
        )

    def show_order(self, order_id=None, order=None):
        if order_id:
            crumb_label = f"Заказ #{order_id}"
        else:
            crumb_label = "Новый заказ"
        self._show_page(
            OrderPage,
            [("Заказы", self.show_orders), (crumb_label, None)],
            order_id=order_id,
        )

    def show_new_order(self):
        self.show_order(order_id=None)

    def show_imposition(self, order_id: int):
        self._show_page(
            ImpositionPage,
            [
                ("Заказы", self.show_orders),
                (f"Заказ #{order_id}", lambda: self.show_order(order_id)),
                ("Спуск полос", None),
            ],
            order_id=order_id,
        )

    def _toggle_theme(self, value: str):
        ctk.set_appearance_mode(value)
        self.cfg["theme"] = value
        config.save(self.cfg)
        # Принудительно перерисовываем текущую страницу
        # CustomTkinter обновляет цвета только при пересоздании виджетов
        self._reload_current_page()

    def _reload_current_page(self):
        """Перезагружает текущую страницу чтобы применить новую тему."""
        # Находим текущую страницу по хлебным крошкам
        for widget in self.content_frame.winfo_children():
            cls = type(widget)
            name = cls.__name__
            break
        else:
            return

        if name == "OrdersPage":
            self.show_orders()
        elif name == "OrderPage" and self._current_page:
            order_id = getattr(self._current_page, "order_id", None)
            self.show_order(order_id=order_id)
        elif name == "ImpositionPage" and self._current_page:
            order_id = getattr(self._current_page, "order_id", None)
            if order_id:
                self.show_imposition(order_id)
            else:
                self.show_orders()
        else:
            self.show_orders()
