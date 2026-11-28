"""Elevación por registro a partir de un modelo digital de elevación (DEM).

Fuente por defecto: Copernicus DEM GLO-30 (resolución ~30 m, cobertura global, licencia abierta),
publicado como COG en AWS Open Data (`copernicus-dem-30m`). Las teselas de 1°×1° se descargan una
vez a `data/cache/dem/` y se reutilizan entre áreas.

Si se dispone de un raster de mayor resolución (p. ej. ALOS PALSAR 12,5 m o un DEM del IGAC),
basta con indicar `dem.local_path` en `config/settings.yaml`: se usa primero donde tenga datos y
Copernicus completa el resto.

El valor se interpola bilinealmente entre los 4 píxeles vecinos.
Nota: GLO-30 es un modelo de superficie (DSM); en bosque denso incluye parte del dosel.
"""
import math
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import rasterio
import requests
from rasterio.warp import transform as warp_transform

from src.config_loader import ROOT_DIR, get_config, get_path
from src.utils.http import USER_AGENT
from src.utils.logger import get_logger

logger = get_logger(__name__)
COPERNICUS_URL = "https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"


def _cfg() -> dict:
    return get_config()["settings"].get("dem") or {}


def _tile_name(lat0: int, lon0: int) -> str:
    ns = f"{'N' if lat0 >= 0 else 'S'}{abs(lat0):02d}"
    ew = f"{'E' if lon0 >= 0 else 'W'}{abs(lon0):03d}"
    return f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"


def _tile_path(lat0: int, lon0: int) -> Optional[Path]:
    """Descarga (una vez) la tesela Copernicus; None si no existe (océano)."""
    d = get_path("cache_dir") / "dem"
    d.mkdir(parents=True, exist_ok=True)
    name = _tile_name(lat0, lon0)
    path, missing = d / f"{name}.tif", d / f"{name}.missing"
    if path.exists():
        return path
    if missing.exists():
        return None
    url = (_cfg().get("url_template") or COPERNICUS_URL).format(name=name)
    logger.info(f"Descargando tesela DEM {name}")
    tmp = path.with_suffix(".part")
    try:
        with requests.get(url, stream=True, timeout=60, headers={"User-Agent": USER_AGENT}) as r:
            if r.status_code in (403, 404):  # sin tesela (océano)
                missing.touch()
                return None
            r.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
    except requests.RequestException as exc:  # error de red: se reintenta en la próxima ejecución
        logger.warning(f"Tesela DEM {name} no disponible: {exc}")
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(path)
    return path


def _bilinear(src: rasterio.DatasetReader, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Interpolación bilineal leyendo solo la ventana que cubre los puntos."""
    out = np.full(len(xs), np.nan)
    if not len(xs):
        return out
    inv = ~src.transform
    cols, rows = inv @ (np.asarray(xs, float), np.asarray(ys, float))
    cols, rows = np.asarray(cols) - 0.5, np.asarray(rows) - 0.5  # centro de píxel
    c0, r0 = np.floor(cols).astype(int), np.floor(rows).astype(int)
    inside = (c0 >= 0) & (r0 >= 0) & (c0 + 1 < src.width) & (r0 + 1 < src.height)
    if not inside.any():
        return out
    cmin, cmax = c0[inside].min(), c0[inside].max() + 1
    rmin, rmax = r0[inside].min(), r0[inside].max() + 1
    win = rasterio.windows.Window(cmin, rmin, cmax - cmin + 1, rmax - rmin + 1)
    arr = src.read(1, window=win, masked=True).astype("float64").filled(np.nan)
    if src.nodata is not None:
        arr[arr == src.nodata] = np.nan
    ci, ri = c0[inside] - cmin, r0[inside] - rmin
    fx, fy = cols[inside] - c0[inside], rows[inside] - r0[inside]
    v = (arr[ri, ci] * (1 - fx) * (1 - fy) + arr[ri, ci + 1] * fx * (1 - fy)
         + arr[ri + 1, ci] * (1 - fx) * fy + arr[ri + 1, ci + 1] * fx * fy)
    out[inside] = v
    return out


def _sample_raster(path: Path, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
    with rasterio.open(path) as src:
        if src.crs and src.crs.to_epsg() != 4326:
            xs, ys = warp_transform("EPSG:4326", src.crs, lon.tolist(), lat.tolist())
            xs, ys = np.asarray(xs), np.asarray(ys)
        else:
            xs, ys = lon, lat
        return _bilinear(src, xs, ys)


def sample_elevation(lon: Iterable[float], lat: Iterable[float]) -> tuple[np.ndarray, str]:
    """Elevación (m) por punto y descripción de la fuente usada."""
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    elev = np.full(len(lon), np.nan)
    sources = []
    local = _cfg().get("local_path")
    if local:
        p = Path(local)
        p = p if p.is_absolute() else ROOT_DIR / p
        if p.exists():
            elev = _sample_raster(p, lon, lat)
            sources.append(p.name)
        else:
            logger.warning(f"DEM local no encontrado: {p}")
    todo = np.isnan(elev) & np.isfinite(lon) & np.isfinite(lat)
    if todo.any():
        lat0, lon0 = np.floor(lat[todo]).astype(int), np.floor(lon[todo]).astype(int)
        idx = np.flatnonzero(todo)
        for la, lo in sorted(set(zip(lat0.tolist(), lon0.tolist()))):
            sel = idx[(lat0 == la) & (lon0 == lo)]
            tile = _tile_path(la, lo)
            if tile is not None:
                elev[sel] = _sample_raster(tile, lon[sel], lat[sel])
        sources.append("Copernicus DEM GLO-30")
    return elev, " + ".join(sources)


def tiles_needed(bbox: tuple[float, float, float, float]) -> int:
    return (math.floor(bbox[2]) - math.floor(bbox[0]) + 1) * (math.floor(bbox[3]) - math.floor(bbox[1]) + 1)
