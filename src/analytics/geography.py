"""Indicador 1 / G1 / G7 — Distribución por unidad administrativa y matriz unidad × año."""
from src.analytics.base import AnalysisContext, Indicator, pct, register


@register
class Geography(Indicator):
    id = "geography"
    title = "Distribución geográfica"
    group = "espacial"
    order = 40
    description = "Top de departamentos/provincias, concentración en el top 3 y heatmap unidad × año."

    def compute(self, ctx: AnalysisContext) -> dict:
        df = ctx.sql(
            """SELECT COALESCE(stateProvince, 'Sin dato') AS unit, COUNT(*) records,
                      COUNT(DISTINCT species) species
               FROM occ GROUP BY 1 ORDER BY 2 DESC"""
        )
        total = int(df["records"].sum())
        df["pct"] = (df["records"] / total * 100).round(2) if total else 0
        df["rank"] = range(1, len(df) + 1)
        top3 = float(df.head(3)["pct"].sum()) if total else 0.0
        mean = float(df["records"].mean()) if len(df) else 0.0

        if len(df) <= 1:
            text = "El área de interés corresponde a una sola unidad administrativa; la concentración no aplica."
        elif top3 > 70:
            text = (f"Sesgo geográfico marcado: las 3 principales unidades concentran el {top3:.0f}% de los "
                    "registros. Mencionarlo en el informe.")
        else:
            text = (f"Registros relativamente distribuidos: el top 3 representa el {top3:.0f}% del total.")

        top_units = df.head(12)["unit"].tolist()
        heat = ctx.sql(
            """SELECT COALESCE(stateProvince,'Sin dato') unit, year, COUNT(*) records FROM occ
               WHERE year IS NOT NULL GROUP BY 1, 2"""
        )
        heat = heat[heat["unit"].isin(top_units)]
        years = sorted(int(y) for y in heat["year"].unique())
        return {
            "summary": {
                "n_units": int(len(df)), "top3_pct": round(top3, 1),
                "leader": df.iloc[0]["unit"] if len(df) else None,
                "leader_pct": float(df.iloc[0]["pct"]) if len(df) else 0, "mean_records": round(mean, 1),
            },
            "units": df.head(25),
            "heatmap": {"units": top_units, "years": years,
                        "cells": heat.to_dict("records")},
            "interpretation": [text],
            "disclaimer": "El ranking refleja dónde hay más observadores activos, no necesariamente "
                          "dónde la biodiversidad es mayor.",
        }
