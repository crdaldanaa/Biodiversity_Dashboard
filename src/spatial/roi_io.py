"""Lectura de áreas de interés en múltiples formatos y selección de CRS métrico."""
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

import geopandas as gpd
from pyproj import CRS
from shapely.geometry import shape

from src.utils.logger import get_logger

logger = get_logger(__name__)
SUPPORTED = {".gpkg", ".geojson", ".json", ".kml", ".zip", ".shp", ".fgb"}


def read_roi_file(path: str | Path, layer: Optional[str] = None) -> gpd.GeoDataFrame:
    """Lee GPKG, GeoJSON, KML, FlatGeobuf o un Shapefile comprimido en ZIP."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"Formato no soportado: {ext}. Usa uno de {sorted(SUPPORTED)}")
    if ext == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="roi_"))
        with zipfile.ZipFile(p) as z:
            for member in z.namelist():
                target = (tmp / member).resolve()
                if not str(target).startswith(str(tmp.resolve())):
                    raise ValueError("ZIP con rutas no permitidas.")
            z.extractall(tmp)
        candidates = list(tmp.rglob("*.shp")) + list(tmp.rglob("*.gpkg")) + list(tmp.rglob("*.geojson"))
        if not candidates:
            raise ValueError("El ZIP no contiene .shp, .gpkg ni .geojson.")
        p = candidates[0]
    gdf = gpd.read_file(p, layer=layer) if layer else gpd.read_file(p)
    return _validate(gdf)


def roi_from_geojson(geojson: dict) -> gpd.GeoDataFrame:
    """ROI a partir de un GeoJSON (Feature, FeatureCollection o Geometry) en WGS84."""
    if geojson.get("type") == "FeatureCollection":
        gdf = gpd.GeoDataFrame.from_features(geojson["features"], crs="EPSG:4326")
    elif geojson.get("type") == "Feature":
        gdf = gpd.GeoDataFrame.from_features([geojson], crs="EPSG:4326")
    else:
        gdf = gpd.GeoDataFrame(geometry=[shape(geojson)], crs="EPSG:4326")
    return _validate(gdf)


def _validate(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.empty:
        raise ValueError("El área de interés no contiene geometrías.")
    if gdf.crs is None:
        logger.warning("ROI sin CRS; se asume EPSG:4326.")
        gdf = gdf.set_crs("EPSG:4326")
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if not all(gdf.geom_type.isin(["Polygon", "MultiPolygon"])):
        raise ValueError("El área de interés debe contener polígonos.")
    gdf["geometry"] = gdf.geometry.make_valid()
    return gdf


def choose_metric_crs(gdf: gpd.GeoDataFrame, preferred: Optional[str]) -> str:
    """Usa el CRS preferido si cubre el ROI; si no, la zona UTM del centroide."""
    g4326 = gdf.to_crs("EPSG:4326")
    minx, miny, maxx, maxy = g4326.total_bounds
    if preferred:
        aou = CRS.from_user_input(preferred).area_of_use
        if aou and aou.west <= minx and aou.east >= maxx and aou.south <= miny and aou.north >= maxy:
            return preferred
    utm = g4326.estimate_utm_crs()
    return utm.to_string() if utm else "EPSG:3857"


def save_roi(gdf: gpd.GeoDataFrame, gpkg_path: Path, geojson_path: Path) -> dict:
    gpkg_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(gpkg_path, layer="roi", driver="GPKG")
    g4326 = gdf.to_crs("EPSG:4326")
    # Versión simplificada para la web (rápida de dibujar, ~10 m de tolerancia)
    web = g4326.copy()
    web["geometry"] = web.geometry.simplify(0.0001, preserve_topology=True)
    geojson_path.write_text(json.dumps(json.loads(web.to_json(drop_id=True))), encoding="utf-8")
    minx, miny, maxx, maxy = g4326.total_bounds
    return {
        "source_crs": gdf.crs.to_string(),
        "bbox": [float(minx), float(miny), float(maxx), float(maxy)],
        "n_features": int(len(gdf)),
    }
