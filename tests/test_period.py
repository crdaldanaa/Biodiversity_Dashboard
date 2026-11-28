"""Análisis por periodo: el contexto filtra por años y los indicadores se recalculan con ese subconjunto."""
from dataclasses import replace

from src.analytics import run_indicators


def test_context_filters_years(ctx):
    total = ctx.scalar("SELECT COUNT(*) FROM occ")
    sub = replace(ctx, years=(2018, 2020), results={}, shared={})
    n = sub.scalar("SELECT COUNT(*) FROM occ")
    assert 0 < n < total
    assert sub.scalar("SELECT MIN(year) FROM occ") >= 2018
    assert sub.scalar("SELECT MAX(year) FROM occ") <= 2020


def test_period_indicators_use_period_records(ctx):
    full = run_indicators(ctx, only=["overview", "temporal"])
    sub = replace(ctx, years=(2020, 2021), results={}, shared={})
    per = run_indicators(sub, only=["overview", "temporal"])
    rf, rp = full["overview"]["data"]["summary"], per["overview"]["data"]["summary"]
    assert rp["records"] < rf["records"]
    assert rp["year_min"] >= 2020 and rp["year_max"] <= 2021
