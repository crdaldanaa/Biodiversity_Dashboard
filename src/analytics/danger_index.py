"""Lección 2.4 — Mapa de peligro: índice compuesto por celda.

Índice = w_a·norm(Σ peso_cat × registros) + w_d·norm(registros/km²) + w_c·norm(1/incertidumbre_media)
Clases 1–5 por quintiles (semáforo). Instrumento didáctico: no es un índice de riesgo validado.
"""
import numpy as np
import pandas as pd

from src.analytics.base import AnalysisContext, Indicator, minmax, register

CLASS_LABELS = {0: "Sin registros", 1: "Muy bajo", 2: "Bajo", 3: "Moderado", 4: "Alto", 5: "Muy alto"}


@register
class DangerIndex(Indicator):
    id = "danger_index"
    title = "Índice compuesto de peligro"
    group = "conservacion"
    order = 95
    requires = ("spatial_grid",)
    description = "Amenaza ponderada (50%), densidad de evidencia (30%) y certeza espacial (20%) por celda."

    def compute(self, ctx: AnalysisContext) -> dict:
        dcfg = ctx.cfg["danger_index"]
        w = dcfg["weights"]
        if abs(sum(w.values()) - 1) > 1e-6:
            raise ValueError("Los pesos del índice de peligro deben sumar 1.0")
        cw = dcfg["category_weights"]
        cat = ctx.threat_of("index")

        pts = ctx.points.assign(cell=ctx.shared["cell_of_point"]).dropna(subset=["cell"])
        pts["weight"] = pts["species"].map(lambda s: cw.get(cat.get(s, "NE"), cw.get("NE", 1.0)))
        amenaza = pts.groupby("cell")["weight"].sum()

        cells: pd.DataFrame = ctx.shared["grid_cells"]
        cells["amenaza_raw"] = cells["cell_id"].map(amenaza).fillna(0.0)
        cells["calidad_raw"] = 1.0 / cells["unc_mean"].where(cells["unc_mean"] > 0)
        has = cells["records"] > 0
        sub = cells.loc[has]
        cells.loc[has, "score_amenaza"] = minmax(sub["amenaza_raw"])
        cells.loc[has, "score_densidad"] = minmax(sub["density_km2"])
        cells.loc[has, "score_calidad"] = minmax(sub["calidad_raw"])
        cells.loc[has, "danger_index"] = (
            w["amenaza"] * cells.loc[has, "score_amenaza"]
            + w["densidad"] * cells.loc[has, "score_densidad"]
            + w["calidad"] * cells.loc[has, "score_calidad"]
        )
        cells["danger_class"] = 0
        if has.sum() >= 5:
            ranks = cells.loc[has, "danger_index"].rank(method="first")
            cells.loc[has, "danger_class"] = pd.qcut(ranks, 5, labels=[1, 2, 3, 4, 5]).astype(int)
        elif has.any():
            cells.loc[has, "danger_class"] = 3

        # Contribución de cada especie al componente de amenaza (Lección 2.4, 3.1)
        contrib = pts.groupby("species").agg(records=("gbifID", "size"), weight=("weight", "first"))
        contrib["contribution"] = contrib["records"] * contrib["weight"]
        contrib["pct"] = (contrib["contribution"] / contrib["contribution"].sum() * 100).round(2)
        contrib["category"] = contrib.index.map(lambda s: cat.get(s, "NE"))
        contrib = contrib.sort_values("contribution", ascending=False).reset_index()

        dist = cells["danger_class"].value_counts().reindex(range(6), fill_value=0)
        top = cells[has].sort_values("danger_index", ascending=False).head(10)
        return {
            "summary": {
                "weights": w, "category_weights": cw,
                "threat_source_priority": dcfg.get("threat_source_priority"),
                "cells_very_high": int(dist[5]), "cells_high": int(dist[4]),
                "mean_index": float(cells.loc[has, "danger_index"].mean()) if has.any() else None,
            },
            "class_distribution": [{"class": int(k), "label": CLASS_LABELS[k], "cells": int(v),
                                    "area_km2": float(cells.loc[cells["danger_class"] == k, "area_km2"].sum())}
                                   for k, v in dist.items()],
            "top_cells": top[["cell_id", "danger_index", "score_amenaza", "score_densidad", "score_calidad",
                              "records", "species", "threatened_species"]],
            "species_contribution": contrib.head(25),
            "interpretation": [
                f"{int(dist[5])} celdas quedan en clase 5 (Muy alto): combinan especies con mayor peso de "
                "amenaza, alta densidad de registros y buena precisión espacial."
            ],
            "disclaimer": "Instrumento didáctico, no un índice de riesgo ecológico validado. Requiere "
                          "validación con expertos y datos de campo antes de usarse en decisiones.",
        }
