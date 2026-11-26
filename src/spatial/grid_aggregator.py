from pathlib import Path
import duckdb
from src.utils.logger import get_logger

logger = get_logger(__name__)


def build_spatial_grid_summary(
    parquet_path: str | Path,
    output_grid_parquet: str | Path,
    cell_size_deg: float = 0.05,
    memory_limit: str = "8GB",
) -> Path:
    """
    Agrega registros puntuales de un GeoParquet en una grilla regular usando DuckDB
    para acelerar el renderizado de mapas cuando existen millones de ocurrencias.
    """
    con = duckdb.connect(":memory:")
    con.execute(f"SET memory_limit = '{memory_limit}';")
    con.execute("INSTALL spatial; LOAD spatial;")

    query = f"""
    COPY (
        WITH binned AS (
            SELECT
                species,
                family,
                FLOOR(ST_X(geometry) / {cell_size_deg}) * {cell_size_deg} AS grid_lon,
                FLOOR(ST_Y(geometry) / {cell_size_deg}) * {cell_size_deg} AS grid_lat
            FROM '{Path(parquet_path).as_posix()}'
        )
        SELECT
            grid_lon,
            grid_lat,
            COUNT(*) AS total_records,
            COUNT(DISTINCT species) AS unique_species,
            COUNT(DISTINCT family) AS unique_families,
            ST_MakeEnvelope(
                grid_lon,
                grid_lat,
                grid_lon + {cell_size_deg},
                grid_lat + {cell_size_deg}
            ) AS geometry
        FROM binned
        GROUP BY grid_lon, grid_lat
    ) TO '{Path(output_grid_parquet).as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD);
    """
    con.execute(query)
    con.close()
    logger.info(f"Grilla agregada generada en: {output_grid_parquet}")
    return Path(output_grid_parquet)