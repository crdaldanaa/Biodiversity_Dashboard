"""G8 — Evidencia GBIF vs amenaza (cuadrantes de priorización)."""
import numpy as np

from src.analytics.base import AnalysisContext, Indicator, register
from src.references.threat import ORDINAL_SCALE

QUADRANTS = {
    "priority": "Alta amenaza + poca evidencia → PRIORITARIO: amenazada y submonitoreada",
    "managed": "Alta amenaza + alta evidencia → documentada pero en riesgo: intensificar gestión",
    "understudied": "Baja amenaza + poca evidencia → poco registrada: posible falta de interés o acceso",
    "baseline": "Baja amenaza + alta evidencia → referencia (baseline) de monitoreo",
}


@register
class EvidenceThreat(Indicator):
    id = "evidence_threat"
    title = "Evidencia vs amenaza"
    group = "conservacion"
    order = 110
    requires = ("species_profiles",)
    description = "Scatter registros (log) × categoría ordinal con cuadrantes de priorización."

    def compute(self, ctx: AnalysisContext) -> dict:
        sp = ctx.species
        if sp is None or sp.empty:
            return {"points": [], "interpretation": ["Sin categorías de amenaza disponibles."]}
        cat = ctx.threat_of("index")
        d = sp[["species", "tax_class", "n_records"] + (["common_name"] if "common_name" in sp else [])].copy()
        d["category"] = d["species"].map(cat)
        d = d.dropna(subset=["category"])
        d["threat_ordinal"] = d["category"].map(ORDINAL_SCALE)
        d = d.dropna(subset=["threat_ordinal"])
        if d.empty:
            return {"points": [], "interpretation": ["Ninguna especie tiene categoría asignada."]}
        d["log_records"] = np.log10(d["n_records"].clip(lower=1))
        ev_thr = float(d["log_records"].median())
        hi_threat = d["threat_ordinal"] >= 2
        hi_ev = d["log_records"] > ev_thr
        d["quadrant"] = np.select(
            [hi_threat & ~hi_ev, hi_threat & hi_ev, ~hi_threat & ~hi_ev], ["priority", "managed", "understudied"],
            default="baseline",
        )
        counts = d["quadrant"].value_counts().to_dict()
        priority = d[d["quadrant"] == "priority"].sort_values(["threat_ordinal", "n_records"], ascending=[False, True])
        return {
            "summary": {"evidence_threshold_records": round(10 ** ev_thr, 1), "threat_threshold": "VU",
                        **{f"n_{k}": int(counts.get(k, 0)) for k in QUADRANTS}},
            "quadrants": QUADRANTS,
            "points": d.to_dict("records"),
            "priority_species": priority.head(30).to_dict("records"),
            "interpretation": [
                f"{counts.get('priority', 0)} especies están en el cuadrante prioritario (amenazadas y con "
                f"menos de {10 ** ev_thr:,.0f} registros): candidatas a investigación y monitoreo dirigido."
            ],
        }
