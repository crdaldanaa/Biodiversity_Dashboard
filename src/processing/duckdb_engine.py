import os
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional
import duckdb
import geopandas as gpd
from src.utils.logger import get_logger

logger = get_logger(__name__)


def process_gbif_zip_with_duckdb(
    zip_path: str | Path,
    gpkg_path: str | Path,
    layer: Optional[str],
    source_crs: str,
    output_parquet: str | Path,
    duckdb_cfg: Dict[str, Any],
    interim_dir: str | Path = "data/interim",
) -> int:
    """
    Extrae el TSV de GBIF a disco y ejecuta filtrado tabular + cruce espacial ST_Within
    en streaming con DuckDB Spatial, exportando directamente a GeoParquet (ZSTD).
    """
    interim_path = Path(interim_dir)
    interim_path.mkdir(parents=True, exist_ok=True)
    output_path = Path(output_parquet)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Reproyectar el ROI exacto a EPSG:4326 con GeoPandas para evitar inversiones de ejes en PROJ
    gdf_roi = gpd.read_file(gpkg_path, layer=layer).to_crs("EPSG:4326")
    exact_roi_wkt = gdf_roi.geometry.union_all().buffer(0).wkt

    logger.info(f"Extrayendo TSV desde {zip_path}...")
    with zipfile.ZipFile(zip_path, "r") as z:
        csv_files = [f for f in z.namelist() if f.endswith(".csv")]
        if not csv_files:
            raise FileNotFoundError(f"No se encontró ningún archivo .csv dentro de {zip_path}")
        extracted_tsv = Path(z.extract(csv_files[0], path=interim_path))

    memory_limit = duckdb_cfg.get("memory_limit", "8GB")
    threads = duckdb_cfg.get("threads", 4)
    preserve_order = str(duckdb_cfg.get("preserve_insertion_order", False)).lower()

    con = duckdb.connect(database=":memory:")
    try:
        con.execute(f"SET memory_limit = '{memory_limit}';")
        con.execute(f"SET threads = {threads};")
        con.execute(f"SET temp_directory = '{interim_path.as_posix()}';")
        con.execute(f"SET preserve_insertion_order = {preserve_order};")
        con.execute("INSTALL spatial; LOAD spatial;")

        logger.info("Cargando geometría exacta del ROI en WGS84 (EPSG:4326) en DuckDB...")
        con.execute(
            "CREATE TEMP TABLE roi AS SELECT ST_GeomFromText(?) AS geom;",
            [exact_roi_wkt],
        )

        logger.info("Ejecutando filtrado espacial en streaming y exportando a GeoParquet...")
        query = f"""
        COPY (
            WITH gbif_clean AS (
                SELECT
                    CAST(gbifID AS BIGINT) AS gbifID,
                    CAST(datasetKey AS VARCHAR) AS datasetKey,
                    CAST(kingdom AS VARCHAR) AS kingdom,
                    CAST(phylum AS VARCHAR) AS phylum,
                    CAST("class" AS VARCHAR) AS tax_class,
                    CAST("order" AS VARCHAR) AS tax_order,
                    CAST(family AS VARCHAR) AS family,
                    CAST(genus AS VARCHAR) AS genus,
                    CAST(species AS VARCHAR) AS species,
                    CAST(taxonRank AS VARCHAR) AS taxonRank,
                    CAST(scientificName AS VARCHAR) AS scientificName,
                    TRY_CAST(decimalLongitude AS DOUBLE) AS lon,
                    TRY_CAST(decimalLatitude AS DOUBLE) AS lat,
                    TRY_CAST(coordinateUncertaintyInMeters AS DOUBLE) AS coordinateUncertaintyInMeters,
                    TRY_CAST(elevation AS DOUBLE) AS elevation,
                    CAST(eventDate AS VARCHAR) AS eventDate,
                    TRY_CAST(year AS INTEGER) AS year,
                    TRY_CAST(month AS INTEGER) AS month,
                    CAST(basisOfRecord AS VARCHAR) AS basisOfRecord,
                    CAST(institutionCode AS VARCHAR) AS institutionCode,
                    CAST(recordedBy AS VARCHAR) AS recordedBy,
                    CAST(license AS VARCHAR) AS license,
                    ST_Point(
                        TRY_CAST(decimalLongitude AS DOUBLE),
                        TRY_CAST(decimalLatitude AS DOUBLE)
                    ) AS geometry
                FROM read_csv(
                    '{extracted_tsv.as_posix()}',
                    delim = '\\t',
                    header = true,
                    quote = '',
                    auto_detect = true,
                    all_varchar = true,
                    ignore_errors = true
                )
                WHERE TRY_CAST(decimalLatitude AS DOUBLE) IS NOT NULL
                  AND TRY_CAST(decimalLongitude AS DOUBLE) IS NOT NULL
                  AND UPPER(COALESCE(occurrenceStatus, 'PRESENT')) != 'ABSENT'
            )
            SELECT g.* EXCLUDE (lon, lat)
            FROM gbif_clean g
            JOIN roi r
              ON ST_Within(g.geometry, r.geom)
        ) TO '{output_path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD);
        """
        con.execute(query)

        total_exported = con.execute(
            f"SELECT COUNT(*) FROM '{output_path.as_posix()}'"
        ).fetchone()[0]
        logger.info(f"Exportación finalizada: {total_exported:,} registros en {output_path}")
        return int(total_exported)
    finally:
        con.close()
        if extracted_tsv.exists():
            os.remove(extracted_tsv)
            logger.info("Archivo TSV temporal eliminado.")