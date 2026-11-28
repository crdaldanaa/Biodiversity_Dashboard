"""Workspaces: crear desde un área de interés (archivo o dibujo), estado, análisis y exportaciones."""
import json
import shutil
import tempfile
from pathlib import Path
from typing import Literal, Optional

import duckdb
import geopandas as gpd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from src.api.deps import occ_query, ready_or_409, species_df, workspace_or_404
from src.services import pipeline
from src.spatial.roi_io import SUPPORTED, read_roi_file, roi_from_geojson
from src.workspaces.workspace import delete_workspace, list_workspaces

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])
Mode = Literal["fast", "full"]


class DrawRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    geojson: dict
    mode: Mode = "fast"
    max_records: Optional[int] = Field(default=None, ge=100, le=100_000)
    year_start: Optional[int] = None
    year_end: Optional[int] = None


def _start(gdf: gpd.GeoDataFrame, name: str, mode: str, opts: dict) -> dict:
    ws = pipeline.new_workspace(gdf, name, mode, opts)
    pipeline.submit(ws.id)
    return {**ws.meta, "status": ws.status}


@router.get("")
def list_all():
    return list_workspaces()


@router.post("", status_code=202)
async def create_from_file(
    file: UploadFile = File(...),
    name: str = Form(...),
    mode: Mode = Form("fast"),
    max_records: Optional[int] = Form(None),
    year_start: Optional[int] = Form(None),
    year_end: Optional[int] = Form(None),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED:
        raise HTTPException(400, f"Formato no soportado ({ext}). Usa: {', '.join(sorted(SUPPORTED))}")
    tmp_dir = Path(tempfile.mkdtemp(prefix="upload_"))
    try:
        target = tmp_dir / f"roi{ext}"
        with target.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            gdf = read_roi_file(target)
        except Exception as exc:
            raise HTTPException(400, f"No se pudo leer el área de interés: {exc}")
        return _start(gdf, name, mode, {"max_records": max_records, "year_start": year_start, "year_end": year_end})
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/draw", status_code=202)
def create_from_drawing(req: DrawRequest):
    try:
        gdf = roi_from_geojson(req.geojson)
    except Exception as exc:
        raise HTTPException(400, f"GeoJSON inválido: {exc}")
    return _start(gdf, req.name, req.mode,
                  {"max_records": req.max_records, "year_start": req.year_start, "year_end": req.year_end})


@router.get("/{ws_id}")
def detail(ws_id: str):
    ws = workspace_or_404(ws_id)
    return {**ws.meta, "status": ws.status}


@router.get("/{ws_id}/status")
def status(ws_id: str):
    return workspace_or_404(ws_id).status


@router.post("/{ws_id}/rerun", status_code=202)
def rerun(ws_id: str, steps: str = "analyze"):
    ws = workspace_or_404(ws_id)
    wanted = [s for s in steps.split(",") if s in pipeline.STEPS]
    if not wanted:
        raise HTTPException(400, f"Pasos válidos: {pipeline.STEPS}")
    if ws.status.get("state") in ("running", "queued"):
        raise HTTPException(409, "El workspace ya tiene un proceso en curso")
    pipeline.submit(ws_id, wanted)
    return ws.status


@router.delete("/{ws_id}")
def remove(ws_id: str):
    ws = workspace_or_404(ws_id)
    if ws.status.get("state") == "running":
        raise HTTPException(409, "No se puede eliminar mientras se procesa")
    delete_workspace(ws_id)
    return {"deleted": ws_id}


@router.get("/{ws_id}/roi")
def roi(ws_id: str):
    ws = workspace_or_404(ws_id)
    return FileResponse(ready_or_409(ws, ws.path("roi.geojson")), media_type="application/geo+json")


def _period(ws, year_from: Optional[int], year_to: Optional[int]):
    ready_or_409(ws, ws.analysis)
    return pipeline.period_bounds(ws, year_from, year_to)


@router.get("/{ws_id}/grid")
def grid(ws_id: str, year_from: Optional[int] = None, year_to: Optional[int] = None):
    """Grilla de análisis; con `year_from`/`year_to` se recalcula solo con los registros del periodo."""
    ws = workspace_or_404(ws_id)
    path = pipeline.grid_for_period(ws, _period(ws, year_from, year_to))
    if not path.exists():  # periodo sin registros
        return JSONResponse({"type": "FeatureCollection", "features": []})
    return FileResponse(ready_or_409(ws, path), media_type="application/geo+json")


@router.get("/{ws_id}/analysis")
def analysis(ws_id: str, year_from: Optional[int] = None, year_to: Optional[int] = None):
    """Indicadores. Con `year_from`/`year_to` se recalculan para ese periodo (bajo demanda, en caché)."""
    ws = workspace_or_404(ws_id)
    years = _period(ws, year_from, year_to)
    if years is None:
        return FileResponse(ws.analysis, media_type="application/json")
    return pipeline.analysis_for_period(ws, years)


@router.get("/{ws_id}/analysis/{indicator}")
def analysis_one(ws_id: str, indicator: str, year_from: Optional[int] = None, year_to: Optional[int] = None):
    ws = workspace_or_404(ws_id)
    data = pipeline.analysis_for_period(ws, _period(ws, year_from, year_to)).get("indicators", {})
    if indicator not in data:
        raise HTTPException(404, f"Indicador '{indicator}' no calculado")
    return data[indicator]


@router.get("/{ws_id}/points")
def points(ws_id: str, species: Optional[str] = None, year_from: Optional[int] = None,
           year_to: Optional[int] = None, limit: int = 60000):
    """Puntos en formato columnar compacto para deck.gl: [lon, lat, year, threat, species_idx]."""
    ws = workspace_or_404(ws_id)
    where, params = ["1=1"], []
    if species:
        where.append("species = ?")
        params.append(species)
    if year_from:
        where.append("year >= ?")
        params.append(year_from)
    if year_to:
        where.append("year <= ?")
        params.append(year_to)
    limit = max(1, min(limit, 200_000))
    # USING SAMPLE se aplica antes del WHERE: filtrar primero en una subconsulta
    df = occ_query(ws, f"""SELECT * FROM (SELECT lon, lat, year, month, species FROM occ_spatial
                           WHERE {' AND '.join(where)}) USING SAMPLE reservoir({limit} ROWS)""", params)
    sp = species_df(ws).set_index("species")
    threat = sp["threat_national"].fillna(sp["threat_global"]).fillna("NE")
    names = sorted(df["species"].dropna().unique().tolist())
    idx = {n: i for i, n in enumerate(names)}
    payload = {
        "species": names,
        "threat": [threat.get(n, "NE") for n in names],
        "lon": df["lon"].round(5).tolist(), "lat": df["lat"].round(5).tolist(),
        "year": df["year"].fillna(0).astype(int).tolist(),
        "month": df["month"].fillna(0).astype(int).tolist(),
        "sp": [idx.get(s, -1) if isinstance(s, str) else -1 for s in df["species"]],
    }
    return Response(json.dumps(payload, separators=(",", ":")), media_type="application/json")


@router.get("/{ws_id}/export/{kind}")
def export(ws_id: str, kind: Literal["occurrences.csv", "species.csv", "grid.geojson", "grid.gpkg",
                                     "analysis.json", "roi.gpkg"]):
    ws = workspace_or_404(ws_id)
    stem = ws.meta.get("id", ws_id)
    if kind == "occurrences.csv":
        out = ws.path("export_occurrences.csv")
        con = duckdb.connect(":memory:")
        con.execute("INSTALL spatial; LOAD spatial;")
        con.execute(f"COPY (SELECT * EXCLUDE (geometry) FROM '{ready_or_409(ws, ws.occurrences).as_posix()}') "
                    f"TO '{out.as_posix()}' (HEADER, DELIMITER ',')")
        con.close()
        return FileResponse(out, filename=f"{stem}_ocurrencias.csv", media_type="text/csv")
    if kind == "species.csv":
        out = ws.path("export_species.csv")
        species_df(ws).to_csv(out, index=False)
        return FileResponse(out, filename=f"{stem}_especies.csv", media_type="text/csv")
    if kind == "grid.gpkg":
        out = ws.path("export_grid.gpkg")
        gpd.read_file(ready_or_409(ws, ws.grid)).to_file(out, layer="grilla", driver="GPKG")
        return FileResponse(out, filename=f"{stem}_grilla.gpkg")
    path = {"grid.geojson": ws.grid, "analysis.json": ws.analysis, "roi.gpkg": ws.roi_gpkg}[kind]
    return FileResponse(ready_or_409(ws, path), filename=f"{stem}_{kind}")


@router.get("/{ws_id}/summary-text")
def summary_text(ws_id: str):
    """Todas las interpretaciones automáticas, listas para pegar en un informe."""
    ws = workspace_or_404(ws_id)
    ind = pipeline.load_analysis(ws).get("indicators", {})
    return JSONResponse({k: {"title": v["title"], "interpretation": v.get("data", {}).get("interpretation", []),
                             "disclaimer": v.get("data", {}).get("disclaimer")} for k, v in ind.items() if v.get("ok")})
