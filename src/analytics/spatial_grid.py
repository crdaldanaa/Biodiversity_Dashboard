"""Lección 2.3 — Grilla de conteos, densidad normalizada (registros/km²) y riqueza por celda."""
import numpy as np
import pandas as pd

from src.analytics.base import AnalysisContext, Indicator, register
from src.references.threat import THREATENED
from src.spatial.grid import auto_cell_size, build_grid


def _shannon(counts: pd.Series) -> float:
    p = counts / counts.sum()
    return float(-(p * np.log(p)).sum())


@register
class SpatialGrid(Indicator):
    id = "spatial_grid"
    title = "Grilla de densidad y riqueza"
    group = "espacial"
    order = 90
    description = "Conteos, densidad normalizada por área, riqueza y riqueza amenazada por celda."

    def compute(self, ctx: AnalysisContext) -> dict:
        size_cfg = ctx.cfg["grid"].get("cell_size_m", "auto")
        size = auto_cell_size(ctx.roi_area_km2) if str(size_cfg) == "auto" else int(size_cfg)
        grid = build_grid(ctx.roi_metric, size)
        pts = ctx.points
        cell = grid.assign(pts["x"].to_numpy(), pts["y"].to_numpy())
        cell.index = pts.index
        ctx.shared["grid"] = grid
        ctx.shared["cell_of_point"] = cell

        p = pts.assign(cell=cell).dropna(subset=["cell"])
        threat = ctx.threat_of("national")
        glob = ctx.threat_of("global")
        p["thr"] = p["species"].map(lambda s: threat.get(s) in THREATENED or glob.get(s) in THREATENED)
        agg = p.groupby("cell").agg(
            records=("gbifID", "size"),
            species=("species", "nunique"),
            unc_mean=("unc", "mean"),
            year_min=("year", "min"),
            year_max=("year", "max"),
        )
        agg["threatened_species"] = p[p["thr"]].groupby("cell")["species"].nunique()
        sh = p.dropna(subset=["species"]).groupby(["cell", "species"]).size()
        agg["shannon"] = sh.groupby(level=0).apply(_shannon)

        cells = grid.cells.merge(agg, left_on="cell_id", right_index=True, how="left")
        for c in ("records", "species", "threatened_species"):
            cells[c] = cells[c].fillna(0).astype(int)
        cells["density_km2"] = cells["records"] / cells["area_km2"]
        cells["richness_km2"] = cells["species"] / cells["area_km2"]
        ctx.shared["grid_cells"] = cells

        occ = cells[cells["records"] > 0]
        return {
            "summary": {
                "cell_size_m": size, "n_cells": int(len(cells)), "occupied_cells": int(len(occ)),
                "pct_occupied": round(len(occ) / len(cells) * 100, 1) if len(cells) else 0,
                "max_records_cell": int(cells["records"].max()) if len(cells) else 0,
                "max_species_cell": int(cells["species"].max()) if len(cells) else 0,
                "median_density_km2": float(occ["density_km2"].median()) if len(occ) else 0,
                "gini_records": _gini(cells["records"].to_numpy()),
            },
            "top_cells": occ.sort_values("species", ascending=False)
                .head(10)[["cell_id", "records", "species", "threatened_species", "density_km2"]],
            "interpretation": [
                f"Solo el {len(occ) / max(len(cells), 1) * 100:.0f}% de las celdas de {size / 1000:g} km tiene "
                "registros: las celdas vacías no implican ausencia de especies."
            ],
            "disclaimer": "Los hotspots representan concentración de registros documentados; reflejan presencia "
                          "y esfuerzo de observación, no abundancia poblacional.",
        }


def _gini(x: np.ndarray) -> float | None:
    """Gini de la distribución de registros entre celdas (0 = uniforme, 1 = concentrado)."""
    if len(x) == 0 or x.sum() == 0:
        return None
    x = np.sort(x.astype(float))
    n = len(x)
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()))
