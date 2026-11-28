"""Resumen de la depuración aplicada antes del análisis (paso `clean` del pipeline)."""
from src.analytics.base import AnalysisContext, Indicator, pct, register

LABELS = {
    "removed_basis": "Especímenes de museo / fósiles",
    "removed_no_year": "Sin año",
    "removed_before_min": "Anteriores al año mínimo",
    "removed_after_max": "Posteriores al año máximo",
    "removed_duplicates": "Duplicados (especie + coordenada + fecha)",
}


@register
class Cleaning(Indicator):
    id = "cleaning"
    title = "Depuración de registros"
    group = "calidad"
    order = 1

    def compute(self, ctx: AnalysisContext) -> dict:
        st = ctx.shared.get("cleaning")
        if not st:
            return {"summary": {"applied": False},
                    "interpretation": ["Este workspace no tiene paso de depuración: vuelve a ejecutar 'clean'."]}
        raw = st["raw"]
        steps = [{"key": k, "label": l, "records": st[k], "pct": pct(st[k], raw)} for k, l in LABELS.items() if st.get(k)]
        crit = st.get("criteria", {})
        lim = crit.get("spatial_max_uncertainty_m")
        return {
            "summary": {"applied": True, "raw": raw, "final": st["final"], "removed": raw - st["final"],
                        "retention_pct": pct(st["final"], raw), "spatial_ok": st["spatial_ok"],
                        "spatial_excluded": st["spatial_excluded"], "max_uncertainty_m": lim,
                        "year_max": crit.get("year_max"), "year_min": crit.get("year_min")},
            "steps": steps,
            "criteria": crit,
            "interpretation": [
                f"Se descargaron {raw:,} registros y quedan {st['final']:,} ({pct(st['final'], raw)}%) tras la depuración.",
                *(f"{s['label']}: {s['records']:,} registros eliminados ({s['pct']}%)." for s in steps),
                f"{st['spatial_excluded']:,} registros con incertidumbre mayor a {lim:,.0f} m cuentan para riqueza y "
                f"temporalidad, pero no para grilla, AOO/EOO, hotspots, elevación ni mapas." if lim else
                "No se excluyen registros de los análisis espaciales por incertidumbre.",
            ],
            "disclaimer": "La descarga original se conserva en occurrences_raw.parquet; los criterios están en "
                          "config/settings.yaml (sección cleaning).",
        }
