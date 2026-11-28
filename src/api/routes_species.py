"""Catálogo digital de especies y fichas individuales."""
import json
from typing import Literal, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException

from src.api.deps import occ_query, species_df, workspace_or_404
from src.ingestion import iucn_client, res0126, sib_catalog
from src.references.threat import CATEGORY_ORDER, THREATENED
from src.services import media

router = APIRouter(prefix="/api", tags=["species"])
SortKey = Literal["records", "name", "threat", "aoo", "trend", "recent", "period"]
Presence = Literal["", "period"]
_THREAT_RANK = {c: i for i, c in enumerate(CATEGORY_ORDER)}


def _clean(rec: dict) -> dict:
    out = {}
    for k, v in rec.items():
        if v is pd.NA or (isinstance(v, float) and pd.isna(v)):
            v = None
        elif hasattr(v, "item"):
            v = v.item()
        if k == "gbif_key" and v is not None:
            v = int(v)
        out[k] = v
    if isinstance(out.get("common_names"), str):
        out["common_names"] = json.loads(out["common_names"] or "[]")
    return out


@router.get("/workspaces/{ws_id}/species")
def catalog(ws_id: str, q: Optional[str] = None, threat: Optional[str] = None,
            tax_class: Optional[str] = None, kingdom: Optional[str] = None, flag: Optional[str] = None,
            sort: SortKey = "records", limit: int = 48, offset: int = 0,
            year_from: Optional[int] = None, year_to: Optional[int] = None, presence: Presence = ""):
    """Catálogo filtrable. Con `year_from`/`year_to` añade por especie los registros del periodo
    (`n_period`); `presence=period` deja solo las especies registradas en él."""
    ws = workspace_or_404(ws_id)
    df = species_df(ws).copy()
    df["threat_any"] = df["threat_national"].fillna(df["threat_global"])
    period = None
    if year_from or year_to:
        period = _period_counts(ws, year_from, year_to)
        df = df.merge(period["table"], on="species", how="left")
        df["n_period"] = df["n_period"].fillna(0).astype(int)
        if presence == "period":
            df = df[df["n_period"] > 0]
    if q:
        ql = q.strip().lower()
        hay = (df["species"].str.lower().str.contains(ql, regex=False)
               | df["common_names"].fillna("").str.lower().str.contains(ql, regex=False)
               | df["family"].fillna("").str.lower().str.contains(ql, regex=False))
        df = df[hay]
    if threat == "threatened":
        df = df[df["threat_national"].isin(THREATENED) | df["threat_global"].isin(THREATENED)]
    elif threat == "national":
        df = df[df["threat_national"].isin(THREATENED)]
    elif threat:
        df = df[(df["threat_national"] == threat) | (df["threat_global"] == threat)]
    if tax_class:
        df = df[df["tax_class"] == tax_class]
    if kingdom:
        df = df[df["kingdom"] == kingdom]
    if flag in ("cites",):
        df = df[df["cites"].fillna("") != ""]
    elif flag in ("exotic", "invasive", "new_in_2024"):
        df = df[df[flag].fillna(False).astype(bool)]

    if sort == "name":
        df = df.sort_values("species")
    elif sort == "threat":
        df = df.assign(_r=df["threat_any"].map(_THREAT_RANK).fillna(99)).sort_values(["_r", "n_records"], ascending=[True, False])
    elif sort == "aoo" and "aoo_km2" in df:
        df = df.sort_values("aoo_km2", ascending=False)
    elif sort == "trend" and "trend_pct" in df:
        df = df.sort_values("trend_pct", ascending=False, na_position="last")
    elif sort == "recent" and "last_year" in df:
        df = df.sort_values(["last_year", "n_records"], ascending=False)
    elif sort == "period" and "n_period" in df:
        df = df.sort_values(["n_period", "n_records"], ascending=False)
    else:
        df = df.sort_values("n_records", ascending=False)

    total = len(df)
    page = df.iloc[offset: offset + max(1, min(limit, 200))]
    items = []
    for rec in page.drop(columns=["_r"], errors="ignore").to_dict("records"):
        r = _clean(rec)
        r["media"] = media.cached_media(r["species"])
        items.append(r)
    facets = {
        "tax_class": species_df(ws)["tax_class"].value_counts().head(30).to_dict(),
        "kingdom": species_df(ws)["kingdom"].value_counts().to_dict(),
    }
    out = {"total": total, "offset": offset, "items": items, "facets": facets}
    if period:
        out["period"] = {k: v for k, v in period.items() if k != "table"}
    return out


def _period_counts(ws, y0: Optional[int], y1: Optional[int]) -> dict:
    """Registros por especie dentro del periodo [y0, y1]."""
    yr = occ_query(ws, "SELECT MIN(year), MAX(year) FROM occ WHERE year IS NOT NULL").iloc[0].tolist()
    y0, y1 = sorted((int(y0 or yr[0]), int(y1 or yr[1])))
    t = occ_query(ws, """SELECT species, COUNT(*) FILTER (WHERE year BETWEEN ? AND ?) AS n_period
                         FROM occ WHERE species IS NOT NULL GROUP BY 1""", [y0, y1])
    return {"table": t, "from": y0, "to": y1, "records": int(t["n_period"].sum()),
            "species": int((t["n_period"] > 0).sum())}


@router.get("/workspaces/{ws_id}/species/{name}")
def species_detail(ws_id: str, name: str):
    ws = workspace_or_404(ws_id)
    df = species_df(ws)
    row = df[df["species"] == name]
    if row.empty:
        raise HTTPException(404, f"'{name}' no tiene registros en este workspace")
    rec = _clean(row.iloc[0].to_dict())
    yearly = occ_query(ws, "SELECT year, COUNT(*) n FROM occ WHERE species = ? AND year IS NOT NULL GROUP BY 1 ORDER BY 1", [name])
    monthly = occ_query(ws, "SELECT month, COUNT(*) n FROM occ WHERE species = ? AND month BETWEEN 1 AND 12 GROUP BY 1 ORDER BY 1", [name])
    ym = occ_query(ws, """SELECT year, month, COUNT(*) n FROM occ WHERE species = ? AND year IS NOT NULL
                          AND month BETWEEN 1 AND 12 GROUP BY 1, 2 ORDER BY 1, 2""", [name])
    pts = occ_query(ws, """SELECT * FROM (SELECT lon, lat, year, basisOfRecord, gbifID, elevation FROM occ_spatial
                         WHERE species = ?) USING SAMPLE reservoir(5000 ROWS)""", [name])
    basis = occ_query(ws, "SELECT basisOfRecord, COUNT(*) n FROM occ WHERE species = ? GROUP BY 1 ORDER BY 2 DESC", [name])
    sib_full = sib_catalog.complete_record(rec["sib_id"]) if rec.get("sib_id") else None
    iucn = iucn_client.get_status(name, rec.get("gbif_key"))
    m = media.get_media(name, rec.get("gbif_key"), rec.get("image_url"),
                        {"author": rec.get("image_author"), "license": rec.get("image_license"),
                         "source": rec.get("image_source")}, rec.get("threat_national") or rec.get("threat_global"))
    return {
        **rec,
        "media": m,
        "res0126": _clean(res0126.lookup(name) or {}) or None,
        "iucn": iucn,
        "sib": sib_full,
        "yearly": yearly.to_dict("records"),
        "monthly": monthly.to_dict("records"),
        "year_month": {"year": ym["year"].astype(int).tolist(), "month": ym["month"].astype(int).tolist(),
                       "n": ym["n"].astype(int).tolist()},
        "basis": basis.to_dict("records"),
        "points": {"lon": pts["lon"].round(5).tolist(), "lat": pts["lat"].round(5).tolist(),
                   "year": pts["year"].fillna(0).astype(int).tolist(),
                   "id": pts["gbifID"].astype("Int64").astype(str).tolist()},
        "links": {
            "gbif": f"https://www.gbif.org/species/{rec['gbif_key']}" if rec.get("gbif_key") else None,
            "sib": rec.get("sib_url"), "iucn": (iucn or {}).get("url") or rec.get("iucn_url"),
        },
    }


@router.get("/media/{name}")
def species_media(name: str, gbif_key: Optional[int] = None, category: Optional[str] = None):
    """Foto + paleta de colores (descarga y cachea en el primer acceso)."""
    cached = media.cached_media(name)
    if cached:
        return cached
    sib = sib_catalog.search(name) or {}
    img = sib.get("image") or {}
    return media.get_media(name, gbif_key, img.get("url"), img, category)


@router.get("/references/res0126")
def res0126_summary():
    return res0126.summary()
