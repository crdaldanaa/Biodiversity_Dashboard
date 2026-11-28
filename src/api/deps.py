from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd
from fastapi import HTTPException

from src.workspaces.workspace import Workspace, get_workspace


def workspace_or_404(ws_id: str) -> Workspace:
    ws = get_workspace(ws_id)
    if ws is None:
        raise HTTPException(404, f"Workspace '{ws_id}' no existe")
    return ws


def ready_or_409(ws: Workspace, path: Path) -> Path:
    if not path.exists():
        raise HTTPException(409, f"El workspace aún no tiene '{path.name}'. Estado: {ws.status.get('state')}")
    return path


@lru_cache(maxsize=16)
def _species_cached(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path)


def species_df(ws: Workspace) -> pd.DataFrame:
    p = ready_or_409(ws, ws.species)
    return _species_cached(str(p), p.stat().st_mtime)


def occ_query(ws: Workspace, sql: str, params: list | None = None) -> pd.DataFrame:
    """Consulta DuckDB sobre la vista `occ` del GeoParquet del workspace (lon/lat incluidos)."""
    p = ready_or_409(ws, ws.occurrences).as_posix()
    con = duckdb.connect(":memory:")
    try:
        cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{p}'").fetchall()}
        if {"lon", "lat"} <= cols:
            con.execute(f"CREATE VIEW occ AS SELECT * EXCLUDE (geometry) FROM '{p}'")
        else:
            con.execute("INSTALL spatial; LOAD spatial;")
            con.execute(f"CREATE VIEW occ AS SELECT * EXCLUDE (geometry), ST_X(geometry) lon, ST_Y(geometry) lat FROM '{p}'")
        # Puntos aptos para mapas (incertidumbre aceptable, ver paso `clean`)
        con.execute(f"CREATE VIEW occ_spatial AS SELECT * FROM occ {'WHERE spatial_ok' if 'spatial_ok' in cols else ''}")
        return con.execute(sql, params or []).df()
    finally:
        con.close()
