"""Orquestación por área de interés: ingesta → enriquecimiento → análisis → artefactos web.

Modos de ingesta:
  * fast — API /occurrence/search paginada (sin credenciales, hasta 100.000 registros)
  * full — descarga asíncrona GBIF con DOI citable (requiere GBIF_USER/PWD/EMAIL)
  * zip  — reprocesa un ZIP SIMPLE_CSV ya descargado
"""
import json
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import duckdb
import geopandas as gpd
import pandas as pd

from src.analytics import AnalysisContext, run_indicators
from src.config_loader import get_config, get_path
from src.ingestion import gbif_api
from src.ingestion.gbif_client import request_and_download_gbif
from src.processing.duckdb_engine import (
    process_gbif_zip_with_duckdb, process_records_parquet_with_duckdb, records_to_parquet,
)
from src.processing.cleaning import clean_occurrences
from src.services import media
from src.services.enrichment import enrich_species
from src.spatial import dem
from src.spatial.roi_handler import prepare_roi_for_gbif
from src.spatial.roi_io import choose_metric_crs, save_roi
from src.utils.logger import get_logger
from src.workspaces.workspace import Workspace, create_workspace, get_workspace, now_iso

logger = get_logger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pipeline")
STEPS = ("ingest", "clean", "elevation", "enrich", "analyze")
GRID_COLUMNS = [
    "cell_id", "records", "species", "threatened_species", "area_km2", "density_km2", "richness_km2",
    "shannon", "unc_mean", "year_min", "year_max", "amenaza_raw", "score_amenaza", "score_densidad",
    "score_calidad", "danger_index", "danger_class", "gi_richness", "hot_richness", "gi_records",
    "hot_records", "gi_threatened", "hot_threatened",
]


def new_workspace(gdf: gpd.GeoDataFrame, name: str, mode: str, options: Optional[dict] = None) -> Workspace:
    options = options or {}
    settings = get_config()["settings"]
    metric_crs = choose_metric_crs(gdf, settings["project"].get("metric_crs"))
    ws = create_workspace(name, mode=mode, options=options, metric_crs=metric_crs)
    roi_info = save_roi(gdf, ws.roi_gpkg, ws.path("roi.geojson"))
    area = float(gdf.to_crs(metric_crs).geometry.union_all().area / 1e6)
    ws.update_meta(roi=roi_info, area_km2=round(area, 3))
    return ws


def submit(ws_id: str, steps: Iterable[str] = STEPS) -> None:
    ws = get_workspace(ws_id)
    if ws:
        ws.set_status(state="queued", progress=0, log=f"En cola: {', '.join(steps)}")
    _executor.submit(run, ws_id, tuple(steps))


def run(ws_id: str, steps: Iterable[str] = STEPS) -> None:
    ws = get_workspace(ws_id)
    if ws is None:
        return
    steps = [s for s in STEPS if s in steps]
    weights = {"ingest": 0.38, "clean": 0.02, "elevation": 0.08, "enrich": 0.32, "analyze": 0.20}
    done = sum(weights[s] for s in STEPS if s not in steps and STEPS.index(s) < STEPS.index(steps[0]))
    ws.set_status(state="running", started_at=now_iso(), error=None)
    try:
        for step in steps:
            span = weights[step]

            def prog(frac: float, msg: Optional[str] = None, _b=done, _s=span, _step=step) -> None:
                ws.set_status(step=_step, progress=round(min(_b + _s * frac, 0.999), 4), message=msg)

            ws.set_status(step=step, log=f"Inicio: {step}")
            {"ingest": _ingest, "clean": _clean, "elevation": _elevation, "enrich": _enrich, "analyze": _analyze}[step](ws, prog)
            done += span
            ws.set_status(progress=round(done, 4), log=f"Completado: {step}")
        ws.set_status(state="done", progress=1.0, step=None, message="Análisis completo", finished_at=now_iso())
    except Exception as exc:
        logger.error(f"Pipeline {ws_id} falló: {exc}\n{traceback.format_exc()}")
        ws.set_status(state="error", error=str(exc), log=f"Error: {exc}")


# --- Pasos ---------------------------------------------------------------------------------------
def _ingest(ws: Workspace, prog) -> None:
    cfg = get_config()
    settings, meta = cfg["settings"], ws.meta
    mode, opts = meta["mode"], meta.get("options") or {}
    preds = {**cfg["predicates"], **{k: v for k, v in opts.items() if k in ("year_start", "year_end") and v}}
    wkt, source_crs = prepare_roi_for_gbif(
        ws.roi_gpkg, layer="roi", tolerance=settings["spatial"]["simplify_tolerance"],
        max_wkt_length=settings["spatial"]["max_wkt_length"],
    )
    interim = get_path("interim_dir")
    if mode == "fast":
        max_rec = int(opts.get("max_records") or settings["gbif"]["fast_mode_max_records"])
        records: list = []
        for page in gbif_api.iter_occurrences_in_geometry(
            wkt, preds, max_rec, progress=lambda d, t: prog(d / max(t, 1) * 0.9, f"GBIF: {d:,} / {t:,} registros")
        ):
            records.extend(page)
        raw = records_to_parquet(records, ws.path("raw_records.parquet"))
        total = process_records_parquet_with_duckdb(raw, ws.roi_gpkg, "roi", ws.occurrences, settings["duckdb"], interim)
        raw.unlink(missing_ok=True)
        download = {"source": "gbif_search_api", "records_requested": max_rec, "accessed": now_iso()}
    else:
        if mode == "zip":
            zip_path = Path(opts["zip_path"])
            download = {"source": "local_zip", "zip_path": str(zip_path)}
        else:
            prog(0.05, "Solicitando descarga asíncrona a GBIF (puede tardar varios minutos)...")
            zip_path, download = request_and_download_gbif(wkt, preds, cfg["gbif_auth"], get_path("raw_dir"))
        prog(0.6, "Recortando al área de interés con DuckDB Spatial...")
        total = process_gbif_zip_with_duckdb(zip_path, ws.roi_gpkg, "roi", source_crs, ws.occurrences,
                                             settings["duckdb"], interim)
    if total == 0:
        raise RuntimeError("No hay registros GBIF dentro del área de interés con los filtros actuales.")
    ws.path("occurrences_raw.parquet").unlink(missing_ok=True)  # la depuración parte de esta descarga
    ws.update_meta(total_records=total, gbif_download=download, query_wkt_length=len(wkt))
    prog(1.0, f"{total:,} registros dentro del área de interés")


def _clean(ws: Workspace, prog) -> None:
    """Quita duplicados, tipos de registro excluidos y registros sin año o fuera de rango; marca los de
    incertidumbre alta para excluirlos de los análisis espaciales (ver `cleaning` en settings.yaml)."""
    cfg = get_config()["settings"].get("cleaning") or {}
    stats = clean_occurrences(ws.occurrences, ws.path("occurrences_raw.parquet"), cfg)
    ws.update_meta(total_records=stats["final"], cleaning=stats)
    prog(1.0, f"{stats['final']:,} registros tras la depuración (de {stats['raw']:,}); "
              f"{stats['spatial_excluded']:,} fuera de los análisis espaciales por incertidumbre")


def _elevation(ws: Workspace, prog) -> None:
    """Completa la elevación de cada registro con un DEM (Copernicus GLO-30 o raster local).

    Conserva la elevación reportada en `elevation_reported`, guarda la del DEM en `elevation_dem`
    y deja en `elevation` la reportada si existe (o la del DEM si `dem.overwrite_reported`).
    """
    cfg = get_config()["settings"].get("dem") or {}
    if not cfg.get("enabled", True):
        prog(1.0, "Elevación DEM desactivada en la configuración")
        return
    p = ws.occurrences.as_posix()
    con = duckdb.connect(":memory:")
    con.execute("INSTALL spatial; LOAD spatial;")
    try:
        cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{p}'").fetchall()}
        reported = "elevation_reported" if "elevation_reported" in cols else "elevation"
        xy = con.execute(f"SELECT DISTINCT lon, lat FROM '{p}' WHERE lon IS NOT NULL AND lat IS NOT NULL").df()
        n_tiles = dem.tiles_needed((xy.lon.min(), xy.lat.min(), xy.lon.max(), xy.lat.max()))
        prog(0.1, f"Muestreando DEM en {len(xy):,} ubicaciones ({n_tiles} teselas de 1°)...")
        xy["elevation_dem"], source = dem.sample_elevation(xy["lon"], xy["lat"])
        xy["elevation_dem"] = xy["elevation_dem"].round(1)
        con.register("dem_xy", xy)
        drop = [c for c in ("elevation", "elevation_reported", "elevation_dem", "elevation_source") if c in cols]
        main = (f"COALESCE(d.elevation_dem, TRY_CAST(o.{reported} AS DOUBLE))" if cfg.get("overwrite_reported")
                else f"COALESCE(TRY_CAST(o.{reported} AS DOUBLE), d.elevation_dem)")
        tmp = ws.path("occurrences.tmp.parquet")
        con.execute(f"""COPY (
            SELECT o.* EXCLUDE ({', '.join(drop)}),
                   TRY_CAST(o.{reported} AS DOUBLE) AS elevation_reported,
                   d.elevation_dem,
                   {main} AS elevation,
                   CASE WHEN o.{reported} IS NOT NULL {'AND d.elevation_dem IS NULL' if cfg.get('overwrite_reported') else ''}
                        THEN 'reportada' WHEN d.elevation_dem IS NOT NULL THEN 'DEM' END AS elevation_source
            FROM '{p}' o LEFT JOIN dem_xy d ON o.lon = d.lon AND o.lat = d.lat
        ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
        stats = con.execute(f"""SELECT COUNT(*), COUNT(elevation_reported), COUNT(elevation_dem), COUNT(elevation)
                                FROM '{tmp.as_posix()}'""").fetchone()
    finally:
        con.close()
    tmp.replace(ws.occurrences)
    total, rep, dem_n, final = stats
    ws.update_meta(elevation={"source": source, "records": total, "reported": rep, "dem": dem_n, "final": final,
                              "overwrite_reported": bool(cfg.get("overwrite_reported"))})
    prog(1.0, f"Elevación disponible en {final:,} de {total:,} registros ({rep:,} reportadas, fuente DEM: {source})")


def _enrich(ws: Workspace, prog) -> None:
    enrich_species(ws.occurrences, ws.species,
                   progress=lambda d, t: prog(d / t, f"Enriqueciendo especies: {d:,} / {t:,}"))


def _context(ws: Workspace, years: Optional[tuple] = None) -> AnalysisContext:
    settings = get_config()["settings"]
    roi = gpd.read_file(ws.roi_gpkg, layer="roi").to_crs("EPSG:4326")
    species = pd.read_parquet(ws.species) if ws.species.exists() else None
    if years is not None and species is not None:
        # Solo las especies con registros en el periodo, con sus conteos del periodo
        con = duckdb.connect(":memory:")
        try:
            n = con.execute(f"""SELECT species, COUNT(*) AS n_records, MIN(year) AS first_year, MAX(year) AS last_year
                                FROM '{ws.occurrences.as_posix()}' WHERE species IS NOT NULL AND year BETWEEN ? AND ?
                                GROUP BY 1""", list(years)).df()
        finally:
            con.close()
        keep = species.drop(columns=[c for c in ("n_records", "first_year", "last_year") if c in species])
        species = keep.merge(n, on="species", how="inner")
    return AnalysisContext(
        occurrences_path=ws.occurrences.as_posix(), roi=roi, metric_crs=ws.meta["metric_crs"],
        cfg=settings["analysis"], species=species, years=years,
        shared={"cleaning": ws.meta.get("cleaning")},
    )


def _grid_geojson(ctx: AnalysisContext) -> Optional[str]:
    if "grid_cells" not in ctx.shared:
        return None
    cells = ctx.shared["grid_cells"]
    cols = [c for c in GRID_COLUMNS if c in cells.columns]
    g = cells[cols + ["geometry"]].to_crs("EPSG:4326")
    g["geometry"] = g.geometry.simplify(0.00001)
    return g.to_json(drop_id=True, na="null")


def _analyze(ws: Workspace, prog) -> None:
    ctx = _context(ws)
    species = ctx.species
    results = run_indicators(ctx, progress=lambda i, n, t: prog(i / n * 0.85, f"Calculando: {t}"))
    ws.write_json("analysis.json", {"generated_at": now_iso(), "indicators": results})
    grid = _grid_geojson(ctx)
    if grid:
        ws.grid.write_text(grid, encoding="utf-8")
    # Los análisis por periodo en caché quedan obsoletos
    for f in ws.path("periods").glob("*") if ws.path("periods").exists() else []:
        f.unlink(missing_ok=True)

    if species is not None and "species_metrics" in ctx.shared:
        metrics = ctx.shared["species_metrics"].drop(columns=["n_records"], errors="ignore")
        species = species.drop(columns=[c for c in metrics.columns if c != "species" and c in species], errors="ignore")
        species.merge(metrics, on="species", how="left").to_parquet(ws.species, index=False)

    prog(0.9, "Preparando fotos y paletas de color de las especies destacadas...")
    _prefetch_media(ws, limit=96)


def _prefetch_media(ws: Workspace, limit: int) -> None:
    if not ws.species.exists():
        return
    sp = pd.read_parquet(ws.species)
    thr = sp["threat_national"].isin(["CR", "EN", "VU"]) | sp["threat_global"].isin(["CR", "EN", "VU"])
    top = pd.concat([sp[thr], sp.sort_values("n_records", ascending=False)]).drop_duplicates("species").head(limit)
    with ThreadPoolExecutor(max_workers=int(get_config()["settings"]["http"]["max_workers"])) as pool:
        list(pool.map(lambda r: _safe_media(r), top.to_dict("records")))


def _safe_media(r: Dict[str, Any]) -> None:
    r = {k: (None if not isinstance(v, (list, dict)) and pd.isna(v) else v) for k, v in r.items()}
    try:
        media.get_media(
            r["species"], int(r["gbif_key"]) if r.get("gbif_key") else None, r.get("image_url"),
            {"author": r.get("image_author"), "license": r.get("image_license"), "source": r.get("image_source")},
            r.get("threat_national") or r.get("threat_global"),
        )
    except Exception as exc:
        logger.warning(f"Media {r['species']}: {exc}")


def load_analysis(ws: Workspace) -> Dict[str, Any]:
    return json.loads(ws.analysis.read_text(encoding="utf-8")) if ws.analysis.exists() else {}


# --- Análisis por periodo (bajo demanda, en caché) ------------------------------------------------
PERIOD_CACHE_VERSION = 3  # súbelo si cambia el cálculo por periodo para invalidar la caché
_PERIOD_LOCKS: Dict[str, threading.Lock] = {}
_PERIOD_LOCKS_GUARD = threading.Lock()


def period_bounds(ws: Workspace, year_from: Optional[int], year_to: Optional[int]) -> Optional[tuple]:
    """Normaliza el periodo pedido a los años con datos. None si cubre toda la serie (= análisis base)."""
    if not year_from and not year_to:
        return None
    temporal = (load_analysis(ws).get("indicators", {}).get("temporal") or {}).get("data", {}).get("summary", {})
    lo, hi = temporal.get("year_min"), temporal.get("year_max")
    y0, y1 = int(year_from or lo or 0), int(year_to or hi or 9999)
    if y0 > y1:
        y0, y1 = y1, y0
    if lo is not None and hi is not None and y0 <= lo and y1 >= hi:
        return None
    return (y0, y1)


def analysis_for_period(ws: Workspace, years: Optional[tuple]) -> Dict[str, Any]:
    """Indicadores y grilla recalculados solo con los registros del periodo `years` (año0, año1).

    Se guardan en `periods/` y se invalidan cuando cambian las ocurrencias o la tabla de especies.
    """
    if years is None:
        return {**load_analysis(ws), "period": None}
    y0, y1 = years
    out_dir = ws.path("periods")
    out_dir.mkdir(exist_ok=True)
    a_path, g_path = out_dir / f"analysis_v{PERIOD_CACHE_VERSION}_{y0}_{y1}.json", out_dir / f"grid_{y0}_{y1}.geojson"
    newest = max(p.stat().st_mtime for p in (ws.occurrences, ws.species) if p.exists())
    key = f"{ws.id}:{y0}:{y1}"
    with _PERIOD_LOCKS_GUARD:
        lock = _PERIOD_LOCKS.setdefault(key, threading.Lock())
    with lock:
        if a_path.exists() and a_path.stat().st_mtime >= newest:
            return json.loads(a_path.read_text(encoding="utf-8"))
        ctx = _context(ws, years)
        if ctx.scalar("SELECT COUNT(*) FROM occ") == 0:
            payload = {"generated_at": now_iso(), "period": {"from": y0, "to": y1}, "empty": True, "indicators": {}}
        else:
            results = run_indicators(ctx)
            payload = {"generated_at": now_iso(), "period": {"from": y0, "to": y1}, "indicators": results}
            grid = _grid_geojson(ctx)
            if grid:
                g_path.write_text(grid, encoding="utf-8")
        a_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload


def grid_for_period(ws: Workspace, years: Optional[tuple]) -> Path:
    if years is None:
        return ws.grid
    analysis_for_period(ws, years)
    return ws.path("periods") / f"grid_{years[0]}_{years[1]}.geojson"
