"""Un *workspace* agrupa todo lo calculado para un área de interés (ROI).

data/workspaces/<id>/
  meta.json              nombre, fuente de datos, fechas, CRS, DOI de GBIF
  status.json            estado del job (paso, progreso, log)
  roi.gpkg / roi.geojson geometría del ROI (original y WGS84 para la web)
  occurrences.parquet    GeoParquet recortado al ROI
  species.parquet        especies enriquecidas (Res. 0126, IUCN, SiB) + métricas por especie
  grid.geojson           grilla con densidad, riqueza, índice de peligro y hotspots
  analysis.json          resultados de todos los indicadores registrados
"""
import json
import re
import shutil
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config_loader import get_path

_lock = threading.Lock()


def slugify(text: str, max_len: int = 40) -> str:
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", norm).strip("-").lower()
    return slug[:max_len] or "roi"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Workspace:
    id: str

    @property
    def dir(self) -> Path:
        return get_path("workspaces_dir") / self.id

    def path(self, name: str) -> Path:
        return self.dir / name

    @property
    def roi_gpkg(self) -> Path:
        return self.path("roi.gpkg")

    @property
    def occurrences(self) -> Path:
        return self.path("occurrences.parquet")

    @property
    def species(self) -> Path:
        return self.path("species.parquet")

    @property
    def grid(self) -> Path:
        return self.path("grid.geojson")

    @property
    def analysis(self) -> Path:
        return self.path("analysis.json")

    def exists(self) -> bool:
        return self.path("meta.json").exists()

    # --- JSON helpers -------------------------------------------------------
    def read_json(self, name: str, default: Any = None) -> Any:
        p = self.path(name)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))

    def write_json(self, name: str, payload: Any) -> Path:
        p = self.path(name)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(p)
        return p

    @property
    def meta(self) -> Dict[str, Any]:
        return self.read_json("meta.json", {})

    def update_meta(self, **fields: Any) -> Dict[str, Any]:
        with _lock:
            meta = self.meta
            meta.update(fields)
            meta["updated_at"] = now_iso()
            self.write_json("meta.json", meta)
            return meta

    @property
    def status(self) -> Dict[str, Any]:
        return self.read_json("status.json", {"state": "unknown"})

    def set_status(self, **fields: Any) -> Dict[str, Any]:
        with _lock:
            st = self.status
            msg = fields.pop("log", None)
            st.update(fields)
            if msg:
                st.setdefault("log", []).append({"t": now_iso(), "msg": msg})
                st["log"] = st["log"][-80:]
            st["updated_at"] = now_iso()
            self.write_json("status.json", st)
            return st


def create_workspace(name: str, **meta: Any) -> Workspace:
    ws_id = f"{slugify(name)}-{uuid.uuid4().hex[:6]}"
    ws = Workspace(ws_id)
    ws.dir.mkdir(parents=True, exist_ok=True)
    ws.write_json("meta.json", {"id": ws_id, "name": name, "created_at": now_iso(), **meta})
    ws.write_json("status.json", {"state": "queued", "step": None, "progress": 0, "log": []})
    return ws


def get_workspace(ws_id: str) -> Optional[Workspace]:
    if not re.fullmatch(r"[a-z0-9-]{1,64}", ws_id or ""):
        return None
    ws = Workspace(ws_id)
    return ws if ws.exists() else None


def list_workspaces() -> List[Dict[str, Any]]:
    root = get_path("workspaces_dir")
    items = []
    for d in sorted(root.iterdir() if root.exists() else []):
        ws = Workspace(d.name)
        if ws.exists():
            items.append({**ws.meta, "status": ws.status})
    return sorted(items, key=lambda m: m.get("created_at", ""), reverse=True)


def delete_workspace(ws_id: str) -> bool:
    ws = get_workspace(ws_id)
    if not ws:
        return False
    shutil.rmtree(ws.dir)
    return True
