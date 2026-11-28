"""Foto por especie + paleta de colores vibrante extraída de la imagen.

La interfaz del catálogo usa esta paleta para teñir cada ficha con los colores reales de la
especie. Las imágenes se descargan una vez, se redimensionan y se sirven localmente
(evita cargar originales de varios MB y problemas de CORS en el navegador).
"""
import colorsys
import hashlib
import io
import json
import threading
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

from src.config_loader import get_config, get_path
from src.ingestion import gbif_api
from src.references.threat import CATEGORY_COLORS
from src.utils.http import get_bytes
from src.utils.logger import get_logger

logger = get_logger(__name__)
_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _dir() -> Path:
    d = get_path("cache_dir") / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


def slug(name: str) -> str:
    return hashlib.sha1(name.strip().lower().encode()).hexdigest()[:16]


def _hex(rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*[int(max(0, min(255, c))) for c in rgb])


def _web_url(url: str) -> str:
    # iNaturalist publica "original" (varios MB); "large" basta para la ficha
    return url.replace("/original.", "/large.") if "inaturalist" in url else url


def extract_palette(img: Image.Image) -> dict:
    """Elige colores 'vibrant', 'muted', 'dark' y 'light' a partir de una cuantización."""
    small = img.convert("RGB").resize((96, 96))
    q = small.quantize(colors=12, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[: 12 * 3]
    counts = sorted(q.getcolors(), reverse=True)
    total = sum(c for c, _ in counts)
    swatches = []
    for count, idx in counts:
        r, g, b = pal[idx * 3: idx * 3 + 3]
        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        swatches.append({"rgb": (r, g, b), "h": h, "l": l, "s": s, "pop": count / total})

    def best(score):
        return max(swatches, key=score) if swatches else None

    vibrant = best(lambda c: c["s"] * 2 + (1 - abs(c["l"] - 0.5) * 2) + c["pop"] * 0.6)
    second = best(lambda c: (c["s"] + (1 - abs(c["l"] - 0.55) * 2)) * min(abs(c["h"] - vibrant["h"]) * 3, 1.0)
                  + c["pop"] * 0.3)
    dark = best(lambda c: (1 - c["l"]) * 1.5 + c["s"] + c["pop"] * 0.2 if c["l"] < 0.45 else -1)
    light = best(lambda c: c["l"] + c["s"] * 0.5 if c["l"] > 0.55 else -1)

    def boost(sw, min_s=0.55, l_range=(0.45, 0.65)):
        h, l, s = sw["h"], sw["l"], sw["s"]
        s = max(s, min_s)
        l = min(max(l, l_range[0]), l_range[1])
        return _hex([v * 255 for v in colorsys.hls_to_rgb(h, l, s)])

    return {
        "vibrant": boost(vibrant),
        "secondary": boost(second, 0.5, (0.5, 0.7)),
        "dark": boost(dark, 0.35, (0.08, 0.18)),
        "light": boost(light, 0.4, (0.78, 0.9)),
        "dominant": _hex(swatches[0]["rgb"]),
        "swatches": [_hex(c["rgb"]) for c in swatches[:6]],
    }


def fallback_palette(name: str, category: Optional[str]) -> dict:
    """Paleta determinista por nombre (hue) con acento IUCN si no hay foto."""
    h = int(hashlib.md5(name.encode()).hexdigest()[:4], 16) / 0xFFFF
    mk = lambda hh, l, s: _hex([v * 255 for v in colorsys.hls_to_rgb(hh % 1, l, s)])  # noqa: E731
    return {
        "vibrant": mk(h, 0.52, 0.55), "secondary": mk(h + 0.33, 0.58, 0.5), "dark": mk(h, 0.12, 0.35),
        "light": mk(h, 0.85, 0.4), "dominant": CATEGORY_COLORS.get(category or "NE", "#888888"),
        "swatches": [], "fallback": True,
    }


def get_media(name: str, gbif_key: Optional[int] = None, image_url: Optional[str] = None,
              credits: Optional[dict] = None, category: Optional[str] = None) -> dict:
    key = slug(name)
    meta_path = _dir() / f"{key}.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    with _guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        if meta_path.exists():
            return json.loads(meta_path.read_text(encoding="utf-8"))
        info = None
        candidates = []
        if image_url:
            candidates.append({"url": image_url, **(credits or {})})
        country = get_config()["settings"]["gbif"].get("media_country")
        found, attempted = None, False
        for cand in candidates + [None]:
            if cand is None:
                found = gbif_api.find_image(gbif_key, name, country)
                if not found:
                    break
                cand = found
            attempted = True
            data = get_bytes(_web_url(cand["url"]))
            if not data:
                continue
            try:
                img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
            except Exception:
                continue
            img.thumbnail((1200, 1200))
            img.save(_dir() / f"{key}.jpg", "JPEG", quality=84, optimize=True)
            thumb = img.copy()
            thumb.thumbnail((480, 480))
            thumb.save(_dir() / f"{key}_t.jpg", "JPEG", quality=80, optimize=True)
            info = {
                "image": f"/media/{key}.jpg", "thumb": f"/media/{key}_t.jpg",
                "author": cand.get("author"), "license": cand.get("license"),
                "source": cand.get("source"), "origin_url": cand.get("occurrence") or cand.get("url"),
                "palette": extract_palette(img), "width": img.width, "height": img.height,
            }
            break
        if info is None:
            info = {"image": None, "thumb": None, "palette": fallback_palette(name, category)}
            if attempted:  # hubo foto pero falló la descarga: no se cachea, se reintenta luego
                return info
        meta_path.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
        return info


def cached_media(name: str) -> Optional[dict]:
    p = _dir() / f"{slug(name)}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
