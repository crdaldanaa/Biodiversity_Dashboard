from pathlib import Path
from typing import Optional, Tuple
import duckdb
import pandas as pd


def get_connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute("INSTALL spatial; LOAD spatial;")
    return con


def load_summary_metrics(
    parquet_path: str | Path,
    kingdom: Optional[str] = None,
    year_range: Optional[Tuple[int, int]] = None,
) -> dict:
    con = get_connection()
    where_sql = _build_where_clause(kingdom, year_range)
    query = f'''
    SELECT
        COUNT(*) AS total_records,
        COUNT(DISTINCT species) AS total_species,
        COUNT(DISTINCT family) AS total_families,
        COUNT(DISTINCT datasetKey) AS total_datasets
    FROM '{Path(parquet_path).as_posix()}'
    {where_sql}
    '''
    row = con.execute(query).fetchone()
    con.close()
    return {
        "total_records": row[0],
        "total_species": row[1],
        "total_families": row[2],
        "total_datasets": row[3],
    }


def load_filter_options(parquet_path: str | Path) -> dict:
    con = get_connection()
    p = Path(parquet_path).as_posix()
    kingdoms = [
        r[0]
        for r in con.execute(
            f"SELECT DISTINCT kingdom FROM '{p}' WHERE kingdom IS NOT NULL ORDER BY kingdom"
        ).fetchall()
    ]
    min_yr, max_yr = con.execute(
        f"SELECT MIN(year), MAX(year) FROM '{p}' WHERE year IS NOT NULL"
    ).fetchone()
    con.close()
    return {"kingdoms": kingdoms, "min_year": min_yr, "max_year": max_yr}


def load_top_species(
    parquet_path: str | Path,
    kingdom: Optional[str] = None,
    year_range: Optional[Tuple[int, int]] = None,
    limit: int = 15,
) -> pd.DataFrame:
    con = get_connection()
    where_sql = _build_where_clause(kingdom, year_range)
    extra = "AND species IS NOT NULL" if where_sql else "WHERE species IS NOT NULL"
    query = f'''
    SELECT species, family, COUNT(*) AS registros
    FROM '{Path(parquet_path).as_posix()}'
    {where_sql}
    {extra}
    GROUP BY species, family
    ORDER BY registros DESC
    LIMIT {limit}
    '''
    df = con.execute(query).df()
    con.close()
    return df


def load_yearly_trend(
    parquet_path: str | Path,
    kingdom: Optional[str] = None,
    year_range: Optional[Tuple[int, int]] = None,
) -> pd.DataFrame:
    con = get_connection()
    where_sql = _build_where_clause(kingdom, year_range)
    extra = "AND year IS NOT NULL" if where_sql else "WHERE year IS NOT NULL"
    query = f'''
    SELECT year, COUNT(*) AS registros
    FROM '{Path(parquet_path).as_posix()}'
    {where_sql}
    {extra}
    GROUP BY year
    ORDER BY year
    '''
    df = con.execute(query).df()
    con.close()
    return df


def load_map_points(
    parquet_path: str | Path,
    kingdom: Optional[str] = None,
    year_range: Optional[Tuple[int, int]] = None,
    max_points: int = 25000,
) -> pd.DataFrame:
    con = get_connection()
    where_sql = _build_where_clause(kingdom, year_range)
    query = f"""
    SELECT
        species,
        scientificName,
        family,
        year,
        basisOfRecord,
        ST_X(geometry) AS lon,
        ST_Y(geometry) AS lat
    FROM '{Path(parquet_path).as_posix()}'
    {where_sql}
    USING SAMPLE {max_points} ROWS
    """
    df = con.execute(query).df()
    con.close()
    return df


def _build_where_clause(
    kingdom: Optional[str], year_range: Optional[Tuple[int, int]]
) -> str:
    clauses = []
    if kingdom and kingdom != "Todos":
        clauses.append(f"kingdom = '{kingdom}'")
    if year_range:
        clauses.append(f"year BETWEEN {year_range[0]} AND {year_range[1]}")
    return f"WHERE {' AND '.join(clauses)}" if clauses else ""
