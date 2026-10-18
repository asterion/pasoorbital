"""Ventana principal de PasoOrbital para GNOME (GTK4 + libadwaita)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from . import __version__, format as fmt  # noqa: E402
from .data import PassItem, PasoOrbitalData  # noqa: E402
from .skyplot import ElevationPlot, SkyPlot  # noqa: E402

DAYS = [1, 2, 3, 7]
MIN_EL = [0, 5, 10, 15, 20, 30]
GROUPS = [
    ("stations", "Estación Espacial"),
    ("weather", "Meteorológicos"),
    ("amateur", "Radioaficionados"),
    ("cubesat", "CubeSats"),
]


class PasoOrbitalWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, data: PasoOrbitalData):
        super().__init__(application=app)
        self.app = app
        self.data = data
        self.config_path = Path(GLib.get_user_config_dir()) / "pasoorbital" / "config.json"

        self.config = self._read_config()
        self.items: list[PassItem] = []
        self.filtered: list[PassItem] = []
        self._geo_results: list[dict] = []
        self._elevation_token: tuple[float, float] | None = None
        self._setting_alt = False
        self._row_widgets: dict[tuple[int, int], Gtk.Widget] = {}
        self._notified: set[tuple[int, int]] = set()
        self._detail_dialog: Adw.Dialog | None = None
        self.shown = 250
        self.elapsed = 0.0
        self.busy = False
        self._has_location = self.config.get("lat") is not None and self.config.get("lon") is not None

        self.set_default_size(1280, 840)
        self.set_size_request(980, 640)
        self.set_title("PasoOrbital")

        self._build_ui()
        self._apply_config()
        GLib.idle_add(self._initial_load)
        GLib.timeout_add_seconds(10, self._tick)

    # ================================================================ UI
    def _build_ui(self) -> None:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.WindowTitle(title="PasoOrbital", subtitle="Pasos de satélites para escucha")
        )
        self.refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        self.refresh_btn.set_tooltip_text("Actualizar TLE")
        self.refresh_btn.connect("clicked", lambda *_: self.refresh_tle())
        header.pack_start(self.refresh_btn)

        menu = Gio.Menu()
        menu.append("Actualizar TLE", "app.refresh")
        menu.append("Acerca de PasoOrbital", "app.about")
        menu.append("Salir", "app.quit")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_btn.set_menu_model(menu)
        menu_btn.set_tooltip_text("Menú")
        header.pack_end(menu_btn)

        self.calc_btn = Gtk.Button(label="Calcular")
        self.calc_btn.add_css_class("suggested-action")
        self.calc_btn.set_tooltip_text("Calcular pasos")
        self.calc_btn.connect("clicked", lambda *_: self.calculate())
        header.pack_end(self.calc_btn)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(380)
        paned.set_resize_start_child(False)
        paned.set_shrink_start_child(False)

        paned.set_start_child(self._build_sidebar())
        paned.set_end_child(self._build_content())
        toolbar.add_top_bar(header)
        toolbar.set_content(paned)
        self.set_content(toolbar)

    def _build_sidebar(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        page.set_vexpand(True)

        location = Adw.PreferencesGroup(title="Ubicación")
        self.address_row = Adw.EntryRow(title="Dirección")
        self.address_row.set_text(str(self.config.get("label") or ""))
        self.address_row.connect("apply", lambda *_: self.geocode())
        self.search_btn = Gtk.Button(icon_name="system-search-symbolic")
        self.search_btn.set_valign(Gtk.Align.CENTER)
        self.search_btn.add_css_class("flat")
        self.search_btn.set_tooltip_text("Buscar dirección")
        self.search_btn.connect("clicked", lambda *_: self.geocode())
        self.address_row.add_suffix(self.search_btn)
        location.add(self.address_row)

        self.lat_row = Adw.SpinRow.new_with_range(-90.0, 90.0, 0.0001)
        self.lat_row.set_title("Latitud")
        self.lat_row.set_digits(4)
        self.lon_row = Adw.SpinRow.new_with_range(-180.0, 180.0, 0.0001)
        self.lon_row.set_title("Longitud")
        self.lon_row.set_digits(4)
        self.alt_row = Adw.SpinRow.new_with_range(-500.0, 9000.0, 10.0)
        self.alt_row.set_title("Altitud (m)")
        self.alt_row.set_digits(0)
        self.alt_row.set_subtitle("Del terreno; ajusta la altura del edificio a mano")
        self.alt_btn = Gtk.Button(icon_name="find-location-symbolic")
        self.alt_btn.set_tooltip_text("Calcular la altitud del terreno con Open-Meteo")
        self.alt_btn.add_css_class("flat")
        self.alt_btn.connect("clicked", lambda *_: self.auto_elevation())
        self.alt_row.add_suffix(self.alt_btn)
        self.alt_row.connect("notify::value", self._on_alt_changed)
        for row in (self.lat_row, self.lon_row, self.alt_row):
            location.add(row)
        page.add(location)

        prediction = Adw.PreferencesGroup(title="Predicción")
        self.days_row = Adw.ComboRow(title="Días")
        self.days_row.set_model(Gtk.StringList.new(["1 día", "2 días", "3 días", "7 días"]))
        self.el_row = Adw.ComboRow(title="Elevación mínima")
        self.el_row.set_model(
            Gtk.StringList.new(["0° (horizonte)", "5°", "10°", "15°", "20°", "30°"])
        )
        prediction.add(self.days_row)
        prediction.add(self.el_row)

        self.switches: dict[str, Gtk.CheckButton] = {}
        groups_row = Adw.ActionRow(title="Grupos")
        groups_row.set_use_markup(False)
        groups_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        row_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        row_bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        labels = {"stations": "Estación", "weather": "Meteo", "amateur": "Amateur", "cubesat": "CubeSats"}
        for index, (group_id, _title) in enumerate(GROUPS):
            check = Gtk.CheckButton(label=labels.get(group_id, _title))
            check.set_active(group_id in ("stations", "weather", "amateur"))
            self.switches[group_id] = check
            (row_top if index < 2 else row_bottom).append(check)
        groups_box.append(row_top)
        groups_box.append(row_bottom)
        groups_row.add_suffix(groups_box)
        prediction.add(groups_row)

        self.notify_row = Adw.SwitchRow(title="Avisar 5 min antes")
        self.notify_row.set_active(True)
        self.notify_row.set_tooltip_text("Notificación del escritorio al acercarse un paso")
        self.notify_row.connect("notify::active", lambda *_: self._save_config())
        prediction.add(self.notify_row)

        page.add(prediction)

        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bottom.set_margin_top(10)
        bottom.set_margin_bottom(12)
        bottom.set_margin_start(14)
        bottom.set_margin_end(14)

        self.only_freq_check = Gtk.CheckButton(label="Solo con frecuencia conocida")
        self.only_freq_check.set_active(True)
        bottom.append(self.only_freq_check)

        self.status = Gtk.Label(label="")
        self.status.set_xalign(0)
        self.status.set_wrap(True)
        self.status.add_css_class("caption")
        self.status.add_css_class("dim-label")
        bottom.append(self.status)

        self.tle_label = Gtk.Label(label="TLE: —")
        self.tle_label.set_xalign(0)
        self.tle_label.add_css_class("caption")
        self.tle_label.add_css_class("dim-label")
        bottom.append(self.tle_label)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.set_size_request(380, -1)
        side_scroll = Gtk.ScrolledWindow()
        side_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        side_scroll.set_overlay_scrolling(False)
        side_scroll.set_child(page)
        side_scroll.set_vexpand(True)
        side.append(side_scroll)
        side.append(Gtk.Separator())
        side.append(bottom)

        # Glosario de resultados de geocodificación
        self.geo_popover = Gtk.Popover()
        self.geo_popover.set_parent(self.address_row)
        self.geo_list = Gtk.ListBox()
        self.geo_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.geo_list.connect("row-activated", self._on_geo_row_activated)
        geo_scroll = Gtk.ScrolledWindow()
        geo_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        geo_scroll.set_child(self.geo_list)
        geo_scroll.set_size_request(430, 260)
        self.geo_popover.set_child(geo_scroll)
        return side

    def _build_content(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        head.set_margin_top(16)
        head.set_margin_bottom(8)
        head.set_margin_start(18)
        head.set_margin_end(18)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        title = Gtk.Label(label="Pasos")
        title.set_xalign(0)
        title.add_css_class("title-1")
        self.meta_label = Gtk.Label(label="Configura tu ubicación y pulsa «Calcular pasos».")
        self.meta_label.set_xalign(0)
        self.meta_label.add_css_class("caption")
        self.meta_label.add_css_class("dim-label")
        titles.append(title)
        titles.append(self.meta_label)
        head.append(titles)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Filtrar por satélite…")
        self.search_entry.set_hexpand(True)
        self.search_entry.set_halign(Gtk.Align.END)
        self.search_entry.set_max_width_chars(26)
        self.search_entry.connect("search-changed", lambda *_: self._render_list())
        head.append(self.search_entry)
        box.append(head)

        self.stack = Gtk.Stack()
        self.stack.set_vexpand(True)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

        self.empty_page = Adw.StatusPage()
        self.empty_page.set_icon_name("applications-science-symbolic")
        self.empty_page.set_title("Sin pasos todavía")
        self.empty_page.set_description("Configura tu ubicación y pulsa «Calcular pasos».")
        self.stack.add_named(self.empty_page, "empty")

        loading = Adw.StatusPage()
        loading.set_title("Calculando…")
        loading.set_description("Consultando órbitas y frecuencias")
        self.loading_spinner = Gtk.Spinner()
        self.loading_spinner.set_size_request(36, 36)
        loading.set_child(self.loading_spinner)
        self.stack.add_named(loading, "loading")

        results = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_margin_start(18)
        self.listbox.set_margin_end(18)
        self.listbox.set_margin_bottom(8)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(self.listbox)
        scroll.set_vexpand(True)
        results.append(scroll)
        self.more_btn = Gtk.Button(label="Mostrar más")
        self.more_btn.add_css_class("pill")
        self.more_btn.set_halign(Gtk.Align.CENTER)
        self.more_btn.set_margin_bottom(12)
        self.more_btn.set_visible(False)
        self.more_btn.connect("clicked", lambda *_: self._show_more())
        results.append(self.more_btn)
        self.stack.add_named(results, "results")

        self.stack.set_visible_child_name("empty")
        box.append(self.stack)
        return box

    # ============================================================== config
    def _read_config(self) -> dict:
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_config(self) -> None:
        groups = self._groups()
        cfg = {
            "lat": self.lat_row.get_value(),
            "lon": self.lon_row.get_value(),
            "alt": self.alt_row.get_value(),
            "alt_source": self.config.get("alt_source", "manual"),
            "days": DAYS[self.days_row.get_selected()],
            "min_el": MIN_EL[self.el_row.get_selected()],
            "groups": groups,
            "only_freq": self.only_freq_check.get_active(),
            "notify": self.notify_row.get_active(),
            "label": self.config.get("label", ""),
        }
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        self.config = cfg

    def _apply_config(self) -> None:
        cfg = self.config
        self.lat_row.set_value(float(cfg.get("lat") or 0.0))
        self.lon_row.set_value(float(cfg.get("lon") or 0.0))
        self._setting_alt = True
        self.alt_row.set_value(float(cfg.get("alt") or 0.0))
        self._setting_alt = False
        if cfg.get("alt_source") == "open-meteo":
            self.alt_row.set_subtitle("Terreno · Open-Meteo (suma el edificio a mano)")
        else:
            self.alt_row.set_subtitle("Del terreno; ajusta la altura del edificio a mano")

        days = int(cfg.get("days", 2))
        self.days_row.set_selected(DAYS.index(days) if days in DAYS else 1)
        min_el = int(cfg.get("min_el", 5))
        self.el_row.set_selected(MIN_EL.index(min_el) if min_el in MIN_EL else 1)

        groups = cfg.get("groups") or ["stations", "weather", "amateur"]
        for group_id, switch in self.switches.items():
            switch.set_active(group_id in groups)
        self.only_freq_check.set_active(bool(cfg.get("only_freq", True)))
        self.notify_row.set_active(bool(cfg.get("notify", True)))

        if cfg.get("label"):
            self.address_row.set_text(str(cfg["label"]))

    def _groups(self) -> list[str]:
        return [group_id for group_id, switch in self.switches.items() if switch.get_active()]

    # ============================================================ threading
    def _run_bg(self, fn: Callable[[], object], on_done: Callable[[object], object]) -> None:
        def worker() -> None:
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001
                GLib.idle_add(self._on_bg_error, str(exc))
                return
            GLib.idle_add(on_done, result)

        threading.Thread(target=worker, daemon=True).start()

    def _on_bg_error(self, message: str) -> None:
        self._set_busy(False)
        self._update_tle_status()
        self.stack.set_visible_child_name("results" if self.items else "empty")
        self._alert("No se pudo completar", message)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.calc_btn.set_sensitive(not busy)
        self.refresh_btn.set_sensitive(not busy)
        if busy:
            self.status.set_text("Calculando…")
            self.loading_spinner.start()
        else:
            self.status.set_text("")
            self.loading_spinner.stop()

    # ============================================================== arranque
    def _initial_load(self) -> bool:
        self._set_busy(True)
        self.stack.set_visible_child_name("loading")
        self._run_bg(lambda: self.data.load_catalog(self._groups()), self._on_catalog_loaded)
        return False

    def _on_catalog_loaded(self, _result: object) -> None:
        self._set_busy(False)
        self._update_tle_status()
        if self._has_location:
            self.calculate()
        else:
            self.stack.set_visible_child_name("empty")

    def _update_tle_status(self) -> None:
        if not self.data.tle_status:
            self.tle_label.set_text("TLE: —")
            return
        errors = [s for s in self.data.tle_status if s.get("error")]
        suffix = " · caché" if errors else ""
        self.tle_label.set_text(f"TLE: {fmt.fmt_age(self.data.tle_age_seconds())}{suffix}")

    # =============================================================== cálculo
    def calculate(self) -> None:
        if self.busy:
            return
        lat = self.lat_row.get_value()
        lon = self.lon_row.get_value()
        alt = self.alt_row.get_value()
        if not -90.0 <= lat <= 90.0:
            self._alert("Latitud no válida", "La latitud debe estar entre -90 y 90.")
            return
        if not -180.0 <= lon <= 180.0:
            self._alert("Longitud no válida", "La longitud debe estar entre -180 y 180.")
            return
        groups = self._groups()
        if not groups:
            self._alert("Sin grupos", "Selecciona al menos un grupo de satélites.")
            return

        days = DAYS[self.days_row.get_selected()]
        min_el = MIN_EL[self.el_row.get_selected()]
        only_freq = self.only_freq_check.get_active()
        self._has_location = True
        self._save_config()
        self._set_busy(True)
        self.stack.set_visible_child_name("loading")

        def work():
            self.data.load_catalog(groups)
            return self.data.find_passes(lat, lon, alt, days, min_el, groups, only_freq)

        self._run_bg(work, self._on_passes_ready)

    def _on_passes_ready(self, result: object) -> None:
        items, elapsed = result  # type: ignore[misc]
        self.items = items
        self.elapsed = elapsed
        self.shown = 250
        self._set_busy(False)
        self._update_tle_status()
        self.search_entry.set_text("")
        if not items:
            self.empty_page.set_title("No hay pasos")
            self.empty_page.set_description("Prueba con más días o una elevación mínima menor.")
            self.meta_label.set_text("")
            self.stack.set_visible_child_name("empty")
            return
        self._render_list()

    # ================================================================ lista
    def _show_more(self) -> None:
        self.shown += 250
        self._render_list()

    def _render_list(self) -> None:
        child = self.listbox.get_first_child()
        while child is not None:
            self.listbox.remove(child)
            child = self.listbox.get_first_child()
        self._row_widgets.clear()

        query = self.search_entry.get_text().strip().lower()
        self.filtered = [item for item in self.items if not query or query in item.sat.name.lower()]
        if not self.filtered:
            self.empty_page.set_title("Ningún paso coincide")
            self.empty_page.set_description("Prueba con otro nombre o borra el filtro.")
            self.meta_label.set_text(f"0 de {len(self.items)} pasos")
            self.stack.set_visible_child_name("empty")
            self.more_btn.set_visible(False)
            return

        self.stack.set_visible_child_name("results")
        for item in self.filtered[: self.shown]:
            row = self._make_row(item)
            self.listbox.append(row)
            self._row_widgets[self._pass_key(item)] = row
        self.meta_label.set_text(
            f"{len(self.filtered)} de {len(self.items)} pasos · calculado en {self.elapsed:.1f} s"
        )
        remaining = len(self.filtered) - self.shown
        self.more_btn.set_visible(remaining > 0)
        if remaining > 0:
            self.more_btn.set_label(f"Mostrar más ({remaining} restantes)")
        self._tick()

    def _make_row(self, item: PassItem) -> Gtk.Widget:
        now = time.time()
        live = item.aos <= now <= item.los
        subtitle = (
            f"Aparece {fmt.fmt_time(item.aos)} ({fmt.relative_day(item.aos)}) · "
            f"{fmt.fmt_dur(item.duration_s)} · Altura {item.max_el:.0f}° · "
            f"{fmt.compass_word(item.az_aos).capitalize()} → "
            f"{fmt.compass_word(item.az_los).capitalize()}"
        )
        if live:
            subtitle += " · en curso"

        row = Adw.ActionRow()
        row.add_css_class("pass-row")
        row.set_use_markup(False)
        row.set_title(item.sat.name)
        row.set_subtitle(subtitle)
        row.set_subtitle_lines(2)
        row.set_activatable(True)

        suffix = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        suffix.set_valign(Gtk.Align.CENTER)
        freq = Gtk.Label(label=fmt.fmt_freq(item.freq_hz))
        freq.set_xalign(1)
        freq.add_css_class("mono")
        suffix.append(freq)
        if item.doppler_max_hz is not None:
            dop = Gtk.Label(label=f"±{abs(item.doppler_max_hz) / 1000:.1f} kHz")
            dop.set_xalign(1)
            dop.add_css_class("caption")
            dop.add_css_class("dim-label")
            suffix.append(dop)
        row.add_suffix(suffix)
        row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        row.connect("activated", lambda *_: self.show_detail(item))
        return row

    # ================================================================ avisos
    @staticmethod
    def _pass_key(item: PassItem) -> tuple[int, int]:
        return (item.sat.norad, int(round(item.aos)))

    def _tick(self) -> bool:
        """Resalta los pasos próximos y avisa 5 minutos antes."""
        now = time.time()
        lead = 5 * 60.0
        soon: set[tuple[int, int]] = set()
        live: set[tuple[int, int]] = set()
        for item in self.items:
            key = self._pass_key(item)
            if item.aos <= now <= item.los:
                live.add(key)
            elif 0 < item.aos - now <= lead:
                soon.add(key)
                if self.notify_row.get_active() and key not in self._notified:
                    self._notified.add(key)
                    self._send_notification(item, now)
        for key, row in self._row_widgets.items():
            row.remove_css_class("soon")
            row.remove_css_class("live")
            if key in soon:
                row.add_css_class("soon")
            elif key in live:
                row.add_css_class("live")
        return True

    def _send_notification(self, item: PassItem, now: float) -> None:
        minutes = max(1, round((item.aos - now) / 60.0))
        note = Gio.Notification.new(f"{item.sat.name} en {minutes} min")
        direction = (
            f"{fmt.compass_word(item.az_aos).capitalize()} → "
            f"{fmt.compass_word(item.az_los).capitalize()}"
        )
        freq = f" · {fmt.fmt_freq(item.freq_hz)}" if item.freq_hz else ""
        note.set_body(
            f"{fmt.fmt_time(item.aos)} · Altura {item.max_el:.0f}° · {direction}{freq}"
        )
        note.set_icon(Gio.ThemedIcon.new("io.github.asterion.PasoOrbital"))
        note.set_priority(Gio.NotificationPriority.HIGH)
        note.set_default_action("app.present")
        self.app.send_notification(
            f"pass-{item.sat.norad}-{int(item.aos)}", note
        )

    # ================================================================ detalle
    def show_detail(self, item: PassItem) -> None:
        if self._detail_dialog is not None:
            self._detail_dialog.close()

        dialog = Adw.Dialog()
        dialog.set_content_width(960)
        dialog.set_content_height(600)
        dialog.set_can_close(True)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(
            Adw.WindowTitle(title=item.sat.name, subtitle=f"NORAD {item.sat.norad}")
        )

        stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher()
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        switcher.set_stack(stack)
        header.pack_start(switcher)

        toolbar.add_top_bar(header)

        stack.add_titled(self._detail_summary_page(item, stack), "summary", "Resumen")
        stack.add_titled(self._detail_radio_page(item), "radio", "Radio")
        stack.add_titled(self._detail_sky_page(item), "sky", "Cielo")
        stack.set_visible_child_name("summary")
        stack.set_vexpand(True)
        toolbar.set_content(stack)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.set_margin_top(8)
        footer.set_margin_bottom(8)
        footer.set_margin_start(14)
        footer.set_margin_end(14)
        save = Gtk.Button(label="Guardar .ics")
        save.add_css_class("flat")
        save.connect("clicked", lambda *_: self._save_ics(item))
        footer.append(save)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        footer.append(spacer)
        close = Gtk.Button(label="Cerrar")
        close.connect("clicked", lambda *_: dialog.close())
        footer.append(close)
        toolbar.add_bottom_bar(footer)

        dialog.set_child(toolbar)
        self._detail_dialog = dialog
        dialog.present(self)

    def _detail_summary_page(self, item: PassItem, stack: Adw.ViewStack) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(20)
        box.set_margin_bottom(18)
        box.set_margin_start(24)
        box.set_margin_end(24)
        box.set_vexpand(True)

        now = time.time()
        if item.aos <= now <= item.los:
            state = "En curso"
        elif now < item.aos:
            minutes = max(1, round((item.aos - now) / 60.0))
            state = (
                f"Empieza en {minutes} min"
                if minutes < 60
                else f"Empieza {fmt.relative_day(item.aos)} a las {fmt.fmt_time(item.aos)}"
            )
        else:
            state = "Pasado"
        badge = Gtk.Label(label=state)
        badge.set_xalign(0)
        badge.set_halign(Gtk.Align.START)
        badge.add_css_class("badge")
        box.append(badge)

        summary = Gtk.Label()
        summary.set_markup(fmt.summary(item))
        summary.set_wrap(True)
        summary.set_xalign(0)
        summary.add_css_class("summary")
        box.append(summary)

        box.append(self._heading("Horario"))
        box.append(self._stats_grid(item))

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        radio = Gtk.Button(label="Ver radio")
        radio.add_css_class("flat")
        radio.connect("clicked", lambda *_: stack.set_visible_child_name("radio"))
        sky = Gtk.Button(label="Ver cielo")
        sky.add_css_class("flat")
        sky.connect("clicked", lambda *_: stack.set_visible_child_name("sky"))
        actions.append(radio)
        actions.append(sky)
        box.append(actions)

        hint = Gtk.Label(
            label="Usa las pestañas Radio y Cielo para frecuencias, comandos y trayectoria."
        )
        hint.set_xalign(0)
        hint.set_wrap(True)
        hint.add_css_class("caption")
        hint.add_css_class("dim-label")
        box.append(hint)
        return box

    def _detail_radio_page(self, item: PassItem) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(20)
        box.set_margin_bottom(18)
        box.set_margin_start(24)
        box.set_margin_end(24)
        box.set_vexpand(True)

        channels = item.sat.channels
        if not channels:
            hint = Gtk.Label(label="Sin frecuencia de escucha registrada para este satélite.")
            hint.set_xalign(0)
            hint.set_wrap(True)
            hint.add_css_class("dim-label")
            box.append(hint)
            return box

        selector = None
        if len(channels) > 1:
            labels = [
                f"{fmt.fmt_freq(ch.get('freq_hz'))} · {ch.get('mode') or 'sin modo'}"
                for ch in channels
            ]
            selector = Adw.ComboRow(title="Frecuencia")
            selector.set_model(Gtk.StringList.new(labels))
            box.append(selector)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.append(body)

        def rebuild(*_args) -> None:
            child = body.get_first_child()
            while child is not None:
                body.remove(child)
                child = body.get_first_child()
            index = selector.get_selected() if selector is not None else 0
            channel = channels[index] if 0 <= index < len(channels) else channels[0]
            body.append(self._channel_card(channel))
            if channel.get("freq_hz"):
                body.append(self._heading("Doppler"))
                body.append(self._doppler_grid(item, channel["freq_hz"]))
            body.append(self._heading("Comando de escucha"))
            body.append(self._command_card(channel, item))
            note = Gtk.Label(
                label=(
                    "El Doppler se calcula sobre la frecuencia seleccionada. "
                    "En SatDump, el primer argumento es el pipeline y el segundo la carpeta de salida."
                )
            )
            note.set_xalign(0)
            note.set_wrap(True)
            note.add_css_class("caption")
            note.add_css_class("dim-label")
            body.append(note)

        if selector is not None:
            selector.connect("notify::selected", rebuild)
        rebuild()
        return box

    def _detail_sky_page(self, item: PassItem) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(20)
        box.set_margin_bottom(18)
        box.set_margin_start(24)
        box.set_margin_end(24)
        box.set_vexpand(True)

        hint = Gtk.Label(
            label="El centro del círculo polar es el cenit; el borde es el horizonte."
        )
        hint.set_xalign(0)
        hint.set_wrap(True)
        hint.add_css_class("caption")
        hint.add_css_class("dim-label")
        box.append(hint)

        points = self.data.track(item)
        plots = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        plots.set_halign(Gtk.Align.CENTER)
        plots.set_valign(Gtk.Align.CENTER)
        plots.set_vexpand(True)
        plots.append(SkyPlot(points, item))
        plots.append(ElevationPlot(points, item))
        box.append(plots)

        legend = Gtk.Label(
            label="Verde: aparición · Ámbar: punto más alto · Rojo: salida"
        )
        legend.set_xalign(0)
        legend.add_css_class("caption")
        legend.add_css_class("dim-label")
        box.append(legend)
        return box

    def _heading(self, text: str) -> Gtk.Label:
        label = Gtk.Label(label=text)
        label.set_xalign(0)
        label.add_css_class("title-4")
        return label

    def _stat_card(self, key: str, value: str, small: str = "") -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        card.add_css_class("stat")
        title = Gtk.Label(label=key)
        title.set_xalign(0)
        title.add_css_class("caption")
        title.add_css_class("dim-label")
        val = Gtk.Label(label=value)
        val.set_xalign(0)
        val.add_css_class("stat-value")
        card.append(title)
        card.append(val)
        if small:
            sub = Gtk.Label(label=small)
            sub.set_xalign(0)
            sub.add_css_class("caption")
            sub.add_css_class("dim-label")
            card.append(sub)
        return card

    def _stats_grid(self, item: PassItem) -> Gtk.Widget:
        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(10)
        grid.set_column_homogeneous(True)

        dir_a = fmt.compass_word(item.az_aos).capitalize()
        dir_l = fmt.compass_word(item.az_los).capitalize()
        cards = [
            ("Aparece", fmt.fmt_time(item.aos), fmt.relative_day(item.aos)),
            ("Punto más alto", fmt.fmt_time(item.tca), fmt.relative_day(item.tca)),
            ("Termina", fmt.fmt_time(item.los), fmt.relative_day(item.los)),
            ("Duración", fmt.fmt_dur(item.duration_s), ""),
            ("Altura máxima", f"{item.max_el:.1f}°", ""),
            ("Dirección", f"{dir_a} → {dir_l}", f"{round(item.az_aos)}° → {round(item.az_los)}°"),
            ("Distancia en el punto más alto", f"{item.range_tca:.0f} km", ""),
            ("TLE", f"{item.sat.tle_age_days:.1f} días", ""),
        ]
        for index, (key, value, small) in enumerate(cards):
            grid.attach(self._stat_card(key, value, small), index % 4, index // 4, 1, 1)
        return grid

    def _channel_card(self, channel: dict) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        card.add_css_class("stat")
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        freq = Gtk.Label(label=fmt.fmt_freq(channel.get("freq_hz")))
        freq.set_xalign(0)
        freq.add_css_class("mono")
        top.append(freq)
        if channel.get("mode"):
            mode = Gtk.Label(label=channel["mode"])
            mode.add_css_class("badge")
            top.append(mode)
        card.append(top)
        if channel.get("label"):
            label = Gtk.Label(label=channel["label"])
            label.set_xalign(0)
            label.set_wrap(True)
            card.append(label)
        if channel.get("note"):
            note = Gtk.Label(label=channel["note"])
            note.set_xalign(0)
            note.set_wrap(True)
            note.add_css_class("caption")
            note.add_css_class("dim-label")
            card.append(note)
        if channel.get("uplink_hz"):
            uplink = Gtk.Label(label=f"Subida: {fmt.fmt_freq(channel['uplink_hz'])}")
            uplink.set_xalign(0)
            uplink.add_css_class("caption")
            uplink.add_css_class("dim-label")
            card.append(uplink)
        return card

    def _doppler_grid(self, item: PassItem, freq_hz: int | None = None) -> Gtk.Widget:
        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(10)
        grid.set_column_homogeneous(True)
        freq = freq_hz or item.freq_hz or 0
        entries = [
            ("Al aparecer (se acerca)", item.doppler_aos_hz),
            ("En el punto más alto", item.doppler_tca_hz),
            ("Al irse (se aleja)", item.doppler_los_hz),
        ]
        for index, (key, shift) in enumerate(entries):
            if shift is None:
                continue
            shifted = freq + shift
            card = self._stat_card(key, fmt.fmt_freq(round(shifted)), fmt.fmt_dop(shift))
            grid.attach(card, index, 0, 1, 1)
        return grid

    def _command_card(self, channel: dict, item: PassItem) -> Gtk.Widget:
        command = fmt.command_for(channel, item)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("command")
        text = Gtk.Label(label=command)
        text.set_xalign(0)
        text.set_wrap(True)
        text.set_selectable(True)
        text.add_css_class("mono")
        card.append(text)
        copy = Gtk.Button(label="Copiar")
        copy.add_css_class("flat")
        copy.set_halign(Gtk.Align.END)
        copy.connect("clicked", lambda *_: self._copy(command, copy))
        card.append(copy)
        return card

    def _copy(self, text: str, button: Gtk.Button) -> None:
        clipboard = self.get_clipboard()
        value = GObject.Value()
        value.init(GObject.TYPE_STRING)
        value.set_string(text)
        clipboard.set(value)
        button.set_label("Copiado")
        GLib.timeout_add(1500, self._reset_copy_button, button)

    def _reset_copy_button(self, button: Gtk.Button) -> bool:
        button.set_label("Copiar")
        return False

    def _save_ics(self, item: PassItem) -> None:
        dialog = Gtk.FileDialog()
        dialog.set_title("Guardar calendario")
        dialog.set_initial_name(f"pasoorbital-{item.sat.norad}-{int(item.aos)}.ics")
        dialog.save(self, None, self._on_ics_saved, item)

    def _on_ics_saved(self, dialog: Gtk.FileDialog, result, item: PassItem) -> None:
        try:
            file = dialog.save_finish(result)
        except GLib.Error:
            return
        path = file.get_path()
        if not path:
            return
        try:
            Path(path).write_text(fmt.calendar(item), encoding="utf-8")
        except OSError as exc:
            self._alert("No se pudo guardar", str(exc))
            return
        self._alert("Calendario guardado", path)

    # ============================================================ geocodificación
    def geocode(self) -> None:
        query = self.address_row.get_text().strip()
        if len(query) < 3:
            self._alert("Dirección corta", "Escribe una dirección de al menos 3 caracteres.")
            return
        self.address_row.set_sensitive(False)
        self.search_btn.set_sensitive(False)
        self._run_bg(lambda: self.data.geocoder.search(query), self._on_geo_results)

    def _on_geo_results(self, results: object) -> None:
        self.address_row.set_sensitive(True)
        self.search_btn.set_sensitive(True)
        self._geo_results = list(results)  # type: ignore[arg-type]
        if not self._geo_results:
            self._alert("Sin resultados", "No se encontró esa dirección. Prueba con más detalle.")
            return

        child = self.geo_list.get_first_child()
        while child is not None:
            self.geo_list.remove(child)
            child = self.geo_list.get_first_child()

        for result in self._geo_results:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(10)
            box.set_margin_end(10)
            name = Gtk.Label(label=result["name"])
            name.set_xalign(0)
            name.set_wrap(True)
            coords = Gtk.Label(label=f"{result['lat']:.4f}, {result['lon']:.4f}")
            coords.set_xalign(0)
            coords.add_css_class("caption")
            coords.add_css_class("dim-label")
            box.append(name)
            box.append(coords)
            row.set_child(box)
            self.geo_list.append(row)
        self.geo_popover.popup()

    def _on_geo_row_activated(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        index = row.get_index()
        if 0 <= index < len(self._geo_results):
            self._choose_location(self._geo_results[index])

    def _choose_location(self, result: dict) -> None:
        self.geo_popover.popdown()
        self.lat_row.set_value(float(result["lat"]))
        self.lon_row.set_value(float(result["lon"]))
        self.config["label"] = result["name"]
        self.address_row.set_text(result["name"])
        self._has_location = True
        self._save_config()
        self.auto_elevation()

    # ---------------------------------------------------------- altitud
    def auto_elevation(self) -> None:
        lat = float(self.lat_row.get_value())
        lon = float(self.lon_row.get_value())
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            self._alert("Coordenadas no válidas", "Revisa la latitud y la longitud.")
            return
        self._has_location = True
        self._elevation_token = (round(lat, 4), round(lon, 4))
        self.status.set_text("Buscando la altitud del terreno…")
        self._run_bg(
            lambda: self.data.geocoder.elevation(lat, lon), self._on_elevation
        )

    def _on_alt_changed(self, *_args) -> None:
        if self._setting_alt:
            return
        self.config["alt_source"] = "manual"
        self.alt_row.set_subtitle("Del terreno; ajusta la altura del edificio a mano")
        self._save_config()

    def _on_elevation(self, value: object) -> None:
        lat = round(float(self.lat_row.get_value()), 4)
        lon = round(float(self.lon_row.get_value()), 4)
        if self._elevation_token != (lat, lon):
            return
        self.status.set_text("")
        alt = None
        try:
            if value is not None:
                alt = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            alt = None
        if alt is not None and -500.0 <= alt <= 9000.0:
            meters = int(round(alt))
            self._setting_alt = True
            self.alt_row.set_value(float(meters))
            self._setting_alt = False
            self.config["alt"] = meters
            self.config["alt_source"] = "open-meteo"
            self.alt_row.set_subtitle("Terreno · Open-Meteo (suma el edificio a mano)")
        else:
            self.config["alt_source"] = "manual"
            self.alt_row.set_subtitle("Ajusta la altitud a mano")
        self._save_config()
        if self._has_location:
            self.calculate()

    # ================================================================ varios
    def refresh_tle(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self.status.set_text("Actualizando TLE…")
        self._run_bg(
            lambda: self.data.load_catalog(self._groups(), force=True),
            self._on_tle_refreshed,
        )

    def _on_tle_refreshed(self, _result: object) -> None:
        self._set_busy(False)
        self._update_tle_status()
        if self._has_location:
            self.calculate()

    def _alert(self, heading: str, body: str) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "Aceptar")
        dialog.present(self)

    def show_about(self) -> None:
        about = Adw.AboutDialog(
            application_name="PasoOrbital",
            application_icon="io.github.asterion.PasoOrbital",
            developer_name="Marcos Matamala Fernandez",
            developers=[
                "Marcos Matamala Fernandez",
                "DeepSeek Harness (deepseek-flash)",
            ],
            documenters=["DeepSeek Harness (deepseek-flash)"],
            copyright="© 2026 Marcos Matamala Fernandez",
            version=__version__,
            license_type=Gtk.License.MIT_X11,
            comments="Predicción de pasos de satélites para escucha radio.",
            website="https://github.com/asterion/pasoorbital",
            issue_url="https://github.com/asterion/pasoorbital/issues",
        )
        about.present(self)
