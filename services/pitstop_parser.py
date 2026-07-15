"""
Парсинг XML отчётов Enfocus PitStop Server (версия 3.0).

Структура файла:
  <EnfocusReport>
    <PreflightReport errors="N" warnings="N">
      <Errors>
        <PreflightReportItem>
          <Message>...</Message>
          <Location page="N" .../>
        </PreflightReportItem>
      </Errors>
      <Warnings>...</Warnings>
    </PreflightReport>
  </EnfocusReport>
"""
import os
import datetime
import xml.etree.ElementTree as ET
from collections import defaultdict


def list_pitstop_reports_for_order(order_folder_name: str) -> list:
    """
    Возвращает ВСЕ отчёты PitStop для заказа — и из pitstop_log
    (туда попадают проверки С ошибками), и из pitstop_ok (туда
    PitStop Server кладёт оригинал файла + XML, когда ошибок НЕТ —
    это отдельная папка, pitstop_log при этом не используется вообще).
    Объединённый список отсортирован от новых к старым.
    """
    import config
    dirs = [
        os.path.join(config.CFG.get("pitstop_log", ""), order_folder_name),
        os.path.join(config.CFG.get("pitstop_ok", ""),  order_folder_name),
    ]
    reports = []
    for d in dirs:
        if d and os.path.isdir(d):
            reports.extend(list_pitstop_reports(d))
    reports.sort(key=lambda r: r["dt"], reverse=True)
    return reports


def list_pitstop_reports(log_dir: str) -> list:
    """
    Возвращает список отчётов PitStop в папке лога, отсортированный
    от новых к старым (по времени проверки).
    Каждый элемент:
      {
        "fname": "...", "xml_path": "...", "pdf_path": "..." | None,
        "dt": datetime, "errors": int, "warnings": int,
        "page_sizes": {"150.0x225.0 мм": [1,2,3,...]},
        "page_count": int,
        "text": "отформатированный текст отчёта",
      }
    """
    if not os.path.isdir(log_dir):
        return []

    xml_files = [f for f in os.listdir(log_dir) if f.lower().endswith(".xml")]
    reports = []
    for fname in xml_files:
        path = os.path.join(log_dir, fname)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue

        try:
            tree = ET.parse(path)
            root = tree.getroot()
        except ET.ParseError:
            continue

        # Дата/время проверки — берём из самого отчёта
        # (<ProcessInfo><PreflightDateTime>), это точнее, чем дата
        # изменения файла (которая "плывёт" при копировании файлов
        # между папками). Если вдруг отсутствует — берём mtime.
        dt = None
        dt_el = root.find(".//ProcessInfo/PreflightDateTime")
        if dt_el is not None and dt_el.text:
            try:
                dt = datetime.datetime.fromisoformat(dt_el.text.strip())
                dt = dt.replace(tzinfo=None)  # чтобы сравнение с naive mtime не падало
            except ValueError:
                dt = None
        if dt is None:
            dt = datetime.datetime.fromtimestamp(mtime)

        report_el = root.find(".//PreflightReport")
        errors   = int(report_el.get("errors", "0"))   if report_el is not None and report_el.get("errors", "0").isdigit()   else 0
        warnings = int(report_el.get("warnings", "0")) if report_el is not None and report_el.get("warnings", "0").isdigit() else 0

        page_sizes = _extract_page_sizes(root)

        # Кол-во полос — берём из <GeneralDocInfo><DocumentProperties>
        # <NumPages>, это надёжнее, чем считать по TrimBox (TrimBox
        # может быть не определён на части страниц).
        num_pages_el = root.find(".//GeneralDocInfo/DocumentProperties/NumPages")
        if num_pages_el is not None and (num_pages_el.text or "").strip().isdigit():
            page_count = int(num_pages_el.text.strip())
        else:
            page_count = len({p for pages in page_sizes.values() for p in pages})

        # Ищем PDF-версию того же отчёта рядом (стандартная выгрузка
        # Enfocus PitStop Server кладёт .xml и .pdf с одинаковым именем)
        stem = os.path.splitext(fname)[0]
        pdf_candidate = os.path.join(log_dir, stem + ".pdf")
        pdf_path = pdf_candidate if os.path.isfile(pdf_candidate) else None

        reports.append({
            "fname": fname,
            "xml_path": path,
            "pdf_path": pdf_path,
            "dt": dt,
            "errors": errors,
            "warnings": warnings,
            "page_sizes": page_sizes,
            "page_count": page_count,
            "text": _parse_enfocus_xml(path, fname),
        })

    reports.sort(key=lambda r: r["dt"], reverse=True)
    return reports


def parse_pitstop_log(log_dir: str) -> str:
    """Читает все XML в папке, возвращает текст для UI."""
    if not os.path.isdir(log_dir):
        return f"Папка лога не найдена:\n{log_dir}"

    xml_files = sorted(
        f for f in os.listdir(log_dir)
        if f.lower().endswith(".xml")
    )
    if not xml_files:
        return "XML лог PitStop не найден.\nОжидание проверки файлов..."

    results = []
    for fname in xml_files:
        path = os.path.join(log_dir, fname)
        results.append(_parse_enfocus_xml(path, fname))

    return "\n\n".join(results)


def _parse_enfocus_xml(path: str, fname: str) -> str:
    lines = [f"📄  {fname}", "─" * 55]

    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except ET.ParseError as e:
        return "\n".join(lines) + f"\nОшибка чтения XML: {e}"

    # ── Заголовок PreflightReport ─────────────────────────────────
    report = root.find(".//PreflightReport")
    if report is not None:
        n_err  = report.get("errors",           "?")
        n_warn = report.get("warnings",         "?")
        n_crit = report.get("criticalfailures", "0")
        lines.append(f"Ошибок: {n_err}   Предупреждений: {n_warn}   Критических: {n_crit}")
        lines.append("")

    # ── Формат страниц (из PageInfo или PageGeometry) ─────────────
    page_sizes = _extract_page_sizes(root)
    if page_sizes:
        lines.append("📐 Форматы страниц:")
        for size_str, pages in page_sizes.items():
            pg_list = _format_page_list(pages)
            lines.append(f"   {size_str}  →  стр. {pg_list}")
        lines.append("")

    # ── Ошибки ────────────────────────────────────────────────────
    errors = root.findall(".//Errors/PreflightReportItem")
    if errors:
        lines.append(f"🔴 ОШИБКИ ({len(errors)}):")
        for item in errors:
            lines.append(_format_item(item))
        lines.append("")
    else:
        # Проверяем атрибут errors= в заголовке
        if report is not None and report.get("errors", "0") != "0":
            lines.append("🔴 Ошибки найдены (детали не распарсены)")
        else:
            lines.append("✅ Ошибок не найдено")
        lines.append("")

    # ── Предупреждения ────────────────────────────────────────────
    warnings = root.findall(".//Warnings/PreflightReportItem")
    if warnings:
        lines.append(f"⚠️  ПРЕДУПРЕЖДЕНИЯ ({len(warnings)}):")
        for item in warnings:
            lines.append(_format_item(item))

    return "\n".join(lines)


def _format_item(item) -> str:
    """Форматирует один PreflightReportItem."""
    msg = ""

    # Берём текст из <Message> напрямую
    msg_el = item.find("Message")
    if msg_el is not None and msg_el.text:
        msg = msg_el.text.strip()
    else:
        # Если нет — собираем из StringContext
        base_el = item.find(".//BaseString")
        if base_el is not None and base_el.text:
            msg = base_el.text.strip()
            # Подставляем переменные %[]VarName% → значения
            for var in item.findall(".//Var"):
                name = var.get("name", "")
                val  = var.text or ""
                msg  = msg.replace(f"%[]{name}%", val)
                msg  = msg.replace(f"%{name}%", val)

    # Страницы из <Location page="N">
    pages = sorted(set(
        int(loc.get("page"))
        for loc in item.findall("Location")
        if loc.get("page", "").isdigit()
    ))
    pg_str = f"  [стр. {_format_page_list(pages)}]" if pages else ""

    return f"   • {msg}{pg_str}"


def _extract_page_sizes(root) -> dict:
    """
    Извлекает обрезной формат (TrimBox) по страницам из блока
    PageBoxInfo — это реальная структура отчёта Enfocus PitStop
    Server v3:

      <EnfocusReport version="3.0" unit="mm">
        <PageBoxInfo pageBoxesEqual="true">
          <Page index="1" rotate="0" scaling="1">
            <TrimBox defined="true" width="326" height="245" .../>
          </Page>
        </PageBoxInfo>
      </EnfocusReport>

    ВАЖНО: единица измерения (мм или пункты) указана в атрибуте
    unit корневого элемента EnfocusReport, а не отдельно на каждом
    Page/TrimBox — раньше это не учитывалось, из-за чего формат
    определялся неверно.

    Возвращает {size_str: [page_numbers]}.
    """
    sizes = defaultdict(list)
    unit = (root.get("unit") or "pt").strip().lower()

    def _to_mm(value: float) -> float:
        if unit in ("pt", "point", "points"):
            return round(value / 2.8346, 1)
        # unit == "mm" (или что-то ещё — считаем, что уже в мм)
        return round(value, 1)

    for page_el in root.findall(".//PageBoxInfo/Page"):
        idx = page_el.get("index")
        if not idx or not idx.isdigit():
            continue

        trim = page_el.find("TrimBox")
        if trim is None or trim.get("defined") == "false":
            continue

        w = trim.get("width")
        h = trim.get("height")
        if not w or not h:
            continue

        try:
            wf = _to_mm(float(w))
            hf = _to_mm(float(h))
            sizes[f"{wf}×{hf} мм"].append(int(idx))
        except (ValueError, TypeError):
            pass

    if sizes:
        return dict(sizes)

    # ── Фоллбэк на случай другой версии/схемы отчёта ────────────────
    # (старые варианты поиска — на случай, если PageBoxInfo в
    # конкретном отчёте отсутствует)
    for pi in root.findall(".//PageInfo"):
        page = pi.get("page")
        w    = pi.get("width") or pi.get("mediaWidth")
        h    = pi.get("height") or pi.get("mediaHeight")
        pi_unit = pi.get("unit", unit)
        if page and w and h:
            try:
                wf = float(w)
                hf = float(h)
                if pi_unit in ("pt", "point", "points"):
                    wf = round(wf / 2.8346, 1)
                    hf = round(hf / 2.8346, 1)
                else:
                    wf = round(wf, 1)
                    hf = round(hf, 1)
                sizes[f"{wf}×{hf} мм"].append(int(page))
            except (ValueError, TypeError):
                pass

    for page_el in root.findall(".//Page"):
        page = page_el.get("number") or page_el.get("index")
        tb   = page_el.find("TrimBox") or page_el.find("MediaBox")
        if page and tb is not None:
            w = tb.get("width")
            h = tb.get("height")
            if w and h:
                try:
                    wf = round(float(w) / 2.8346, 1)
                    hf = round(float(h) / 2.8346, 1)
                    sizes[f"{wf}×{hf} мм"].append(int(page))
                except (ValueError, TypeError):
                    pass

    return dict(sizes)


def check_mismatch(report: dict, order) -> list:
    """
    Сравнивает данные последнего отчёта PitStop с данными заказа.
    Возвращает список текстовых предупреждений о несовпадениях
    (обрезной формат, количество полос). Пустой список — совпадает
    или сравнивать не с чем.
    """
    warnings_out = []
    if not report:
        return warnings_out

    # ── Формат ────────────────────────────────────────────────────
    if order.width and order.height and report.get("page_sizes"):
        # Берём самый частый формат в отчёте (по кол-ву страниц)
        best_size = max(report["page_sizes"].items(), key=lambda kv: len(kv[1]))[0]
        try:
            w_str, h_str = best_size.replace(" мм", "").split("×")
            w_pdf, h_pdf = float(w_str), float(h_str)
            tol = 2.0  # мм — допуск на погрешность обмера
            match = (
                (abs(w_pdf - order.width) <= tol and abs(h_pdf - order.height) <= tol) or
                (abs(w_pdf - order.height) <= tol and abs(h_pdf - order.width) <= tol)  # с учётом поворота
            )
            if not match:
                warnings_out.append(
                    f"⚠ Формат в PitStop: {best_size}, в заказе: {order.width}×{order.height} мм"
                )
        except (ValueError, IndexError):
            pass

    # ── Количество полос (сравниваем с «Объём блок») ────────────────
    if order.pages_block and report.get("page_count"):
        if report["page_count"] != order.pages_block:
            warnings_out.append(
                f"⚠ Полос в файле PitStop: {report['page_count']}, "
                f"в заказе (Объём блок): {order.pages_block}"
            )

    return warnings_out


def _format_page_list(pages: list) -> str:
    """[1,2,3,5,6,10] → '1–3, 5–6, 10'"""
    if not pages:
        return ""
    pages = sorted(set(pages))
    ranges = []
    start = end = pages[0]
    for p in pages[1:]:
        if p == end + 1:
            end = p
        else:
            ranges.append(f"{start}" if start == end else f"{start}–{end}")
            start = end = p
    ranges.append(f"{start}" if start == end else f"{start}–{end}")
    return ", ".join(ranges)
