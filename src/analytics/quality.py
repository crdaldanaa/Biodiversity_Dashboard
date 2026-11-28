"""Indicador 4 — Auditoría de calidad del dataset (Lección 1.4)."""
import pandas as pd

from src.analytics.base import AnalysisContext, Indicator, pct, register

SEVERE_COORD_ISSUES = [
    "ZERO_COORDINATE", "COORDINATE_INVALID", "COORDINATE_OUT_OF_RANGE", "PRESUMED_SWAPPED_COORDINATE",
    "PRESUMED_NEGATED_LATITUDE", "PRESUMED_NEGATED_LONGITUDE", "COUNTRY_COORDINATE_MISMATCH",
    "COORDINATE_REPROJECTION_FAILED",
]

KEY_FIELDS = {
    "lat": "Latitud", "lon": "Longitud", "year": "Año", "month": "Mes", "day": "Día",
    "species": "Especie", "stateProvince": "Departamento / provincia",
    "basisOfRecord": "Tipo de registro", "coordinateUncertaintyInMeters": "Incertidumbre espacial",
    "datasetKey": "Dataset", "recordedBy": "Registrado por", "individualCount": "Conteo individual",
    "elevation": "Elevación",
}


@register
class QualityAudit(Indicator):
    id = "quality"
    title = "Auditoría de calidad"
    group = "calidad"
    order = 20
    description = "Duplicados, coordenadas problemáticas, outliers IQR, completitud y score 0–100."

    def compute(self, ctx: AnalysisContext) -> dict:
        q = ctx.cfg["quality"]
        max_unc = float(q["max_uncertainty_m"])
        n_total = int(ctx.scalar("SELECT COUNT(*) FROM occ"))
        if n_total == 0:
            return {"summary": {"score": 0, "label": "BAJA", "n_total": 0}}

        # 4.1 Duplicados en tres niveles
        dups = ctx.sql(
            """SELECT
                 (SELECT COUNT(*) - COUNT(DISTINCT gbifID) FROM occ) AS by_id,
                 (SELECT COUNT(*) FROM (SELECT COUNT(*) c FROM occ
                    GROUP BY species, lat, lon, year, month, day HAVING c > 1)) AS st_groups,
                 (SELECT SUM(c - 1) FROM (SELECT COUNT(*) c FROM occ
                    GROUP BY species, lat, lon, year, month, day HAVING c > 1)) AS spatiotemporal,
                 (SELECT SUM(c - 1) FROM (SELECT COUNT(*) c FROM occ
                    GROUP BY species, lat, lon HAVING c > 1)) AS spatial"""
        ).iloc[0].fillna(0).astype(int).to_dict()

        # 4.2 Coordenadas problemáticas
        issue_cases = ", ".join(
            f"COUNT(*) FILTER (WHERE issue LIKE '%{i}%') AS \"{i}\"" for i in SEVERE_COORD_ISSUES
        )
        coord = ctx.sql(
            f"""SELECT
                 COUNT(*) FILTER (WHERE lat = 0 AND lon = 0) AS zero,
                 COUNT(*) FILTER (WHERE lat NOT BETWEEN -90 AND 90) AS lat_invalid,
                 COUNT(*) FILTER (WHERE lon NOT BETWEEN -180 AND 180) AS lon_invalid,
                 COUNT(*) FILTER (WHERE coordinateUncertaintyInMeters > {max_unc}) AS high_uncertainty,
                 COUNT(*) FILTER (WHERE issue LIKE '%COORDINATE_ROUNDED%') AS rounded,
                 COUNT(*) FILTER (WHERE {' OR '.join(f"issue LIKE '%{i}%'" for i in SEVERE_COORD_ISSUES)})
                    AS severe_issue,
                 {issue_cases}
               FROM occ"""
        ).iloc[0].fillna(0).astype(int).to_dict()
        coord_problems = coord["zero"] + coord["lat_invalid"] + coord["lon_invalid"] + coord["severe_issue"]
        pct_ok_coord = 100 - pct(coord_problems, n_total, 4)

        # 4.3 Outliers espaciales IQR (se marcan, no se eliminan)
        f = float(q["iqr_factor"])
        pts = ctx.sql("SELECT lat, lon FROM occ")
        bounds, mask = {}, pd.Series(False, index=pts.index)
        for c in ("lat", "lon"):
            q1, q3 = pts[c].quantile([0.25, 0.75])
            iqr = q3 - q1
            lo, hi = q1 - f * iqr, q3 + f * iqr
            bounds[c] = [round(lo, 5), round(hi, 5)]
            mask |= (pts[c] < lo) | (pts[c] > hi)
        n_outliers = int(mask.sum())

        # 4.4 Completitud con semáforo
        hi_t, mid_t = q["completeness_high"], q["completeness_medium"]
        exprs = ", ".join(f'COUNT("{c}") AS "{c}"' for c in KEY_FIELDS)
        counts = ctx.sql(f"SELECT {exprs} FROM occ").iloc[0].to_dict()
        completeness = []
        for field, label in KEY_FIELDS.items():
            p = pct(counts[field], n_total)
            completeness.append({
                "field": field, "label": label, "complete": int(counts[field]), "pct": p,
                "level": "ALTA" if p >= hi_t else ("MEDIA" if p >= mid_t else "BAJA"),
            })
        high_fields = sum(1 for c in completeness if c["level"] == "ALTA")

        # 4.5 Score (fórmula del curso: 40% coordenadas + 60% completitud)
        score = round(pct_ok_coord * 0.4 + high_fields / len(completeness) * 100 * 0.6, 1)
        label = "ALTA" if score >= 75 else ("MEDIA" if score >= 50 else "BAJA")
        n_clean = int(ctx.scalar(
            f"""SELECT COUNT(*) FROM (SELECT DISTINCT species, lat, lon, year, month, day FROM occ
                WHERE coordinateUncertaintyInMeters IS NULL OR coordinateUncertaintyInMeters <= {max_unc})"""
        ))
        top_issues = ctx.sql(
            """SELECT issue_name AS issue, COUNT(*) AS records FROM (
                 SELECT UNNEST(string_split(issue, ';')) AS issue_name FROM occ WHERE issue IS NOT NULL)
               WHERE issue_name <> '' GROUP BY 1 ORDER BY 2 DESC LIMIT 12"""
        )
        top_issues["pct"] = (top_issues["records"] / n_total * 100).round(1)

        interp = {
            "ALTA": "Dataset apto para análisis e informe. Mencionar las limitaciones encontradas, que no bloquean su uso.",
            "MEDIA": "Dataset usable con precaución. Incluir una sección de limitaciones visible en el informe.",
            "BAJA": "Dataset con problemas significativos. Revisar filtros de descarga antes de continuar.",
        }[label]
        return {
            "summary": {
                "score": score, "label": label, "n_total": n_total, "n_clean": n_clean,
                "retention_pct": pct(n_clean, n_total), "pct_ok_coordinates": round(pct_ok_coord, 2),
                "fields_high_completeness": high_fields, "fields_evaluated": len(completeness),
                "outliers_iqr": n_outliers, "max_uncertainty_m": max_unc,
            },
            "duplicates": {**dups, "pct_spatiotemporal": pct(dups["spatiotemporal"], n_total),
                           "pct_spatial": pct(dups["spatial"], n_total)},
            "coordinates": coord,
            "outliers": {"factor": f, "bounds": bounds, "n": n_outliers, "pct": pct(n_outliers, n_total)},
            "completeness": completeness,
            "top_issues": top_issues,
            "interpretation": [interp],
            "disclaimer": "El score es una referencia pedagógica (no un estándar del campo). "
                          "Los outliers se marcan pero no se eliminan: pueden ser registros genuinos.",
        }
