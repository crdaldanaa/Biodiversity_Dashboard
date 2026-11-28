import math

import numpy as np
import pandas as pd
import pytest

from src.analytics import REGISTRY, run_indicators
from src.analytics.base import minmax
from src.analytics.diversity import alpha_indices, chao2, rarefaction
from src.analytics.hotspots import classify
from src.ingestion.res0126 import canonical_binomial
from src.references.threat import normalize_category

def test_all_registered_indicators_run(ctx):
    results = run_indicators(ctx)
    assert set(results) == set(REGISTRY)
    failed = {k: v.get("error") for k, v in results.items() if not v["ok"]}
    assert not failed, failed


def test_quality_score_formula(ctx):
    q = run_indicators(ctx, only=["quality"])["quality"]["data"]["summary"]
    high = q["fields_high_completeness"] / q["fields_evaluated"] * 100
    assert q["score"] == pytest.approx(round(q["pct_ok_coordinates"] * 0.4 + high * 0.6, 1), abs=0.11)
    assert q["label"] in {"ALTA", "MEDIA", "BAJA"}


def test_danger_index_bounds_and_classes(ctx):
    run_indicators(ctx, only=["danger_index"])
    cells = ctx.shared["grid_cells"]
    occ = cells[cells["records"] > 0]
    assert occ["danger_index"].between(0, 1).all()
    assert set(occ["danger_class"].unique()) <= {1, 2, 3, 4, 5}
    assert (cells.loc[cells["records"] == 0, "danger_class"] == 0).all()
    # Las celdas ocupadas cubren todos los registros
    assert occ["records"].sum() == 600


def test_grid_area_matches_roi(ctx):
    run_indicators(ctx, only=["spatial_grid"])
    assert ctx.shared["grid_cells"]["area_km2"].sum() == pytest.approx(ctx.roi_area_km2, rel=1e-3)


def test_alpha_indices_known_values():
    a = alpha_indices(np.array([10, 10, 10, 10]))
    assert a["S"] == 4
    assert a["shannon_H"] == pytest.approx(math.log(4))
    assert a["pielou_J"] == pytest.approx(1.0)
    assert a["hill_q2"] == pytest.approx(4.0)
    b = alpha_indices(np.array([1, 1, 2, 5]))  # F1=2, F2=1 → Chao1 = 4 + 4/2 = 6
    assert b["chao1"] == pytest.approx(6.0)


def test_rarefaction_monotonic_and_ends_at_S():
    curve = rarefaction(np.array([50, 20, 5, 1, 1]))
    vals = [p["expected_species"] for p in curve]
    assert all(x <= y + 1e-9 for x, y in zip(vals, vals[1:]))
    assert vals[-1] == pytest.approx(5.0)


def test_chao2():
    inc = pd.Series([1, 1, 2, 5, 7])
    out = chao2(inc, m=10)
    assert out["chao2"] == pytest.approx(5 + 0.9 * (2 ** 2) / (2 * 1))


def test_minmax_neutral():
    assert (minmax(pd.Series([3.0, 3.0])) == 0.5).all()
    assert minmax(pd.Series([0.0, 5.0, 10.0])).tolist() == [0.0, 0.5, 1.0]


def test_hotspot_classes():
    assert classify(pd.Series([3.0, 2.0, 1.7, 0.0, -2.0])).tolist() == [3, 2, 1, 0, -2]


@pytest.mark.parametrize("raw,code", [("VULNERABLE", "VU"), ("Vulnerable (VU)", "VU"), ("LR/nt", "NT"),
                                      ("CRITICALLY_ENDANGERED", "CR"), ("cr", "CR"), (None, None), ("xx", None)])
def test_normalize_category(raw, code):
    assert normalize_category(raw) == code


def test_canonical_binomial():
    assert canonical_binomial("Tremarctos ornatus (F.G.Cuvier, 1825)") == "tremarctos ornatus"
    assert canonical_binomial("Tremarctos") is None
