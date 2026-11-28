"""G5 / G6 — Distribución de la incertidumbre espacial (histograma lineal + log y boxplot por unidad)."""
import numpy as np

from src.analytics.base import AnalysisContext, Indicator, pct, register


def five_numbers(values: np.ndarray) -> dict:
    q1, med, q3 = np.percentile(values, [25, 50, 75])
    iqr = q3 - q1
    lo = values[values >= q1 - 1.5 * iqr].min()
    hi = values[values <= q3 + 1.5 * iqr].max()
    return {"min": float(lo), "q1": float(q1), "median": float(med), "q3": float(q3), "max": float(hi),
            "n_outliers": int(((values < lo) | (values > hi)).sum())}


@register
class Uncertainty(Indicator):
    id = "uncertainty"
    title = "Incertidumbre espacial"
    group = "calidad"
    order = 60
    description = "Histograma (lineal y logarítmico) de coordinateUncertaintyInMeters y boxplot por unidad."

    def compute(self, ctx: AnalysisContext) -> dict:
        min_n = int(ctx.cfg["grid"]["min_records_boxplot"])
        max_unc = float(ctx.cfg["quality"]["max_uncertainty_m"])
        df = ctx.sql(
            """SELECT coordinateUncertaintyInMeters u, COALESCE(stateProvince,'Sin dato') unit FROM occ
               WHERE coordinateUncertaintyInMeters > 0"""
        )
        n_all = int(ctx.scalar("SELECT COUNT(*) FROM occ"))
        if df.empty:
            return {"summary": {"n_with_value": 0, "completeness_pct": 0.0},
                    "interpretation": ["Ningún registro reporta incertidumbre espacial."]}
        u = df["u"].to_numpy()
        lin_counts, lin_edges = np.histogram(u, bins=30, range=(0, np.percentile(u, 99)))
        log_edges = np.logspace(0, np.log10(u.max()) + 0.01, 30)
        log_counts, _ = np.histogram(u, bins=log_edges)

        boxes = []
        for unit, g in df.groupby("unit"):
            if len(g) >= min_n:
                boxes.append({"unit": unit, "n": int(len(g)), **five_numbers(g["u"].to_numpy())})
        boxes.sort(key=lambda b: b["median"])

        stats = {
            "n_with_value": int(len(u)), "completeness_pct": pct(len(u), n_all),
            "mean_m": float(u.mean()), "median_m": float(np.median(u)), "p90_m": float(np.percentile(u, 90)),
            "max_m": float(u.max()), "pct_over_threshold": pct(int((u > max_unc).sum()), len(u)),
            "threshold_m": max_unc,
        }
        interp = [
            f"Mediana de incertidumbre: {stats['median_m']:,.0f} m; el {stats['pct_over_threshold']:.1f}% "
            f"supera {max_unc:,.0f} m (umbral para análisis a escala regional)."
        ]
        if stats["completeness_pct"] < 40:
            interp.append(
                f"Solo el {stats['completeness_pct']:.0f}% de los registros reporta incertidumbre: limitación "
                "conocida de plataformas como eBird/iNaturalist, no necesariamente baja calidad espacial."
            )
        return {
            "summary": stats,
            "histogram_linear": {"edges": lin_edges, "counts": lin_counts},
            "histogram_log": {"edges": log_edges, "counts": log_counts},
            "boxplot": boxes,
            "interpretation": interp,
        }
