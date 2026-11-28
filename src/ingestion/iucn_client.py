"""Estado de conservación global (IUCN Red List).

1. Si existe IUCN_TOKEN en .env → API v4 oficial (categoría, año de evaluación, criterios, historial).
2. Sin token → la categoría IUCN que GBIF expone por taxón (sin año ni criterios).
"""
from typing import Any, Dict, Optional

from src.config_loader import get_config
from src.ingestion import gbif_api
from src.references.threat import normalize_category
from src.utils.http import get_json


def _v4(scientific_name: str, token: str) -> Optional[Dict[str, Any]]:
    parts = scientific_name.split()
    if len(parts) < 2:
        return None
    base = get_config()["settings"]["sources"]["iucn"]["api_base"].rstrip("/")
    data = get_json(
        f"{base}/taxa/scientific_name",
        {"genus_name": parts[0], "species_name": parts[1]},
        headers={"Authorization": f"Bearer {token}"},
    )
    if not data:
        return None
    assessments = data.get("assessments") or []
    if not assessments:
        return None
    history = sorted(
        (
            {
                "year": int(a["year_published"]) if a.get("year_published") else None,
                "category": normalize_category(a.get("red_list_category_code")),
                "latest": bool(a.get("latest")),
                "assessment_id": a.get("assessment_id"),
                "url": a.get("url"),
            }
            for a in assessments
            if (a.get("scopes") or [{}])[0].get("code") in (None, "1")  # alcance global
        ),
        key=lambda a: a["year"] or 0,
    )
    latest = next((a for a in reversed(history) if a["latest"]), history[-1] if history else None)
    if not latest:
        return None
    return {
        "category": latest["category"],
        "year": latest["year"],
        "url": latest["url"],
        "history": history,
        "source": "IUCN Red List API v4",
    }


def get_status(scientific_name: str, species_key: Optional[int] = None) -> Optional[Dict[str, Any]]:
    token = get_config().get("iucn_token")
    if token:
        res = _v4(scientific_name, token)
        if res:
            return res
    if species_key:
        res = gbif_api.iucn_category(species_key)
        if res and res.get("category"):
            tid = res.get("iucn_taxon_id")
            return {
                "category": res["category"],
                "year": None,
                "url": f"https://www.iucnredlist.org/species/{tid}" if tid else None,
                "history": [],
                "source": "IUCN vía GBIF",
            }
    return None
