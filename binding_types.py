"""
Сопоставление типов скрепления между текстом, как он написан в
спецификации (то, что показываем и редактируем в интерфейсе), и
4-символьным кодом, который пишется в БД (колонка printery_order.binding
VARCHAR(4) — унаследована от схемы Printery, менять длину нельзя).

  скрепка              -> SKR
  термоклей            -> KBS
  твердый переплет     -> HARD
  резка в формат       -> REZ
  на пружину           -> PRU
  шитье                -> SHT
  шитье+термоклей       -> SHK   (порядок слов в спецификации не важен —
                                   "шитье+термоклей" и "термоклей+шитье"
                                   распознаются одинаково)
"""

# Простые (одиночные) типы скрепления.
BINDING_LABELS = [
    ("скрепка",          "SKR"),
    ("термоклей",        "KBS"),
    ("твердый переплет", "HARD"),
    ("резка в формат",   "REZ"),
    ("на пружину",       "PRU"),
    ("шитье",            "SHT"),
    ("фальцовка",        "FALC"),
]

# Составные типы — набор компонентов, которые должны присутствовать в
# тексте ОДНОВРЕМЕННО, независимо от порядка и разделителя между ними
# ("шитье+термоклей", "термоклей + шитье", "шитье и термоклей" — всё
# сводится к одному каноническому варианту и коду).
COMPOUND_BINDING_LABELS = [
    (("шитье", "термоклей"), "шитье+термоклей", "SHK"),
]


def _norm(s: str) -> str:
    """ё→е, схлопывание пробелов, нижний регистр — для устойчивого
    сравнения (спецификации пишут по-разному: "твердый"/"твёрдый",
    лишние пробелы, "шитье"/"шитьё" и т.п.)."""
    return " ".join((s or "").lower().replace("ё", "е").split())


_NORM_TO_LABEL = {_norm(label): label for label, _code in BINDING_LABELS}
_NORM_TO_CODE  = {_norm(label): code  for label, code  in BINDING_LABELS}
_CODE_TO_LABEL = {code: label for label, code in BINDING_LABELS}

for _components, _label, _code in COMPOUND_BINDING_LABELS:
    _CODE_TO_LABEL[_code] = _label


def _match_compound(n: str):
    """Если в тексте присутствуют ВСЕ компоненты составного типа
    (независимо от порядка/разделителя) — возвращает (label, code).
    Иначе None."""
    for components, label, code in COMPOUND_BINDING_LABELS:
        if all(_norm(comp) in n for comp in components):
            return label, code
    return None


def normalize_binding_label(raw: str) -> str:
    """
    Приводит "сырой" текст скрепления (из спецификации или введённый
    вручную) к одному из канонических вариантов, если он похож на
    один из них — сначала проверяются составные типы (напр.
    "шитье+термоклей", порядок слов не важен), потом простые. Если
    не похоже ни на что — возвращает исходный текст как есть, не
    теряя данные (в спецификации может быть что-то нестандартное).
    """
    n = _norm(raw)
    if not n:
        return (raw or "").strip()

    compound = _match_compound(n)
    if compound:
        return compound[0]

    if n in _NORM_TO_LABEL:
        return _NORM_TO_LABEL[n]
    for key, label in _NORM_TO_LABEL.items():
        if key in n or n in key:
            return label
    return raw.strip()


def binding_to_code(raw: str) -> str:
    """Текст скрепления (как в форме/спецификации) → 4-символьный код
    для БД. Неизвестные варианты обрезаются до 4 символов — БД не
    примет больше (VARCHAR(4))."""
    n = _norm(raw)
    if not n:
        return ""

    compound = _match_compound(n)
    if compound:
        return compound[1]

    if n in _NORM_TO_CODE:
        return _NORM_TO_CODE[n]
    for key, code in _NORM_TO_CODE.items():
        if key in n or n in key:
            return code
    return (raw or "").strip()[:4]


def binding_code_to_label(code: str) -> str:
    """4-символьный код из БД → текст для отображения в интерфейсе.
    Если код неизвестен (например, остался от старых заказов Printery
    до этого изменения) — показываем код как есть."""
    if not code:
        return ""
    return _CODE_TO_LABEL.get(code.strip().upper(), code)