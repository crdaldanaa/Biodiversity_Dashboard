"""Enriquecimiento de especies: Resolución 0126/2024 + IUCN + Catálogo SiB + GBIF.

Corre en paralelo con caché HTTP persistente: la primera ejecución consulta las APIs,
las siguientes se resuelven desde caché en segundos.
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Optional

import duckdb
import pandas as pd

from src.config_loader import get_config
from src.ingestion import gbif_api, iucn_client, res0126, sib_catalog
from src.utils.logger import get_logger

logger = get_logger(__name__)

SPECIES_COLUMNS = [
    "species", "kingdom", "phylum", "tax_class", "tax_order", "family", "genus", "n_records",
    "gbif_key", "common_name", "common_names", "threat_national", "threat_national_source",
    "threat_global", "iucn_source", "iucn_url", "iucn_year", "cites", "exotic", "invasive",
    "new_in_2024", "res0126_remarks", "sib_id", "sib_url",
    "image_url", "image_author", "image_license", "image_source",
]


def species_table(occurrences: Path) -> pd.DataFrame:
    con = duckdb.connect(":memory:")
    df = con.execute(
        f"""SELECT species, ANY_VALUE(kingdom) kingdom, ANY_VALUE(phylum) phylum,
                   ANY_VALUE(tax_class) tax_class, ANY_VALUE(tax_order) tax_order,
                   ANY_VALUE(family) family, ANY_VALUE(genus) genus, COUNT(*) n_records
            FROM '{occurrences.as_posix()}' WHERE species IS NOT NULL GROUP BY species
            ORDER BY n_records DESC"""
    ).df()
    con.close()
    return df


def enrich_one(row: dict) -> dict:
    name = row["species"]
    out = dict(row)
    res = res0126.lookup(name)
    match = gbif_api.match_species(name)
    out["gbif_key"] = match["species_key"] if match else None
    iucn = iucn_client.get_status(name, out["gbif_key"])
    sib = sib_catalog.search(name)

    out["threat_national"] = (res or {}).get("threat_res0126") or (sib or {}).get("threat_sib_national")
    out["threat_national_source"] = (
        "Res. 0126/2024" if res else ("SiB Colombia" if out["threat_national"] else None)
    )
    out["new_in_2024"] = bool((res or {}).get("new_in_2024"))
    out["res0126_remarks"] = (res or {}).get("remarks")
    out["threat_global"] = (iucn or {}).get("category") or (sib or {}).get("threat_sib_global")
    out["iucn_source"] = (iucn or {}).get("source") or ("SiB Colombia" if out["threat_global"] else None)
    out["iucn_url"] = (iucn or {}).get("url")
    out["iucn_year"] = (iucn or {}).get("year")

    names = list((sib or {}).get("common_names") or [])
    if res and res.get("vernacular_name"):
        names = [n.strip() for n in res["vernacular_name"].split("|")] + names
    if not names and out["gbif_key"]:
        names = gbif_api.vernacular_names(out["gbif_key"])
    names = list(dict.fromkeys(n for n in names if n))
    out["common_name"] = names[0] if names else None
    out["common_names"] = json.dumps(names[:8], ensure_ascii=False)
    out["cites"] = ",".join((sib or {}).get("cites") or [])
    out["exotic"] = bool((sib or {}).get("exotic"))
    out["invasive"] = bool((sib or {}).get("invasive"))
    out["sib_id"] = (sib or {}).get("sib_id")
    out["sib_url"] = (sib or {}).get("sib_url")
    img = (sib or {}).get("image") or {}
    out["image_url"], out["image_author"] = img.get("url"), img.get("author")
    out["image_license"], out["image_source"] = img.get("license"), img.get("source")
    return out


def enrich_species(
    occurrences: Path, output: Path, progress: Optional[Callable[[int, int], None]] = None
) -> pd.DataFrame:
    base = species_table(occurrences)
    rows = base.to_dict("records")
    workers = int(get_config()["settings"]["http"].get("max_workers", 8))
    res0126.build_reference()  # asegura la referencia local antes de paralelizar
    results, done = [], 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(enrich_one, r): r for r in rows}
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except Exception as exc:  # una especie fallida no detiene el resto
                logger.warning(f"Enriquecimiento falló para {futures[fut]['species']}: {exc}")
                results.append(dict(futures[fut]))
            done += 1
            if progress and (done % 25 == 0 or done == len(rows)):
                progress(done, len(rows))
    df = pd.DataFrame(results)
    for col in SPECIES_COLUMNS:
        if col not in df:
            df[col] = None
    df = df[SPECIES_COLUMNS].sort_values("n_records", ascending=False).reset_index(drop=True)
    df["gbif_key"] = pd.to_numeric(df["gbif_key"], errors="coerce").astype("Int64")
    df["iucn_year"] = pd.to_numeric(df["iucn_year"], errors="coerce").astype("Int64")
    df.to_parquet(output, index=False)
    logger.info(f"Especies enriquecidas: {len(df):,} → {output}")
    return df
