import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
from pygbif import occurrences as occ
from src.utils.logger import get_logger

logger = get_logger(__name__)


def build_gbif_predicates(wkt_polygon: str, pred_cfg: Dict[str, Any]) -> List[str]:
    predicates = [f"geometry within {wkt_polygon}"]

    if pred_cfg.get("has_coordinate", True):
        predicates.append("hasCoordinate = true")
    if pred_cfg.get("has_geospatial_issue", False) is False:
        predicates.append("hasGeospatialIssue = false")
    if pred_cfg.get("occurrence_status"):
        predicates.append(f"occurrenceStatus = {pred_cfg['occurrence_status']}")

    kingdom_keys = pred_cfg.get("kingdom_keys") or []
    if kingdom_keys:
        keys_str = ",".join(str(k) for k in kingdom_keys)
        predicates.append(f"taxonKey in [{keys_str}]")

    year_start = pred_cfg.get("year_start")
    year_end = pred_cfg.get("year_end")
    if year_start and year_end:
        predicates.append(f"year >= {year_start}")
        predicates.append(f"year <= {year_end}")
    elif year_start:
        predicates.append(f"year >= {year_start}")
    elif year_end:
        predicates.append(f"year <= {year_end}")

    max_unc = pred_cfg.get("max_coordinate_uncertainty_m")
    if max_unc is not None:
        predicates.append(f"coordinateUncertaintyInMeters <= {max_unc}")

    return predicates


def request_and_download_gbif(
    wkt_polygon: str,
    pred_cfg: Dict[str, Any],
    auth: Dict[str, str],
    raw_dir: str | Path = "data/raw",
    poll_interval: int = 15,
) -> Tuple[Path, Dict[str, Any]]:
    '''
    Lanza una descarga asíncrona en GBIF, espera a que termine y descarga el ZIP.

    Returns:
        Tuple[Path, Dict[str, Any]]: (ruta_al_zip, metadatos_de_descarga_con_doi)
    '''
    if not all([auth.get("user"), auth.get("pwd"), auth.get("email")]):
        raise EnvironmentError(
            "Faltan credenciales de GBIF. Define GBIF_USER, GBIF_PWD y GBIF_EMAIL en .env."
        )

    out_dir = Path(raw_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    predicates = build_gbif_predicates(wkt_polygon, pred_cfg)
    logger.info(f"Enviando solicitud asíncrona a GBIF con {len(predicates)} predicados...")

    download_key, _ = occ.download(
        predicates,
        format="SIMPLE_CSV",
        user=auth["user"],
        pwd=auth["pwd"],
        email=auth["email"],
    )
    logger.info(f"Solicitud aceptada. Download Key: {download_key}")

    while True:
        meta = occ.download_meta(download_key)
        status = meta.get("status")
        logger.info(f"Estado de descarga [{download_key}]: {status}")
        if status == "SUCCEEDED":
            break
        if status in ("KILLED", "CANCELLED", "FILE_ERASED"):
            raise RuntimeError(f"La descarga {download_key} falló con estado: {status}")
        time.sleep(poll_interval)

    logger.info(f"Descargando archivo ZIP de {download_key}...")
    occ.download_get(download_key, path=str(out_dir))
    zip_path = out_dir / f"{download_key}.zip"

    download_info = {
        "download_key": download_key,
        "doi": meta.get("doi"),
        "total_records_gbif": meta.get("totalRecords"),
        "license": meta.get("license"),
        "created": meta.get("created"),
    }
    logger.info(f"Descarga completada: {zip_path} | DOI: {download_info['doi']}")
    return zip_path, download_info
