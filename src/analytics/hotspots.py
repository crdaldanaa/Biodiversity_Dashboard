"""Hotspots estadísticos Getis-Ord Gi* sobre la grilla (vecindad reina 3×3 incluyendo la celda)."""
import numpy as np
import pandas as pd

from src.analytics.base import AnalysisContext, Indicator, register

BINS = [(-np.inf, -2.58, -3), (-2.58, -1.96, -2), (-1.96, -1.65, -1), (-1.65, 1.65, 0),
        (1.65, 1.96, 1), (1.96, 2.58, 2), (2.58, np.inf, 3)]
LABELS = {3: "Hotspot 99%", 2: "Hotspot 95%", 1: "Hotspot 90%", 0: "No significativo",
          -1: "Coldspot 90%", -2: "Coldspot 95%", -3: "Coldspot 99%"}


def gi_star(cells: pd.DataFrame, col: str) -> pd.Series:
    vals = cells.set_index(["ix", "iy"])[col].astype(float)
    n = len(vals)
    if n < 9 or vals.std() == 0:
        return pd.Series(0.0, index=cells.index)
    xbar, s = vals.mean(), np.sqrt((vals ** 2).mean() - vals.mean() ** 2)
    lookup = vals.to_dict()
    z = []
    for ix, iy in zip(cells["ix"], cells["iy"]):
        neigh = [lookup[(ix + dx, iy + dy)] for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (ix + dx, iy + dy) in lookup]
        wsum = len(neigh)
        num = sum(neigh) - xbar * wsum
        den = s * np.sqrt((n * wsum - wsum ** 2) / (n - 1))
        z.append(num / den if den else 0.0)
    return pd.Series(z, index=cells.index)


def classify(z: pd.Series) -> pd.Series:
    out = pd.Series(0, index=z.index)
    for lo, hi, k in BINS:
        out[(z > lo) & (z <= hi)] = k
    return out


@register
class Hotspots(Indicator):
    id = "hotspots"
    title = "Hotspots estadísticos (Gi*)"
    group = "espacial"
    order = 96
    requires = ("spatial_grid",)
    description = "Agrupamientos significativos de riqueza y de registros (Getis-Ord Gi*)."

    def compute(self, ctx: AnalysisContext) -> dict:
        cells = ctx.shared["grid_cells"]
        out = {}
        for col, key in (("species", "richness"), ("records", "records"), ("threatened_species", "threatened")):
            z = gi_star(cells, col)
            cells[f"gi_{key}"] = z.round(3)
            cells[f"hot_{key}"] = classify(z)
            vc = cells[f"hot_{key}"].value_counts()
            out[key] = [{"class": int(k), "label": LABELS[k], "cells": int(vc.get(k, 0))} for k in sorted(LABELS, reverse=True)]
        hot = int((cells["hot_richness"] >= 2).sum())
        return {
            "summary": {"richness_hotspots_95": hot,
                        "threatened_hotspots_95": int((cells["hot_threatened"] >= 2).sum())},
            "classes": out,
            "interpretation": [
                f"{hot} celdas forman hotspots de riqueza documentada con 95% de confianza o más. "
                "Superponer con vías y áreas protegidas para separar esfuerzo de muestreo de riqueza real."
            ],
        }
