import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin

from src.analytics import run_indicators
from src.analytics.elevation import band_size
from src.spatial import dem


@pytest.fixture()
def ramp_tif(tmp_path):
    """Raster 10×10 de 0,1° con elevación = 100·columna (gradiente oeste→este)."""
    path = tmp_path / "ramp.tif"
    arr = np.tile(np.arange(10, dtype="float32") * 100, (10, 1))
    with rasterio.open(path, "w", driver="GTiff", width=10, height=10, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(-74.0, 4.0, 0.1, 0.1), nodata=-9999) as dst:
        dst.write(arr, 1)
    return path


def test_bilinear_interpolates_between_pixel_centres(ramp_tif):
    # Centro del píxel 2 → 200 m; a medio camino entre los píxeles 2 y 3 → 250 m
    out = dem._sample_raster(ramp_tif, np.array([-73.75, -73.70, -80.0]), np.array([3.5, 3.5, 3.5]))
    assert out[0] == pytest.approx(200, abs=1e-3)
    assert out[1] == pytest.approx(250, abs=1e-3)
    assert np.isnan(out[2])  # fuera del raster


def test_local_dem_has_priority(ramp_tif, monkeypatch):
    monkeypatch.setattr(dem, "_cfg", lambda: {"local_path": str(ramp_tif)})
    monkeypatch.setattr(dem, "_tile_path", lambda *a: None)  # sin red
    elev, source = dem.sample_elevation([-73.75], [3.5])
    assert elev[0] == pytest.approx(200, abs=1e-3)
    assert "ramp.tif" in source


def test_tile_names():
    assert dem._tile_name(3, -74) == "Copernicus_DSM_COG_10_N03_00_W074_00_DEM"
    assert dem._tile_name(-1, 5) == "Copernicus_DSM_COG_10_S01_00_E005_00_DEM"


def test_band_size():
    assert band_size(165, 1542) == 200
    assert band_size(0, 300) == 50
    assert band_size(0, 5800) == 500


def test_elevation_indicator_bands(ctx):
    df = pd.read_parquet(ctx.occurrences_path)
    df["elevation"] = np.linspace(100, 1100, len(df))
    df["elevation_source"] = np.where(np.arange(len(df)) % 2, "DEM", "reportada")
    df.to_parquet(ctx.occurrences_path)
    e = run_indicators(ctx, only=["elevation"])["elevation"]["data"]
    assert e["summary"]["with_elevation"] == len(df)
    assert e["summary"]["n_dem"] == len(df) // 2
    assert sum(b["records"] for b in e["bands"]) == len(df)
