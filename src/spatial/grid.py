"""Grilla regular en CRS métrico recortada al ROI (equivalente a Create Fishnet + Intersect)."""
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

NICE_SIZES_M = [250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000, 100000]


def auto_cell_size(area_km2: float, target_cells: int = 1500) -> int:
    raw = np.sqrt(area_km2 * 1e6 / target_cells)
    return int(min(NICE_SIZES_M, key=lambda s: abs(np.log(s / raw))))


@dataclass
class Grid:
    cells: gpd.GeoDataFrame  # CRS métrico; columnas: cell_id, ix, iy, area_km2, geometry
    size_m: int
    origin: tuple  # (minx, miny)

    def assign(self, x: np.ndarray, y: np.ndarray) -> pd.Series:
        ix = np.floor((x - self.origin[0]) / self.size_m).astype(int)
        iy = np.floor((y - self.origin[1]) / self.size_m).astype(int)
        keys = pd.Series([f"{a}_{b}" for a, b in zip(ix, iy)])
        valid = set(self.cells["cell_id"])
        return keys.where(keys.isin(valid))


def build_grid(roi_metric: gpd.GeoDataFrame, size_m: int) -> Grid:
    geom = roi_metric.geometry.union_all()
    minx, miny, maxx, maxy = geom.bounds
    minx, miny = np.floor(minx / size_m) * size_m, np.floor(miny / size_m) * size_m
    nx, ny = int(np.ceil((maxx - minx) / size_m)), int(np.ceil((maxy - miny) / size_m))
    rows = [
        (f"{i}_{j}", i, j, box(minx + i * size_m, miny + j * size_m, minx + (i + 1) * size_m, miny + (j + 1) * size_m))
        for i in range(nx)
        for j in range(ny)
    ]
    full = gpd.GeoDataFrame(rows, columns=["cell_id", "ix", "iy", "geometry"], crs=roi_metric.crs)
    full = full[full.intersects(geom)].copy()
    full["geometry"] = full.geometry.intersection(geom)
    full = full[~full.geometry.is_empty]
    full["area_km2"] = full.geometry.area / 1e6
    full = full[full["area_km2"] > 1e-6].reset_index(drop=True)  # elimina artefactos de borde (AREA = 0)
    return Grid(cells=full, size_m=size_m, origin=(minx, miny))
