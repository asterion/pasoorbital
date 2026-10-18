"""Predicción de pasos de satélites sobre un observador.

Propaga la órbita con SGP4 (paquete ``sgp4``) y calcula la geometría
topocéntrica: azimut, elevación, distancia y velocidad radial (necesaria
para el efecto Doppler).

Convenios
---------
* tiempos: segundos desde la época Unix, en UTC
* distancias: km; velocidades: km/s
* azimut: 0° = norte, 90° = este; elevación: 0° = horizonte, 90° = cenit
"""

from __future__ import annotations

import math

import numpy as np
from sgp4.api import Satrec, SatrecArray

WGS84_A = 6378.137  # semieje mayor (km)
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)
C_KM_S = 299792.458  # velocidad de la luz (km/s)
OMEGA_EARTH = 7.2921150e-5  # rotación terrestre (rad/s)
J2000_JD = 2451545.0
UNIX_JD = 2440587.5
#: Los satélites geostacionarios no tienen "pasos": están siempre en el mismo
#: punto del cielo. Se excluyen de la predicción (período ≈ 1436 min).
GSO_PERIOD_MIN = 1200.0


class Observer:
    """Observador geodésico (WGS84) con su base local este-norte-cenit."""

    def __init__(self, lat: float, lon: float, alt_m: float = 0.0):
        if not -90.0 <= lat <= 90.0:
            raise ValueError("la latitud debe estar entre -90 y 90")
        if not -180.0 <= lon <= 180.0:
            raise ValueError("la longitud debe estar entre -180 y 180")
        self.lat = float(lat)
        self.lon = float(lon)
        self.alt_m = float(alt_m)

        phi = math.radians(self.lat)
        lam = math.radians(self.lon)
        self.sin_lat, self.cos_lat = math.sin(phi), math.cos(phi)
        self.sin_lon, self.cos_lon = math.sin(lam), math.cos(lam)

        n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * self.sin_lat**2)
        h = self.alt_m / 1000.0
        self.ecef = np.array(
            [
                (n + h) * self.cos_lat * self.cos_lon,
                (n + h) * self.cos_lat * self.sin_lon,
                (n * (1.0 - WGS84_E2) + h) * self.sin_lat,
            ]
        )
        self.east = np.array([-self.sin_lon, self.cos_lon, 0.0])
        self.north = np.array(
            [
                -self.sin_lat * self.cos_lon,
                -self.sin_lat * self.sin_lon,
                self.cos_lat,
            ]
        )
        self.up = np.array(
            [self.cos_lat * self.cos_lon, self.cos_lat * self.sin_lon, self.sin_lat]
        )


def gmst_rad(jd):
    """Tiempo sidéreo medio de Greenwich (IAU 1982) en radianes."""
    d = jd - J2000_JD
    t = d / 36525.0
    theta = (
        280.46061837
        + 360.98564736629 * d
        + 0.000387933 * t * t
        - (t * t * t) / 38710000.0
    )
    return np.deg2rad(np.mod(theta, 360.0))


def gmst_rad_scalar(jd: float) -> float:
    """Igual que :func:`gmst_rad` pero para un único instante (más rápido)."""
    d = jd - J2000_JD
    t = d / 36525.0
    theta = (
        280.46061837
        + 360.98564736629 * d
        + 0.000387933 * t * t
        - (t * t * t) / 38710000.0
    )
    return math.radians(theta % 360.0)


def _look_scalar(obs: Observer, r, v, jd: float):
    """Versión escalar de :func:`_look` con matemáticas puras."""
    theta = gmst_rad_scalar(jd)
    ct, st = math.cos(theta), math.sin(theta)

    x = ct * r[0] + st * r[1]
    y = -st * r[0] + ct * r[1]
    z = r[2]
    vx = ct * v[0] + st * v[1] + OMEGA_EARTH * y
    vy = -st * v[0] + ct * v[1] - OMEGA_EARTH * x
    vz = v[2]

    dx = x - obs.ecef[0]
    dy = y - obs.ecef[1]
    dz = z - obs.ecef[2]

    east = -obs.sin_lon * dx + obs.cos_lon * dy
    north = (
        -obs.sin_lat * obs.cos_lon * dx
        - obs.sin_lat * obs.sin_lon * dy
        + obs.cos_lat * dz
    )
    up = (
        obs.cos_lat * obs.cos_lon * dx
        + obs.cos_lat * obs.sin_lon * dy
        + obs.sin_lat * dz
    )

    rng = math.sqrt(east * east + north * north + up * up)
    el = math.degrees(math.asin(max(-1.0, min(1.0, up / rng))))
    az = math.degrees(math.atan2(east, north)) % 360.0
    rate = (dx * vx + dy * vy + dz * vz) / rng
    return az, el, rng, rate


def _look(obs: Observer, r, v, jd):
    """Geometría topocéntrica a partir de posición/velocidad TEME.

    Acepta arrays (N, 3) o un único vector (3,).  Devuelve azimut y elevación
    en grados, distancia en km y velocidad radial en km/s (positiva al
    alejarse).
    """
    theta = gmst_rad(jd)
    ct, st = np.cos(theta), np.sin(theta)

    # TEME -> ECEF (rotación por GMST; error por precesión despreciable aquí).
    x = ct * r[..., 0] + st * r[..., 1]
    y = -st * r[..., 0] + ct * r[..., 1]
    z = r[..., 2]

    # Velocidad en ECEF: rotar y restar la rotación terrestre.
    vx = ct * v[..., 0] + st * v[..., 1] + OMEGA_EARTH * y
    vy = -st * v[..., 0] + ct * v[..., 1] - OMEGA_EARTH * x
    vz = v[..., 2]

    dx = x - obs.ecef[0]
    dy = y - obs.ecef[1]
    dz = z - obs.ecef[2]

    east = -obs.sin_lon * dx + obs.cos_lon * dy
    north = (
        -obs.sin_lat * obs.cos_lon * dx
        - obs.sin_lat * obs.sin_lon * dy
        + obs.cos_lat * dz
    )
    up = (
        obs.cos_lat * obs.cos_lon * dx
        + obs.cos_lat * obs.sin_lon * dy
        + obs.sin_lat * dz
    )

    rng = np.sqrt(east * east + north * north + up * up)
    el = np.degrees(np.arcsin(np.clip(up / rng, -1.0, 1.0)))
    az = np.mod(np.degrees(np.arctan2(east, north)), 360.0)
    rate = (dx * vx + dy * vy + dz * vz) / rng
    return az, el, rng, rate


def propagate(sat: Satrec, ts):
    """Propaga SGP4 para un array de tiempos. Devuelve (err, r, v, jd)."""
    ts = np.atleast_1d(np.asarray(ts, dtype=np.float64))
    jd = UNIX_JD + ts / 86400.0
    jd_i = np.floor(jd)
    fr = jd - jd_i
    err, r, v = SatrecArray([sat]).sgp4(jd_i, fr)
    return err[0], r[0], v[0], jd


def look_series(sat: Satrec, obs: Observer, ts):
    """Azimut, elevación, distancia y velocidad radial para varios tiempos."""
    err, r, v, jd = propagate(sat, ts)
    az, el, rng, rate = _look(obs, r, v, jd)
    bad = err != 0
    if np.any(bad):
        az = np.where(bad, np.nan, az)
        el = np.where(bad, np.nan, el)
        rng = np.where(bad, np.nan, rng)
        rate = np.where(bad, np.nan, rate)
    return az, el, rng, rate


def look_at(sat: Satrec, obs: Observer, t: float):
    """Instante único: (az, el, distancia, velocidad radial) o ``None``."""
    jd = UNIX_JD + float(t) / 86400.0
    e, r, v = sat.sgp4(int(jd), jd - int(jd))
    if e != 0:
        return None
    az, el, rng, rate = _look_scalar(obs, r, v, jd)
    return float(az), float(el), float(rng), float(rate)


def _el_at(sat: Satrec, obs: Observer, t: float) -> float:
    st = look_at(sat, obs, t)
    return -90.0 if st is None else st[1]


def _bisect_crossing(sat: Satrec, obs: Observer, a: float, b: float, min_el: float) -> float:
    """Bisección del cruce de elevación ``min_el`` en [a, b]."""
    fa = _el_at(sat, obs, a) - min_el
    for _ in range(22):
        m = 0.5 * (a + b)
        fm = _el_at(sat, obs, m) - min_el
        if (fa >= 0.0) == (fm >= 0.0):
            a, fa = m, fm
        else:
            b = m
    return 0.5 * (a + b)


def _parabola_vertex(t1, e1, t2, e2, t3, e3) -> float:
    """Vértice de la parábola por (t1,e1), (t2,e2), (t3,e3); t2 si no es cóncava."""
    den = e1 - 2.0 * e2 + e3
    if abs(den) < 1e-12:
        return t2
    return t2 + 0.5 * (e1 - e3) / den * (t3 - t1) / 2.0


def _maximize(sat: Satrec, obs: Observer, ts, el, k: int, t_aos: float, t_los: float) -> float:
    """Instante de máxima elevación alrededor del máximo muestreado ``k``.

    Ajusta una parábola a los tres puntos muestreados y refina con un segundo
    ajuste alrededor del vértice (3 evaluaciones extra en total).
    """
    n = len(ts)
    i0 = max(0, k - 1)
    i2 = min(n - 1, k + 1)
    if i2 <= i0:
        return float(ts[k])

    t = _parabola_vertex(float(ts[i0]), el[i0], float(ts[k]), el[k], float(ts[i2]), el[i2])
    t = min(max(t, t_aos), t_los)

    h = max(2.0, min(60.0, float(ts[i2] - ts[i0])) * 0.25)
    t1, t3 = t - h, t + h
    if t1 < t_aos or t3 > t_los:
        return t
    e1 = _el_at(sat, obs, t1)
    e2 = _el_at(sat, obs, t)
    e3 = _el_at(sat, obs, t3)
    t_new = _parabola_vertex(t1, e1, t, e2, t3, e3)
    return min(max(t_new, t_aos), t_los)


def visible_possible(sat: Satrec, lat: float) -> bool:
    """Descarte rápido: ¿puede este satélite verse desde esa latitud?"""
    incl = math.degrees(sat.inclo)
    max_lat = incl if incl <= 90.0 else 180.0 - incl
    alt = max(1.0, (sat.a - 1.0) * WGS84_A) if sat.a else 500.0
    horizon = math.degrees(math.acos(WGS84_A / (WGS84_A + alt)))
    return abs(lat) <= max_lat + horizon + 2.0


def find_passes(
    sat: Satrec,
    obs: Observer,
    t0: float,
    t1: float,
    min_el: float = 5.0,
    step: float = 10.0,
) -> list[dict]:
    """Pasos del satélite por encima de ``min_el`` en la ventana [t0, t1].

    Estrategia: muestreo uniforme a ``step`` segundos, detección de cruces y
    refinamiento por bisección (AOS/LOS) y sección áurea (TCA).
    """
    t0, t1 = float(t0), float(t1)
    if t1 <= t0 or not visible_possible(sat, obs.lat):
        return []
    if sat.no and (2.0 * math.pi / sat.no) > GSO_PERIOD_MIN:
        return []

    ts = np.arange(t0, t1, step, dtype=np.float64)
    if ts.size == 0 or ts[-1] < t1:
        ts = np.append(ts, t1)

    az, el, rng, rate = look_series(sat, obs, ts)
    above = np.isfinite(el) & (el >= min_el)
    n = len(ts)

    d = np.diff(above.astype(np.int8))
    rises = np.flatnonzero(d == 1) + 1
    falls = np.flatnonzero(d == -1) + 1

    starts = np.concatenate(([0], rises)) if above[0] else rises
    ends = np.concatenate((falls, [n - 1])) if above[-1] else falls
    if starts.size != ends.size:
        return []

    out: list[dict] = []
    for i0, i1 in zip(starts.tolist(), ends.tolist()):
        p = _build_pass(sat, obs, ts, el, rate, above, i0, i1, min_el)
        if p is not None:
            out.append(p)
    return out


def _build_pass(sat, obs, ts, el, rate, above, i0: int, i1: int, min_el: float):
    n = len(ts)
    partial_start = i0 == 0 and bool(above[0])
    partial_end = i1 == n - 1 and bool(above[-1])

    if partial_start:
        t_aos = float(ts[0])
    else:
        t_aos = _bisect_crossing(sat, obs, float(ts[i0 - 1]), float(ts[i0]), min_el)

    if partial_end:
        t_los = float(ts[-1])
    else:
        t_los = _bisect_crossing(sat, obs, float(ts[i1 - 1]), float(ts[i1]), min_el)

    seg = el[i0 : i1 + 1]
    if not np.any(np.isfinite(seg)):
        return None
    k = i0 + int(np.nanargmax(seg))

    if i1 > i0:
        t_tca = _maximize(sat, obs, ts, el, k, t_aos, t_los)
    else:
        t_tca = float(ts[k])

    st_aos = look_at(sat, obs, t_aos)
    st_tca = look_at(sat, obs, t_tca)
    st_los = look_at(sat, obs, t_los)
    if st_aos is None or st_tca is None or st_los is None:
        return None

    rate_max = float(np.nanmax(np.abs(rate[i0 : i1 + 1])))
    if not math.isfinite(rate_max):
        rate_max = max(abs(st_aos[3]), abs(st_los[3]))

    return {
        "aos": t_aos,
        "tca": t_tca,
        "los": t_los,
        "max_el": st_tca[1],
        "az_aos": st_aos[0],
        "az_tca": st_tca[0],
        "az_los": st_los[0],
        "range_aos": st_aos[2],
        "range_tca": st_tca[2],
        "range_los": st_los[2],
        "rate_aos": st_aos[3],
        "rate_tca": st_tca[3],
        "rate_los": st_los[3],
        "rate_max": rate_max,
        "partial_start": partial_start,
        "partial_end": partial_end,
    }


def track(sat: Satrec, obs: Observer, t0: float, t1: float, n: int = 160):
    """Trayectoria aparente (az/el/distancia/velocidad radial) entre t0 y t1."""
    ts = np.linspace(float(t0), float(t1), int(n))
    az, el, rng, rate = look_series(sat, obs, ts)
    return ts, az, el, rng, rate
