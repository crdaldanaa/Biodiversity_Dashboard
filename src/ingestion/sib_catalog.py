"""Cliente del Catálogo de la Biodiversidad de Colombia (SiB Colombia).

API: https://api.catalogo.biodiversidad.co
 - /record_search/advanced_search?scientificName=...  → resumen (nombres comunes, amenaza, imagen)
 - /complete-record/{id}                               → ficha completa (descripción, hábitat, ...)
"""
from typing import Any, Dict, List, Optional

from src.config_loader import get_config
from src.references.threat import normalize_category
from src.utils.http import get_json

PORTAL_URL = "https://catalogo.biodiversidad.co/fichas/{id}"


def _base() -> str:
    return get_config()["settings"]["sources"]["sib_catalog"]["api_base"].rstrip("/")


def _canonical(record: dict) -> str:
    try:
        return record["taxonRecordNameApprovedInUse"]["taxonRecordName"]["scientificName"][
            "canonicalName"
        ]["simple"].strip()
    except (KeyError, TypeError):
        return (record.get("scientificNameSimple") or "").strip()


def _threats(record: dict) -> Dict[str, Any]:
    out: Dict[str, Any] = {"national": None, "global": None, "cites": []}
    items = ((record.get("threatStatusApprovedInUse") or {}).get("threatStatus")) or []
    for item in items:
        at = item.get("threatStatusAtomized") or {}
        cat = at.get("threatCategory") or {}
        mtype = (cat.get("measurementType") or "").upper()
        value = normalize_category(cat.get("measurementValue"))
        if mtype == "MADS" and value:
            out["national"] = value
        elif mtype in ("UICN", "IUCN") and value:
            out["global"] = value
        out["cites"].extend(at.get("apendiceCITES") or [])
    out["cites"] = sorted(set(out["cites"]))
    return out


def _common_names(record: dict) -> List[str]:
    names = record.get("commonNames") or []
    es = [n["name"] for n in names if n.get("name") and (n.get("language") or "").startswith("Espa")]
    # Sin idioma declarado suelen ser nombres locales en español; se excluyen otros idiomas (chino, alemán...)
    local = [n["name"] for n in names if n.get("name") and not n.get("language")
             and all(ord(c) < 0x2E80 for c in n["name"]) and n["name"] not in es]
    en = [n["name"] for n in names if n.get("name") and (n.get("language") or "").startswith(("Ingl", "Engl"))]
    return es + local + en


def _text(record: dict, path: List[str], limit: int = 1800) -> Optional[str]:
    node: Any = record
    for key in path:
        if isinstance(node, list):
            node = node[0] if node else None
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if isinstance(node, str) and node.strip():
        txt = " ".join(node.split())
        return txt if len(txt) <= limit else txt[:limit].rsplit(" ", 1)[0] + "…"
    return None


def search(scientific_name: str) -> Optional[Dict[str, Any]]:
    """Resumen normalizado del registro SiB para un nombre científico (o None)."""
    data = get_json(f"{_base()}/record_search/advanced_search", {"scientificName": scientific_name})
    if not data or not isinstance(data, list):
        return None
    target = scientific_name.strip().lower()
    match = next((r for r in data if _canonical(r).lower() == target), None)
    if match is None:
        return None
    origin = match.get("originAtomized") or {}
    img = match.get("imageInfo") or {}
    threats = _threats(match)
    return {
        "sib_id": match.get("_id"),
        "sib_url": PORTAL_URL.format(id=match.get("_id")),
        "common_names": _common_names(match),
        "threat_sib_national": threats["national"],
        "threat_sib_global": threats["global"] or normalize_category(match.get("threatStatusValue")),
        "cites": threats["cites"],
        "exotic": bool(origin.get("exotic")),
        "invasive": bool(origin.get("invasive")),
        "image": {
            "url": img.get("mainImage"),
            "author": img.get("rightsHolder"),
            "license": img.get("license"),
            "source": "SiB Colombia",
        }
        if img.get("mainImage")
        else None,
    }


def complete_record(sib_id: str) -> Optional[Dict[str, Any]]:
    """Textos de la ficha completa (resumen, distribución, hábitat, alimentación, amenazas...)."""
    r = get_json(f"{_base()}/complete-record/{sib_id}")
    if not r:
        return None
    sections = {
        "abstract": ["abstractApprovedInUse", "abstract"],
        "distribution": ["distributionApprovedInUse", "distribution", "distributionUnstructured"],
        "habitat": ["habitatsApprovedInUse", "habitats", "habitatUnstructured"],
        "feeding": ["feedingApprovedInUse", "feeding", "feedingUnstructured"],
        "reproduction": ["reproductionApprovedInUse", "reproduction", "reproductionUnstructured"],
        "behavior": ["behaviorApprovedInUse", "behavior", "behaviorUnstructured"],
        "threats": ["directThreatsApprovedInUse", "directThreats", "directThreatsUnstructured"],
        "conservation": [
            "usesManagementAndConservationApprovedInUse",
            "usesManagementAndConservation",
            "managementAndConservation",
            "managementAndConservationUnstructured",
        ],
    }
    out = {k: _text(r, p) for k, p in sections.items()}
    habitats_atomized = (
        ((r.get("habitats_version") or {}).get("habitats") or {}).get("habitatAtomized") or []
    )
    out["habitat_tags"] = [
        h.get("measurementOrFact", {}).get("measurementValue")
        for h in habitats_atomized
        if h.get("measurementOrFact", {}).get("measurementValue")
    ]
    return {k: v for k, v in out.items() if v}
