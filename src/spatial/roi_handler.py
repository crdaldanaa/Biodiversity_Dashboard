from pathlib import Path
from typing import Optional, Tuple
import geopandas as gpd
from shapely.ops import orient
from src.utils.logger import get_logger

logger = get_logger(__name__)


def prepare_roi_for_gbif(
    gpkg_path: str | Path,
    layer: Optional[str] = None,
    target_crs: str = "EPSG:4326",
    tolerance: float = 0.005,
    max_wkt_length: int = 4000,
) -> Tuple[str, str]:
    '''
    Lee un GeoPackage, reproyecta a WGS84, obtiene el CRS de origen y genera
    una cadena WKT simplificada en sentido antihorario (CCW) válida para GBIF.

    Returns:
        Tuple[str, str]: (wkt_ccw_para_api, source_crs_authority_string)
    '''
    gdf = gpd.read_file(gpkg_path, layer=layer)
    if gdf.empty:
        raise ValueError(f"La capa '{layer}' en '{gpkg_path}' está vacía.")

    if gdf.crs is None:
        raise ValueError(f"El archivo '{gpkg_path}' no tiene un CRS definido.")

    source_crs = gdf.crs.to_string()
    logger.info(f"CRS original del ROI detectado: {source_crs}")

    gdf_4326 = gdf.to_crs(target_crs)
    geom_exact = gdf_4326.geometry.union_all().buffer(0)

    # Simplificación progresiva para cumplir límites de longitud WKT de GBIF
    geom_query = geom_exact.simplify(tolerance, preserve_topology=True)
    if len(geom_query.wkt) > max_wkt_length:
        logger.warning(
            f"WKT simplificado supera {max_wkt_length} caracteres ({len(geom_query.wkt)}). "
            "Usando envolvente convexa (convex_hull) para la consulta inicial en API."
        )
        geom_query = geom_query.convex_hull

    # Regla de la mano derecha (antihorario / CCW) requerida por GBIF
    geom_ccw = orient(geom_query, sign=1.0)
    logger.info(f"WKT generado correctamente ({len(geom_ccw.wkt)} caracteres).")
    return geom_ccw.wkt, source_crs
