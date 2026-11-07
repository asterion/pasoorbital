"""Formato y textos en lenguaje llano para la interfaz GTK."""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone

from .data import PassItem

WEEKDAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
COMPASS_WORDS = [
    "norte",
    "noreste",
    "este",
    "sureste",
    "sur",
    "suroeste",
    "oeste",
    "noroeste",
]


def fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def fmt_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M:%S")


def short_address(name: str) -> str:
    """Resume una dirección larga para mostrarla en una sola línea.

    Conserva el primer componente y el país, y elimina códigos postales
    numéricos. La dirección completa se mantiene en la configuración y en el
    tooltip.
    """
    text = " ".join(str(name or "").split()).strip()
    if not text:
        return ""
    parts = [part.strip() for part in text.split(",") if part.strip()]
    parts = [part for part in parts if not part.isdigit()]
    if not parts:
        return text
    if len(parts) <= 2:
        return ", ".join(parts)
    first, last = parts[0], parts[-1]
    if first.casefold() == last.casefold():
        return first
    summary = f"{first}, {last}"
    if len(summary) > 48:
        summary = summary[:47].rstrip() + "…"
    return summary


def fmt_hm(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def relative_day(ts: float) -> str:
    day = datetime.fromtimestamp(ts).date()
    today = datetime.now().date()
    delta = (day - today).days
    if delta == 0:
        return "hoy"
    if delta == 1:
        return "mañana"
    return f"{WEEKDAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]}"


def fmt_dur(seconds: float) -> str:
    total = max(0, round(seconds))
    if total < 60:
        return "< 1 min"
    mins = round(total / 60)
    if mins < 60:
        return f"{mins} min"
    hours, rest = divmod(mins, 60)
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def fmt_age(seconds: float) -> str:
    if seconds < 3600:
        return f"hace {max(1, round(seconds / 60))} min"
    if seconds < 48 * 3600:
        return f"hace {round(seconds / 3600)} h"
    return f"hace {round(seconds / 86400)} d"


def compass_index(deg: float) -> int:
    return round(((deg % 360) + 360) % 360 / 45) % 8


def compass_word(deg: float) -> str:
    return COMPASS_WORDS[compass_index(deg)]


def fmt_freq(hz: int | None) -> str:
    """Frecuencia en MHz con tres decimales fijos y coma decimal."""
    if not hz:
        return "—"
    return f"{hz / 1e6:.3f}".replace(".", ",") + " MHz"


def fmt_deg(value: float, decimals: int = 1) -> str:
    """Grados con coma decimal y sin ceros sobrantes: «15,8°», «38°»."""
    text = f"{value:.{decimals}f}".replace(".", ",")
    if "," in text:
        text = text.rstrip("0").rstrip(",")
    return text + "°"


def fmt_km(km: float) -> str:
    """Distancia en km con separador de millares: «686 km», «1 208 km»."""
    return f"{round(km):,}".replace(",", " ") + " km"


def pass_quality(max_el: float) -> str:
    """Calificación divulgativa de un paso según su elevación máxima."""
    if max_el >= 60:
        return "paso muy alto"
    if max_el >= 30:
        return "paso alto"
    if max_el >= 15:
        return "paso aceptable"
    return "paso bajo"


def fmt_dop(hz: float | None) -> str:
    if hz is None:
        return "—"
    khz = hz / 1000.0
    if abs(khz) < 0.05:
        return "0,0 kHz"
    sign = "+" if khz > 0 else "−"
    return f"{sign}{abs(khz):.1f} kHz".replace(".", ",")


def fmt_az(deg: float) -> str:
    return f"{compass_word(deg).capitalize()} · {round(deg)}°"


def _esc(text: str) -> str:
    return html.escape(str(text), quote=False)


#: Nombre divulgativo de los tipos de OSM que devuelve Nominatim/Photon.
TYPE_NAMES = {
    "city": "ciudad",
    "town": "pueblo",
    "village": "pueblo",
    "hamlet": "aldea",
    "administrative": "comuna (administrativa)",
    "state": "región",
    "region": "región",
    "county": "provincia",
    "suburb": "barrio",
    "neighbourhood": "barrio",
    "residential": "zona residencial",
    "road": "calle",
    "house": "edificio",
    "building": "edificio",
    "country": "país",
    "municipality": "municipio",
    "locality": "localidad",
    "isolated_dwelling": "vivienda aislada",
    "postcode": "código postal",
}


def type_label(osm_type: str | None) -> str:
    """Traduce el tipo de OSM a una etiqueta corta en español."""
    return TYPE_NAMES.get((osm_type or "").lower(), (osm_type or "").replace("_", " "))


def geo_icon(osm_type: str | None) -> str:
    """Icono simbólico de Adwaita según el tipo de resultado."""
    tipo = (osm_type or "").lower()
    if tipo in ("city", "town", "village", "hamlet", "municipality", "locality",
                "isolated_dwelling", "house", "building", "road", "residential"):
        return "mark-location-symbolic"
    if tipo in ("administrative", "state", "region", "county", "suburb",
                "neighbourhood", "country", "postcode"):
        return "map-symbolic"
    return "mark-location-symbolic"


#: Polarizaciones de recepción y cómo se le explican al usuario.
POLARIZATIONS = {
    "RHCP": "circular a la derecha (RHCP)",
    "LHCP": "circular a la izquierda (LHCP)",
    "linear": "lineal (vertical u horizontal)",
}


def polarization_label(code: str | None) -> str:
    """Texto divulgativo de la polarización de un canal."""
    return POLARIZATIONS.get((code or "").upper(), POLARIZATIONS.get(code or "", ""))


def fmt_coords(lat: float, lon: float) -> str:
    """Coordenadas con coma decimal y cuatro decimales, separadas por «·»."""
    return f"{lat:.4f} · {lon:.4f}".replace(".", ",")


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:40] or "pasoorbital"


def summary(item: PassItem) -> str:
    """Frase divulgativa de una o dos líneas, sin marcas y sin artículo.

    Va como texto secundario del detalle: la información accionable está en las
    tarjetas, así que aquí solo se cuenta el paso en lenguaje llano.
    """
    name = item.sat.name
    dir_a = compass_word(item.az_aos)
    dir_l = compass_word(item.az_los)
    el = fmt_deg(item.max_el)

    if item.partial_start:
        return (
            f"{name} ya está en curso: ahora va por el {dir_a}, llega a {el} sobre el "
            f"horizonte a las {fmt_time(item.tca)} y se va por el {dir_l} a las "
            f"{fmt_time(item.los)}."
        )
    if item.partial_end:
        return (
            f"{name} aparece por el {dir_a} a las {fmt_time(item.aos)} y llega a {el} "
            f"sobre el horizonte a las {fmt_time(item.tca)}. Sigue visible al menos "
            f"hasta el final de la ventana ({fmt_time(item.los)})."
        )
    return (
        f"{name} aparece por el {dir_a} a las {fmt_time(item.aos)}, sube hasta {el} "
        f"sobre el horizonte a las {fmt_time(item.tca)} y se va por el {dir_l} a las "
        f"{fmt_time(item.los)}. Dura {fmt_dur(item.duration_s)}."
    )


def command_for(channel: dict, item: PassItem) -> str:
    hz = channel.get("freq_hz") or 0
    mhz = f"{hz / 1e6:.4f}".rstrip("0").rstrip(".")
    lrpt_mhz = f"{hz / 1e6:.3f}".rstrip("0").rstrip(".")
    slug = _slug(item.sat.name)
    mode = (channel.get("mode") or "").upper()

    if "APT" in mode:
        return (
            "# APT: graba el paso y decodifica la imagen\n"
            f"rtl_fm -f {mhz}M -M fm -s 60k -r 60k -g 40 | \\\n"
            f"  sox -t raw -r 60k -e s -b 16 -c 1 - -r 11025 {slug}.wav\n"
            f"noaa-apt {slug}.wav -o {slug}.png"
        )
    if "LRPT" in mode:
        return (
            "# LRPT con SatDump 1.2.2 (Ctrl+C para terminar)\n"
            f"satdump live meteor_m2-x_lrpt ./{slug}-lrpt --source rtlsdr \\\n"
            f"  --frequency {lrpt_mhz}e6 --samplerate 2.4e6 --gain 30"
        )
    if "APRS" in mode:
        return (
            "# APRS / AX.25\n"
            f"rtl_fm -f {mhz}M -M fm -s 24k -r 24k -g 40 | \\\n"
            "  sox -t raw -r 24k -e s -b 16 -c 1 - -t wav - | direwolf -r 24000 -"
        )
    if "FM" in mode:
        return (
            "# FM: escucha en directo\n"
            f"rtl_fm -f {mhz}M -M fm -s 24k -r 24k -g 40 | \\\n"
            "  sox -t raw -r 24k -e s -b 16 -c 1 - -d"
        )
    return (
        "# SSB/CW: escucha en directo\n"
        f"rtl_fm -f {mhz}M -M usb -s 12k -r 12k -g 40 | \\\n"
        "  sox -t raw -r 12k -e s -b 16 -c 1 - -d"
    )


def _ics_escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_date(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def calendar(item: PassItem) -> str:
    freq = f"{fmt_freq(item.freq_hz)}{f' ({item.mode})' if item.mode else ''}" if item.freq_hz else "sin frecuencia"
    description = "\n".join(
        [
            f"NORAD {item.sat.norad}",
            freq,
            f"Altura máxima {item.max_el:.0f}°",
            f"Dirección {round(item.az_aos)}° → {round(item.az_los)}°",
            f"Duración {fmt_dur(item.duration_s)}",
            f"Punto más alto {fmt_time(item.tca)}",
        ]
    )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//PasoOrbital//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:pasoorbital-{item.sat.norad}-{round(item.aos)}@local",
        f"DTSTAMP:{_ics_date(__import__('time').time())}",
        f"DTSTART:{_ics_date(item.aos)}",
        f"DTEND:{_ics_date(item.los)}",
        f"SUMMARY:{_ics_escape(item.sat.name)} — paso ({item.max_el:.0f}°)",
        f"DESCRIPTION:{_ics_escape(description)}",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines)
