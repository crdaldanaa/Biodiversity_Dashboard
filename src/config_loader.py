from functools import lru_cache
from pathlib import Path
from typing import Any, Dict
import os
import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent


def load_yaml(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT_DIR / p


def load_project_config(
    settings_path: str | Path = "config/settings.yaml",
    predicates_path: str | Path = "config/gbif_predicates.yaml",
    env_path: str | Path = ".env",
) -> Dict[str, Any]:
    load_dotenv(dotenv_path=_resolve(env_path), override=False)
    settings = load_yaml(_resolve(settings_path))
    predicates = load_yaml(_resolve(predicates_path))

    for folder in settings.get("paths", {}).values():
        if folder:
            _resolve(folder).mkdir(parents=True, exist_ok=True)

    return {
        "settings": settings,
        "predicates": predicates.get("predicates", {}),
        "gbif_auth": {
            "user": os.getenv("GBIF_USER"),
            "pwd": os.getenv("GBIF_PWD"),
            "email": os.getenv("GBIF_EMAIL"),
        },
        "iucn_token": os.getenv("IUCN_TOKEN"),
    }


@lru_cache(maxsize=1)
def get_config() -> Dict[str, Any]:
    """Configuración cacheada para el proceso (API, servicios y jobs)."""
    return load_project_config()


def get_path(key: str) -> Path:
    """Ruta absoluta de una carpeta declarada en settings.paths."""
    return _resolve(get_config()["settings"]["paths"][key])
