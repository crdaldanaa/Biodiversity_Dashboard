import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def get_logger(name: str = "biodiversity_pipeline") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        logger.propagate = False
    return logger


def save_metadata_audit(output_parquet: str | Path, metadata: Dict[str, Any]) -> Path:
    output_path = Path(output_parquet)
    meta_path = output_path.with_suffix(".metadata.json")
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_file": str(output_path),
        **metadata,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return meta_path
