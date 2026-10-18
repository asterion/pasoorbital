"""Gráfico polar de la trayectoria aparente de un paso."""

from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from .data import PassItem  # noqa: E402

BG = (0.031, 0.063, 0.098)
GRID = (0.114, 0.165, 0.227)
TEXT = (0.498, 0.576, 0.655)
ACCENT = (0.247, 0.878, 0.773)
AMBER = (1.0, 0.706, 0.329)
RED = (1.0, 0.435, 0.435)


def _rgb(cr, color):
    cr.set_source_rgb(*color)


class SkyPlot(Gtk.DrawingArea):
    def __init__(self, points: list[tuple[float, float, float, float, float]], item: PassItem):
        super().__init__()
        self.points = points
        self.item = item
        self.set_content_width(320)
        self.set_content_height(320)
        self.set_hexpand(False)
        self.set_halign(Gtk.Align.CENTER)
        self.set_draw_func(self._draw)

    def _xy(self, cx: float, cy: float, radius: float, az: float, el: float):
        r = radius * (1.0 - max(0.0, min(90.0, el)) / 90.0)
        rad = math.radians(az)
        return cx + r * math.sin(rad), cy - r * math.cos(rad)

    def _draw(self, _area, cr, width: int, height: int):
        if width <= 0 or height <= 0:
            return
        cx, cy = width / 2.0, height / 2.0
        radius = min(width, height) * 0.38

        # fondo
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        _rgb(cr, BG)
        cr.fill()

        # anillos
        cr.set_line_width(1.0)
        for el in (0, 30, 60, 90):
            r = radius * (1.0 - el / 90.0)
            if r <= 0:
                continue
            cr.arc(cx, cy, r, 0, 2 * math.pi)
            _rgb(cr, GRID)
            cr.stroke()

        # radios
        for angle in (0, 90, 180, 270):
            rad = math.radians(angle)
            cr.move_to(cx, cy)
            cr.line_to(cx + radius * math.sin(rad), cy - radius * math.cos(rad))
            _rgb(cr, GRID)
            cr.stroke()

        # trayectoria
        pts = [
            self._xy(cx, cy, radius, az, el)
            for _t, az, el, _rng, _rate in self.points
            if el is not None and el >= 0
        ]
        if len(pts) >= 2:
            cr.move_to(*pts[0])
            for x, y in pts[1:]:
                cr.line_to(x, y)
            _rgb(cr, ACCENT)
            cr.set_line_width(2.6)
            cr.set_line_cap(1)  # Cairo.LINE_CAP_ROUND
            cr.stroke()

        def dot(x, y, color):
            cr.arc(x, y, 4.5, 0, 2 * math.pi)
            _rgb(cr, color)
            cr.fill()
            cr.set_line_width(1.2)
            _rgb(cr, BG)
            cr.stroke()

        if pts:
            dot(*pts[0], ACCENT)
            dot(*pts[-1], RED)

        # punto más alto
        if self.points:
            best = max(self.points, key=lambda p: p[2] if p[2] is not None else -90)
            if best[2] is not None:
                dot(*self._xy(cx, cy, radius, best[1], best[2]), AMBER)

        # puntos cardinales
        cr.set_font_size(11)
        cr.select_font_face("Sans")
        for text, dx, dy in (
            ("N", 0, -radius - 8),
            ("S", 0, radius + 16),
            ("E", radius + 12, 4),
            ("O", -radius - 12, 4),
        ):
            ext = cr.text_extents(text)
            cr.move_to(cx + dx - ext.width / 2 - ext.x_bearing, cy + dy)
            _rgb(cr, TEXT)
            cr.show_text(text)
