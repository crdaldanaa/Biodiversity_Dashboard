"""G3 / G4 — Serie anual con media móvil y tendencia, estacionalidad mensual y curva de descubrimiento."""
import numpy as np

from src.analytics.base import AnalysisContext, Indicator, register

MONTHS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def linear_trend(x: np.ndarray, y: np.ndarray) -> dict:
    if len(x) < 3:
        return {"slope": None, "r2": None}
    slope, intercept = np.polyfit(x, y, 1)
    pred = slope * x + intercept
    ss_res, ss_tot = float(((y - pred) ** 2).sum()), float(((y - y.mean()) ** 2).sum())
    return {"slope": float(slope), "intercept": float(intercept),
            "r2": 1 - ss_res / ss_tot if ss_tot else None}


def pct_change_window(years: np.ndarray, counts: np.ndarray, window: int) -> float | None:
    """% de cambio de los últimos `window` años respecto a los `window` previos."""
    if len(years) == 0:
        return None
    last = years.max()
    recent = counts[(years > last - window)].sum()
    prev = counts[(years <= last - window) & (years > last - 2 * window)].sum()
    return round((recent - prev) / prev * 100, 1) if prev else None


@register
class Temporal(Indicator):
    id = "temporal"
    title = "Dinámica temporal"
    group = "temporal"
    order = 50
    description = "Registros por año con media móvil, tendencia lineal, estacionalidad y acumulación de especies."

    def compute(self, ctx: AnalysisContext) -> dict:
        tcfg = ctx.cfg["temporal"]
        w = int(tcfg["moving_average_window"])
        yearly = ctx.sql(
            """SELECT year, COUNT(*) records, COUNT(DISTINCT species) species FROM occ
               WHERE year IS NOT NULL GROUP BY 1 ORDER BY 1"""
        )
        if not yearly.empty:  # completa años sin registros con 0
            full = np.arange(yearly["year"].min(), yearly["year"].max() + 1)
            yearly = yearly.set_index("year").reindex(full, fill_value=0).rename_axis("year").reset_index()
        yearly["moving_avg"] = yearly["records"].rolling(w, center=True, min_periods=1).mean().round(2)

        # Curva de descubrimiento: especies nuevas acumuladas por año
        first = ctx.sql(
            "SELECT MIN(year) y FROM occ WHERE species IS NOT NULL AND year IS NOT NULL GROUP BY species"
        )
        disc = first["y"].value_counts().sort_index()
        yearly["new_species"] = yearly["year"].map(disc).fillna(0).astype(int)
        yearly["cumulative_species"] = yearly["new_species"].cumsum()

        trend = linear_trend(yearly["year"].to_numpy(float), yearly["records"].to_numpy(float))
        change = pct_change_window(yearly["year"].to_numpy(), yearly["records"].to_numpy(), int(tcfg["trend_years"]))

        monthly = ctx.sql(
            """SELECT month, COUNT(*) records, COUNT(DISTINCT species) species FROM occ
               WHERE month BETWEEN 1 AND 12 GROUP BY 1 ORDER BY 1"""
        ).set_index("month").reindex(range(1, 13), fill_value=0).rename_axis("month").reset_index()
        monthly["label"] = MONTHS
        total_m = monthly["records"].sum()
        peak = monthly.loc[monthly["records"].idxmax()] if total_m else None
        # Índice de estacionalidad: coeficiente de variación mensual
        cv = float(monthly["records"].std() / monthly["records"].mean()) if total_m else None

        # Matriz año × mes: el dashboard compara cualquier periodo seleccionado contra la totalidad
        ym = ctx.sql(
            """SELECT year, month, COUNT(*) records FROM occ
               WHERE year IS NOT NULL AND month BETWEEN 1 AND 12 GROUP BY 1, 2 ORDER BY 1, 2"""
        )

        weekday = ctx.sql(
            """SELECT dayofweek(TRY_CAST(year || '-' || month || '-' || day AS DATE)) dow, COUNT(*) records
               FROM occ WHERE day IS NOT NULL AND month IS NOT NULL AND year IS NOT NULL
               GROUP BY 1 HAVING dow IS NOT NULL ORDER BY 1"""
        )
        weekend_pct = (float(weekday.loc[weekday["dow"].isin([0, 6]), "records"].sum() / weekday["records"].sum() * 100)
                       if not weekday.empty else None)

        interp = []
        if change is not None:
            direction = "aumentaron" if change > 0 else "disminuyeron"
            interp.append(
                f"Los registros {direction} un {abs(change):.0f}% en los últimos {tcfg['trend_years']} años "
                "frente al periodo anterior. Una tendencia creciente casi nunca significa recuperación "
                "poblacional: suele reflejar más observadores."
            )
        if peak is not None and cv is not None:
            interp.append(
                f"El mes con más registros es {peak['label']} ({int(peak['records']):,}). "
                f"Coeficiente de variación mensual: {cv:.2f} "
                f"({'estacionalidad marcada' if cv > 0.5 else 'distribución relativamente uniforme'})."
            )
        if weekend_pct is not None and weekend_pct > 35:
            interp.append(
                f"El {weekend_pct:.0f}% de los registros fechados ocurre en fin de semana (esperado ≈ 28,6%): "
                "indicio de sesgo del observador."
            )
        return {
            "summary": {
                "year_min": int(yearly["year"].min()) if len(yearly) else None,
                "year_max": int(yearly["year"].max()) if len(yearly) else None,
                "trend_slope_per_year": trend["slope"], "trend_r2": trend["r2"],
                "pct_change_recent": change, "peak_month": peak["label"] if peak is not None else None,
                "seasonality_cv": cv, "weekend_pct": weekend_pct,
            },
            "yearly": yearly, "trend": trend, "monthly": monthly, "weekday": weekday,
            "year_month": {"year": ym["year"].astype(int).tolist(), "month": ym["month"].astype(int).tolist(),
                           "records": ym["records"].astype(int).tolist()},
            "interpretation": interp,
        }
