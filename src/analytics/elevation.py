"""Gradiente altitudinal: registros, riqueza y especies amenazadas por franja de elevación.

La elevación de cada registro se completa con un DEM (paso `elevation` del pipeline); aquí se
resume cuántos valores provienen del observador y cuántos del DEM.
"""
import pandas as pd

from src.analytics.base import AnalysisContext, Indicator, pct, register

NICE_STEPS = (50, 100, 200, 250, 500, 1000)


def band_size(lo: float, hi: float, target: int = 12) -> int:
    span = max(hi - lo, 1)
    return next((s for s in NICE_STEPS if span / s <= target), NICE_STEPS[-1])


@register
class Elevation(Indicator):
    id = "elevation"
    title = "Gradiente altitudinal"
    group = "espacial"
    order = 45
    description = "Registros, especies y amenazadas por franja de elevación (elevación reportada + DEM)."

    def compute(self, ctx: AnalysisContext) -> dict:
        src = ctx.sql("""SELECT COALESCE(elevation_source, CASE WHEN elevation IS NOT NULL THEN 'reportada' END,
                                         'sin dato') src, COUNT(*) n FROM occ_spatial GROUP BY 1""")
        total = int(src["n"].sum())
        by_src = dict(zip(src["src"], src["n"].astype(int)))
        rng = ctx.sql("SELECT MIN(elevation) lo, MAX(elevation) hi, MEDIAN(elevation) med FROM occ_spatial "
                      "WHERE elevation BETWEEN -100 AND 6500").iloc[0]
        if pd.isna(rng["lo"]):
            return {"summary": {"records": total, "with_elevation": 0, **{f"n_{k}": v for k, v in by_src.items()}},
                    "bands": [], "interpretation": ["No hay elevación disponible para los registros."]}
        step = band_size(float(rng["lo"]), float(rng["hi"]))
        bands = ctx.sql(
            f"""SELECT CAST(FLOOR(elevation / {step}) * {step} AS INTEGER) band_from,
                       COUNT(*) records, COUNT(DISTINCT species) species
                FROM occ_spatial WHERE elevation BETWEEN -100 AND 6500 GROUP BY 1 ORDER BY 1"""
        )
        thr = set(k for k, v in ctx.threat_of("national").items() if v in ("CR", "EN", "VU")) | \
            set(k for k, v in ctx.threat_of("global").items() if v in ("CR", "EN", "VU"))
        if thr:
            ctx.con.register("thr_tbl", pd.DataFrame({"species": sorted(thr)}))
            t = ctx.sql(f"""SELECT CAST(FLOOR(elevation / {step}) * {step} AS INTEGER) band_from,
                                   COUNT(DISTINCT o.species) threatened_species
                            FROM occ_spatial o JOIN thr_tbl USING (species)
                            WHERE elevation BETWEEN -100 AND 6500 GROUP BY 1""")
            bands = bands.merge(t, on="band_from", how="left")
        bands["threatened_species"] = bands.get("threatened_species", 0)
        bands["threatened_species"] = bands["threatened_species"].fillna(0).astype(int)
        bands["band_to"] = bands["band_from"] + step
        bands["label"] = bands["band_from"].astype(str) + "–" + bands["band_to"].astype(str) + " m"
        with_elev = int(bands["records"].sum())
        peak = bands.loc[bands["species"].idxmax()]
        n_dem = by_src.get("DEM", 0)
        interp = [
            f"El {pct(with_elev, total):.1f}% de los registros tiene elevación; {n_dem:,} valores se completaron "
            "con el DEM (Copernicus GLO-30 o el raster local configurado).",
            f"Los registros van de {rng['lo']:,.0f} a {rng['hi']:,.0f} m (mediana {rng['med']:,.0f} m). "
            f"La mayor riqueza documentada está entre {int(peak['band_from']):,} y {int(peak['band_to']):,} m "
            f"({int(peak['species']):,} especies).",
        ]
        return {
            "summary": {"records": total, "with_elevation": with_elev, "pct_with_elevation": pct(with_elev, total),
                        "n_reported": by_src.get("reportada", 0), "n_dem": n_dem, "n_missing": by_src.get("sin dato", 0),
                        "elev_min": rng["lo"], "elev_max": rng["hi"], "elev_median": rng["med"], "band_m": step},
            "bands": bands,
            "interpretation": interp,
            "disclaimer": "Copernicus GLO-30 es un modelo de superficie (DSM): bajo bosque denso puede sobrestimar "
                          "la elevación del suelo en varios metros. La riqueza por franja depende del esfuerzo de muestreo.",
        }
