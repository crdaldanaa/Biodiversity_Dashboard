"""Depuración de ocurrencias (paso `clean` del pipeline), configurable en `settings.yaml > cleaning`.

Elimina registros que no deben entrar a ningún análisis:
  * tipos de registro excluidos (p. ej. especímenes de museo, PRESERVED_SPECIMEN)
  * registros sin año o fuera del rango [year_min, year_max]
  * duplicados: misma especie (o nombre científico), coordenada y fecha; se conserva el de menor incertidumbre

Y marca con `spatial_ok = FALSE` los de incertidumbre alta: siguen contando para riqueza, temporalidad
y composición, pero no para los análisis espaciales (grilla, AOO/EOO, hotspots, elevación, mapa).
Sin incertidumbre reportada se considera válido (es lo habitual en observaciones con GPS).

La copia original queda en `occurrences_raw.parquet`, de modo que el paso puede repetirse con otros
criterios sin volver a descargar.
"""
import shutil
from pathlib import Path
from typing import Any, Dict

import duckdb

DEFAULTS: Dict[str, Any] = {
    "exclude_basis": ["PRESERVED_SPECIMEN", "FOSSIL_SPECIMEN"],
    "require_year": True,
    "year_min": None,
    "year_max": None,
    "drop_duplicates": True,
    "spatial_max_uncertainty_m": 10000,
}


def clean_occurrences(occurrences: Path, raw_backup: Path, cfg: Dict[str, Any] | None = None) -> Dict[str, Any]:
    cfg = {**DEFAULTS, **(cfg or {})}
    if not raw_backup.exists():
        shutil.copy2(occurrences, raw_backup)
    src = raw_backup.as_posix()
    con = duckdb.connect(":memory:")
    try:
        cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{src}'").fetchall()}
        steps, stats = [], {"raw": con.execute(f"SELECT COUNT(*) FROM '{src}'").fetchone()[0]}
        sel = "* EXCLUDE (spatial_ok)" if "spatial_ok" in cols else "*"
        con.execute(f"CREATE TEMP TABLE t AS SELECT {sel} FROM '{src}'")

        def drop(key: str, where: str, params: list | None = None) -> None:
            n = con.execute(f"SELECT COUNT(*) FROM t WHERE {where}", params or []).fetchone()[0]
            con.execute(f"DELETE FROM t WHERE {where}", params or [])
            stats[key] = int(n)
            steps.append(key)

        basis = [b for b in cfg["exclude_basis"] or []]
        if basis and "basisOfRecord" in cols:
            drop("removed_basis", f"basisOfRecord IN ({', '.join('?' * len(basis))})", basis)
        if cfg["require_year"]:
            drop("removed_no_year", "year IS NULL")
        if cfg["year_min"]:
            drop("removed_before_min", "year < ?", [int(cfg["year_min"])])
        if cfg["year_max"]:
            drop("removed_after_max", "year > ?", [int(cfg["year_max"])])
        if cfg["drop_duplicates"]:
            date = "CAST(eventDate AS VARCHAR)" if "eventDate" in cols else "CONCAT(year, '-', month, '-', day)"
            key = "COALESCE(species, scientificName)" if "scientificName" in cols else "species"
            unc = "coordinateUncertaintyInMeters" if "coordinateUncertaintyInMeters" in cols else "NULL"
            con.execute(f"""CREATE TEMP TABLE keep AS SELECT gbifID FROM (
                SELECT gbifID, ROW_NUMBER() OVER (PARTITION BY {key}, ROUND(lon, 5), ROUND(lat, 5), {date}
                                                  ORDER BY {unc} NULLS LAST, gbifID) rn FROM t) WHERE rn = 1""")
            n0 = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            con.execute("DELETE FROM t WHERE gbifID NOT IN (SELECT gbifID FROM keep)")
            stats["removed_duplicates"] = int(n0 - con.execute("SELECT COUNT(*) FROM t").fetchone()[0])
        lim = cfg["spatial_max_uncertainty_m"]
        ok = (f"(coordinateUncertaintyInMeters IS NULL OR coordinateUncertaintyInMeters <= {float(lim)})"
              if lim and "coordinateUncertaintyInMeters" in cols else "TRUE")
        tmp = occurrences.with_suffix(".tmp.parquet")
        con.execute(f"COPY (SELECT *, {ok} AS spatial_ok FROM t) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        final, spatial = con.execute(f"SELECT COUNT(*), COUNT(*) FILTER (WHERE spatial_ok) FROM '{tmp.as_posix()}'").fetchone()
    finally:
        con.close()
    tmp.replace(occurrences)
    stats.update(final=int(final), spatial_ok=int(spatial), spatial_excluded=int(final - spatial),
                 criteria={k: cfg[k] for k in DEFAULTS})
    return stats
