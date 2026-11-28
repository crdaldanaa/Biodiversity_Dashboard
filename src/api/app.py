"""API + dashboard web.  Ejecutar:  python scripts/biodiv.py serve   (o)   uvicorn src.api.app:app"""
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from src.analytics import REGISTRY
from src.api import routes_species, routes_workspaces
from src.config_loader import ROOT_DIR, get_config, get_path
from src.references.threat import CATEGORY_COLORS, CATEGORY_LABELS_ES, CATEGORY_ORDER

app = FastAPI(title="Biodiversity Intelligence API", version="0.2.0")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.include_router(routes_workspaces.router)
app.include_router(routes_species.router)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def config():
    s = get_config()["settings"]
    return {
        "project": s["project"]["name"],
        "categories": [{"code": c, "label": CATEGORY_LABELS_ES[c], "color": CATEGORY_COLORS[c]} for c in CATEGORY_ORDER],
        "indicators": sorted(
            ({"id": c.id, "title": c.title, "group": c.group, "description": c.description, "order": c.order}
             for c in REGISTRY.values()), key=lambda d: d["order"]),
        "danger_index": s["analysis"]["danger_index"],
        "iucn_token": bool(get_config().get("iucn_token")),
        "gbif_credentials": all(get_config()["gbif_auth"].values()),
        "fast_mode_max_records": s["gbif"]["fast_mode_max_records"],
    }


app.mount("/media", StaticFiles(directory=get_path("cache_dir") / "media", check_dir=False), name="media")
app.mount("/", StaticFiles(directory=ROOT_DIR / "web", html=True), name="web")
