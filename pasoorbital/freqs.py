"""Frecuencias de escucha de satélites (base local, ampliable).

La clave es el número NORAD.  Cada satélite puede tener varios canales; el
primero se considera el principal (el que se muestra en la tabla).  Los datos
son orientativos: confirma siempre la frecuencia con la web de la misión o de
AMSAT antes de una escucha importante.

Para añadir o corregir frecuencias sin tocar el código, crea
``data/frequencies.json`` con el mismo formato::

    {
      "25544": [
        {"freq_hz": 145800000, "mode": "FM", "label": "Voz", "note": "..."}
      ]
    }

Ese fichero tiene prioridad sobre la base integrada.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# --- Base integrada ---------------------------------------------------------

CHANNELS: dict[int, list[dict]] = {
    # --- Estación Espacial Internacional ---------------------------------
    25544: [
        {
            "freq_hz": 145_800_000,
            "mode": "FM",
            "label": "Voz / SSTV",
            "uplink_hz": 145_200_000,
            "note": "Voz en FM (región 1: subida 145.200). SSTV en eventos, también en 145.800.",
        },
        {
            "freq_hz": 437_800_000,
            "mode": "FM",
            "label": "Repetidor FM (bajada)",
            "uplink_hz": 145_990_000,
            "tone_hz": 67.0,
            "note": "Subida 145.990 con tono 67.0 Hz.",
        },
        {
            "freq_hz": 145_825_000,
            "mode": "APRS",
            "label": "APRS / digipeater",
            "note": "AX.25 1200 bps AFSK.",
        },
    ],
    # --- Meteorológicos NOAA (APT) ----------------------------------------
    25338: [
        {
            "freq_hz": 137_620_000,
            "mode": "APT",
            "label": "APT (imagen analógica)",
            "note": "AM, 2 líneas/s. Decodifica con noaa-apt o wximg.",
        }
    ],
    28654: [
        {
            "freq_hz": 137_912_500,
            "mode": "APT",
            "label": "APT (imagen analógica)",
            "note": "AM, 2 líneas/s. Decodifica con noaa-apt o wximg.",
        }
    ],
    33591: [
        {
            "freq_hz": 137_100_000,
            "mode": "APT",
            "label": "APT (imagen analógica)",
            "note": "AM, 2 líneas/s. Decodifica con noaa-apt o wximg.",
        }
    ],
    # --- Meteor-M (LRPT digital) ------------------------------------------
    40069: [
        {
            "freq_hz": 137_100_000,
            "mode": "LRPT",
            "label": "LRPT (imagen digital)",
            "note": "Meteor-M N2; puede estar inactivo. Decodifica con SatDump.",
        }
    ],
    44387: [
        {
            "freq_hz": 137_100_000,
            "mode": "LRPT",
            "label": "LRPT (imagen digital)",
            "note": "Meteor-M2 2; puede estar inactivo. Decodifica con SatDump.",
        }
    ],
    57166: [
        {
            "freq_hz": 137_900_000,
            "mode": "LRPT",
            "label": "LRPT (imagen digital)",
            "note": "Meteor-M N2-3. Decodifica con SatDump; si no hay señal, prueba 137.1 MHz.",
        },
        {
            "freq_hz": 137_100_000,
            "mode": "LRPT",
            "label": "LRPT (frecuencia alternativa)",
            "note": "Meteor-M N2-3: algunas emisiones usan 137.1 MHz.",
        },
    ],
    59051: [
        {
            "freq_hz": 137_900_000,
            "mode": "LRPT",
            "label": "LRPT (imagen digital)",
            "note": "Meteor-M N2-4. Decodifica con SatDump; si no hay señal, prueba 137.1 MHz.",
        },
        {
            "freq_hz": 137_100_000,
            "mode": "LRPT",
            "label": "LRPT (frecuencia alternativa)",
            "note": "Meteor-M N2-4: frecuencia alternativa reportada.",
        },
    ],
    # --- Radioaficionados (AMSAT) -----------------------------------------
    7530: [  # AO-7
        {"freq_hz": 145_950_000, "mode": "SSB/CW", "label": "Transpondedor B (bajada)", "note": "Subida 432.125–432.175 MHz."},
        {"freq_hz": 29_450_000, "mode": "SSB/CW", "label": "Transpondedor A (bajada)", "note": "Subida 145.850–145.900 MHz."},
    ],
    22825: [  # AO-27
        {"freq_hz": 436_795_000, "mode": "FM", "label": "Repetidor FM (bajada)", "note": "Subida 145.850 MHz."}
    ],
    24278: [  # FO-29
        {"freq_hz": 435_800_000, "mode": "SSB/CW", "label": "Transpondedor (bajada)", "note": "Subida 145.900–146.000 MHz."}
    ],
    27607: [  # SO-50
        {"freq_hz": 436_795_000, "mode": "FM", "label": "Repetidor FM (bajada)", "uplink_hz": 145_850_000, "tone_hz": 67.0, "note": "Subida 145.850 con tono 67.0 Hz."}
    ],
    39444: [  # AO-73 / Funcube-1
        {"freq_hz": 145_935_000, "mode": "SSB/CW", "label": "Transpondedor (bajada)", "note": "Subida 435.150–435.130 MHz."}
    ],
    40967: [  # AO-85 / Fox-1A
        {"freq_hz": 145_980_000, "mode": "FM", "label": "Repetidor FM (bajada)", "note": "Subida 435.180 MHz."}
    ],
    43770: [  # AO-95 / Fox-1Cliff
        {"freq_hz": 145_920_000, "mode": "FM", "label": "Repetidor FM (bajada)", "note": "Subida 435.300 MHz (verificar)."}
    ],
    42017: [  # EO-88 / Nayif-1
        {"freq_hz": 145_939_000, "mode": "SSB/CW", "label": "Transpondedor (bajada)", "note": "Subida 435.045 MHz (aprox.)."}
    ],
    43017: [  # AO-91
        {"freq_hz": 145_960_000, "mode": "FM", "label": "Repetidor FM (bajada)", "note": "Subida 435.250 MHz."}
    ],
    43137: [  # AO-92
        {"freq_hz": 145_880_000, "mode": "FM", "label": "Repetidor FM (bajada)", "note": "Subida 435.350 MHz."}
    ],
    43678: [  # PO-101 / Diwata-2
        {"freq_hz": 145_900_000, "mode": "FM", "label": "Repetidor FM (bajada)", "note": "Subida 437.500 MHz."}
    ],
    44909: [  # RS-44
        {"freq_hz": 435_610_000, "mode": "SSB/CW", "label": "Transpondedor (bajada)", "note": "Subida 145.935–145.965 MHz."}
    ],
    42761: [  # CAS-4A
        {"freq_hz": 145_855_000, "mode": "SSB/CW", "label": "Transpondedor (bajada)", "note": "Subida 435.220 MHz (verificar)."}
    ],
    42759: [  # CAS-4B
        {"freq_hz": 145_925_000, "mode": "SSB/CW", "label": "Transpondedor (bajada)", "note": "Subida 435.270 MHz (verificar)."}
    ],
}

#: Reglas por nombre, por si cambia el número NORAD de algún satélite.
NAME_RULES: list[tuple[re.Pattern, list[dict]]] = [
    (re.compile(r"^ISS \(ZARYA\)$|^ZARYA$", re.I), CHANNELS[25544]),
    (re.compile(r"NOAA\s*15\b", re.I), CHANNELS[25338]),
    (re.compile(r"NOAA\s*18\b", re.I), CHANNELS[28654]),
    (re.compile(r"NOAA\s*19\b", re.I), CHANNELS[33591]),
    (re.compile(r"METEOR-M.*N2-3", re.I), CHANNELS[57166]),
    (re.compile(r"METEOR-M.*N2-4", re.I), CHANNELS[59051]),
]


class FrequencyDB:
    """Consulta de frecuencias con posibilidad de sobrescritura local."""

    def __init__(self, data_dir: str | Path | None = None):
        self.user: dict[int, list[dict]] = {}
        if data_dir is not None:
            path = Path(data_dir) / "frequencies.json"
            if path.exists():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    for key, value in raw.items():
                        try:
                            norad = int(key)
                        except ValueError:
                            continue
                        if isinstance(value, list):
                            self.user[norad] = [c for c in value if isinstance(c, dict)]
                except (OSError, ValueError):
                    self.user = {}

    def lookup(self, norad: int, name: str = "") -> list[dict]:
        chans = self.user.get(int(norad)) or CHANNELS.get(int(norad))
        if chans is None and name:
            for pattern, rule in NAME_RULES:
                if pattern.search(name):
                    chans = rule
                    break
        return [dict(c) for c in (chans or [])]
