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

USER_AGENT = "pasoorbital/1.4 (herramienta local de prediccion de pasos)"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
PHOTON = "https://photon.komoot.io/api/"
ELEVATION = "https://api.open-meteo.com/v1/elevation"
CACHE_TTL_S = 30 * 86400
ELEVATION_TTL_S = 365 * 86400


class Geocoder:
    def __init__(self, data_dir: str | Path):
        self.path = Path(data_dir) / "cache" / "geocode.json"
        self.elev_path = Path(data_dir) / "cache" / "elevation.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._cache = self._read_json(self.path)
        self._elev_cache = self._read_json(self.elev_path)

    def _read_json(self, path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_json(self, path: Path, data: dict) -> None:
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    def _read_cache(self) -> dict:
        return self._read_json(self.path)

    def _save_cache(self) -> None:
        self._write_json(self.path, self._cache)

    def _save_elev_cache(self) -> None:
        self._write_json(self.elev_path, self._elev_cache)

    # ------------------------------------------------------------------
    def elevation(self, lat: float, lon: float) -> float | None:
        """Altitud del terreno (DEM de Open-Meteo) para unas coordenadas.

        Devuelve metros sobre el nivel del mar, o ``None`` si no se pudo
        consultar.  El resultado se cachea porque el terreno no cambia.
        """
        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            return None
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return None

        key = f"{lat:.4f},{lon:.4f}"
        entry = self._elev_cache.get(key)
        if entry and time.time() - entry.get("ts", 0) < ELEVATION_TTL_S:
            return entry.get("m")

        params = urllib.parse.urlencode(
            {"latitude": f"{lat:.6f}", "longitude": f"{lon:.6f}"}
        )
        req = urllib.request.Request(
            f"{ELEVATION}?{params}", headers={"User-Agent": USER_AGENT}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            values = data.get("elevation")
            if not isinstance(values, list) or not values:
                return None
            value = float(values[0])
        except Exception:
            return None
        if value != value or not (-500.0 <= value <= 9000.0):
            return None

        self._elev_cache[key] = {"ts": time.time(), "m": value}
        self._save_elev_cache()
        return value

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
