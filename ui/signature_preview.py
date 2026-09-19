"""
Графическое превью сигнатуры шаблона Preps.

Модуль решает две задачи:

1. Разбирает геометрию одной сигнатуры (блок строк от %SSiSignature:
   до следующей %SSiSignature:) — формат печатного листа и положение
   каждой полосы на нём: parse_signature_geometry().

2. Рисует эту геометрию на tk.Canvas в отдельной панели
   SignaturePreviewPanel — её imposition_page.py вставляет в свой
   PanedWindow СЛЕВА от панели "Шаблоны Preps" по клику на имени
   сигнатуры.

── Что читаем из .tpl ──────────────────────────────────────────────
%SSiPressSheet: <W> <H> ...            — размер печатного листа в pt
%SSiPrshPage: <X> <Y> <W> <H> <rot> <лицо> <оборот> <вылеты×4> ... <секция>
    X, Y   — левый нижний угол полосы (система координат PostScript:
             начало в левом нижнем углу листа, Y растёт ВВЕРХ);
    W, H   — размер полосы как она лежит на листе;
    rot    — код разворота полосы. Поворот содержимого (против
             часовой) = ((rot + 1) mod 4) × 90°, то есть
                 3 → 0°   (голова вверх)
                 4 → 90°  (голова влево)
                 1 → 180° (голова вниз)
                 6 → 270° (голова вправо)
             коды 5..8 — то же самое, но с зеркалом.
             Проверено по зазорам: внутри секции соседние ряды
             (и половинки обложки) встают ГОЛОВА К ГОЛОВЕ через
             зазор «в голове» — при таком чтении так и получается.
             При 90°/270° габарит полосы на листе — H×W (W и H
             меняются местами). Проверено на всех 32 сигнатурах
             примера: при таком чтении ни одна полоса не вылезает
             за лист и полосы внутри секции не перекрываются, а
             поля листа слева/справа получаются симметричными;
    лицо / оборот — номера полос на стороне A и на стороне B
             (0 — полосы нет, например у обложек 4+0);
    секция — номер секции (одна сигнатура может содержать несколько
             секций на одном листе: например 32 стр. = 2 × 16).

Строки с нулевыми W/H — служебные «заготовки», их пропускаем.

ВАЖНО про ориентацию: рисуем строго в системе координат файла
(PostScript, Y вверх, сторона A — вид со стороны лица). Preps и
некоторые печатные машины показывают тот же лист повёрнутым на 180°
(лист «под клапан»), поэтому в панели есть кнопка «⟲ 180°» — она
только разворачивает картинку, данные не меняет.
"""
import tkinter as tk
import customtkinter as ctk

_PT_PER_MM = 72.0 / 25.4

# Палитра — повторяет imposition_page.py (импортировать оттуда нельзя:
# imposition_page импортирует этот модуль, получилось бы кольцо).
ACCENT   = "#c8f135"
ACCENT2  = "#9bc429"
DARK_BD2 = "#3a3a3a"
BTN_TEXT = ("gray10", "gray90")

# Цвета самой схемы листа (светлая/тёмная тема)
_SHEET_FILL   = ("#e3e3e3", "#202020")
_SHEET_LINE   = ("#9a9a9a", "#4a4a4a")
_PAGE_FILL    = ("#ffffff", "#f2f2f2")
_PAGE_LINE    = ("#4a4a4a", "#6e6e6e")
_PAGE_TEXT    = "#1a1a1a"
_HEAD_BAR     = "#111111"
_EMPTY_FILL   = ("#d0d0d0", "#3a3a3a")


def _pick(pair):
    """Выбирает цвет из пары (светлая, тёмная) по текущей теме —
    tk.Canvas, в отличие от виджетов CTk, пары не понимает."""
    if isinstance(pair, (tuple, list)):
        return pair[1] if ctk.get_appearance_mode().lower() == "dark" else pair[0]
    return pair


def _mm(pt: float) -> float:
    return pt / _PT_PER_MM


def _fmt_mm(pt: float) -> str:
    v = round(_mm(pt), 1)
    return f"{v:g}"


def parse_signature_geometry(sig: dict) -> dict:
    """
    sig — элемент списка из _parse_tpl_file() (нужен только ключ
    "raw_lines"). Возвращает словарь:

        {
          "sheet_w": float(pt), "sheet_h": float(pt),
          "pages": [ {x, y, w, h, rot, front, back, section}, ... ],
          "sections": [1, 2, ...],
          "ok": bool,          # хватило ли данных, чтобы рисовать
        }
    """
    sheet_w = sheet_h = 0.0
    pages = []

    for line in sig.get("raw_lines", []):
        line = line.strip()
        if line.startswith("%SSiPressSheet:") and not sheet_w:
            t = line.split(":", 1)[1].split()
            try:
                sheet_w, sheet_h = float(t[0]), float(t[1])
            except (IndexError, ValueError):
                sheet_w = sheet_h = 0.0
        elif line.startswith("%SSiPrshPage:"):
            t = line.split(":", 1)[1].split()
            if len(t) < 8:
                continue
            try:
                x, y, w, h = (float(v) for v in t[:4])
                rot   = int(float(t[4]))
                front = int(float(t[5]))
                back  = int(float(t[6]))
                section = int(float(t[-1]))
            except ValueError:
                continue
            if w <= 0 or h <= 0:
                continue  # служебная «нулевая» строка
            angle = ((rot + 1) % 4) * 90
            swapped = angle in (90, 270)
            pages.append({
                "x": x, "y": y, "w": w, "h": h, "rot": rot,
                "angle": angle,                 # поворот содержимого, °
                "mirror": rot >= 5,             # зеркало (коды 5..8)
                "fw": h if swapped else w,      # габарит на листе
                "fh": w if swapped else h,
                "front": front, "back": back, "section": section,
            })

    sections = sorted({p["section"] for p in pages})
    return {
        "sheet_w": sheet_w, "sheet_h": sheet_h,
        "pages": pages, "sections": sections,
        "ok": bool(pages and sheet_w > 0 and sheet_h > 0),
    }


def _axis_gaps(pages: list, start_key: str, size_key: str) -> list:
    """
    ВСЕ зазоры между соседними полосами вдоль одной оси, каждый со
    своей позицией (без дедупликации по значению — если в раскладке
    несколько зазоров одного размера, каждый возвращается отдельно,
    чтобы на схеме была подсвечена именно ЕГО позиция).

    Возвращает список {"start": pt, "end": pt, "size": pt}, слева
    направо / снизу вверх. Зазоры меньше ~0.2мм (шум округления)
    отбрасываются.
    """
    spans = sorted({(round(p[start_key], 2), round(p[size_key], 2)) for p in pages})
    gaps = []
    for i in range(1, len(spans)):
        prev_start, prev_size = spans[i - 1]
        start = prev_start + prev_size
        end = spans[i][0]
        if end - start > 0.5:
            gaps.append({"start": start, "end": end, "size": end - start})
    return gaps


def _axis_touching_boundary(pages: list, start_key: str, size_key: str):
    """
    Первая пара соседних полос, стоящих ВПЛОТНУЮ (зазор ~0) вдоль
    этой оси — нужна для разворотных обложек, где корешок — это сама
    линия соприкосновения панелей, а не измеримый зазор.
    """
    spans = sorted({(round(p[start_key], 2), round(p[size_key], 2)) for p in pages})
    for i in range(1, len(spans)):
        prev_start, prev_size = spans[i - 1]
        gap = spans[i][0] - (prev_start + prev_size)
        if -0.5 <= gap <= 0.5:
            pos = prev_start + prev_size
            return pos
    return None


def measure_layout(geo: dict) -> dict:
    """
    Величины, которые нужно подсветить на схеме: поля листа (для
    клапана) и ВСЕ зазоры между полосами (для зазоров/корешка).
    Всё в pt.
    """
    pages = geo["pages"]
    if not pages:
        return {}

    left   = min(p["x"] for p in pages)
    right  = geo["sheet_w"] - max(p["x"] + p["fw"] for p in pages)
    bottom = min(p["y"] for p in pages)
    top    = geo["sheet_h"] - max(p["y"] + p["fh"] for p in pages)

    return {
        "left": left, "right": right, "bottom": bottom, "top": top,
        "x_gaps": _axis_gaps(pages, "x", "fw"),
        "y_gaps": _axis_gaps(pages, "y", "fh"),
        "x_touch": _axis_touching_boundary(pages, "x", "fw"),
        "y_touch": _axis_touching_boundary(pages, "y", "fh"),
    }


class SignaturePreviewPanel(ctk.CTkFrame):
    """
    Панель с графической схемой одной сигнатуры.

    Использование:
        panel = SignaturePreviewPanel(parent, on_close=cb)
        panel.show(sig, template_name="0058_....tpl")
    """

    def __init__(self, parent, on_close=None, **kwargs):
        super().__init__(parent, fg_color=("gray90", "gray17"),
                         corner_radius=0, **kwargs)
        self._on_close = on_close
        self._sig = None
        self._geo = None
        self._tpl_name = ""
        self._side = "A"        # "A" — лицо, "B" — оборот
        self._flip180 = False
        self._show_dims = True
        self._redraw_job = None

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ── Заголовок: имя сигнатуры + крестик ───────────────────
        hdr = ctk.CTkFrame(self, fg_color=("gray85", "gray20"), height=36,
                           corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)

        self._title_lbl = ctk.CTkLabel(
            hdr, text="СИГНАТУРА", font=("JetBrains Mono", 12, "bold"),
            text_color=("gray15", "gray90"), anchor="w",
        )
        self._title_lbl.pack(side="left", padx=(12, 6), pady=8)

        ctk.CTkButton(
            hdr, text="✕", width=28, height=24, font=("JetBrains Mono", 12),
            fg_color=("gray80", "gray25"), hover_color=DARK_BD2,
            text_color=BTN_TEXT, command=self._close,
        ).pack(side="right", padx=(4, 10), pady=6)

        # ── Панель управления: сторона / 180° / размеры ──────────
        bar = ctk.CTkFrame(self, fg_color=("gray88", "gray15"), corner_radius=0)
        bar.grid(row=1, column=0, sticky="ew")

        self._side_seg = ctk.CTkSegmentedButton(
            bar, values=["Лицо", "Оборот"], font=("JetBrains Mono", 10),
            selected_color=ACCENT2, unselected_color=("gray80", "gray24"),
            command=self._on_side_change, height=26,
        )
        self._side_seg.set("Лицо")
        self._side_seg.pack(side="left", padx=(10, 6), pady=6)

        ctk.CTkButton(
            bar, text="⟲ 180°", width=60, height=26, font=("JetBrains Mono", 10),
            fg_color=("gray80", "gray25"), hover_color=DARK_BD2,
            text_color=BTN_TEXT, command=self._toggle_flip,
        ).pack(side="left", padx=(0, 6), pady=6)

        self._dims_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            bar, text="Размеры", variable=self._dims_var,
            font=("JetBrains Mono", 10), checkbox_width=16, checkbox_height=16,
            fg_color=ACCENT2, checkmark_color="black",
            command=self._on_dims_toggle,
        ).pack(side="left", padx=(0, 10), pady=6)

        # ── Холст со схемой ──────────────────────────────────────
        is_dark = ctk.get_appearance_mode().lower() == "dark"
        self._canvas = tk.Canvas(
            self, bg="#161616" if is_dark else "#dcdcdc",
            highlightthickness=0, bd=0,
        )
        self._canvas.grid(row=2, column=0, sticky="nsew")
        self._canvas.bind("<Configure>", self._on_resize)

        # ── Подпись под схемой: параметры сигнатуры ──────────────
        self._info_lbl = ctk.CTkLabel(
            self, text="", font=("JetBrains Mono", 10),
            text_color=("gray25", "gray75"), justify="left", anchor="w",
        )
        self._info_lbl.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 10))

    # ── ПУБЛИЧНОЕ API ────────────────────────────────────────────
    def show(self, sig: dict, tpl_name: str = ""):
        """Показать сигнатуру (можно вызывать повторно — панель
        просто перерисуется под новую сигнатуру)."""
        self._sig = sig
        self._tpl_name = tpl_name
        self._geo = parse_signature_geometry(sig)
        self._side = "A"
        self._side_seg.set("Лицо")

        name = sig.get("name") or "(без имени)"
        self._title_lbl.configure(text=name)

        parts = []
        if sig.get("pages") is not None:
            parts.append(f"{sig['pages']} стр.")
        if sig.get("press_format"):
            parts.append(f"лист {sig['press_format']}")
        if sig.get("clapan_mm") is not None:
            parts.append(f"клапан {sig['clapan_mm']} мм")
        if sig.get("gutter_total_mm") is not None:
            parts.append(f"в голове {sig['gutter_total_mm']} мм")
        if self._geo["ok"]:
            n_sec = len(self._geo["sections"])
            if n_sec > 1:
                parts.append(f"{n_sec} секции")
        info = " · ".join(parts)
        if tpl_name:
            info = f"{info}\n{tpl_name}" if info else tpl_name
        self._info_lbl.configure(text=info)

        self._redraw_canvas()

    # ── ОБРАБОТЧИКИ ──────────────────────────────────────────────
    def _close(self):
        if callable(self._on_close):
            self._on_close()

    def _on_side_change(self, value: str):
        self._side = "A" if value == "Лицо" else "B"
        self._redraw_canvas()

    def _toggle_flip(self):
        self._flip180 = not self._flip180
        self._redraw_canvas()

    def _on_dims_toggle(self):
        self._show_dims = bool(self._dims_var.get())
        self._redraw_canvas()

    def _on_resize(self, _event=None):
        # Перерисовка «с задержкой» — иначе при перетаскивании
        # границы панели схема пересчитывается на каждый пиксель.
        if self._redraw_job is not None:
            try:
                self.after_cancel(self._redraw_job)
            except Exception:
                pass
        self._redraw_job = self.after(60, self._redraw_canvas)

    # ── ОТРИСОВКА ────────────────────────────────────────────────
    def _redraw_canvas(self):
        self._redraw_job = None
        c = self._canvas
        c.delete("all")

        cw = c.winfo_width()
        ch = c.winfo_height()
        if cw < 20 or ch < 20:
            return

        if not self._geo or not self._geo["ok"]:
            c.create_text(
                cw / 2, ch / 2, text="Не удалось разобрать геометрию\nэтой сигнатуры",
                fill=_pick(("gray35", "gray65")), font=("JetBrains Mono", 11),
                justify="center",
            )
            return

        geo = self._geo
        sw, sh = geo["sheet_w"], geo["sheet_h"]

        pad = 46 if self._show_dims else 16
        scale = min((cw - 2 * pad) / sw, (ch - 2 * pad) / sh)
        if scale <= 0:
            return
        ox = (cw - sw * scale) / 2
        oy = (ch - sh * scale) / 2

        def transform_x(x_pt, w_pt):
            """X с учётом зеркала оборота и разворота на 180°."""
            x = x_pt
            if self._side == "B":
                x = sw - x - w_pt
            if self._flip180:
                x = sw - x - w_pt
            return x

        def transform_y(y_pt, h_pt):
            """Y с учётом разворота на 180° (оборот Y не трогает)."""
            y = y_pt
            if self._flip180:
                y = sh - y - h_pt
            return y

        def to_canvas(x_pt, y_pt, w_pt, h_pt):
            """PostScript (Y вверх, начало слева снизу) → холст."""
            x = transform_x(x_pt, w_pt)
            y = transform_y(y_pt, h_pt)
            x1 = ox + x * scale
            y1 = oy + (sh - y - h_pt) * scale
            return x1, y1, x1 + w_pt * scale, y1 + h_pt * scale

        def x_band_to_canvas(x_start_pt, size_pt):
            """Вертикальная полоса (зазор/поле по оси X) на всю высоту листа."""
            x = transform_x(x_start_pt, size_pt)
            x1 = ox + x * scale
            return x1, oy, x1 + size_pt * scale, oy + sh * scale

        def y_band_to_canvas(y_start_pt, size_pt):
            """Горизонтальная полоса (зазор/поле по оси Y) на всю ширину листа."""
            y = transform_y(y_start_pt, size_pt)
            y1 = oy + (sh - y - size_pt) * scale
            return ox, y1, ox + sw * scale, y1 + size_pt * scale

        sheet_line = _pick(_SHEET_LINE)

        # Печатный лист
        c.create_rectangle(
            ox, oy, ox + sw * scale, oy + sh * scale,
            fill=_pick(_SHEET_FILL), outline=sheet_line, width=1,
        )

        # Зазоры между полосами, "в корешке" и клапан — рисуем ДО
        # страниц, чтобы страницы легли поверх и красным осталась
        # видна только сама пустая зона (зазор/поле), как на образце.
        if self._show_dims:
            self._draw_measurements(c, geo, ox, oy, scale, sw, sh,
                                     x_band_to_canvas, y_band_to_canvas)

        # Полосы
        page_line = _pick(_PAGE_LINE)
        for p in geo["pages"]:
            x1, y1, x2, y2 = to_canvas(p["x"], p["y"], p["fw"], p["fh"])
            num = p["front"] if self._side == "A" else p["back"]
            empty = not num

            c.create_rectangle(
                x1, y1, x2, y2,
                fill=_pick(_EMPTY_FILL if empty else _PAGE_FILL),
                outline=page_line, width=1,
            )

            # Куда смотрит ГОЛОВА полосы. Поворот против часовой:
            # 0° — вверх, 90° — влево, 180° — вниз, 270° — вправо.
            angle = p["angle"]
            if self._side == "B" or self._flip180:
                # Оборот — зеркало по X, разворот листа — поворот на
                # 180°; и то и другое меняет направление головы.
                if self._side == "B" and angle in (90, 270):
                    angle = 360 - angle
                if self._flip180:
                    angle = (angle + 180) % 360

            # Чёрная полоса «головы»: потолще и с отступом от краёв
            # страницы (и от головного края, и от боковых).
            dim = min(x2 - x1, y2 - y1)
            bar = max(6.0, min(20.0, dim * 0.10))
            inset = min(max(3.0, min(9.0, dim * 0.06)), dim / 4)
            if angle == 0:      # голова вверху
                c.create_rectangle(x1 + inset, y1 + inset,
                                   x2 - inset, y1 + inset + bar,
                                   fill=_HEAD_BAR, outline="")
            elif angle == 180:  # голова внизу
                c.create_rectangle(x1 + inset, y2 - inset - bar,
                                   x2 - inset, y2 - inset,
                                   fill=_HEAD_BAR, outline="")
            elif angle == 90:   # голова слева
                c.create_rectangle(x1 + inset, y1 + inset,
                                   x1 + inset + bar, y2 - inset,
                                   fill=_HEAD_BAR, outline="")
            else:               # 270° — голова справа
                c.create_rectangle(x2 - inset - bar, y1 + inset,
                                   x2 - inset, y2 - inset,
                                   fill=_HEAD_BAR, outline="")

            if not empty:
                # Номер полосы разворачиваем вместе с самой полосой —
                # так сразу видно, где у неё верх (как в Preps).
                fs = max(7, min(16, int(min(x2 - x1, y2 - y1) / 4)))
                try:
                    c.create_text(
                        (x1 + x2) / 2, (y1 + y2) / 2, text=str(num),
                        fill=_PAGE_TEXT, font=("JetBrains Mono", fs, "bold"),
                        angle=angle,
                    )
                except tk.TclError:  # очень старый Tk без angle=
                    c.create_text(
                        (x1 + x2) / 2, (y1 + y2) / 2, text=str(num),
                        fill=_PAGE_TEXT, font=("JetBrains Mono", fs, "bold"),
                    )

        # Подпись стороны — как в Preps: Side A (front) / Side B (back).
        # Выше линейки зазоров (та рисуется чуть ниже, у самого края
        # листа), чтобы подписи не наезжали друг на друга.
        side_label_y = max(9, oy - (28 if self._show_dims else 12))
        c.create_text(
            ox + sw * scale / 2, side_label_y,
            text="Сторона A (лицо)" if self._side == "A" else "Сторона B (оборот)",
            fill=_pick(("gray25", "gray75")), font=("JetBrains Mono", 10, "bold"),
        )

    def _draw_measurements(self, c, geo, ox, oy, scale, sw, sh,
                            x_band_to_canvas, y_band_to_canvas):
        """
        Подсвечивает красным ровно три вещи (как просил заказчик):
          • ВСЕ зазоры между полосами (обе оси, каждая позиция);
          • зазор(ы) "в корешке" — те из них, что совпадают по
            величине с gutter_total_mm из .tpl (SmartMark-матрица),
            выделяются отдельной подписью "Корешок";
          • клапан — единственное поле листа, снизу при ландшафтной
            ориентации и слева при портретной (сторона A/лицо; для
            оборота и разворота на 180° позиция того же поля просто
            едет по тем же правилам, что и страницы).
        Больше никакие поля (остальные 3 стороны) не подсвечиваются.
        """
        m = measure_layout(geo)
        if not m:
            return

        # Нейтральный зелёный вместо красного для выделения расстояний
        # и значений в превью сигнатуры.
        GREEN_FILL = "#8DBF9D"
        GREEN_TEXT = "#4D7C5A" if ctk.get_appearance_mode().lower() != "dark" else "#9AD3A8"
        font_num = ("JetBrains Mono", 10, "bold")

        sig = self._sig or {}
        gutter_mm = sig.get("gutter_total_mm")

        def is_spine(size_pt):
            if gutter_mm is None:
                return False
            return abs(_mm(size_pt) - gutter_mm) < 0.35

        # ── ВСЕ зазоры по X: полоса на всю высоту, подпись сверху ──
        for gap in m["x_gaps"]:
            x1, y1, x2, y2 = x_band_to_canvas(gap["start"], gap["size"])
            c.create_rectangle(x1, y1, x2, y2, fill=GREEN_FILL, outline="")
            label = _fmt_mm(gap["size"])
            cx = (x1 + x2) / 2
            c.create_text(cx, oy - 10, text=label, fill=GREEN_TEXT, font=font_num)

        # ── ВСЕ зазоры по Y: полоса на всю ширину, подпись слева ───
        for gap in m["y_gaps"]:
            x1, y1, x2, y2 = y_band_to_canvas(gap["start"], gap["size"])
            c.create_rectangle(x1, y1, x2, y2, fill=GREEN_FILL, outline="")
            label = _fmt_mm(gap["size"])
            cy = (y1 + y2) / 2
            c.create_text(ox - 10, cy, text=label, fill=GREEN_TEXT, font=font_num, angle=0)

        # ── Корешок без измеримого зазора (панели впритык) ──────────
        # Бывает на разворотных обложках: панели стоят вплотную, но
        # у сигнатуры всё равно задан gutter_total_mm — отмечаем саму
        # линию соприкосновения тонкой чертой с подписью.
        if gutter_mm is not None and not any(is_spine(g["size"]) for g in m["x_gaps"] + m["y_gaps"]):
            if m["x_touch"] is not None:
                x1, y1, x2, y2 = x_band_to_canvas(m["x_touch"], 1.4)
                c.create_rectangle(x1, y1, x2, y2, fill=GREEN_FILL, outline="")
                c.create_text((x1 + x2) / 2, oy - 10, text=f"{gutter_mm:g}",
                              fill=GREEN_TEXT, font=font_num)
            elif m["y_touch"] is not None:
                x1, y1, x2, y2 = y_band_to_canvas(m["y_touch"], 1.4)
                c.create_rectangle(x1, y1, x2, y2, fill=GREEN_FILL, outline="")
                c.create_text(ox - 10, (y1 + y2) / 2, text=f"{gutter_mm:g}",
                              fill=GREEN_TEXT, font=font_num, angle=0)

        # ── Клапан: единственное поле листа ─────────────────────────
        # Bottom при ландшафтном листе, Left при портретном (сторона
        # A/лицо — так задаёт clapan_side парсер .tpl). Позиция того
        # же поля дальше едет по тем же правилам зеркалирования, что
        # и страницы (x_band_to_canvas/y_band_to_canvas).
        clapan_side = sig.get("clapan_side")
        clapan_mm = sig.get("clapan_mm")
        if clapan_side == "Left" and m["left"] > 0.5:
            x1, y1, x2, y2 = x_band_to_canvas(0, m["left"])
            c.create_rectangle(x1, y1, x2, y2, fill=GREEN_FILL, outline="")
            label = f"{clapan_mm:g}" if clapan_mm is not None else ""
            c.create_text((x1 + x2) / 2, oy - 10, text=label, fill=GREEN_TEXT, font=font_num)
        elif clapan_side == "Bottom" and m["bottom"] > 0.5:
            x1, y1, x2, y2 = y_band_to_canvas(0, m["bottom"])
            c.create_rectangle(x1, y1, x2, y2, fill=GREEN_FILL, outline="")
            label = f"{clapan_mm:g}" if clapan_mm is not None else ""
            c.create_text(ox - 10, (y1 + y2) / 2, text=label, fill=GREEN_TEXT, font=font_num, angle=0)

        # ── Остальные поля листа: только значение, серым шрифтом ────
        # Сторона клапана уже подписана выше (зелёным), поэтому здесь
        # она пропускается. Заливки нет — только число в мм. Подписи
        # ставятся так же, как у зазоров: для вертикальных полей
        # (лево/право) — над листом, для горизонтальных (низ/верх) —
        # слева от листа. Позиция считается теми же функциями, что и
        # страницы, поэтому корректно едет при обороте и развороте 180°.
        GRAY_TEXT = _pick(("#707070", "#9a9a9a"))
        font_gray = ("JetBrains Mono", 10)

        margins = []
        if clapan_side != "Left":
            margins.append(("x", 0, m["left"]))
        margins.append(("x", sw - m["right"], m["right"]))
        if clapan_side != "Bottom":
            margins.append(("y", 0, m["bottom"]))
        margins.append(("y", sh - m["top"], m["top"]))

        for axis, start, size in margins:
            if size <= 0.5:
                continue
            label = _fmt_mm(size)
            if axis == "x":
                x1, y1, x2, y2 = x_band_to_canvas(start, size)
                c.create_text((x1 + x2) / 2, oy - 10, text=label,
                              fill=GRAY_TEXT, font=font_gray)
            else:
                x1, y1, x2, y2 = y_band_to_canvas(start, size)
                c.create_text(ox - 10, (y1 + y2) / 2, text=label,
                              fill=GRAY_TEXT, font=font_gray)
