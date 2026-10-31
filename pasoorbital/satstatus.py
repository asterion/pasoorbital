"""Estado operativo de satélites según el catálogo SATCAT de CelesTrak.

El código ``OPS_STATUS_CODE`` es información administrativa del catálogo: no
garantiza que el transmisor esté encendido. La aplicación debe mostrar siempre
la fuente y la fecha del dato.
"""

from __future__ import annotations

import csv
import json
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SATCAT_URL = "https://celestrak.org/pub/satcat.csv"
USER_AGENT = "PasoOrbital/1.9.2 (herramienta local de prediccion de pasos)"
CACHE_MAX_AGE_S = 24 * 3600


@dataclass(frozen=True)
class SatelliteStatus:
    norad: int
    code: str
    label: str
    source: str = "CelesTrak SATCAT"
    fetched_at: float = 0.0
    object_type: str = ""
    decay_date: str = ""

    @property
    def slug(self) -> str:
        return {
            "+": "operational",
            "-": "nonoperational",
            "P": "partial",
            "S": "standby",
            "B": "spare",
            "X": "extended",
            "D": "decayed",
            "?": "unknown",
        }.get(self.code, "unknown")

    @property
    def short(self) -> str:
        return {
            "+": "Operativo",
            "-": "No operativo",
            "P": "Parcial",
            "S": "En espera",
            "B": "Reserva",
            "X": "Extendido",
            "D": "Decaído",
            "?": "Desconocido",
        }.get(self.code, "Desconocido")

    def tooltip(self, now: float | None = None) -> str:
        when = "fecha desconocida"
        if self.fetched_at:
            age = max(0.0, (now if now is not None else time.time()) - self.fetched_at)
            if age < 3600:
                when = f"actualizado hace {max(1, round(age / 60))} min"
            elif age < 48 * 3600:
                when = f"actualizado hace {round(age / 3600)} h"
            else:
                when = f"actualizado hace {round(age / 86400)} d"
        lines = [
            f"{self.short} · {self.source}",
            when,
            "El estado del catálogo no garantiza que el satélite esté transmitiendo.",
        ]
        if self.decay_date:
            lines.append(f"Fecha de decaimiento: {self.decay_date}")
        return "\n".join(lines)


def label_for_code(code: str) -> str:
    return {
        "+": "Operativo",
        "-": "No operativo",
        "P": "Parcialmente operativo",
        "S": "En espera",
        "B": "Reserva",
        "X": "Misión extendida",
        "D": "Decaído",
        "?": "Desconocido",
    }.get(code, f"Desconocido ({code or 'sin código'})")


def parse_satcat(
    rows: Iterable[dict[str, str]], fetched_at: float = 0.0
) -> dict[int, SatelliteStatus]:
    """Convierte filas del CSV de SATCAT en un índice por NORAD."""
    statuses: dict[int, SatelliteStatus] = {}
    for row in rows:
        raw_norad = (row.get("NORAD_CAT_ID") or "").strip()
        if not raw_norad:
            continue
        try:
            norad = int(raw_norad)
        except ValueError:
            continue
        code = (row.get("OPS_STATUS_CODE") or "?").strip() or "?"
        statuses[norad] = SatelliteStatus(
            norad=norad,
            code=code,
            label=label_for_code(code),
            fetched_at=fetched_at,
            object_type=(row.get("OBJECT_TYPE") or "").strip(),
            decay_date=(row.get("DECAY_DATE") or "").strip(),
        )
    return statuses


class StatusDB:
    """Descarga y cachea el SATCAT completo."""

    def __init__(self, cache_dir: Path):
        self.dir = Path(cache_dir) / "status"
        self.csv_path = self.dir / "satcat.csv"
        self.meta_path = self.dir / "meta.json"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _read_meta(self) -> dict:
        try:
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write_meta(self, fetched_at: float) -> None:
        tmp = self.meta_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {"fetched_at": fetched_at, "source": "CelesTrak SATCAT", "url": SATCAT_URL},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp.replace(self.meta_path)

    def _parse_path(self, fetched_at: float) -> dict[int, SatelliteStatus]:
        with self.csv_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            return parse_satcat(csv.DictReader(handle), fetched_at)

    def _fresh(self) -> bool:
        return (
            self.csv_path.exists()
            and self.csv_path.stat().st_size > 0
            and time.time() - self.csv_path.stat().st_mtime < CACHE_MAX_AGE_S
        )

    def _download(self) -> dict[int, SatelliteStatus]:
        request = urllib.request.Request(SATCAT_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=40) as response:
            data = response.read()
        if not data:
            raise OSError("CelesTrak devolvió un SATCAT vacío")
        tmp = self.csv_path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(self.csv_path)
        fetched_at = time.time()
        self._write_meta(fetched_at)
        return self._parse_path(fetched_at)

    def load(self, force: bool = False) -> dict[int, SatelliteStatus]:
        """Devuelve el estado por NORAD; usa caché y tolera fallos de red."""
        try:
            if not force and self._fresh():
                return self._parse_path(self._read_meta().get("fetched_at", 0.0))
            try:
                return self._download()
            except Exception:
                if self.csv_path.exists():
                    return self._parse_path(self._read_meta().get("fetched_at", 0.0))
                return {}
        except Exception:
            return {}
