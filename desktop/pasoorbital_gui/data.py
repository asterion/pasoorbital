"""Capa de datos de la aplicación de escritorio.

Reutiliza el paquete ``pasoorbital`` (TLE, SGP4, frecuencias y geocodificación)
y añade objetos ligeros para la interfaz GTK.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from pasoorbital import freqs, geo, passes, tle


@dataclass
class Satellite:
    norad: int
    name: str
    satrec: object
    epoch_ts: float
    incl_deg: float
    period_min: float
    alt_km: float
    channels: list[dict] = field(default_factory=list)
    groups: tuple[str, ...] = ()

    @property
    def tle_age_days(self) -> float:
        return max(0.0, (time.time() - self.epoch_ts) / 86400.0)


@dataclass
class PassItem:
    sat: Satellite
    obs: passes.Observer
    aos: float
    tca: float
    los: float
    max_el: float
    az_aos: float
    az_tca: float
    az_los: float
    range_tca: float
    rate_aos: float
    rate_tca: float
    rate_los: float
    rate_max: float
    partial_start: bool
    partial_end: bool
    freq_hz: int | None
    mode: str | None
    label: str | None
    doppler_aos_hz: float | None
    doppler_tca_hz: float | None
    doppler_los_hz: float | None
    doppler_max_hz: float | None

    @property
    def duration_s(self) -> float:
        return self.los - self.aos

    @classmethod
    def from_raw(cls, sat: Satellite, obs: passes.Observer, raw: dict) -> "PassItem":
        channels = sat.channels
        freq = channels[0]["freq_hz"] if channels else None
        mode = channels[0].get("mode") if channels else None
        label = channels[0].get("label") if channels else None

        def dop(rate: float) -> float | None:
            return round(-rate / passes.C_KM_S * freq, 1) if freq else None

        return cls(
            sat=sat,
            obs=obs,
            aos=raw["aos"],
            tca=raw["tca"],
            los=raw["los"],
            max_el=raw["max_el"],
            az_aos=raw["az_aos"],
            az_tca=raw["az_tca"],
            az_los=raw["az_los"],
            range_tca=raw["range_tca"],
            rate_aos=raw["rate_aos"],
            rate_tca=raw["rate_tca"],
            rate_los=raw["rate_los"],
            rate_max=raw["rate_max"],
            partial_start=raw["partial_start"],
            partial_end=raw["partial_end"],
            freq_hz=freq,
            mode=mode,
            label=label,
            doppler_aos_hz=dop(raw["rate_aos"]),
            doppler_tca_hz=dop(raw["rate_tca"]),
            doppler_los_hz=dop(raw["rate_los"]),
            doppler_max_hz=round(raw["rate_max"] / passes.C_KM_S * freq, 1) if freq else None,
        )


def filter_passes(
    items: list[PassItem],
    query: str = "",
    only_freq: bool = False,
    groups: tuple[str, ...] | list[str] = (),
    min_el: float = 0.0,
    limit: float = float("inf"),
) -> list[PassItem]:
    """Aplica los filtros de la lista sin volver a calcular órbitas."""
    selected = set(groups)
    needle = query.strip().lower()
    out: list[PassItem] = []
    for item in items:
        if only_freq and item.freq_hz is None:
            continue
        if selected and not (set(item.sat.groups) & selected):
            continue
        if item.max_el < min_el or item.aos > limit:
            continue
        if needle and needle not in item.sat.name.lower():
            continue
        out.append(item)
    return out


class PasoOrbitalData:
    """Catálogo, frecuencias y cálculo de pasos para la interfaz."""

    def __init__(self, config_dir: Path, cache_dir: Path):
        self.config_dir = Path(config_dir)
        self.cache_dir = Path(cache_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.catalogue = tle.Catalogue(self.cache_dir)
        self.freqdb = freqs.FrequencyDB(self.config_dir)
        self.geocoder = geo.Geocoder(self.cache_dir)

        self.satellites: dict[int, Satellite] = {}
        self.tle_status: list[dict] = []
        self.last_tle_refresh = 0.0

    # ------------------------------------------------------------------
    def load_catalog(self, groups: list[str], force: bool = False) -> dict[int, Satellite]:
        entries, statuses = self.catalogue.load(groups, force=force)
        self.tle_status = statuses
        sats: dict[int, Satellite] = {}
        for entry in entries.values():
            sats[entry["norad"]] = Satellite(
                norad=entry["norad"],
                name=entry["name"],
                satrec=entry["satrec"],
                epoch_ts=entry["epoch_ts"],
                incl_deg=entry["incl_deg"],
                period_min=entry["period_min"],
                alt_km=entry["alt_km"],
                channels=self.freqdb.lookup(entry["norad"], entry["name"]),
                groups=tuple(entry.get("groups", ())),
            )
        self.satellites = sats
        stamps = [s.get("fetched_at") for s in statuses if s.get("fetched_at")]
        self.last_tle_refresh = max(stamps) if stamps else time.time()
        return sats

    # ------------------------------------------------------------------
    def find_passes(
        self,
        lat: float,
        lon: float,
        alt_m: float,
        days: float,
        min_el: float,
        groups: list[str],
        only_freq: bool,
    ) -> tuple[list[PassItem], float]:
        started = time.perf_counter()
        if not self.satellites:
            self.load_catalog(groups)

        obs = passes.Observer(lat, lon, alt_m)
        t0 = time.time()
        t1 = t0 + days * 86400.0
        step = min(60.0, max(10.0, days * 86400.0 / 12000.0))

        items: list[PassItem] = []
        for sat in self.satellites.values():
            if only_freq and not sat.channels:
                continue
            if not passes.visible_possible(sat.satrec, lat):
                continue
            for raw in passes.find_passes(sat.satrec, obs, t0, t1, min_el, step):
                items.append(PassItem.from_raw(sat, obs, raw))

        items.sort(key=lambda item: item.aos)
        return items, time.perf_counter() - started

    # ------------------------------------------------------------------
    def track(self, item: PassItem, n: int = 160):
        ts, az, el, rng, rate = passes.track(
            item.sat.satrec, item.obs, item.aos, item.los, n=n
        )
        return list(zip(ts.tolist(), az.tolist(), el.tolist(), rng.tolist(), rate.tolist()))

    # ------------------------------------------------------------------
    def tle_age_seconds(self) -> float:
        return max(0.0, time.time() - self.last_tle_refresh)
