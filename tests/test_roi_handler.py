import geopandas as gpd
from shapely.geometry import Polygon
from src.spatial.roi_handler import prepare_roi_for_gbif


def test_prepare_roi_for_gbif_ccw_and_reprojection(tmp_path):
    # Polígono en EPSG:4686 (MAGNA-SIRGAS) alrededor de Bogotá
    poly = Polygon([
        (-74.15, 4.55),
        (-74.00, 4.55),
        (-74.00, 4.70),
        (-74.15, 4.70),
        (-74.15, 4.55),
    ])
    gdf = gpd.GeoDataFrame({"name": ["test_roi"]}, geometry=[poly], crs="EPSG:4686")
    gpkg_file = tmp_path / "test_roi.gpkg"
    gdf.to_file(gpkg_file, layer="roi", driver="GPKG")

    wkt_str, source_crs = prepare_roi_for_gbif(gpkg_file, layer="roi")
    assert source_crs == "EPSG:4686"
    assert wkt_str.startswith("POLYGON ((")
