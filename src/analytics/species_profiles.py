"""Parámetros por especie: AOO, EOO, ocupación, tendencia, fenología, elevación y rareza.

AOO (área de ocupación) usa la convención IUCN de celdas de 2×2 km. EOO (extensión de presencia)
es el polígono convexo mínimo de los registros dentro del ROI (subestima la EOO real de la especie).
"""
import numpy as np
import pandas as pd
from shapely.geometry import MultiPoint

from src.analytics.base import AnalysisContext, Indicator, register

MONTHS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _eoo_km2(xy: np.ndarray) -> float:
    uniq = np.unique(np.round(xy, 0), axis=0)
    if len(uniq) < 3:
        return 0.0
    return float(MultiPoint([tuple(p) for p in uniq]).convex_hull.area / 1e6)


@register
class SpeciesProfiles(Indicator):
    id = "species_profiles"
    title = "Parámetros por especie"
    group = "especies"
    order = 100
    requires = ("spatial_grid",)
    description = "AOO (2 km), EOO, celdas ocupadas, tendencia reciente, mes pico, elevación y rareza."

    def compute(self, ctx: AnalysisContext) -> dict:
        aoo_m = float(ctx.cfg["aoo_cell_m"])
        win = int(ctx.cfg["temporal"]["trend_years"])
        pts = ctx.points.dropna(subset=["species"]).copy()
        pts["cell"] = ctx.shared["cell_of_point"].reindex(pts.index)
        pts["aoo_cell"] = (np.floor(pts["x"] / aoo_m).astype(int).astype(str) + "_"
                           + np.floor(pts["y"] / aoo_m).astype(int).astype(str))
        extra = ctx.sql(
            """SELECT species, MIN(elevation) elev_min, MAX(elevation) elev_max,
                      MEDIAN(coordinateUncertaintyInMeters) unc_median,
                      COUNT(DISTINCT datasetKey) n_datasets,
                      AVG(CASE WHEN basisOfRecord = 'HUMAN_OBSERVATION' THEN 1 ELSE 0 END) * 100 pct_human_obs,
                      MODE(month) peak_month,
                      COUNT(DISTINCT year) n_years,
                      COUNT(*) FILTER (WHERE mediaType ILIKE '%StillImage%') n_media
               FROM occ WHERE species IS NOT NULL GROUP BY 1"""
        ).set_index("species")

        g = pts.groupby("species")
        prof = pd.DataFrame({
            "n_records": g.size(),
            "n_cells": g["cell"].nunique(),
            "aoo_km2": g["aoo_cell"].nunique() * (aoo_m / 1000) ** 2,
            "first_year": g["year"].min(),
            "last_year": g["year"].max(),
        })
        prof["eoo_km2"] = g[["x", "y"]].apply(lambda d: _eoo_km2(d.to_numpy()))
        ymax = pts["year"].max()
        recent = pts[pts["year"] > ymax - win].groupby("species").size()
        prev = pts[(pts["year"] <= ymax - win) & (pts["year"] > ymax - 2 * win)].groupby("species").size()
        prof["trend_pct"] = ((recent.reindex(prof.index, fill_value=0) - prev.reindex(prof.index))
                             / prev.reindex(prof.index) * 100).round(1)
        prof = prof.join(extra)
        n_cells_total = max(int(ctx.shared["grid_cells"].shape[0]), 1)
        prof["occupancy_pct"] = (prof["n_cells"] / n_cells_total * 100).round(2)
        prof["eoo_pct_roi"] = (prof["eoo_km2"] / ctx.roi_area_km2 * 100).clip(upper=100).round(2)
        prof["peak_month_label"] = prof["peak_month"].map(lambda m: MONTHS[int(m) - 1] if pd.notna(m) else None)
        q = prof["occupancy_pct"].quantile([0.25, 0.75])
        prof["rarity"] = np.select(
            [prof["n_records"] == 1, prof["occupancy_pct"] <= q.iloc[0], prof["occupancy_pct"] >= q.iloc[1]],
            ["Registro único", "Restringida", "Amplia"], default="Intermedia",
        )
        prof = prof.reset_index()
        ctx.shared["species_metrics"] = prof

        widest = prof.sort_values("aoo_km2", ascending=False).head(15)
        rising = prof[(prof["n_records"] >= 10) & prof["trend_pct"].notna()].sort_values("trend_pct", ascending=False)
        return {
            "summary": {
                "species": int(len(prof)),
                "single_record_species": int((prof["n_records"] == 1).sum()),
                "median_aoo_km2": float(prof["aoo_km2"].median()),
                "median_eoo_km2": float(prof["eoo_km2"].median()),
                "aoo_cell_km": aoo_m / 1000,
            },
            "rarity": prof["rarity"].value_counts().to_dict(),
            "widest": widest[["species", "n_records", "aoo_km2", "eoo_km2", "occupancy_pct"]],
            "rising": rising.head(10)[["species", "n_records", "trend_pct"]],
            "declining": rising.tail(10).iloc[::-1][["species", "n_records", "trend_pct"]],
            "disclaimer": "AOO y EOO se calculan solo con registros dentro del área de interés; son "
                          "indicadores de la evidencia local, no de la distribución global de la especie.",
        }
