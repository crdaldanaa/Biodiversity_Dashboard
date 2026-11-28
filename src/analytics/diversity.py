"""Índices de diversidad alfa, estimadores de riqueza y curvas de rarefacción/acumulación.

Importante: los conteos son *registros*, no individuos. Los índices basados en abundancia
(Shannon, Simpson, Chao1) se interpretan como diversidad de la evidencia documentada.
Chao2 usa incidencia en celdas de la grilla como unidades de muestreo (más robusto al sesgo).
"""
from math import lgamma, log, sqrt

import numpy as np
import pandas as pd

from src.analytics.base import AnalysisContext, Indicator, register


def alpha_indices(n: np.ndarray) -> dict:
    n = n[n > 0].astype(float)
    N, S = n.sum(), len(n)
    if S == 0:
        return {"S": 0, "N": 0}
    p = n / N
    H = float(-(p * np.log(p)).sum())
    simpson_d = float((n * (n - 1)).sum() / (N * (N - 1))) if N > 1 else 1.0
    F1, F2 = int((n == 1).sum()), int((n == 2).sum())
    if F2 > 0:
        chao1 = S + F1 ** 2 / (2 * F2)
        var = F2 * ((F1 / F2) ** 2 / 2 + (F1 / F2) ** 3 + (F1 / F2) ** 4 / 4)
    else:
        chao1 = S + F1 * (F1 - 1) / 2
        var = F1 * (F1 - 1) / 2 + F1 * (2 * F1 - 1) ** 2 / 4 - F1 ** 4 / (4 * chao1) if chao1 else 0
    return {
        "S": S, "N": int(N),
        "shannon_H": H, "pielou_J": H / log(S) if S > 1 else None,
        "simpson_1_minus_D": 1 - simpson_d, "inverse_simpson": float(1 / (p ** 2).sum()),
        "hill_q0": S, "hill_q1": float(np.exp(H)), "hill_q2": float(1 / (p ** 2).sum()),
        "margalef": (S - 1) / log(N) if N > 1 else None, "menhinick": S / sqrt(N),
        "berger_parker": float(p.max()),
        "singletons": F1, "doubletons": F2,
        "chao1": float(chao1), "chao1_sd": float(sqrt(max(var, 0))),
        "completeness_chao1": float(S / chao1) if chao1 else None,
        "good_coverage": float(1 - F1 / N),
    }


def rarefaction(n: np.ndarray, points: int = 40) -> list:
    """Rarefacción de Hurlbert: E[S_m] = Σ 1 − C(N−n_i, m)/C(N, m)."""
    n = n[n > 0].astype(float)
    N = int(n.sum())
    if N < 2:
        return []
    ms = np.unique(np.round(np.geomspace(1, N, points)).astype(int))
    lgN = lgamma(N + 1)
    out = []
    for m in ms:
        lg_den = lgN - lgamma(m + 1) - lgamma(N - m + 1)
        total = 0.0
        for ni in n:
            if N - ni >= m:
                lg_num = lgamma(N - ni + 1) - lgamma(m + 1) - lgamma(N - ni - m + 1)
                total += 1 - np.exp(lg_num - lg_den)
            else:
                total += 1
        out.append({"records": int(m), "expected_species": round(total, 2)})
    return out


def chao2(incidence: pd.Series, m: int) -> dict:
    """incidence: nº de celdas ocupadas por especie; m: nº de celdas muestreadas."""
    S = int((incidence > 0).sum())
    Q1, Q2 = int((incidence == 1).sum()), int((incidence == 2).sum())
    if m <= 1:
        return {"S": S, "chao2": float(S)}
    k = (m - 1) / m
    est = S + k * (Q1 ** 2 / (2 * Q2) if Q2 > 0 else Q1 * (Q1 - 1) / 2)
    return {"S": S, "Q1_uniques": Q1, "Q2_duplicates": Q2, "sampling_units": m, "chao2": float(est),
            "completeness_chao2": float(S / est) if est else None}


@register
class Diversity(Indicator):
    id = "diversity"
    title = "Diversidad y completitud del inventario"
    group = "biodiversidad"
    order = 92
    requires = ("spatial_grid",)
    description = "Shannon, Simpson, números de Hill, Chao1/Chao2, rarefacción y curva de acumulación espacial."

    def compute(self, ctx: AnalysisContext) -> dict:
        counts = ctx.sql("SELECT species, tax_class, COUNT(*) n FROM occ WHERE species IS NOT NULL GROUP BY 1, 2")
        n = counts.groupby("species")["n"].sum().to_numpy()
        idx = alpha_indices(n)

        rank = counts.groupby("species")["n"].sum().sort_values(ascending=False)
        rank_abundance = [{"rank": i + 1, "species": s, "records": int(v)} for i, (s, v) in
                          enumerate(rank.head(300).items())]

        by_class = []
        for cls, g in counts.groupby(counts["tax_class"].fillna("Sin clase")):
            a = alpha_indices(g["n"].to_numpy())
            by_class.append({"class": cls, "S": a["S"], "N": a["N"], "shannon_H": a.get("shannon_H"),
                             "simpson": a.get("simpson_1_minus_D"), "chao1": a.get("chao1")})
        by_class.sort(key=lambda r: r["S"], reverse=True)

        # Incidencia espacial: celdas como unidades de muestreo
        pts = ctx.points.dropna(subset=["species"])
        pts = pts.assign(cell=ctx.shared["cell_of_point"].reindex(pts.index))
        inc = pts.dropna(subset=["cell"]).groupby("species")["cell"].nunique()
        occupied = int(pts["cell"].nunique())
        c2 = chao2(inc, occupied)

        # Curva de acumulación por celdas (orden aleatorio, promedio de 20 permutaciones)
        cell_sets = pts.dropna(subset=["cell"]).groupby("cell")["species"].apply(set).tolist()
        rng = np.random.default_rng(42)
        steps = np.unique(np.round(np.linspace(1, len(cell_sets), min(40, len(cell_sets)))).astype(int))
        acc = np.zeros(len(steps))
        perms = 20 if len(cell_sets) > 1 else 1
        for _ in range(perms):
            order = rng.permutation(len(cell_sets))
            seen, k, sizes = set(), 0, []
            for i, ci in enumerate(order, start=1):
                seen |= cell_sets[ci]
                if k < len(steps) and i == steps[k]:
                    sizes.append(len(seen))
                    k += 1
            acc += np.array(sizes)
        accumulation = [{"cells": int(s), "species": round(float(v / perms), 1)} for s, v in zip(steps, acc)]

        interp = []
        if idx.get("completeness_chao1"):
            interp.append(
                f"El inventario documentado representa ≈{idx['completeness_chao1'] * 100:.0f}% de la riqueza "
                f"estimada por Chao1 ({idx['chao1']:,.0f} especies) y ≈"
                f"{(c2.get('completeness_chao2') or 0) * 100:.0f}% según Chao2 por incidencia espacial."
            )
        if idx.get("singletons"):
            interp.append(
                f"{idx['singletons']:,} especies tienen un solo registro (singletons): "
                "señal de especies raras o de muestreo insuficiente."
            )
        return {
            "summary": {**idx, **{f"spatial_{k}": v for k, v in c2.items()}},
            "rarefaction": rarefaction(n),
            "accumulation": accumulation,
            "rank_abundance": rank_abundance,
            "by_class": by_class,
            "interpretation": interp,
            "disclaimer": "Índices calculados sobre registros (no individuos): miden la diversidad de la "
                          "evidencia documentada, sensible al esfuerzo de muestreo.",
        }
