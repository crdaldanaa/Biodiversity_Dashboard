"""Endpoints REST de GBIF usados de forma síncrona (sin descarga asíncrona):
resolución taxonómica, categoría IUCN, multimedia y búsqueda paginada por geometría.
"""
from typing import Any, Callable, Dict, Iterator, List, Optional

from src.config_loader import get_config
from src.references.threat import normalize_category
from src.utils.http import get_json
from src.utils.logger import get_logger

logger = get_logger(__name__)
SEARCH_HARD_LIMIT = 100_000  # GBIF no permite offset + limit > 100.000 en /occurrence/search
PAGE_SIZE = 300


def _base() -> str:
    return get_config()["settings"]["gbif"]["api_base"].rstrip("/")


def match_species(name: str) -> Optional[Dict[str, Any]]:
    data = get_json(f"{_base()}/species/match", {"name": name, "strict": "false"})
    if not data or data.get("matchType") == "NONE":
        return None
    return {
        "usage_key": data.get("usageKey"),
        "species_key": data.get("speciesKey") or data.get("usageKey"),
        "canonical_name": data.get("canonicalName"),
        "status": data.get("status"),
        "match_type": data.get("matchType"),
        "confidence": data.get("confidence"),
        "kingdom": data.get("kingdom"),
        "tax_class": data.get("class"),
        "family": data.get("family"),
    }


def iucn_category(species_key: int) -> Optional[Dict[str, Any]]:
    data = get_json(f"{_base()}/species/{species_key}/iucnRedListCategory")
    if not data:
        return None
    return {
        "category": normalize_category(data.get("code") or data.get("category")),
        "iucn_taxon_id": data.get("iucnTaxonID"),
    }


def vernacular_names(species_key: int, language: str = "spa") -> List[str]:
    data = get_json(f"{_base()}/species/{species_key}/vernacularNames", {"limit": 50}) or {}
    names = [v["vernacularName"] for v in data.get("results", []) if v.get("language") == language]
    return list(dict.fromkeys(names))


def find_image(species_key: Optional[int], scientific_name: str, country: Optional[str]) -> Optional[dict]:
    """Lógica de tres niveles (Lección 3.2): foto en el país → foto global → None."""
    base_params: Dict[str, Any] = {"mediaType": "StillImage", "limit": 5}
    if species_key:
        base_params["taxonKey"] = species_key
    else:
        base_params["scientificName"] = scientific_name
    for extra in ({"country": country} if country else None, {}):
        if extra is None:
            continue
        data = get_json(f"{_base()}/occurrence/search", {**base_params, **extra}) or {}
        for rec in data.get("results", []):
            for m in rec.get("media", []):
                url = m.get("identifier")
                if url and (m.get("type") in (None, "StillImage")):
                    return {
                        "url": url,
                        "author": m.get("rightsHolder") or m.get("creator") or rec.get("recordedBy"),
                        "license": m.get("license"),
                        "source": "GBIF",
                        "occurrence": f"https://www.gbif.org/occurrence/{rec.get('key')}",
                    }
    return None


def species_yearly_facets(species_key: int, country: Optional[str] = None) -> Dict[str, Any]:
    """Facetas YEAR y STATE_PROVINCE en una sola llamada (Lección 3.2, sección 4.3)."""
    params: Dict[str, Any] = {
        "taxonKey": species_key,
        "hasCoordinate": "true",
        "limit": 0,
        "facet": ["YEAR", "STATE_PROVINCE"],
        "facetLimit": 300,
    }
    if country:
        params["country"] = country
    data = get_json(f"{_base()}/occurrence/search", params) or {}
    out: Dict[str, Any] = {"count": data.get("count", 0), "year": {}, "state_province": {}}
    for facet in data.get("facets", []):
        key = "year" if facet["field"] == "YEAR" else "state_province"
        out[key] = {c["name"]: c["count"] for c in facet.get("counts", [])}
    return out


def iter_occurrences_in_geometry(
    wkt: str,
    predicates: Dict[str, Any],
    max_records: int,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Iterator[List[dict]]:
    """Recorre /occurrence/search por páginas dentro de un WKT (modo rápido sin credenciales)."""
    max_records = min(max_records, SEARCH_HARD_LIMIT)
    params: Dict[str, Any] = {
        "geometry": wkt,
        "hasCoordinate": "true",
        "hasGeospatialIssue": "false",
        "occurrenceStatus": predicates.get("occurrence_status") or "PRESENT",
        "limit": PAGE_SIZE,
    }
    ys, ye = predicates.get("year_start"), predicates.get("year_end")
    if ys or ye:
        params["year"] = f"{ys or '*'},{ye or '*'}"
    if predicates.get("kingdom_keys"):
        params["kingdomKey"] = predicates["kingdom_keys"]
    if predicates.get("max_coordinate_uncertainty_m") is not None:
        params["coordinateUncertaintyInMeters"] = f"0,{predicates['max_coordinate_uncertainty_m']}"

    offset, total = 0, None
    while offset < max_records:
        data = get_json(f"{_base()}/occurrence/search", {**params, "offset": offset})
        if not data:
            break
        total = data.get("count", 0) if total is None else total
        results = data.get("results", [])
        if not results:
            break
        yield results
        offset += len(results)
        if progress:
            progress(offset, min(total or 0, max_records))
        if data.get("endOfRecords"):
            break
    logger.info(f"Modo rápido GBIF: {offset:,} de {total or 0:,} registros disponibles en el ROI")
