"""Framework de indicadores enchufables.

Para añadir un módulo de análisis nuevo basta con crear un archivo en `src/analytics/`
con una clase que herede de `Indicator` decorada con `@register`. Se descubre sola.

    @register
    class MiIndicador(Indicator):
        id = "mi_indicador"
        title = "Mi indicador"
        group = "biodiversidad"
        order = 50
        def compute(self, ctx: AnalysisContext) -> dict:
            df = ctx.sql("SELECT species, COUNT(*) n FROM occ GROUP BY 1")
            return {"top": df.head(10).to_dict("records")}

Convenciones del resultado (dict JSON-serializable):
  * `summary`        cifras citables en un informe
  * `interpretation` textos automáticos por umbrales (plantillas, no IA)
  * `disclaimer`     límites de interpretación (GBIF ≠ población, IUCN ≠ abundancia)
"""
import math
import re
import time
import traceback
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Callable, Dict, List, Optional, Type

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer

from src.utils.logger import get_logger

logger = get_logger(__name__)

DISCLAIMER_GBIF = (
    "Los registros GBIF documentan presencia observada: no equivalen a abundancia poblacional "
    "y reflejan el esfuerzo de muestreo y la accesibilidad del territorio."
)


@dataclass
class AnalysisContext:
    occurrences_path: str
    roi: gpd.GeoDataFrame  # EPSG:4326
    metric_crs: str
    cfg: Dict[str, Any]
    species: Optional[pd.DataFrame] = None  # tabla enriquecida (Res. 0126, IUCN, SiB)
    results: Dict[str, Any] = field(default_factory=dict)
    shared: Dict[str, Any] = field(default_factory=dict)  # artefactos compartidos (p. ej. grilla)
    # Periodo (año inicial, año final) para recalcular los indicadores solo con esos registros.
    # None = todos los años (incluidos los registros sin fecha).
    years: Optional[tuple] = None

    @cached_property
    def con(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(":memory:")
        con.execute("INSTALL spatial; LOAD spatial;")
        cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{self.occurrences_path}'").fetchall()}
        lonlat = "lon, lat" if {"lon", "lat"} <= cols else "ST_X(geometry) AS lon, ST_Y(geometry) AS lat"
        exclude = [c for c in ("geometry", "lon", "lat") if c in cols]
        optional = {
            "stateProvince": "VARCHAR", "issue": "VARCHAR", "day": "INTEGER", "individualCount": "INTEGER",
            "countryCode": "VARCHAR", "locality": "VARCHAR", "mediaType": "VARCHAR", "elevation_source": "VARCHAR",
        }
        fillers = ", ".join(f"NULL::{t} AS {c}" for c, t in optional.items() if c not in cols)
        where = ""
        if self.years:
            y0, y1 = (int(v) for v in self.years)
            where = f"WHERE year BETWEEN {y0} AND {y1}"
        con.execute(
            f"""CREATE VIEW occ AS SELECT * EXCLUDE ({', '.join(exclude)}), {lonlat}
                {', ' + fillers if fillers else ''} FROM '{self.occurrences_path}' {where}"""
        )
        # Subconjunto apto para análisis espaciales (incertidumbre aceptable; ver paso `clean`)
        ok = "WHERE spatial_ok" if "spatial_ok" in cols else ""
        con.execute(f"CREATE VIEW occ_spatial AS SELECT * FROM occ {ok}")
        if self.species is not None and not self.species.empty:
            con.register("species_tbl", self.species)
        return con

    def sql(self, query: str, params: Optional[list] = None) -> pd.DataFrame:
        return self.con.execute(query, params or []).df()

    def scalar(self, query: str) -> Any:
        return self.con.execute(query).fetchone()[0]

    @cached_property
    def points(self) -> pd.DataFrame:
        """Ocurrencias aptas para análisis espacial (`occ_spatial`) con coordenadas métricas x, y."""
        df = self.sql(
            """SELECT gbifID, species, tax_class, year, coordinateUncertaintyInMeters AS unc, lon, lat
               FROM occ_spatial"""
        )
        tr = Transformer.from_crs("EPSG:4326", self.metric_crs, always_xy=True)
        df["x"], df["y"] = tr.transform(df["lon"].to_numpy(), df["lat"].to_numpy())
        return df

    @cached_property
    def roi_metric(self) -> gpd.GeoDataFrame:
        return self.roi.to_crs(self.metric_crs)

    @cached_property
    def roi_area_km2(self) -> float:
        return float(self.roi_metric.geometry.union_all().area / 1e6)

    def threat_of(self, source: str = "national") -> Dict[str, str]:
        """Diccionario especie → categoría según fuente ('national' | 'global' | 'index')."""
        if self.species is None or self.species.empty:
            return {}
        if source == "index":
            priority = self.cfg["danger_index"].get("threat_source_priority", ["res0126", "iucn"])
            cols = ["threat_national" if p == "res0126" else "threat_global" for p in priority]
            s = self.species.set_index("species")[cols].bfill(axis=1).iloc[:, 0]
        else:
            col = "threat_national" if source == "national" else "threat_global"
            s = self.species.set_index("species")[col]
        return {k: v for k, v in s.items() if isinstance(v, str)}


class Indicator:
    id: str = ""
    title: str = ""
    group: str = "general"
    description: str = ""
    order: int = 100
    requires: tuple = ()  # ids de indicadores que deben ejecutarse antes

    def compute(self, ctx: AnalysisContext) -> Dict[str, Any]:  # pragma: no cover - interfaz
        raise NotImplementedError


REGISTRY: Dict[str, Type[Indicator]] = {}


def register(cls: Type[Indicator]) -> Type[Indicator]:
    if not cls.id:
        raise ValueError(f"{cls.__name__} debe definir 'id'")
    REGISTRY[cls.id] = cls
    return cls


def _ordered(only: Optional[List[str]]) -> List[Type[Indicator]]:
    selected = set(only or REGISTRY)
    stack = list(selected)
    while stack:  # incluye dependencias
        for dep in REGISTRY[stack.pop()].requires:
            if dep not in selected:
                selected.add(dep)
                stack.append(dep)
    return sorted((REGISTRY[i] for i in selected), key=lambda c: (c.order, c.id))


def run_indicators(
    ctx: AnalysisContext,
    only: Optional[List[str]] = None,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, Any]:
    classes = _ordered(only)
    for i, cls in enumerate(classes):
        ind = cls()
        t0 = time.perf_counter()
        if progress:
            progress(i, len(classes), ind.title)
        try:
            payload = _localize_texts(ind.compute(ctx))
            ctx.results[ind.id] = {
                "id": ind.id, "title": ind.title, "group": ind.group,
                "description": ind.description, "ok": True, "data": clean_json(payload),
                "elapsed_s": round(time.perf_counter() - t0, 3),
            }
        except Exception as exc:  # un indicador fallido no tumba el análisis completo
            logger.error(f"Indicador {ind.id} falló: {exc}\n{traceback.format_exc()}")
            ctx.results[ind.id] = {"id": ind.id, "title": ind.title, "group": ind.group, "ok": False,
                                   "error": str(exc)}
    return ctx.results


_NUM = re.compile(r"(?<![\w.,])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w])|(?<![\w.,])\d+\.\d+(?![\w.])")


def localize_numbers(text: str) -> str:
    """'8,351' → '8.351' y '12.3' → '12,3' (formato es-CO) en los textos automáticos."""
    return _NUM.sub(lambda m: m.group(0).replace(",", "\0").replace(".", ",").replace("\0", "."), text)


def _localize_texts(payload: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(payload.get("interpretation"), list):
        payload["interpretation"] = [localize_numbers(t) for t in payload["interpretation"]]
    return payload


def clean_json(obj: Any) -> Any:
    """Convierte numpy/pandas/NaN a tipos JSON nativos."""
    if isinstance(obj, dict):
        return {str(k): clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return clean_json(obj.to_dict("records"))
    if isinstance(obj, pd.Series):
        return clean_json(obj.to_dict())
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return clean_json(obj.tolist())
    if obj is pd.NA or obj is pd.NaT:
        return None
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return obj


def pct(part: float, total: float, nd: int = 1) -> float:
    return round(100.0 * part / total, nd) if total else 0.0


def minmax(s: pd.Series) -> pd.Series:
    """Normalización Min-Max (Lección 2.4): iguales o sin datos → 0.5 neutro."""
    s = s.astype(float)
    lo, hi = s.min(skipna=True), s.max(skipna=True)
    if pd.isna(lo) or hi == lo:
        return pd.Series(0.5, index=s.index)
    return ((s - lo) / (hi - lo)).fillna(0.5)
