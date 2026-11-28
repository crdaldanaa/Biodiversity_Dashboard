"""Sesión HTTP compartida con caché persistente (SQLite) y reintentos.

Todas las integraciones externas (GBIF, SiB, IUCN) usan esta sesión para respetar
buenas prácticas de uso de APIs: cache, reintentos con backoff y timeouts.
"""
from functools import lru_cache
from typing import Any, Optional
import threading

import requests
from requests.adapters import HTTPAdapter
from requests_cache import CachedSession
from urllib3.util.retry import Retry

from src.config_loader import get_config, get_path
from src.utils.logger import get_logger

logger = get_logger(__name__)
_local = threading.local()
USER_AGENT = "biodiversity-pipeline/0.2 (+https://github.com)"


def _build_session() -> requests.Session:
    cfg = get_config()["settings"].get("http", {})
    session = CachedSession(
        cache_name=str(get_path("cache_dir") / "http_cache"),
        backend="sqlite",
        expire_after=int(cfg.get("cache_expire_days", 30)) * 86400,
        allowable_codes=(200, 404, 406),  # SiB responde 406 cuando no hay ficha
        stale_if_error=True,
    )
    retry = Retry(total=4, backoff_factor=0.8, status_forcelist=(429, 500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=32)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers["User-Agent"] = USER_AGENT
    return session


def session() -> requests.Session:
    """Una sesión por hilo (SQLite no se comparte de forma segura entre hilos)."""
    s = getattr(_local, "session", None)
    if s is None:
        s = _local.session = _build_session()
    return s


@lru_cache(maxsize=1)
def _timeout() -> float:
    return float(get_config()["settings"].get("http", {}).get("timeout_s", 30))


def get_json(url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> Any:
    """GET que devuelve JSON o None si 404 / error de red (los errores se registran)."""
    try:
        r = session().get(url, params=params, headers=headers, timeout=_timeout())
        if r.status_code in (404, 406):
            return None
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning(f"GET {url} falló: {exc}")
        return None


def get_bytes(url: str, max_bytes: int = 15_000_000) -> Optional[bytes]:
    try:
        r = session().get(url, timeout=_timeout())
        r.raise_for_status()
        if len(r.content) > max_bytes:
            return None
        return r.content
    except requests.RequestException as exc:
        logger.warning(f"Descarga {url} falló: {exc}")
        return None
