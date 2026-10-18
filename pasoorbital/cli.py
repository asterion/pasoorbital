"""Consulta rápida de pasos desde la terminal.

Ejemplo::

    python -m pasoorbital.cli --lat 40.4168 --lon -3.7038 --days 2
    python -m pasoorbital.cli --lat 40.4168 --lon -3.7038 --norad 25544 --json

La app web (``app.py``) ofrece lo mismo con interfaz gráfica.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import freqs, passes, tle

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _fmt_time(ts: float, utc: bool) -> str:
    dt = datetime.fromtimestamp(ts, timezone.utc if utc else None)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Predicción de pasos de satélites")
    p.add_argument("--lat", type=float, required=True, help="latitud del observador")
    p.add_argument("--lon", type=float, required=True, help="longitud del observador")
    p.add_argument("--alt", type=float, default=0.0, help="altitud en metros (por defecto 0)")
    p.add_argument("--days", type=float, default=2.0, help="días a predecir (por defecto 2)")
    p.add_argument("--min-el", type=float, default=5.0, help="elevación mínima en grados (5)")
    p.add_argument("--groups", default=",".join(tle.DEFAULT_GROUPS), help="grupos CelesTrak")
    p.add_argument("--norad", type=int, action="append", help="limitar a uno o varios NORAD")
    p.add_argument("--utc", action="store_true", help="mostrar horas en UTC")
    p.add_argument("--json", action="store_true", help="salida JSON")
    p.add_argument("--refresh", action="store_true", help="forzar descarga de TLE")
    args = p.parse_args(argv)

    groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    obs = passes.Observer(args.lat, args.lon, args.alt)
    catalog = tle.Catalogue(DATA)
    entries, statuses = catalog.load(groups, force=args.refresh)
    fdb = freqs.FrequencyDB(DATA)

    for status in statuses:
        if status.get("error"):
            print(f"[aviso] {status['label']}: {status['error']}", file=sys.stderr)

    t0 = time.time()
    step = min(60.0, max(10.0, args.days * 86400.0 / 12000.0))
    out = []
    for entry in entries.values():
        if args.norad and entry["norad"] not in args.norad:
            continue
        if not passes.visible_possible(entry["satrec"], obs.lat):
            continue
        for item in passes.find_passes(
            entry["satrec"], obs, t0, t0 + args.days * 86400.0, args.min_el, step
        ):
            chans = fdb.lookup(entry["norad"], entry["name"])
            freq = chans[0]["freq_hz"] if chans else None
            out.append({"sat": entry, "pass": item, "freq": freq, "channels": chans})

    out.sort(key=lambda x: x["pass"]["aos"])

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "norad": x["sat"]["norad"],
                        "name": x["sat"]["name"],
                        "aos": x["pass"]["aos"],
                        "tca": x["pass"]["tca"],
                        "los": x["pass"]["los"],
                        "max_el": round(x["pass"]["max_el"], 2),
                        "az_aos": round(x["pass"]["az_aos"], 1),
                        "az_los": round(x["pass"]["az_los"], 1),
                        "freq_hz": x["freq"],
                    }
                    for x in out
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    unidad = "día" if args.days == 1 else "días"
    print(f"Observador: {obs.lat:.4f}, {obs.lon:.4f}  ({args.days:g} {unidad}, el ≥ {args.min_el:g}°)")
    print()
    if not out:
        print("No hay pasos por encima de la elevación mínima en ese periodo.")
        return 0

    header = f"{'AOS':<19} {'LOS':<8} {'dur':>5} {'el':>4} {'az AOS→LOS':>12}  {'frecuencia':<12} satélite"
    print(header)
    print("-" * len(header))
    for x in out[:400]:
        item = x["pass"]
        dur = int(round(item["los"] - item["aos"]))
        mins, secs = divmod(dur, 60)
        freq = f"{x['freq'] / 1e6:.3f} MHz" if x["freq"] else "—"
        az = f"{item['az_aos']:.0f}° → {item['az_los']:.0f}°"
        print(
            f"{_fmt_time(item['aos'], args.utc):<19} "
            f"{datetime.fromtimestamp(item['los'], timezone.utc if args.utc else None).strftime('%H:%M:%S'):<8} "
            f"{mins:>2}m{secs:02d} "
            f"{item['max_el']:>4.0f}° "
            f"{az:>12}  {freq:<12} {x['sat']['name']}"
        )
    if len(out) > 400:
        print(f"... y {len(out) - 400} pasos más")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
