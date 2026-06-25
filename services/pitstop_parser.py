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
import xml.etree.ElementTree as ET
from collections import defaultdict


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
    Пытается извлечь размеры страниц из разных мест XML.
    Возвращает {size_str: [page_numbers]}.
    """
    sizes = defaultdict(list)

    # Вариант 1: <PageInfo page="N" width="W" height="H" unit="mm">
    for pi in root.findall(".//PageInfo"):
        page = pi.get("page")
        w    = pi.get("width") or pi.get("mediaWidth")
        h    = pi.get("height") or pi.get("mediaHeight")
        unit = pi.get("unit", "pt")
        if page and w and h:
            try:
                wf = float(w)
                hf = float(h)
                if unit == "pt":
                    wf = round(wf / 2.8346, 1)
                    hf = round(hf / 2.8346, 1)
                else:
                    wf = round(wf, 1)
                    hf = round(hf, 1)
                sizes[f"{wf}×{hf} мм"].append(int(page))
            except (ValueError, TypeError):
                pass

    # Вариант 2: <Page number="N"><TrimBox width="W" height="H"/></Page>
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
