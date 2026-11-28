"""Vocabulario común de categorías de amenaza (IUCN global y Resolución 0126/2024 nacional)."""
from typing import Optional

CATEGORY_ORDER = ["EX", "EW", "CR", "EN", "VU", "NT", "DD", "LC", "NE"]
THREATENED = {"CR", "EN", "VU"}

CATEGORY_LABELS_ES = {
    "EX": "Extinta",
    "EW": "Extinta en estado silvestre",
    "CR": "En peligro crítico",
    "EN": "En peligro",
    "VU": "Vulnerable",
    "NT": "Casi amenazada",
    "DD": "Datos insuficientes",
    "LC": "Preocupación menor",
    "NE": "No evaluada",
}

# Colores oficiales de la Lista Roja IUCN
CATEGORY_COLORS = {
    "EX": "#000000",
    "EW": "#542344",
    "CR": "#D81E05",
    "EN": "#FC7F3F",
    "VU": "#F9E814",
    "NT": "#CCE226",
    "DD": "#D1D1C6",
    "LC": "#60C659",
    "NE": "#FFFFFF",
}

# Escala ordinal del gráfico evidencia–amenaza (Lección 1.3, G8)
ORDINAL_SCALE = {"LC": 0.0, "NT": 1.0, "DD": 1.5, "VU": 2.0, "EN": 3.0, "CR": 4.0, "EW": 5.0, "EX": 5.0}

_ALIASES = {
    "EXTINCT": "EX",
    "EXTINCT_IN_THE_WILD": "EW",
    "CRITICALLY_ENDANGERED": "CR",
    "ENDANGERED": "EN",
    "VULNERABLE": "VU",
    "NEAR_THREATENED": "NT",
    "DATA_DEFICIENT": "DD",
    "LEAST_CONCERN": "LC",
    "NOT_EVALUATED": "NE",
    "NOT_APPLICABLE": "NE",
    "LR/NT": "NT",
    "LR/LC": "LC",
    "LR/CD": "NT",
    "EN PELIGRO CRÍTICO": "CR",
    "EN PELIGRO CRITICO": "CR",
    "EN PELIGRO": "EN",
    "PREOCUPACIÓN MENOR": "LC",
    "CASI AMENAZADA": "NT",
    "DATOS INSUFICIENTES": "DD",
}


def normalize_category(value: Optional[str]) -> Optional[str]:
    """Convierte 'VULNERABLE', 'Vulnerable (VU)', 'vu', 'LR/nt'... a un código IUCN."""
    if not value:
        return None
    v = str(value).strip().upper()
    if "(" in v and v.endswith(")"):
        v = v[v.rfind("(") + 1 : -1].strip()
    v = _ALIASES.get(v.replace(" ", "_"), _ALIASES.get(v, v))
    return v if v in CATEGORY_ORDER else None


def is_threatened(code: Optional[str]) -> bool:
    return code in THREATENED
