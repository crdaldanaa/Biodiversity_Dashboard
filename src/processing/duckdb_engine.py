"""Motor DuckDB Spatial: normaliza ocurrencias GBIF y aplica el recorte exacto por el ROI.

Dos entradas producen exactamente el mismo esquema GeoParquet:
  * ZIP SIMPLE_CSV de una descarga asíncrona de GBIF (modo completo, con DOI).
  * Registros JSON de /occurrence/search (modo rápido), ver `records_to_parquet`.
"""
import os
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb
import geopandas as gpd
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Columnas SIMPLE_CSV de GBIF que conservamos (todas se leen como VARCHAR y se tipan abajo)
CSV_COLUMNS = [
    "gbifID", "datasetKey", "occurrenceID", "kingdom", "phylum", "class", "order", "family",
    "genus", "species", "taxonRank", "scientificName", "countryCode", "stateProvince", "locality",
    "occurrenceStatus", "individualCount", "decimalLatitude", "decimalLongitude",
    "coordinateUncertaintyInMeters", "elevation", "eventDate", "day", "month", "year",
    "taxonKey", "speciesKey", "basisOfRecord", "institutionCode", "recordedBy", "license",
    "mediaType", "issue",
]

# Mapeo de campos JSON de /occurrence/search → columnas SIMPLE_CSV
_API_FIELD_MAP = {"gbifID": "key", "issue": "issues"}


def _select_sql(source_sql: str, available: set[str]) -> str:
    def col(name: str) -> str:
        return f'"{name}"' if name in available else "NULL"

    return f"""
    SELECT
        TRY_CAST({col('gbifID')} AS BIGINT) AS gbifID,
        CAST({col('datasetKey')} AS VARCHAR) AS datasetKey,
        CAST({col('occurrenceID')} AS VARCHAR) AS occurrenceID,
        NULLIF(CAST({col('kingdom')} AS VARCHAR), '') AS kingdom,
        NULLIF(CAST({col('phylum')} AS VARCHAR), '') AS phylum,
        NULLIF(CAST({col('class')} AS VARCHAR), '') AS tax_class,
        NULLIF(CAST({col('order')} AS VARCHAR), '') AS tax_order,
        NULLIF(CAST({col('family')} AS VARCHAR), '') AS family,
        NULLIF(CAST({col('genus')} AS VARCHAR), '') AS genus,
        NULLIF(CAST({col('species')} AS VARCHAR), '') AS species,
        CAST({col('taxonRank')} AS VARCHAR) AS taxonRank,
        CAST({col('scientificName')} AS VARCHAR) AS scientificName,
        CAST({col('countryCode')} AS VARCHAR) AS countryCode,
        NULLIF(CAST({col('stateProvince')} AS VARCHAR), '') AS stateProvince,
        NULLIF(CAST({col('locality')} AS VARCHAR), '') AS locality,
        TRY_CAST({col('individualCount')} AS INTEGER) AS individualCount,
        TRY_CAST({col('coordinateUncertaintyInMeters')} AS DOUBLE) AS coordinateUncertaintyInMeters,
        TRY_CAST({col('elevation')} AS DOUBLE) AS elevation,
        CAST({col('eventDate')} AS VARCHAR) AS eventDate,
        TRY_CAST({col('year')} AS INTEGER) AS year,
        TRY_CAST({col('month')} AS INTEGER) AS month,
        TRY_CAST({col('day')} AS INTEGER) AS day,
        CAST({col('taxonKey')} AS VARCHAR) AS taxonKey,
        CAST({col('speciesKey')} AS VARCHAR) AS speciesKey,
        CAST({col('basisOfRecord')} AS VARCHAR) AS basisOfRecord,
        CAST({col('institutionCode')} AS VARCHAR) AS institutionCode,
        CAST({col('recordedBy')} AS VARCHAR) AS recordedBy,
        CAST({col('license')} AS VARCHAR) AS license,
        CAST({col('mediaType')} AS VARCHAR) AS mediaType,
        CAST({col('issue')} AS VARCHAR) AS issue,
        TRY_CAST({col('decimalLongitude')} AS DOUBLE) AS lon,
        TRY_CAST({col('decimalLatitude')} AS DOUBLE) AS lat
    FROM {source_sql}
    WHERE TRY_CAST({col('decimalLatitude')} AS DOUBLE) IS NOT NULL
      AND TRY_CAST({col('decimalLongitude')} AS DOUBLE) IS NOT NULL
      AND UPPER(COALESCE(CAST({col('occurrenceStatus')} AS VARCHAR), 'PRESENT')) != 'ABSENT'
    """


def _connect(duckdb_cfg: Dict[str, Any], interim_path: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(database=":memory:")
    con.execute(f"SET memory_limit = '{duckdb_cfg.get('memory_limit', '8GB')}';")
    con.execute(f"SET threads = {int(duckdb_cfg.get('threads', 4))};")
    con.execute(f"SET temp_directory = '{interim_path.as_posix()}';")
    con.execute(
        f"SET preserve_insertion_order = {str(duckdb_cfg.get('preserve_insertion_order', False)).lower()};"
    )
    con.execute("INSTALL spatial; LOAD spatial;")
    return con


def _clip_to_roi(
    con: duckdb.DuckDBPyConnection,
    source_sql: str,
    available: set[str],
    gpkg_path: str | Path,
    layer: Optional[str],
    output_path: Path,
) -> int:
    # Reproyectar el ROI exacto a EPSG:4326 con GeoPandas para evitar inversiones de ejes en PROJ
    gdf_roi = gpd.read_file(gpkg_path, layer=layer).to_crs("EPSG:4326")
    exact_roi_wkt = gdf_roi.geometry.union_all().buffer(0).wkt
    con.execute("CREATE OR REPLACE TEMP TABLE roi AS SELECT ST_GeomFromText(?) AS geom;", [exact_roi_wkt])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Ejecutando filtrado espacial en streaming y exportando a GeoParquet...")
    con.execute(
        f"""
        COPY (
            WITH clean AS ({_select_sql(source_sql, available)})
            SELECT c.*, ST_Point(c.lon, c.lat) AS geometry
            FROM clean c, roi r
            WHERE ST_Intersects(r.geom, ST_Point(c.lon, c.lat))
        ) TO '{output_path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD);
        """
    )
    total = con.execute(f"SELECT COUNT(*) FROM '{output_path.as_posix()}'").fetchone()[0]
    logger.info(f"Exportación finalizada: {total:,} registros en {output_path}")
    return int(total)


def process_gbif_zip_with_duckdb(
    zip_path: str | Path,
    gpkg_path: str | Path,
    layer: Optional[str],
    source_crs: str,
    output_parquet: str | Path,
    duckdb_cfg: Dict[str, Any],
    interim_dir: str | Path = "data/interim",
) -> int:
    """Extrae el TSV del ZIP de GBIF y aplica filtrado + recorte ST_Intersects en streaming."""
    interim_path = Path(interim_dir)
    interim_path.mkdir(parents=True, exist_ok=True)

    logger.info(f"Extrayendo TSV desde {zip_path}...")
    with zipfile.ZipFile(zip_path, "r") as z:
        csv_files = [f for f in z.namelist() if f.endswith(".csv")]
        if not csv_files:
            raise FileNotFoundError(f"No se encontró ningún archivo .csv dentro de {zip_path}")
        extracted_tsv = Path(z.extract(csv_files[0], path=interim_path))

    con = _connect(duckdb_cfg, interim_path)
    try:
        source = f"""read_csv('{extracted_tsv.as_posix()}', delim='\\t', header=true, quote='',
                     auto_detect=true, all_varchar=true, ignore_errors=true)"""
        available = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()}
        return _clip_to_roi(con, source, available, gpkg_path, layer, Path(output_parquet))
    finally:
        con.close()
        if extracted_tsv.exists():
            os.remove(extracted_tsv)
            logger.info("Archivo TSV temporal eliminado.")


def records_to_parquet(records: List[dict], raw_parquet: str | Path) -> Path:
    """Convierte resultados JSON de /occurrence/search a un Parquet crudo con columnas SIMPLE_CSV."""
    rows = []
    for rec in records:
        row = {}
        for col in CSV_COLUMNS:
            value = rec.get(_API_FIELD_MAP.get(col, col))
            if col == "issue" and isinstance(value, list):
                value = ";".join(value)
            if col == "mediaType":
                value = ";".join(sorted({m.get("type", "") for m in rec.get("media", [])})) or None
            row[col] = None if value is None else str(value)
        rows.append(row)
    out = Path(raw_parquet)
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=CSV_COLUMNS).to_parquet(out, index=False)
    return out


def process_records_parquet_with_duckdb(
    raw_parquet: str | Path,
    gpkg_path: str | Path,
    layer: Optional[str],
    output_parquet: str | Path,
    duckdb_cfg: Dict[str, Any],
    interim_dir: str | Path = "data/interim",
) -> int:
    interim_path = Path(interim_dir)
    interim_path.mkdir(parents=True, exist_ok=True)
    con = _connect(duckdb_cfg, interim_path)
    try:
        source = f"read_parquet('{Path(raw_parquet).as_posix()}')"
        available = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()}
        return _clip_to_roi(con, source, available, gpkg_path, layer, Path(output_parquet))
    finally:
        con.close()
