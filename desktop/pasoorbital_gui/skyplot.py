"""Gráficos del detalle: trayectoria polar, perfil de altura y progreso.

Los colores se derivan del tema activo (``Adw.StyleManager``): en claro la
tarjeta es blanca, la rejilla usa el color de bordes y el texto el color de
ventana, de modo que las etiquetas mantienen un contraste alto.  Los tres
marcadores del paso se distinguen por **forma y letra**, no solo por color:

* **A** — aparece (círculo)
* **T** — punto más alto (rombo)
* **L** — se va (cuadrado)
"""

from __future__ import annotations

import math
from bisect import bisect_left
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .data import PassItem  # noqa: E402

#: Paletas por tema: (fondo, tarjeta, rejilla, texto, acento, ámbar, rojo).
#: El texto claro sobre fondo oscuro da ~11:1; el oscuro sobre blanco, ~12:1.
_PALETAS = {
    True: {
        "bg": (0.031, 0.063, 0.098),
        "card": (0.055, 0.086, 0.122),
        "grid": (0.114, 0.165, 0.227),
        "text": (0.83, 0.87, 0.90),
        "accent": (0.247, 0.878, 0.773),
        "amber": (1.0, 0.706, 0.329),
        "red": (1.0, 0.435, 0.435),
    },
    False: {
        "bg": (1.0, 1.0, 1.0),
        "card": (0.976, 0.976, 0.976),
        "grid": (0.80, 0.82, 0.84),
        "text": (0.176, 0.196, 0.216),
        "accent": (0.043, 0.451, 0.749),
        "amber": (0.71, 0.45, 0.0),
        "red": (0.69, 0.0, 0.063),
    },
}

_ROUND_CAP = 1  # Cairo.LINE_CAP_ROUND sin depender de pycairo


def paleta() -> dict:
    """Colores del tema activo (se consulta en cada dibujo)."""
    return _PALETAS[bool(Adw.StyleManager.get_default().get_dark())]


def sample_track(points, now: float):
    """Interpola az/el/distancia/rate del track en el instante ``now``."""
    if not points:
        return None
    if now <= points[0][0]:
        return points[0]
    if now >= points[-1][0]:
        return points[-1]
    times = [p[0] for p in points]
    index = bisect_left(times, now)
    p0 = points[max(0, index - 1)]
    p1 = points[min(len(points) - 1, index)]
    span = p1[0] - p0[0]
    fraction = (now - p0[0]) / span if span else 0.0
    delta_az = ((p1[1] - p0[1] + 180.0) % 360.0) - 180.0
    az = (p0[1] + delta_az * fraction) % 360.0
    el = p0[2] + (p1[2] - p0[2]) * fraction
    rng = p0[3] + (p1[3] - p0[3]) * fraction
    rate = p0[4] + (p1[4] - p0[4]) * fraction
    return (now, az, el, rng, rate)


def _rgb(cr, color):
    cr.set_source_rgb(*color)


def _texto(cr, x, y, texto, color, tam=11, negrita=False):
    cr.select_font_face("Sans", 0, 1 if negrita else 0)
    cr.set_font_size(tam)
    ext = cr.text_extents(texto)
    cr.move_to(x - ext.width / 2 - ext.x_bearing, y)
    _rgb(cr, color)
    cr.show_text(texto)


class _TemaMixin:
    """Redibuja cuando cambia el tema del sistema."""

    def _conectar_tema(self) -> None:
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self.queue_draw())


class SkyPlot(_TemaMixin, Gtk.DrawingArea):
    """Diagrama polar: cenit en el centro, horizonte en el borde."""

    def __init__(self, points: list[tuple[float, float, float, float, float]], item: PassItem):
        super().__init__()
        self.points = points
        self.item = item
        self.now: float | None = None
        self.set_content_width(360)
        self.set_content_height(340)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self._draw)
        self._conectar_tema()

    def set_now(self, now: float | None) -> None:
        self.now = now
        self.queue_draw()

    def _xy(self, cx: float, cy: float, radius: float, az: float, el: float):
        r = radius * (1.0 - max(0.0, min(90.0, el)) / 90.0)
        rad = math.radians(az)
        return cx + r * math.sin(rad), cy - r * math.cos(rad)

    # ------------------------------------------------------------------
    def _draw(self, _area, cr, width: int, height: int):
        if width <= 0 or height <= 0:
            return
        c = paleta()
        cx, cy = width / 2.0, height / 2.0
        radius = min(width, height) * 0.39

        live = self.now is not None and self.item.aos <= self.now <= self.item.los

        # tarjeta circular
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        _rgb(cr, c["card"])
        cr.fill_preserve()
        _rgb(cr, c["grid"])
        cr.set_line_width(1.0)
        cr.stroke()

        # anillos y radios
        cr.set_line_width(1.0)
        for el in (0, 30, 60, 90):
            r = radius * (1.0 - el / 90.0)
            if r <= 0:
                continue
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            _rgb(cr, c["grid"])
            cr.stroke()
        for angle in (0, 90, 180, 270):
            rad = math.radians(angle)
            cr.move_to(cx, cy)
            cr.line_to(cx + radius * math.sin(rad), cy - radius * math.cos(rad))
            _rgb(cr, c["grid"])
            cr.stroke()

        # trayectoria completa (pendiente, punteada) y tramo recorrido
        pts = [
            self._xy(cx, cy, radius, az, el)
            for _t, az, el, _rng, _rate in self.points
            if el is not None and el >= 0
        ]
        if len(pts) >= 2:
            _rgb(cr, c["accent"])
            cr.set_line_width(2.0)
            cr.set_line_cap(_ROUND_CAP)
            cr.set_dash([5.0, 5.0], 0.0)
            cr.move_to(*pts[0])
            for x, y in pts[1:]:
                cr.line_to(x, y)
            cr.stroke()
            cr.set_dash([], 0.0)

        current = sample_track(self.points, self.now) if live else None
        if current is not None and current[2] is not None and current[2] >= 0:
            trail = [
                self._xy(cx, cy, radius, az, el)
                for t, az, el, _rng, _rate in self.points
                if t <= self.now and el is not None and el >= 0
            ]
            trail.append(self._xy(cx, cy, radius, current[1], current[2]))
            if len(trail) >= 2:
                cr.move_to(*trail[0])
                for x, y in trail[1:]:
                    cr.line_to(x, y)
                _rgb(cr, c["accent"])
                cr.set_line_width(3.0)
                cr.set_line_cap(_ROUND_CAP)
                cr.stroke()

        # marcadores A (círculo), T (rombo) y L (cuadrado)
        def circulo(x, y, color):
            cr.arc(x, y, 5.0, 0, 2 * math.pi)
            _rgb(cr, color)
            cr.fill()
            cr.set_line_width(1.4)
            _rgb(cr, c["card"])
            cr.stroke()

        def rombo(x, y, color):
            d = 6.0
            cr.move_to(x, y - d)
            cr.line_to(x + d, y)
            cr.line_to(x, y + d)
            cr.line_to(x - d, y)
            cr.close_path()
            _rgb(cr, color)
            cr.fill()
            cr.set_line_width(1.4)
            _rgb(cr, c["card"])
            cr.stroke()

        def cuadrado(x, y, color):
            d = 5.0
            cr.rectangle(x - d, y - d, 2 * d, 2 * d)
            _rgb(cr, color)
            cr.fill()
            cr.set_line_width(1.4)
            _rgb(cr, c["card"])
            cr.stroke()

        if pts:
            circulo(*pts[0], c["accent"])
            _texto(cr, pts[0][0] - 11, pts[0][1] - 8, "A", c["text"], 10, True)
            cuadrado(*pts[-1], c["red"])
            _texto(cr, pts[-1][0] + 12, pts[-1][1] + 4, "L", c["text"], 10, True)
        best = max(self.points, key=lambda p: p[2] if p[2] is not None else -90,
                   default=None)
        if best is not None and best[2] is not None:
            bx, by = self._xy(cx, cy, radius, best[1], best[2])
            rombo(bx, by, c["amber"])
            _texto(cr, bx + 12, by - 8, "T", c["text"], 10, True)

        # posición actual con halo
        if current is not None and current[2] is not None and current[2] >= 0:
            x, y = self._xy(cx, cy, radius, current[1], current[2])
            cr.arc(x, y, 11.0, 0, 2 * math.pi)
            _rgb(cr, c["accent"])
            cr.save()
            cr.set_source_rgba(*c["accent"], 0.25)
            cr.fill()
            cr.restore()
            cr.arc(x, y, 5.4, 0, 2 * math.pi)
            _rgb(cr, (1.0, 1.0, 1.0))
            cr.fill()
            cr.set_line_width(1.8)
            _rgb(cr, c["accent"])
            cr.stroke()

        # puntos cardinales en el color de texto del tema
        for letra, dx, dy in (
            ("N", 0, -radius - 12),
            ("S", 0, radius + 20),
            ("E", radius + 16, 4),
            ("O", -radius - 16, 4),
        ):
            _texto(cr, cx + dx, cy + dy, letra, c["text"], 12, True)


class ElevationPlot(_TemaMixin, Gtk.DrawingArea):
    """Altura sobre el horizonte a lo largo del paso."""

    def __init__(self, points: list[tuple[float, float, float, float, float]], item: PassItem):
        super().__init__()
        self.points = points
        self.item = item
        self.now: float | None = None
        self.set_content_width(460)
        self.set_content_height(340)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self._draw)
        self._conectar_tema()

    def set_now(self, now: float | None) -> None:
        self.now = now
        self.queue_draw()

    def _x(self, left: float, pw: float, t: float) -> float:
        return left + pw * (t - self.item.aos) / max(1.0, self.item.los - self.item.aos)

    def _draw(self, _area, cr, width: int, height: int):
        if width <= 0 or height <= 0:
            return
        c = paleta()
        left, right, top, bottom = 48, 18, 34, 46
        pw = width - left - right
        ph = height - top - bottom
        if pw <= 0 or ph <= 0:
            return

        cr.select_font_face("Sans")
        cr.set_font_size(11)
        cr.set_line_width(1.0)

        # rejilla horizontal
        for el in (0, 30, 60, 90):
            y = top + ph * (1.0 - el / 90.0)
            cr.move_to(left, y)
            cr.line_to(left + pw, y)
            _rgb(cr, c["grid"])
            cr.stroke()
            _texto(cr, left - 16, y + 4, f"{el}°", c["text"], 11)

        # curva y relleno
        pts = []
        for t, _az, el, _rng, _rate in self.points:
            if el is None or el < 0:
                continue
            pts.append((self._x(left, pw, t), top + ph * (1.0 - min(90.0, max(0.0, el)) / 90.0)))
        if len(pts) >= 2:
            cr.move_to(pts[0][0], top + ph)
            for x, y in pts:
                cr.line_to(x, y)
            cr.line_to(pts[-1][0], top + ph)
            cr.close_path()
            cr.save()
            cr.set_source_rgba(*c["accent"], 0.14)
            cr.fill()
            cr.restore()

            cr.move_to(*pts[0])
            for x, y in pts[1:]:
                cr.line_to(x, y)
            _rgb(cr, c["accent"])
            cr.set_line_width(2.6)
            cr.set_line_cap(_ROUND_CAP)
            cr.stroke()

        # ahora
        if self.now is not None and self.item.aos <= self.now <= self.item.los:
            current = sample_track(self.points, self.now)
            if current is not None and current[2] is not None:
                x = self._x(left, pw, self.now)
                y = top + ph * (1.0 - min(90.0, max(0.0, current[2])) / 90.0)
                cr.move_to(x, top)
                cr.line_to(x, top + ph)
                cr.save()
                cr.set_source_rgba(*c["accent"], 0.8)
                cr.set_line_width(1.4)
                cr.stroke()
                cr.restore()
                cr.arc(x, y, 11.0, 0, 2 * math.pi)
                cr.save()
                cr.set_source_rgba(*c["accent"], 0.25)
                cr.fill()
                cr.restore()
                cr.arc(x, y, 5.4, 0, 2 * math.pi)
                _rgb(cr, (1.0, 1.0, 1.0))
                cr.fill()
                cr.set_line_width(1.8)
                _rgb(cr, c["accent"])
                cr.stroke()
                etiqueta = f"AHORA · {current[2]:.0f}°"
                cr.set_font_size(10)
                ext = cr.text_extents(etiqueta)
                tx = min(left + pw - ext.width - 6, max(left + 4, x + 9))
                _rgb(cr, c["text"])
                cr.move_to(tx, max(top + 12, y - 10))
                cr.show_text(etiqueta)

        # marcas A / T / L con su hora
        marcas = (
            (self.item.aos, c["accent"], "A"),
            (self.item.tca, c["amber"], "T"),
            (self.item.los, c["red"], "L"),
        )
        for t, color, letra in marcas:
            x = self._x(left, pw, t)
            cr.move_to(x, top)
            cr.line_to(x, top + ph)
            cr.save()
            cr.set_source_rgba(*color, 0.30)
            cr.set_line_width(1.0)
            cr.stroke()
            cr.restore()
            hora = datetime.fromtimestamp(t).strftime("%H:%M")
            cr.set_font_size(10)
            texto = f"{letra} {hora}"
            ext = cr.text_extents(texto)
            tx = min(left + pw - ext.width, max(left, x - ext.width / 2))
            _rgb(cr, c["text"])
            cr.move_to(tx, height - 16)
            cr.show_text(texto)

        cr.set_font_size(12)
        cr.move_to(left, 20)
        _rgb(cr, c["text"])
        cr.show_text("Altura sobre el horizonte")


class ProgressWithMarks(_TemaMixin, Gtk.DrawingArea):
    """Barra de progreso con el borde del tema y marcas A/T/L."""

    def __init__(self, marks: list[tuple[float, str]]):
        super().__init__()
        self.fraction = 0.0
        self.marks = marks
        self.set_content_height(26)
        self.set_hexpand(True)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._draw)
        self._conectar_tema()

    def set_fraction(self, fraction: float) -> None:
        self.fraction = max(0.0, min(1.0, float(fraction)))
        self.queue_draw()

    def _draw(self, _area, cr, width: int, height: int):
        if width <= 0 or height <= 0:
            return
        c = paleta()
        alto, y = 8.0, max(13.0, height - 12.0)
        radio = alto / 2.0

        # fondo
        cr.rectangle(0, y, width, alto)
        cr.save()
        cr.set_source_rgba(*c["grid"], 0.55)
        cr.fill()
        cr.restore()
        if self.fraction > 0:
            cr.rectangle(0, y, width * self.fraction, alto)
            _rgb(cr, c["accent"])
            cr.fill()
        cr.rectangle(0.5, y + 0.5, width - 1, alto - 1)
        cr.save()
        cr.set_source_rgba(*c["text"], 0.35)
        cr.set_line_width(1.0)
        cr.stroke()
        cr.restore()

        for fraccion, letra in self.marks:
            x = min(width - 6.0, max(6.0, width * fraccion))
            cr.move_to(x, y - 1.0)
            cr.line_to(x, y + alto + 1.0)
            _rgb(cr, c["text"])
            cr.set_line_width(1.4)
            cr.stroke()
            _texto(cr, x, y - 4.0, letra, c["text"], 9, True)
