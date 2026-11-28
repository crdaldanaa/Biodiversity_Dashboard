"""Indicador 3 — Ranking por clases, pivot clase × categoría y jerarquía taxonómica."""
import pandas as pd

from src.analytics.base import AnalysisContext, Indicator, register
from src.references.threat import CATEGORY_ORDER, THREATENED


def _pivot(sp: pd.DataFrame, col: str) -> dict:
    d = sp.assign(cat=sp[col].fillna("NE"))
    pv = pd.crosstab(d["tax_class"].fillna("Sin clase"), d["cat"])
    cats = [c for c in CATEGORY_ORDER if c in pv.columns]
    pv = pv[cats]
    pv["TOTAL"] = pv.sum(axis=1)
    threatened = pv[[c for c in cats if c in THREATENED]].sum(axis=1) if any(c in THREATENED for c in cats) else 0
    pv["threatened"] = threatened
    pv["pct_threatened"] = (pv["threatened"] / pv["TOTAL"] * 100).round(1)
    pv = pv.sort_values("TOTAL", ascending=False)
    return {"categories": cats, "rows": pv.reset_index().rename(columns={"tax_class": "class"}).to_dict("records")}


@register
class Taxonomy(Indicator):
    id = "taxonomy"
    title = "Perfil taxonómico"
    group = "biodiversidad"
    order = 70
    description = "Registros y especies por clase, % de amenazadas por clase y árbol reino→familia."

    def compute(self, ctx: AnalysisContext) -> dict:
        ranking = ctx.sql(
            """SELECT COALESCE(tax_class,'Sin clase') class, COUNT(*) records, COUNT(DISTINCT species) species,
                      COUNT(DISTINCT family) families
               FROM occ GROUP BY 1 ORDER BY 2 DESC"""
        )
        total = ranking["records"].sum()
        ranking["pct_records"] = (ranking["records"] / total * 100).round(2)
        ranking["records_per_species"] = (ranking["records"] / ranking["species"].clip(lower=1)).round(1)

        tree = ctx.sql(
            """SELECT kingdom, tax_class, tax_order, family, COUNT(DISTINCT species) species, COUNT(*) records
               FROM occ WHERE kingdom IS NOT NULL GROUP BY ALL"""
        )
        hierarchy = []
        for k, gk in tree.groupby("kingdom"):
            classes = []
            for c, gc in gk.groupby(gk["tax_class"].fillna("Sin clase")):
                orders = []
                for o, go in gc.groupby(gc["tax_order"].fillna("Sin orden")):
                    fams = [{"name": f, "value": int(r.species), "records": int(r.records)}
                            for f, r in go.set_index(go["family"].fillna("Sin familia")).iterrows()]
                    orders.append({"name": o, "value": int(go["species"].sum()), "children": fams})
                classes.append({"name": c, "value": int(gc["species"].sum()), "children": orders})
            hierarchy.append({"name": k, "value": int(gk["species"].sum()), "children": classes})

        out = {"ranking": ranking, "hierarchy": hierarchy, "top_families": ctx.sql(
            """SELECT family, tax_class class, COUNT(DISTINCT species) species, COUNT(*) records FROM occ
               WHERE family IS NOT NULL GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20""")}
        sp = ctx.species
        if sp is not None and not sp.empty:
            out["pivot_national"] = _pivot(sp, "threat_national")
            out["pivot_global"] = _pivot(sp, "threat_global")
        top = ranking.iloc[0] if len(ranking) else None
        interp = []
        if top is not None and top["pct_records"] > 60:
            interp.append(
                f"{top['class']} concentra el {top['pct_records']:.0f}% de los registros. El sesgo taxonómico "
                "de GBIF es pronunciado: más registros no significa mayor abundancia, sino más observadores dedicados."
            )
        out["interpretation"] = interp
        out["summary"] = {"n_classes": int(len(ranking)), "dominant_class": top["class"] if top is not None else None,
                          "dominant_class_pct": float(top["pct_records"]) if top is not None else 0}
        return out
