"""Indicador 2 / G2 — Composición por tipo de registro (basisOfRecord) y fuentes."""
from src.analytics.base import AnalysisContext, Indicator, pct, register

BASIS_LABELS = {
    "HUMAN_OBSERVATION": "Observación humana",
    "PRESERVED_SPECIMEN": "Espécimen preservado",
    "MACHINE_OBSERVATION": "Observación automática",
    "MATERIAL_SAMPLE": "Muestra de material",
    "MATERIAL_CITATION": "Cita de material",
    "OCCURRENCE": "Ocurrencia",
    "LIVING_SPECIMEN": "Espécimen vivo",
    "FOSSIL_SPECIMEN": "Fósil",
    "OBSERVATION": "Observación",
}


@register
class Composition(Indicator):
    id = "composition"
    title = "Composición de fuentes"
    group = "calidad"
    order = 30
    description = "Porcentaje por tipo de registro, dominancia y principales datasets e instituciones."

    def compute(self, ctx: AnalysisContext) -> dict:
        df = ctx.sql(
            "SELECT COALESCE(basisOfRecord,'SIN_DATO') basis, COUNT(*) records FROM occ GROUP BY 1 ORDER BY 2 DESC"
        )
        total = int(df["records"].sum())
        df["label"] = df["basis"].map(lambda b: BASIS_LABELS.get(b, b.title()))
        df["pct"] = (df["records"] / total * 100).round(2)
        df["pct_cum"] = df["pct"].cumsum().round(2)
        dom = df.iloc[0] if len(df) else None
        get = lambda b: float(df.loc[df["basis"] == b, "pct"].sum())  # noqa: E731

        interp = []
        if dom is not None and dom["pct"] >= 90:
            interp.append(
                f"El {dom['pct']:.1f}% de los registros son «{dom['label']}». Un solo tipo domina el "
                "dataset, por lo que hereda sus sesgos espacio-temporales."
            )
        if get("HUMAN_OBSERVATION") >= 50:
            interp.append(
                "Predomina la observación humana (ciencia ciudadana: eBird, iNaturalist). Hay sesgo "
                "hacia zonas accesibles y periodos de alta actividad; la tendencia temporal refleja en "
                "buena parte el crecimiento de las plataformas."
            )
        if get("PRESERVED_SPECIMEN") >= 20:
            interp.append(
                "Hay una fracción relevante de especímenes de colección: mejor precisión taxonómica, "
                "pero pueden reflejar distribuciones históricas."
            )

        datasets = ctx.sql(
            "SELECT datasetKey, COUNT(*) records, COUNT(DISTINCT species) species FROM occ "
            "GROUP BY 1 ORDER BY 2 DESC LIMIT 15"
        )
        datasets["pct"] = (datasets["records"] / total * 100).round(2)
        institutions = ctx.sql(
            "SELECT COALESCE(institutionCode,'SIN_DATO') institution, COUNT(*) records FROM occ "
            "GROUP BY 1 ORDER BY 2 DESC LIMIT 15"
        )
        n_obs = int(ctx.scalar("SELECT COUNT(DISTINCT recordedBy) FROM occ"))
        top_dataset_pct = float(datasets["pct"].iloc[0]) if len(datasets) else 0.0
        if top_dataset_pct >= 60:
            interp.append(
                f"Un solo dataset aporta el {top_dataset_pct:.0f}% de los registros: "
                "la cobertura depende de una única fuente."
            )
        return {
            "summary": {
                "dominant": dom["label"] if dom is not None else None,
                "dominant_pct": float(dom["pct"]) if dom is not None else 0,
                "n_types": int(len(df)),
                "pct_human_observation": get("HUMAN_OBSERVATION"),
                "pct_preserved_specimen": get("PRESERVED_SPECIMEN"),
                "pct_machine_observation": get("MACHINE_OBSERVATION"),
                "n_datasets": int(ctx.scalar("SELECT COUNT(DISTINCT datasetKey) FROM occ")),
                "n_observers": n_obs,
                "top_dataset_pct": top_dataset_pct,
            },
            "basis": df,
            "datasets": datasets,
            "institutions": institutions,
            "interpretation": interp,
        }
