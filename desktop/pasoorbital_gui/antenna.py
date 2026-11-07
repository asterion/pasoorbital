"""Gráficos de la pestaña Antena: rosa de los vientos y cobertura.

La brújula dibuja la trayectoria del paso y el cono del haz de la antena; la
barra de cobertura muestra qué tramos del paso caen dentro de ese cono.  Ambos
usan la paleta del tema activo (la misma que los gráficos de Cielo).
"""

from __future__ import annotations

import math
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .skyplot import _ROUND_CAP, _rgb, _texto, paleta  # noqa: E402


class AntennaPlot(Gtk.DrawingArea):
    """Rosa de los vientos con la trayectoria y el cono del haz."""

    def __init__(self, az, el, marks: dict, pointing: tuple[float, float] | None,
                 beam_deg: float):
        super().__init__()
        self.az = [float(v) for v in az]
        self.el = [float(v) for v in el]
        self.marks = marks            # {"aos": (az, el), "tca": (az, el), "los": (az, el)}
        self.pointing = pointing      # (az, el) recomendado o None
        self.beam_deg = float(beam_deg)
        self.set_content_width(300)
        self.set_content_height(280)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_draw_func(self._draw)
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self.queue_draw())

    def set_state(self, az, el, marks, pointing, beam_deg) -> None:
        self.az = [float(v) for v in az]
        self.el = [float(v) for v in el]
        self.marks = marks
        self.pointing = pointing
        self.beam_deg = float(beam_deg)
        self.queue_draw()

    # ------------------------------------------------------------------
    def _xy(self, cx: float, cy: float, r: float, az: float, el: float):
        radio = r * (1.0 - max(0.0, min(90.0, el)) / 90.0)
        rad = math.radians(az)
        return cx + radio * math.sin(rad), cy - radio * math.cos(rad)

    def _draw(self, _area, cr, width: int, height: int):
        if width <= 0 or height <= 0:
            return
        c = paleta()
        cx, cy = width / 2.0, height / 2.0 - 6
        r = min(width, height) * 0.36

        # disco y retícula
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        _rgb(cr, c["card"])
        cr.fill_preserve()
        _rgb(cr, c["grid"])
        cr.set_line_width(1.0)
        cr.stroke()
        for frac in (0.33, 0.66, 1.0):
            cr.arc(cx, cy, r * frac, 0, 2 * math.pi)
            _rgb(cr, c["grid"])
            cr.stroke()
        for ang in (0, 90, 180, 270):
            rad = math.radians(ang)
            cr.move_to(cx, cy)
            cr.line_to(cx + r * math.sin(rad), cy - r * math.cos(rad))
            _rgb(cr, c["grid"])
            cr.stroke()

        # cono del haz
        if self.pointing is not None:
            az_ant, _el_ant = self.pointing
            semi = math.radians(self.beam_deg / 2.0)
            ang = math.radians(az_ant)
            cr.move_to(cx, cy)
            for i in range(25):
                a = ang - semi + (2 * semi) * i / 24
                cr.line_to(cx + r * 0.99 * math.sin(a), cy - r * 0.99 * math.cos(a))
            cr.close_path()
            cr.save()
            cr.set_source_rgba(*c["accent"], 0.18)
            cr.fill()
            cr.restore()
            cr.set_source_rgba(*c["accent"], 0.55)
            cr.set_line_width(1.2)
            cr.stroke()

        # trayectoria
        visibles = [(a, e) for a, e in zip(self.az, self.el) if e >= 0]
        if len(visibles) >= 2:
            puntos = [self._xy(cx, cy, r, a, e) for a, e in visibles]
            cr.set_dash([5.0, 5.0], 0.0)
            cr.move_to(*puntos[0])
            for x, y in puntos[1:]:
                cr.line_to(x, y)
            _rgb(cr, c["accent"])
            cr.set_line_width(2.2)
            cr.set_line_cap(_ROUND_CAP)
            cr.stroke()
            cr.set_dash([], 0.0)

        # marcadores A / T / L
        for clave, forma, color, letra in (
            ("aos", "circulo", c["accent"], "A"),
            ("tca", "rombo", c["amber"], "T"),
            ("los", "cuadrado", c["red"], "L"),
        ):
            punto = self.marks.get(clave)
            if punto is None:
                continue
            x, y = self._xy(cx, cy, r, punto[0], punto[1])
            if forma == "circulo":
                cr.arc(x, y, 5.0, 0, 2 * math.pi)
            elif forma == "rombo":
                d = 6.0
                cr.move_to(x, y - d)
                cr.line_to(x + d, y)
                cr.line_to(x, y + d)
                cr.line_to(x - d, y)
                cr.close_path()
            else:
                cr.rectangle(x - 5, y - 5, 10, 10)
            _rgb(cr, color)
            cr.fill()
            _texto(cr, x + (10 if clave != "los" else -12), y - 9, letra, c["text"], 9, True)

        # orientación recomendada
        if self.pointing is not None:
            x, y = self._xy(cx, cy, r, self.pointing[0], self.pointing[1])
            cr.arc(x, y, 12.0, 0, 2 * math.pi)
            cr.save()
            cr.set_source_rgba(*c["accent"], 0.22)
            cr.fill()
            cr.restore()
            cr.arc(x, y, 5.5, 0, 2 * math.pi)
            _rgb(cr, (1.0, 1.0, 1.0))
            cr.fill_preserve()
            cr.set_line_width(2.0)
            _rgb(cr, c["accent"])
            cr.stroke()

        # cardinales
        for letra, ang in (("N", 0), ("E", 90), ("S", 180), ("O", 270)):
            rad = math.radians(ang)
            _texto(cr, cx + (r + 18) * math.sin(rad),
                   cy - (r + 18) * math.cos(rad) + 4, letra, c["text"], 10, True)


class CoverageBar(Gtk.DrawingArea):
    """Barra del paso completo con los tramos cubiertos y las marcas A/T/L."""

    def __init__(self, intervals: list[tuple[float, float]], aos: float, los: float,
                 tca: float):
        super().__init__()
        self.intervals = intervals
        self.aos = aos
        self.los = los
        self.tca = tca
        self.set_content_height(26)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        Adw.StyleManager.get_default().connect("notify::dark", lambda *_: self.queue_draw())

    def set_state(self, intervals, aos, los, tca) -> None:
        self.intervals = intervals
        self.aos = aos
        self.los = los
        self.tca = tca
        self.queue_draw()

    def _x(self, width: float, t: float) -> float:
        return width * (t - self.aos) / max(1.0, self.los - self.aos)

    def _draw(self, _area, cr, width: int, height: int):
        if width <= 0 or height <= 0:
            return
        c = paleta()
        alto, y = 8.0, max(13.0, height - 12.0)

        cr.rectangle(0, y, width, alto)
        cr.save()
        cr.set_source_rgba(*c["grid"], 0.55)
        cr.fill()
        cr.restore()

        for ini, fin in self.intervals:
            x0 = max(0.0, min(width, self._x(width, ini)))
            x1 = max(0.0, min(width, self._x(width, fin)))
            if x1 > x0:
                cr.rectangle(x0, y, x1 - x0, alto)
                _rgb(cr, c["accent"])
                cr.fill()

        cr.rectangle(0.5, y + 0.5, width - 1, alto - 1)
        cr.save()
        cr.set_source_rgba(*c["text"], 0.35)
        cr.set_line_width(1.0)
        cr.stroke()
        cr.restore()

        for t, letra in ((self.aos, "A"), (self.tca, "T"), (self.los, "L")):
            x = min(width - 1.0, max(1.0, self._x(width, t)))
            cr.move_to(x, y - 4.0)
            cr.line_to(x, y + alto + 4.0)
            _rgb(cr, c["text"])
            cr.set_line_width(1.4)
            cr.stroke()
            _texto(cr, x, y + alto + 8.0, letra, c["text"], 9, True)


def marcas_de_paso(item) -> dict:
    """Puntos (az, el) de aparición, punto más alto y salida."""
    return {
        "aos": (item.az_aos, 0.0),
        "tca": (item.az_tca, item.max_el),
        "los": (item.az_los, 0.0),
    }
