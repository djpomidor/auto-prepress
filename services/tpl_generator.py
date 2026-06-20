"""
Генерация .tpl и .job файлов для Preps 5.3.
Логика перенесена из impo_reader.html (v0.4).
"""
import os

MM2PT = 2.834645669

# SmartMarks из test.tpl (вставляются в каждую тетрадь)
# В реальной установке читаются из файла конфига или из P:\Preps\Templates\base_marks.txt
_SMARTMARKS_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "smartmarks.txt")


def _load_smartmarks() -> str:
    if os.path.isfile(_SMARTMARKS_PATH):
        with open(_SMARTMARKS_PATH, encoding="utf-8") as f:
            return f.read()
    return ""  # без меток если файл не найден


def _load_matrix() -> str:
    matrix_path = os.path.join(os.path.dirname(__file__), "..", "assets", "matrix.txt")
    if os.path.isfile(matrix_path):
        with open(matrix_path, encoding="utf-8") as f:
            return f.read()
    return ""


def generate_tpl(sheets: list, params: dict = None) -> str:
    p = params or {}
    tpl_name = p.get("tpl_name", "NewTemplate")
    sig_name = p.get("sig_name", "72x104")
    sw = p.get("sheet_w", 720) * MM2PT
    sh = p.get("sheet_h", 1040) * MM2PT
    pw = p.get("page_w", 163) * MM2PT
    ph = p.get("page_h", 245) * MM2PT
    spine = p.get("spine", 24) * MM2PT
    gap   = p.get("gap",    6) * MM2PT
    mx    = p.get("margin_x", 22) * MM2PT
    my    = p.get("margin_y", 12) * MM2PT
    use_marks = p.get("use_marks", True)

    def fmt(n): return f"{n:.5f}"

    def calc_x(col, cols):
        return mx + col * pw + (spine if col >= cols // 2 else 0)

    def calc_y(row, rows):
        hr = rows // 2
        y = my
        for r in range(row):
            y += ph
            y += spine if (r + 1 == hr) else gap
        return y

    sm  = _load_smartmarks() if use_marks else ""
    mxb = _load_matrix()

    L = []
    L.append("%!PS")
    L.append(f"% Template: {tpl_name}.tpl  ImpoReader v1.0")
    L.append("%%FileEncoding: 134217984")
    L.append("%%Creator: Preps 5.3.3   Windows Win32")
    L.append("%SSiPrepsVer: 1")
    L.append(f"%SSiLayout: |{tpl_name}| |{tpl_name}| 1 1 {fmt(pw)} {fmt(ph)} 25 ''")
    L.append(f"%SSiPressSheet: {fmt(sw)} {fmt(sh)} 0.00000 0.00000 0 283.46457 1 14.17330 0")
    L.append("%SSiPrshPage: 0.00000 0.00000 0.00000 0.00000 3 1 2 14.17330 14.17330 14.17330 14.17330 24580 0.00000 1.00000 0.00000 1 0.00000 0.00000 1")

    for si, sheet in enumerate(sheets):
        rows = sheet["rows"]
        cols = sheet["cols"]
        cells = [c for c in sheet.get("cells", []) if c.get("page") is not None]
        side  = sheet.get("side", "face")
        lbl   = f"{sig_name}{' back' if side == 'back' else ''}"

        L.append(f"%SSiSignature: |{lbl}| {len(cells)} 6 1 2 ''")
        L.append(f"%SSiPressSheet: {fmt(sw)} {fmt(sh)} 0.00000 0.00000 0 283.46457 4 14.17323 19")
        if sm:
            L.append(sm)
        if mxb:
            L.append(mxb)

        for cd in cells:
            x = calc_x(cd["col"], cols)
            y = calc_y(cd["row"], rows)
            rot = 7 if cd.get("rotated") else 5
            pg  = cd["page"]
            L.append(
                f"%SSiPrshPage: {fmt(x)} {fmt(y)} {fmt(pw)} {fmt(ph)} "
                f"{rot} {pg} 0 14.17300 14.17300 14.17300 14.17300 "
                f"24580 0.00000 1.00000 0.00000 1 0.00000 0.00000 1"
            )
            L.append("%SSiPrshMark: 0.00000 14.17294 0.00000 14.17294 5 0.00000 '' 0.00000 0 100 100 100 100 3 1 1 1 0 0.00000 0.00000 0 0")
            L.append("%SSiPrshMark: 14.17294 0.00000 14.17294 0.00000 7 0.00000 '' 0.00000 0 100 100 100 100 3 1 1 1 0 0.00000 0.00000 0 0")

        L.append("%SSiPrshMatrix: 7 -1.00000 0.00000 0")

    return "\r\n".join(L)


def generate_job(sheets: list, meta: dict, params: dict = None) -> str:
    p = params or {}
    tpl_name = p.get("tpl_name", "NewTemplate")
    sig_name = p.get("sig_name", "72x104")
    base     = p.get("pdf_base_path", "file://DELL_EVO/dataVolumes").rstrip("/")
    folder   = p.get("pdf_folder", "").rstrip("/")
    pdf_base = p.get("pdf_filename", "block")
    pdf_path = f"{base}/{folder}" if folder else base

    import time
    ts = int(time.time())

    pages = set()
    for sh in sheets:
        for cd in sh.get("cells", []):
            if cd.get("page") is not None:
                pages.add(cd["page"])
    sorted_pages = sorted(pages)

    L = []
    L.append("%!PS")
    L.append(f"% Job: {meta.get('number', '')} {meta.get('name', '')}  ImpoReader v1.0")
    L.append("%%FileEncoding: 134217984")
    L.append("%%Creator: Preps 5.3.3   Windows Win32")
    L.append("%SSiPrepsVer: 1")

    for pg in sorted_pages:
        idx = pg + 5
        pad = str(pg).zfill(4)
        fn  = f"{pdf_base}.p{pad}.pdf"
        L.append(f"%SSiJobFileRef: {idx} '{pdf_path}/{fn}' {idx} {ts} 0 "
                 "0.00000 0.00000 0.00000 0.00000 0.00000 0.00000 1.00000 0 " + str(ts))

    for special in [(-1, "Blank Page"), (-2, "LW/CT Single"),
                    (-3, "LW/CT Reader Left"), (-4, "LW/CT Reader Right")]:
        L.append(f"%SSiJobFileRef: {special[0]} '{special[1]}' 0 0 0 "
                 "0.00000 0.00000 0.00000 0.00000 0.00000 0.00000 1.00000 0 -1")

    for pg in sorted_pages:
        L.append(f"%SSiJobPage: {pg+5} 1 0.00012 0.00010 1.00000 1.00000 3 0.00000 0.00000 '' 1 -1 1")

    L.append("%SSiLaySpecs: 1 0 0.00000 0.00000 '' 0.00000 0.00000 0.00000 0.00000 1.00000 1.00000 14.17294 0 '' '' '' 4 1 1 '' 0")

    for si, sh in enumerate(sheets):
        pgs = sorted(cd["page"] for cd in sh.get("cells", []) if cd.get("page") is not None)
        if not pgs:
            continue
        side = sh.get("side", "face")
        lbl  = f"{sig_name}{' back' if side == 'back' else ''}"
        L.append(f"%SSiSigUsed: '{tpl_name}' '{lbl}' 0 0 '' '' '' 10.00000 '' '' '' '' '' 0 0")
        L.append(f"%SSiJobDelivery: {pgs[0]+5} {si*2+1} 1 0 0")
        L.append(f"%SSiJobDelivery: {pgs[-1]+5} {si*2+2} 1 0 0")

    L.append("%SSiWindowSize: 1 0 0 295 939 4271986")
    L.append("%SSiWindowSize: 2 319 2 550 940 4271986")
    L.append("%SSiJobColor: 'Composite' 150.00000 45.00000 -1 0.00000 0.00000 0.00000 0.00000 0 0 0.00000 0.00000 0.00000 0.00000 150.00000 45.00000")
    L.append("%SSiJobColor: 'Process Cyan' 150.00000 105.00000 -1 0.00000 0.00000 0.00000 0.00000 1 2 1.00000 0.00000 0.00000 0.00000 150.00000 105.00000")
    L.append("%SSiJobColor: 'Process Magenta' 150.00000 75.00000 -1 0.00000 0.00000 0.00000 0.00000 2 2 0.00000 0.00000 0.00000 0.00000 150.00000 75.00000")
    L.append("%SSiJobColor: 'Process Yellow' 150.00000 90.00000 -1 0.00000 0.00000 0.00000 0.00000 3 2 0.00000 0.00000 0.00000 0.00000 150.00000 90.00000")
    L.append("%SSiJobColor: 'Process Black' 150.00000 45.00000 -1 0.00000 0.00000 0.00000 0.00000 4 2 0.00000 0.00000 0.00000 1.00000 150.00000 45.00000")

    return "\r\n".join(L)
