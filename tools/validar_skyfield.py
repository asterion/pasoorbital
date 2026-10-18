"""Validación opcional de la geometría contra Skyfield.

Skyfield es una biblioteca independiente (usa también SGP4, pero su
transformación TEME→ITRS y su topocéntrico son independientes de este
proyecto).  Sirve para comprobar que azimut, elevación y velocidad radial
coinciden.

    pip install -r requirements-dev.txt
    python tools/validar_skyfield.py

La primera vez descarga el fichero de efemérides de421.bsp (~17 MB).
"""

from __future__ import annotations

import datetime
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pasoorbital import passes, tle  # noqa: E402


def main() -> int:
    entries, _ = tle.Catalogue(ROOT / "data").load(["stations"])
    iss = entries.get(25544)
    if iss is None:
        print("No hay TLE del ISS en data/tle/stations.tle")
        return 1

    from skyfield.api import EarthSatellite, load, wgs84

    ts = load.timescale()
    sat = EarthSatellite(iss["line1"], iss["line2"], iss["name"], ts)
    lat, lon, alt = 40.4168, -3.7038, 650.0
    topo = wgs84.latlon(lat, lon, elevation_m=alt)
    obs = passes.Observer(lat, lon, alt)

    t0 = time.time()
    res = passes.find_passes(iss["satrec"], obs, t0, t0 + 86400, 5.0, 10.0)
    print(f"{len(res)} pasos en 24 h; comparando {min(4, len(res))}…")

    worst_az = worst_el = worst_rate = 0.0
    for p in res[:4]:
        for label, t in (("AOS", p["aos"]), ("TCA", p["tca"]), ("LOS", p["los"])):
            when = ts.from_datetime(datetime.datetime.fromtimestamp(t, datetime.timezone.utc))
            alt_deg, az_deg, _ = (sat - topo).at(when).altaz()
            mine = passes.look_at(iss["satrec"], obs, t)
            daz = abs(((mine[0] - az_deg.degrees + 180.0) % 360.0) - 180.0)
            dele = abs(mine[1] - alt_deg.degrees)

            def rng(tt: float) -> float:
                w = ts.from_datetime(datetime.datetime.fromtimestamp(tt, datetime.timezone.utc))
                return (sat - topo).at(w).distance().km

            h = 0.5
            num_rate = (rng(t + h) - rng(t - h)) / (2 * h)
            drate = abs(mine[3] - num_rate)

            worst_az = max(worst_az, daz)
            worst_el = max(worst_el, dele)
            worst_rate = max(worst_rate, drate)
            print(f"  {label}: dAZ={daz:.4f}°  dEL={dele:.4f}°  dVrad={drate:.4f} km/s")

    print()
    print(f"Peor diferencia: azimut {worst_az:.4f}°, elevación {worst_el:.4f}°, velocidad {worst_rate:.4f} km/s")
    ok = worst_az < 0.05 and worst_el < 0.05 and worst_rate < 0.01
    print("OK" if ok else "REVISAR: diferencias mayores de lo esperado")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
