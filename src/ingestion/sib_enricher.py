'''
Módulo de extensión preparado para enriquecer las especies únicas del GeoParquet
consultando APIs externas (ej. Catálogo de la Biodiversidad de Colombia / SiB / IUCN).
'''
from pathlib import Path
import duckdb
from src.utils.logger import get_logger

logger = get_logger(__name__)


def get_unique_species(parquet_path: str | Path) -> list[str]:
    con = duckdb.connect(":memory:")
    rows = con.execute(
        f"SELECT DISTINCT species FROM '{parquet_path}' WHERE species IS NOT NULL ORDER BY species"
    ).fetchall()
    con.close()
    return [r[0] for r in rows]
