"""
Сопоставление типов скрепления между текстом, как он написан в
спецификации (то, что показываем и редактируем в интерфейсе), и
4-символьным кодом, который пишется в БД (колонка printery_order.binding
VARCHAR(4) — унаследована от схемы Printery, менять длину нельзя).

  скрепка            -> SKR
  термоклей          -> KBS
  твердый переплет   -> HARD
  резка в формат     -> REZ
  на пружину         -> PRU
"""

# Порядок важен для сопоставления по частичному совпадению — более
# длинные/специфичные фразы стоит проверять раньше.
BINDING_LABELS = [
    ("скрепка",          "SKR"),
    ("термоклей",        "KBS"),
    ("твердый переплет", "HARD"),
    ("резка в формат",   "REZ"),
    ("на пружину",       "PRU"),
    ("фальцовка",        "FALC"),
]


def _norm(s: str) -> str:
    """ё→е, схлопывание пробелов, нижний регистр — для устойчивого
    сравнения (спецификации пишут по-разному: "твердый"/"твёрдый",
    лишние пробелы и т.п.)."""
    return " ".join((s or "").lower().replace("ё", "е").split())


_NORM_TO_LABEL = {_norm(label): label for label, _code in BINDING_LABELS}
_NORM_TO_CODE  = {_norm(label): code  for label, code  in BINDING_LABELS}
_CODE_TO_LABEL = {code: label for label, code in BINDING_LABELS}


def normalize_binding_label(raw: str) -> str:
    """
    Приводит "сырой" текст скрепления (из спецификации или введённый
    вручную) к одному из 5 канонических вариантов, если он похож на
    один из них. Если не похож ни на что — возвращает исходный текст
    как есть, не теряя данные (в спецификации может быть что-то
    нестандартное).
    """
    n = _norm(raw)
    if not n:
        return (raw or "").strip()
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
    if n in _NORM_TO_CODE:
        return _NORM_TO_CODE[n]
    for key, code in _NORM_TO_CODE.items():
        if key in n or n in key:
            return code
    return (raw or "").strip()[:4]


def binding_code_to_label(code: str) -> str:
    """4-символьный код из БД → текст для отображения в интерфейсе.
    Если код не из известных пяти (например, остался от старых
    заказов Printery до этого изменения) — показываем код как есть."""
    if not code:
        return ""
    return _CODE_TO_LABEL.get(code.strip().upper(), code)
