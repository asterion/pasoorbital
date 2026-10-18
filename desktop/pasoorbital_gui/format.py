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
    if not hz:
        return "—"
    text = f"{hz / 1e6:.4f}"
    if text.endswith("00"):
        text = text[:-1]
    return text + " MHz"


def fmt_dop(hz: float | None) -> str:
    if hz is None:
        return "—"
    khz = hz / 1000.0
    if abs(khz) < 0.05:
        return "0.0 kHz"
    sign = "+" if khz > 0 else "−"
    return f"{sign}{abs(khz):.1f} kHz"


def fmt_az(deg: float) -> str:
    return f"{compass_word(deg).capitalize()} · {round(deg)}°"


def _esc(text: str) -> str:
    return html.escape(str(text), quote=False)


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:40] or "pasoorbital"


def summary(item: PassItem) -> str:
    """Resumen en una frase con marcas Pango (solo <b>)."""
    name = _esc(item.sat.name)
    dir_a = compass_word(item.az_aos)
    dir_l = compass_word(item.az_los)
    el = f"{item.max_el:.0f}"
    freq = (
        f"Podrás escucharlo en <b>{fmt_freq(item.freq_hz)}</b>"
        f"{f' ({_esc(item.mode)})' if item.mode else ''}."
        if item.freq_hz
        else "No hay una frecuencia de escucha registrada para este satélite."
    )

    if item.partial_start:
        text = (
            f"El <b>{name}</b> ya está en curso: ahora va por el <b>{dir_a}</b>, "
            f"llegará a <b>{el}°</b> de altura a las <b>{fmt_time(item.tca)}</b> y "
            f"desaparecerá por el <b>{dir_l}</b> a las <b>{fmt_time(item.los)}</b>."
        )
    elif item.partial_end:
        text = (
            f"El <b>{name}</b> aparecerá por el <b>{dir_a}</b> a las "
            f"<b>{fmt_time(item.aos)}</b> y llegará a <b>{el}°</b> de altura a las "
            f"<b>{fmt_time(item.tca)}</b>. Seguirá visible al menos hasta el final de "
            f"la ventana ({fmt_time(item.los)})."
        )
    else:
        quality = (
            "un paso alto" if item.max_el >= 30 else "un paso aceptable" if item.max_el >= 15 else "un paso bajo"
        )
        text = (
            f"El <b>{name}</b> aparecerá por el <b>{dir_a}</b> a las "
            f"<b>{fmt_time(item.aos)}</b>, subirá hasta <b>{el}°</b> de altura "
            f"({quality}) a las <b>{fmt_time(item.tca)}</b> y desaparecerá por el "
            f"<b>{dir_l}</b> a las <b>{fmt_time(item.los)}</b>. Dura unos "
            f"<b>{fmt_dur(item.duration_s)}</b>."
        )

    doppler = ""
    if item.freq_hz and item.doppler_aos_hz is not None and item.doppler_los_hz is not None:
        if abs(item.doppler_aos_hz) < 50 and abs(item.doppler_los_hz) < 50:
            doppler = " El Doppler será casi nulo."
        else:
            doppler = (
                f" Al empezar, la frecuencia estará {fmt_dop(item.doppler_aos_hz)} respecto a la "
                f"nominal; al final, {fmt_dop(item.doppler_los_hz)}."
            )
    return f"{text} {freq}{doppler}"


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
