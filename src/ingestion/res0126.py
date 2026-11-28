"""Resolución 0126 de 2024 (MADS) — Listado oficial de especies silvestres amenazadas de Colombia.

Fuente oficial publicada por el SiB Colombia como checklist Darwin Core:
  IPT:  https://ipt.biodiversidad.co/sib/resource?r=especies-amenazadas-mads-2024
  GBIF: dataset 09174029-d182-442c-a12f-8013aee328d7 · DOI 10.15472/frowz3 (CC0)

El DwC-A se descarga una sola vez y se materializa como Parquet en data/reference/.
"""
import io
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from src.config_loader import get_config, get_path
from src.references.threat import normalize_category
from src.utils.http import get_bytes
from src.utils.logger import get_logger

logger = get_logger(__name__)
PARQUET_NAME = "res0126_2024.parquet"


def _reference_path() -> Path:
    return get_path("reference_dir") / PARQUET_NAME


def canonical_binomial(name: Optional[str]) -> Optional[str]:
    if not name or not isinstance(name, str):
        return None
    parts = name.strip().split()
    return " ".join(parts[:2]).lower() if len(parts) >= 2 else None


def build_reference(force: bool = False) -> Path:
    out = _reference_path()
    if out.exists() and not force:
        return out
    url = get_config()["settings"]["sources"]["res0126"]["ipt_archive_url"]
    logger.info(f"Descargando Resolución 0126/2024 desde el IPT del SiB: {url}")
    payload = get_bytes(url, max_bytes=50_000_000)
    if not payload:
        raise RuntimeError("No fue posible descargar el DwC-A de la Resolución 0126 de 2024.")

    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        taxa = pd.read_csv(z.open("taxon.txt"), sep="\t", dtype=str, quoting=3).fillna("")
        dist = pd.read_csv(z.open("distribution.txt"), sep="\t", dtype=str, quoting=3).fillna("")

    df = taxa.merge(dist[["id", "threatStatus"]], on="id", how="left")
    df = pd.DataFrame(
        {
            "species_key": df["scientificName"].map(canonical_binomial),
            "scientific_name": df["scientificName"],
            "authorship": df["scientificNameAuthorship"],
            "rank": df["taxonRank"],
            "kingdom": df["kingdom"],
            "phylum": df["phylum"],
            "tax_class": df["class"],
            "tax_order": df["order"],
            "family": df["family"],
            "vernacular_name": df["vernacularName"],
            "threat_res0126": df["threatStatus"].map(normalize_category),
            "remarks": df["taxonRemarks"],
            "new_in_2024": df["taxonRemarks"].str.contains("Nuevo taxón incluido", na=False),
            "gbif_ref": df["taxonID"],
        }
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    logger.info(f"Resolución 0126/2024 materializada: {len(df):,} taxones → {out}")
    _lookup.cache_clear()
    return out


@lru_cache(maxsize=1)
def _lookup() -> Dict[str, dict]:
    df = pd.read_parquet(build_reference())
    # Prioriza el registro a nivel de especie sobre subespecies con el mismo binomio
    df = df.sort_values("rank").drop_duplicates("species_key", keep="first")
    return {r["species_key"]: r for r in df.to_dict("records") if r["species_key"]}


def lookup(scientific_name: str) -> Optional[dict]:
    """Devuelve la entrada de la Resolución 0126/2024 para un nombre científico, si existe."""
    key = canonical_binomial(scientific_name)
    return _lookup().get(key) if key else None


def summary() -> dict:
    df = pd.read_parquet(build_reference())
    return {
        "total": int(len(df)),
        "by_category": df["threat_res0126"].value_counts().to_dict(),
        "by_kingdom": df["kingdom"].value_counts().to_dict(),
        "doi": get_config()["settings"]["sources"]["res0126"]["doi"],
    }
