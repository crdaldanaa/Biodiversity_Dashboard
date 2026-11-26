from pathlib import Path
from typing import Any, Dict
import os
import yaml
from dotenv import load_dotenv


def load_yaml(path: str | Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_project_config(
    settings_path: str | Path = "config/settings.yaml",
    predicates_path: str | Path = "config/gbif_predicates.yaml",
    env_path: str | Path = ".env",
) -> Dict[str, Any]:
    load_dotenv(dotenv_path=env_path, override=False)
    settings = load_yaml(settings_path)
    predicates = load_yaml(predicates_path)

    for folder_key in ("raw_dir", "interim_dir", "processed_dir"):
        folder = settings.get("paths", {}).get(folder_key)
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)

    return {
        "settings": settings,
        "predicates": predicates.get("predicates", {}),
        "gbif_auth": {
            "user": os.getenv("GBIF_USER"),
            "pwd": os.getenv("GBIF_PWD"),
            "email": os.getenv("GBIF_EMAIL"),
        },
    }
