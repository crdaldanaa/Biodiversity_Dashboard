"""KPIs generales del área de interés."""
from src.analytics.base import DISCLAIMER_GBIF, AnalysisContext, Indicator, pct, register
from src.references.threat import THREATENED


@register
class Overview(Indicator):
    id = "overview"
    title = "Panorama general"
    group = "resumen"
    order = 10
    description = "Cifras principales del área de interés: volumen, riqueza taxonómica y cobertura temporal."

    def compute(self, ctx: AnalysisContext) -> dict:
        row = ctx.sql(
            """SELECT COUNT(*) records,
                      COUNT(DISTINCT species) species,
                      COUNT(DISTINCT genus) genera,
                      COUNT(DISTINCT family) families,
                      COUNT(DISTINCT tax_order) orders,
                      COUNT(DISTINCT tax_class) classes,
                      COUNT(DISTINCT kingdom) kingdoms,
                      COUNT(DISTINCT datasetKey) datasets,
                      COUNT(DISTINCT institutionCode) institutions,
                      MIN(year) year_min, MAX(year) year_max,
                      COUNT(*) FILTER (WHERE mediaType ILIKE '%StillImage%') with_media,
                      COUNT(*) FILTER (WHERE species IS NULL) no_species
               FROM occ"""
        ).iloc[0].to_dict()
        area = ctx.roi_area_km2
        out = {
            **row,
            "area_km2": round(area, 2),
            "records_per_km2": round(row["records"] / area, 4) if area else None,
            "species_per_100km2": round(row["species"] / area * 100, 3) if area else None,
            "pct_with_media": pct(row["with_media"], row["records"]),
            "pct_identified_to_species": pct(row["records"] - row["no_species"], row["records"]),
        }
        sp = ctx.species
        if sp is not None and not sp.empty:
            out["threatened_national"] = int(sp["threat_national"].isin(THREATENED).sum())
            out["threatened_global"] = int(sp["threat_global"].isin(THREATENED).sum())
            out["threatened_any"] = int(
                (sp["threat_national"].isin(THREATENED) | sp["threat_global"].isin(THREATENED)).sum()
            )
            flag = lambda c: int(sp[c].fillna(False).astype(bool).sum()) if c in sp else 0  # noqa: E731
            out["cites_species"] = int(sp["cites"].fillna("").astype(bool).sum()) if "cites" in sp else 0
            out["exotic_species"] = flag("exotic")
            out["invasive_species"] = flag("invasive")
            out["new_in_res0126"] = flag("new_in_2024")
        kingdoms = ctx.sql(
            "SELECT kingdom, COUNT(*) records, COUNT(DISTINCT species) species FROM occ "
            "WHERE kingdom IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"
        )
        return {"summary": out, "kingdoms": kingdoms, "disclaimer": DISCLAIMER_GBIF}
