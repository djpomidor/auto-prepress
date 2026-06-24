"""
Парсинг XML логов PitStop Server.
Читает папку D:\\Pitstop_\\Log\<order_folder>\
"""
import os
import xml.etree.ElementTree as ET


def parse_pitstop_log(log_dir: str) -> str:
    """
    Возвращает текст для отображения в UI.
    """
    if not os.path.isdir(log_dir):
        return f"Папка лога не найдена:\n{log_dir}"

    xml_files = [
        f for f in os.listdir(log_dir)
        if f.lower().endswith(".xml")
    ]
    if not xml_files:
        return "XML лог PitStop не найден.\nОжидание проверки файлов..."

    results = []
    for fname in sorted(xml_files):
        path = os.path.join(log_dir, fname)
        results.append(_parse_xml(path, fname))

    return "\n\n".join(results)


def _parse_xml(path: str, fname: str) -> str:
    lines = [f"📄  {fname}", "─" * 50]
    try:
        tree = ET.parse(path)
        root = tree.getroot()

        # Размер страниц
        pages = root.findall(".//Page")
        if pages:
            sizes = set()
            for p in pages:
                w = p.get("Width") or p.get("width")
                h = p.get("Height") or p.get("height")
                if w and h:
                    sizes.add(f"{_pt2mm(w)}×{_pt2mm(h)} мм")
            if sizes:
                lines.append(f"Формат страниц:  {', '.join(sizes)}")
            lines.append(f"Страниц в файле: {len(pages)}")

        # Красочность
        colors = set()
        for p in pages:
            cs = p.get("ColorSpace") or p.get("colorspace")
            if cs:
                colors.add(cs)
        if colors:
            lines.append(f"Цветовое пространство: {', '.join(colors)}")

        # Ошибки и предупреждения
        errors   = root.findall(".//*[@severity='error']") or root.findall(".//Error")
        warnings = root.findall(".//*[@severity='warning']") or root.findall(".//Warning")

        if errors:
            lines.append(f"\n🔴 ОШИБКИ ({len(errors)}):")
            for e in errors[:10]:
                msg = e.get("message") or e.get("Message") or e.text or "—"
                pg  = e.get("page") or e.get("Page") or ""
                lines.append(f"  • {msg}" + (f"  [стр. {pg}]" if pg else ""))
        else:
            lines.append("\n✓ Ошибок не найдено")

        if warnings:
            lines.append(f"\n⚠ ПРЕДУПРЕЖДЕНИЯ ({len(warnings)}):")
            for w in warnings[:10]:
                msg = w.get("message") or w.get("Message") or w.text or "—"
                pg  = w.get("page") or w.get("Page") or ""
                lines.append(f"  • {msg}" + (f"  [стр. {pg}]" if pg else ""))

    except ET.ParseError as e:
        lines.append(f"Ошибка чтения XML: {e}")
    except Exception as e:
        lines.append(f"Ошибка: {e}")

    return "\n".join(lines)


def _pt2mm(pt_str: str) -> str:
    try:
        return str(round(float(pt_str) / 2.834645))
    except ValueError:
        return pt_str
