#!/usr/bin/env python3
"""Servidor local de PasoOrbital.

Uso::

    python app.py                 # http://127.0.0.1:8765
    python app.py --port 9000
    python app.py --refresh       # fuerza la descarga de TLE al arrancar

La interfaz web está en ``static/`` y la API en ``/api/*``.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from pasoorbital import freqs, geo, passes, tle  # noqa: E402

STATIC = ROOT / "static"
DATA = ROOT / "data"
MAX_BODY = 1 << 20  # 1 MB

CATALOG = tle.Catalogue(DATA)
FREQS = freqs.FrequencyDB(DATA)
GEOCODER = geo.Geocoder(DATA)
START_TIME = time.time()


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status
        self.message = message


def iso(ts: float) -> str:
    return (
        datetime.fromtimestamp(float(ts), timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def sat_public(entry: dict) -> dict:
    chans = FREQS.lookup(entry["norad"], entry["name"])
    age = max(0.0, (time.time() - entry["epoch_ts"]) / 86400.0)
    return {
        "norad": entry["norad"],
        "name": entry["name"],
        "groups": entry["groups"],
        "epoch_ts": round(entry["epoch_ts"], 1),
        "tle_age_days": round(age, 2),
        "incl_deg": round(entry["incl_deg"], 2),
        "period_min": round(entry["period_min"], 2),
        "alt_km": round(entry["alt_km"], 1),
        "channels": chans,
    }


def pass_public(entry: dict, item: dict, chans: list[dict]) -> dict:
    freq = chans[0]["freq_hz"] if chans else None
    mode = chans[0].get("mode") if chans else None
    label = chans[0].get("label") if chans else None
    age = max(0.0, (time.time() - entry["epoch_ts"]) / 86400.0)

    def dop(rate: float) -> float | None:
        return round(-rate / passes.C_KM_S * freq, 1) if freq else None

    return {
        "norad": entry["norad"],
        "name": entry["name"],
        "aos_ts": round(item["aos"], 2),
        "tca_ts": round(item["tca"], 2),
        "los_ts": round(item["los"], 2),
        "aos": iso(item["aos"]),
        "tca": iso(item["tca"]),
        "los": iso(item["los"]),
        "duration_s": round(item["los"] - item["aos"], 1),
        "max_el": round(item["max_el"], 2),
        "az_aos": round(item["az_aos"], 1),
        "az_tca": round(item["az_tca"], 1),
        "az_los": round(item["az_los"], 1),
        "range_tca": round(item["range_tca"], 1),
        "rate_aos": round(item["rate_aos"], 4),
        "rate_tca": round(item["rate_tca"], 4),
        "rate_los": round(item["rate_los"], 4),
        "rate_max": round(item["rate_max"], 4),
        "partial_start": item["partial_start"],
        "partial_end": item["partial_end"],
        "tle_age_days": round(age, 2),
        "freq_hz": freq,
        "mode": mode,
        "label": label,
        "doppler_aos_hz": dop(item["rate_aos"]),
        "doppler_los_hz": dop(item["rate_los"]),
        "doppler_max_hz": round(item["rate_max"] / passes.C_KM_S * freq, 1) if freq else None,
    }


def parse_start(value) -> float:
    if value in (None, "", "now"):
        return time.time()
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(f"fecha no válida: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _num(data: dict, key: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(data.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ApiError(f"«{key}» debe ser un número") from exc
    if not (lo <= value <= hi):
        raise ApiError(f"«{key}» fuera de rango ({lo}–{hi})")
    return value


def _coord(data: dict, key: str, lo: float, hi: float) -> float:
    if key not in data or data[key] in (None, ""):
        raise ApiError(f"falta «{key}» (latitud y longitud del observador)")
    return _num(data, key, 0.0, lo, hi)


def api_catalog(query: dict) -> dict:
    raw = query.get("groups", [",".join(tle.GROUPS)])[0]
    groups = [g.strip() for g in raw.split(",") if g.strip() in tle.GROUPS]
    if not groups:
        groups = list(tle.GROUPS)
    refresh = query.get("refresh", ["0"])[0] in ("1", "true", "yes")
    entries, statuses = CATALOG.load(groups, force=refresh)

    if not entries and any(s.get("error") for s in statuses):
        raise ApiError(
            "No se pudo obtener ningún catálogo TLE: "
            + "; ".join(s["error"] for s in statuses if s.get("error")),
            502,
        )

    satellites = [sat_public(e) for e in entries.values()]
    satellites.sort(key=lambda s: s["name"].upper())
    return {"satellites": satellites, "groups": statuses, "now": time.time()}


def api_passes(data: dict) -> dict:
    t_start = time.perf_counter()
    lat = _coord(data, "lat", -90.0, 90.0)
    lon = _coord(data, "lon", -180.0, 180.0)
    alt = _num(data, "alt_m", 0.0, -500.0, 9000.0)
    days = _num(data, "days", 2.0, 0.05, 14.0)
    min_el = _num(data, "min_el", 5.0, 0.0, 80.0)
    start = parse_start(data.get("start"))
    t1 = start + days * 86400.0

    groups = data.get("groups") or list(tle.DEFAULT_GROUPS)
    groups = [g for g in groups if g in tle.GROUPS]
    if not groups:
        raise ApiError("selecciona al menos un grupo de satélites")

    entries, statuses = CATALOG.load(groups)
    if not entries:
        raise ApiError("no hay satélites disponibles (revisa la conexión)", 502)

    norads = data.get("norads")
    if norads:
        wanted = {int(n) for n in norads if str(n).isdigit()}
        entries = {n: e for n, e in entries.items() if n in wanted}

    obs = passes.Observer(lat, lon, alt)
    step = min(60.0, max(10.0, days * 86400.0 / 12000.0))

    found: list[tuple[dict, dict]] = []
    for entry in entries.values():
        if not passes.visible_possible(entry["satrec"], lat):
            continue
        try:
            items = passes.find_passes(entry["satrec"], obs, start, t1, min_el, step)
        except Exception:  # una órbita corrupta no debe tumbar la petición
            traceback.print_exc()
            continue
        for item in items:
            found.append((entry, item))

    found.sort(key=lambda pair: pair[1]["aos"])
    truncated = len(found) > 2000
    found = found[:2000]

    out = []
    for entry, item in found:
        chans = FREQS.lookup(entry["norad"], entry["name"])
        out.append(pass_public(entry, item, chans))

    stamps = [s.get("fetched_at") for s in statuses if s.get("fetched_at")]
    oldest = min(stamps) if stamps else 0
    return {
        "passes": out,
        "meta": {
            "count": len(out),
            "satellites": len(entries),
            "observer": {"lat": lat, "lon": lon, "alt_m": alt},
            "t0": start,
            "t1": t1,
            "step_s": step,
            "elapsed_s": round(time.perf_counter() - t_start, 2),
            "truncated": truncated,
            "groups": statuses,
            "tle_oldest_refresh": oldest,
        },
    }


def api_track(data: dict) -> dict:
    lat = _coord(data, "lat", -90.0, 90.0)
    lon = _coord(data, "lon", -180.0, 180.0)
    alt = _num(data, "alt_m", 0.0, -500.0, 9000.0)
    try:
        norad = int(data.get("norad"))
    except (TypeError, ValueError) as exc:
        raise ApiError("falta el número NORAD") from exc
    aos = parse_start(data.get("aos"))
    los = parse_start(data.get("los"))
    if los <= aos:
        raise ApiError("el fin del paso debe ser posterior al inicio")

    entries, _ = CATALOG.load(list(tle.GROUPS))
    entry = entries.get(norad)
    if entry is None:
        raise ApiError("satélite desconocido", 404)

    obs = passes.Observer(lat, lon, alt)
    ts, az, el, rng, rate = passes.track(entry["satrec"], obs, aos, los, n=180)
    chans = FREQS.lookup(norad, entry["name"])
    freq = chans[0]["freq_hz"] if chans else None

    return {
        "norad": norad,
        "name": entry["name"],
        "aos": aos,
        "los": los,
        "channels": chans,
        "freq_hz": freq,
        "points": {
            "t": [round(float(v), 1) for v in ts],
            "az": [None if v != v else round(float(v), 2) for v in az],
            "el": [None if v != v else round(float(v), 2) for v in el],
            "rng": [None if v != v else round(float(v), 1) for v in rng],
            "rate": [None if v != v else round(float(v), 4) for v in rate],
        },
    }


def api_geocode(query: dict) -> dict:
    text = (query.get("q", [""])[0] or "").strip()
    if len(text) < 3:
        raise ApiError("escribe una dirección de al menos 3 caracteres")
    results = GEOCODER.search(text, limit=6)
    return {"query": text, "results": results}


def api_elevation(query: dict) -> dict:
    try:
        lat = float(query.get("lat", [""])[0])
        lon = float(query.get("lon", [""])[0])
    except (TypeError, ValueError) as exc:
        raise ApiError("indica latitud y longitud válidas") from exc
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ApiError("latitud o longitud fuera de rango")
    value = GEOCODER.elevation(lat, lon)
    if value is None:
        raise ApiError("no se pudo obtener la altitud del terreno", 502)
    return {
        "lat": lat,
        "lon": lon,
        "alt_m": round(value, 1),
        "source": "Open-Meteo · Copernicus DEM",
        "approx": True,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "PasoOrbital/1.6"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- helpers
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"error": message}, status=status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ApiError("petición demasiado grande", 413)
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError("JSON no válido") from exc
        if not isinstance(data, dict):
            raise ApiError("se esperaba un objeto JSON")
        return data

    # -------------------------------------------------------------- rutas
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/api/health":
                self._json({"ok": True, "uptime_s": round(time.time() - START_TIME, 1)})
            elif path == "/api/catalog":
                self._json(api_catalog(query))
            elif path == "/api/geocode":
                self._json(api_geocode(query))
            elif path == "/api/elevation":
                self._json(api_elevation(query))
            elif path.startswith("/api/"):
                self._error("ruta desconocida", 404)
            else:
                self._static(path)
        except ApiError as exc:
            self._error(exc.message, exc.status)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._error(f"error interno: {exc}", 500)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            data = self._body()
            if path == "/api/passes":
                self._json(api_passes(data))
            elif path == "/api/track":
                self._json(api_track(data))
            else:
                self._error("ruta desconocida", 404)
        except ApiError as exc:
            self._error(exc.message, exc.status)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._error(f"error interno: {exc}", 500)

    def _static(self, path: str) -> None:
        rel = path.lstrip("/") or "index.html"
        if rel == "favicon.ico":
            rel = "favicon.svg"
        if rel.startswith("static/"):
            rel = rel[len("static/") :]
        target = (STATIC / rel).resolve()
        try:
            target.relative_to(STATIC.resolve())
        except ValueError:
            self._error("ruta no válida", 403)
            return
        if not target.is_file():
            self._error("no encontrado", 404)
            return
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))


def main() -> int:
    parser = argparse.ArgumentParser(description="PasoOrbital — servidor local")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="no abrir el navegador")
    parser.add_argument("--refresh", action="store_true", help="descargar TLE al arrancar")
    args = parser.parse_args()

    if args.refresh:
        print("Descargando TLE de CelesTrak…", flush=True)
        _, statuses = CATALOG.load(list(tle.GROUPS), force=True)
        for s in statuses:
            state = "ERROR: " + s["error"] if s.get("error") else f"{s['count']} satélites"
            print(f"  {s['label']}: {state}")

    server = None
    port = args.port
    for candidate in range(args.port, args.port + 25):
        try:
            server = ThreadingHTTPServer((args.host, candidate), Handler)
            port = candidate
            break
        except OSError:
            continue
    if server is None:
        print("No hay ningún puerto libre entre", args.port, "y", args.port + 24, file=sys.stderr)
        return 1

    server.daemon_threads = True
    url = f"http://{args.host}:{port}/"
    print()
    print("  PasoOrbital · pasos de satélites para escucha", flush=True)
    print(f"  Interfaz: {url}", flush=True)
    print(f"  Datos:    {DATA}", flush=True)
    print("  Ctrl+C para detener", flush=True)
    print(flush=True)

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando…")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
