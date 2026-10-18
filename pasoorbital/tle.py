"""Catálogo de TLE: descarga desde CelesTrak y caché local.

CelesTrak publica los elementos orbitales agrupados por temática
(estaciones, meteorológicos, radioaficionados, CubeSats).  Este módulo los
descarga, los guarda en ``data/tle/<grupo>.tle`` y los cachea en memoria.

La caché en disco permite arrancar y predecir sin conexión (con TLE algo
antiguos); si el grupo caduca se intenta refrescar y, si la red falla, se
sigue usando la copia local marcándola como ``stale``.
"""

from __future__ import annotations

import json
import math
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from sgp4.api import Satrec

CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP={group}&FORMAT=tle"
USER_AGENT = "satelites-escucha/1.0 (herramienta local de prediccion de pasos)"
MAX_AGE_S = 6 * 3600  # los TLE se refrescan como máximo cada 6 h

#: Grupos disponibles.  La clave es la que usa la API de CelesTrak.
GROUPS: dict[str, str] = {
    "stations": "Estación Espacial y misiones tripuladas",
    "weather": "Meteorológicos (NOAA, Meteor, ...)",
    "amateur": "Radioaficionados (AMSAT)",
    "cubesat": "CubeSats y telemetría",
}

DEFAULT_GROUPS = ("stations", "weather", "amateur")


class TleError(RuntimeError):
    """No se pudo obtener ni leer un catálogo."""


def parse_tle(text: str) -> list[dict]:
    """Convierte un texto en formato TLE de tres líneas en una lista de satélites.

    Cada elemento incluye el objeto :class:`sgp4.api.Satrec` ya construido y
    metadatos derivados de la órbita (época, inclinación, período, altura).
    """
    lines = [ln.strip("\ufeff").rstrip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln.strip()]

    out: list[dict] = []
    i = 0
    while i < len(lines):
        line1 = lines[i]
        if line1.startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
            line2 = lines[i + 1]
            name = ""
            if i > 0 and not lines[i - 1].startswith(("1 ", "2 ")):
                name = lines[i - 1]
                if name.startswith("0 "):
                    name = name[2:]
            out.append(_make_entry(name, line1, line2))
            i += 2
            continue
        i += 1
    return [e for e in out if e is not None]


def _make_entry(name: str, line1: str, line2: str) -> dict | None:
    try:
        norad = int(line1[2:7])
    except ValueError:
        return None
    try:
        sat = Satrec.twoline2rv(line1, line2)
    except ValueError:
        return None

    epoch_ts = (sat.jdsatepoch + getattr(sat, "jdsatepochF", 0.0) - 2440587.5) * 86400.0
    incl = math.degrees(sat.inclo)
    period_min = 2.0 * math.pi / sat.no if sat.no else 0.0
    alt_km = max(0.0, (sat.a - 1.0) * 6378.137) if sat.a else 0.0

    return {
        "norad": norad,
        "name": (name or f"NORAD {norad}").strip(),
        "line1": line1,
        "line2": line2,
        "satrec": sat,
        "epoch_ts": epoch_ts,
        "incl_deg": incl,
        "period_min": period_min,
        "alt_km": alt_km,
    }


class Catalogue:
    """Catálogo de satélites con caché en disco y en memoria."""

    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir) / "tle"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._meta_path = self.dir / "_meta.json"
        self._meta = self._read_meta()
        self._lock = threading.RLock()
        self._parsed: dict[str, tuple[float, int, list[dict]]] = {}

    # ------------------------------------------------------------------ meta
    def _read_meta(self) -> dict:
        try:
            return json.loads(self._meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_meta(self) -> None:
        tmp = self._meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._meta, indent=2), encoding="utf-8")
        tmp.replace(self._meta_path)

    # --------------------------------------------------------------- lectura
    def _parse_file(self, group: str, path: Path) -> list[dict]:
        stat = path.stat()
        key = (stat.st_mtime, stat.st_size)
        cached = self._parsed.get(group)
        if cached and cached[0] == key[0] and cached[1] == key[1]:
            return cached[2]
        try:
            items = parse_tle(path.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            raise TleError(f"no se pudo leer {path.name}: {exc}") from exc
        if not items:
            raise TleError(f"{path.name} no contiene TLE válidos")
        self._parsed[group] = (key[0], key[1], items)
        return items

    # -------------------------------------------------------------- descarga
    @staticmethod
    def _fetch(group: str) -> str:
        url = CELESTRAK_URL.format(group=group)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TleError(f"sin conexión con CelesTrak ({exc})") from exc
        if "1 " not in raw or "2 " not in raw:
            raise TleError("CelesTrak devolvió una respuesta sin TLE")
        return raw

    def _store(self, group: str, path: Path, text: str, count: int) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        self._meta[group] = {"fetched_at": time.time(), "count": count}
        self._write_meta()
        self._parsed.pop(group, None)

    # ------------------------------------------------------------------- API
    def _group(self, group: str, max_age_s: float, force: bool) -> tuple[list[dict], dict]:
        path = self.dir / f"{group}.tle"
        meta = self._meta.get(group, {})
        fetched_at = meta.get("fetched_at")
        if fetched_at is None and path.exists():
            fetched_at = path.stat().st_mtime

        fresh = bool(fetched_at) and (time.time() - fetched_at) < max_age_s
        if not force and fresh and path.exists():
            items = self._parse_file(group, path)
            return items, {
                "id": group,
                "label": GROUPS.get(group, group),
                "count": len(items),
                "fetched_at": fetched_at,
                "stale": False,
                "error": None,
            }

        try:
            text = self._fetch(group)
            items = parse_tle(text)
            if not items:
                raise TleError("respuesta vacía")
            self._store(group, path, text, len(items))
            return items, {
                "id": group,
                "label": GROUPS.get(group, group),
                "count": len(items),
                "fetched_at": self._meta[group]["fetched_at"],
                "stale": False,
                "error": None,
            }
        except TleError as exc:
            if path.exists():
                items = self._parse_file(group, path)
                return items, {
                    "id": group,
                    "label": GROUPS.get(group, group),
                    "count": len(items),
                    "fetched_at": fetched_at,
                    "stale": True,
                    "error": str(exc),
                }
            raise

    def load(
        self,
        groups: list[str] | tuple[str, ...] | None = None,
        max_age_s: float = MAX_AGE_S,
        force: bool = False,
    ) -> tuple[dict[int, dict], list[dict]]:
        """Carga los grupos indicados y devuelve ``{norad: satélite}``.

        Los satélites presentes en varios grupos se deduplican y acumulan sus
        etiquetas en ``groups``.  Devuelve también el estado de cada grupo.
        """
        groups = list(groups or DEFAULT_GROUPS)
        entries: dict[int, dict] = {}
        statuses: list[dict] = []

        with self._lock:
            for group in groups:
                if group not in GROUPS:
                    continue
                try:
                    items, status = self._group(group, max_age_s, force)
                except TleError as exc:
                    statuses.append(
                        {
                            "id": group,
                            "label": GROUPS.get(group, group),
                            "count": 0,
                            "fetched_at": None,
                            "stale": False,
                            "error": str(exc),
                        }
                    )
                    continue
                statuses.append(status)
                for item in items:
                    prev = entries.get(item["norad"])
                    if prev is None:
                        entries[item["norad"]] = {**item, "groups": [group]}
                    elif group not in prev["groups"]:
                        prev["groups"].append(group)

        return entries, statuses
