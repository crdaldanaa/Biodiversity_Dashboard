"""Estado de amenaza: Resolución 0126/2024 (nacional) vs IUCN (global), CITES y especies exóticas."""
import pandas as pd

from src.analytics.base import AnalysisContext, Indicator, pct, register
from src.references.threat import CATEGORY_ORDER, ORDINAL_SCALE, THREATENED

COLS = ["species", "common_name", "tax_class", "family", "n_records", "threat_national", "threat_global", "cites"]


def _records(df: pd.DataFrame, limit: int = 200) -> list:
    cols = [c for c in COLS if c in df.columns]
    return df.sort_values("n_records", ascending=False)[cols].head(limit).to_dict("records")


@register
class Threats(Indicator):
    id = "threats"
    title = "Especies amenazadas"
    group = "conservacion"
    order = 85
    description = "Categorías de la Res. 0126/2024 y la IUCN, discrepancias, CITES, exóticas e invasoras."

    def compute(self, ctx: AnalysisContext) -> dict:
        sp = ctx.species
        if sp is None or sp.empty:
            return {"summary": {}, "interpretation": ["Sin enriquecimiento de especies disponible."]}
        S = len(sp)
        nat = sp["threat_national"].value_counts().reindex(CATEGORY_ORDER).dropna().astype(int)
        glo = sp["threat_global"].fillna("NE").value_counts().reindex(CATEGORY_ORDER).dropna().astype(int)
        thr_nat = sp[sp["threat_national"].isin(THREATENED)]
        thr_glo = sp[sp["threat_global"].isin(THREATENED)]

        o_nat = sp["threat_national"].map(ORDINAL_SCALE)
        o_glo = sp["threat_global"].map(ORDINAL_SCALE)
        stricter_nat = sp[(o_nat >= 2) & (o_glo.fillna(-1) < 2)]
        stricter_glo = sp[(o_glo >= 2) & (o_nat.isna())]

        total_records = int(sp["n_records"].sum())
        rec_thr = int(sp.loc[sp["threat_national"].isin(THREATENED) | sp["threat_global"].isin(THREATENED),
                             "n_records"].sum())
        out = {
            "summary": {
                "species_total": S,
                "threatened_national": int(len(thr_nat)), "threatened_global": int(len(thr_glo)),
                "pct_threatened_national": pct(len(thr_nat), S), "pct_threatened_global": pct(len(thr_glo), S),
                "records_threatened_pct": pct(rec_thr, total_records),
                "national_stricter": int(len(stricter_nat)), "global_only": int(len(stricter_glo)),
            },
            "national_by_category": nat.to_dict(),
            "global_by_category": glo.to_dict(),
            "threatened_national": _records(thr_nat),
            "threatened_global": _records(thr_glo),
            "national_stricter": _records(stricter_nat, 50),
            "global_only": _records(stricter_glo, 50),
        }
        if "cites" in sp:
            cites = sp[sp["cites"].fillna("").astype(str) != ""]
            out["cites"] = _records(cites, 100)
            out["summary"]["cites_species"] = int(len(cites))
        for flag in ("exotic", "invasive", "new_in_2024"):
            if flag in sp:
                sel = sp[sp[flag].fillna(False).astype(bool)]
                out[flag] = _records(sel, 100)
                out["summary"][f"{flag}_species"] = int(len(sel))

        interp = [
            f"{len(thr_nat):,} especies del área están amenazadas a nivel nacional (Res. 0126/2024) y "
            f"{len(thr_glo):,} a nivel global (IUCN). Sus registros suman el {out['summary']['records_threatened_pct']:.1f}% del total."
        ]
        if len(stricter_nat):
            interp.append(
                f"{len(stricter_nat):,} especies están amenazadas en Colombia pero no globalmente: la categoría "
                "global no representa la situación nacional."
            )
        out["interpretation"] = interp
        out["disclaimer"] = ("La categoría IUCN es global y puede tener años de antigüedad. Una especie LC puede "
                             "estar en declive. DD no significa 'no amenazada'.")
        return out
