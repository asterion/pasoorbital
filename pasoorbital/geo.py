"""Geocodificación de direcciones (OpenStreetMap / Nominatim).

Convierte una dirección escrita por el usuario en latitud/longitud.  Los
resultados se guardan en caché para no repetir consultas.  Si Nominatim no
responde se intenta Photon (Komoot), que también usa datos de OSM.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "satelites-escucha/1.0 (herramienta local de prediccion de pasos)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
PHOTON = "https://photon.komoot.io/api/"
CACHE_TTL_S = 30 * 86400


class Geocoder:
    def __init__(self, data_dir: str | Path):
        self.path = Path(data_dir) / "cache" / "geocode.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._cache = self._read_cache()

    def _read_cache(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_cache(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._cache, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def _throttle(self) -> None:
        # Nominatim pide como máximo 1 petición por segundo.
        wait = 1.05 - (time.time() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def search(self, query: str, limit: int = 6) -> list[dict]:
        query = " ".join(query.split())
        if len(query) < 3:
            return []
        key = query.lower()
        entry = self._cache.get(key)
        if entry and time.time() - entry.get("ts", 0) < CACHE_TTL_S:
            return entry.get("results", [])[:limit]

        results: list[dict] = []
        try:
            results = self._nominatim(query, limit)
        except Exception:
            results = []
        if not results:
            try:
                results = self._photon(query, limit)
            except Exception:
                results = []

        if results:
            self._cache[key] = {"ts": time.time(), "results": results}
            self._save_cache()
        return results[:limit]

    # ------------------------------------------------------------------
    def _nominatim(self, query: str, limit: int) -> list[dict]:
        params = urllib.parse.urlencode(
            {
                "q": query,
                "format": "jsonv2",
                "limit": limit,
                "addressdetails": 0,
                "accept-language": "es",
            }
        )
        req = urllib.request.Request(
            f"{NOMINATIM}?{params}",
            headers={"User-Agent": USER_AGENT, "Accept-Language": "es"},
        )
        self._throttle()
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = []
        for item in data:
            try:
                out.append(
                    {
                        "name": item.get("display_name", query),
                        "lat": float(item["lat"]),
                        "lon": float(item["lon"]),
                        "type": item.get("type", ""),
                    }
                )
            except (KeyError, ValueError):
                continue
        return out

    def _photon(self, query: str, limit: int) -> list[dict]:
        params = urllib.parse.urlencode({"q": query, "limit": limit, "lang": "es"})
        req = urllib.request.Request(
            f"{PHOTON}?{params}", headers={"User-Agent": USER_AGENT}
        )
        self._throttle()
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = []
        for feature in data.get("features", []):
            props = feature.get("properties", {})
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            parts = [props.get("name"), props.get("city"), props.get("state"), props.get("country")]
            label = ", ".join(p for p in parts if p) or query
            try:
                out.append(
                    {
                        "name": label,
                        "lat": float(coords[1]),
                        "lon": float(coords[0]),
                        "type": props.get("osm_value", ""),
                    }
                )
            except (TypeError, ValueError):
                continue
        return out
