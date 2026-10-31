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
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk  # noqa: E402

from . import __version__, format as fmt  # noqa: E402
from .data import PassItem, PasoOrbitalData, filter_passes  # noqa: E402
from pasoorbital.passes import C_KM_S, look_at  # noqa: E402
from .skyplot import ElevationPlot, SkyPlot, sample_track  # noqa: E402

DAYS = [1, 2, 3, 7]
MIN_EL = [0, 5, 10, 15, 20, 30]
GROUPS = [
    ("stations", "Estación Espacial"),
    ("weather", "Meteorológicos"),
    ("amateur", "Radioaficionados"),
    ("cubesat", "CubeSats"),
]

ASSETS_DIR = Path(__file__).with_name("assets")
ASTRO_FILE = ASSETS_DIR / "astro.png"


class PasoOrbitalWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, data: PasoOrbitalData):
        super().__init__(application=app)
        self.app = app
        self.data = data
        self.config_path = Path(GLib.get_user_config_dir()) / "pasoorbital" / "config.json"

        self.config = self._read_config()
        self._address_full = str(self.config.get("label") or "")
        self.items: list[PassItem] = []
        self.filtered: list[PassItem] = []
        self._geo_results: list[dict] = []
        self._elevation_token: tuple[float, float] | None = None
        self._setting_alt = False
        self._row_widgets: dict[tuple[int, int], Gtk.Widget] = {}
        self._row_meta: dict[Gtk.ListBoxRow, tuple[str, float]] = {}
        self._notified: set[tuple[int, int]] = set()
        self._detail_dialog: Adw.Dialog | None = None
        self._listen_phase: Gtk.Label | None = None
        self._listen_countdown: Gtk.Label | None = None
        self._listen_now: Gtk.Label | None = None
        self._listen_doppler: Gtk.Label | None = None
        self._pending_pass_key: str | None = None
        self._live_item: PassItem | None = None
        self._live_points: list[tuple[float, float, float, float, float]] = []
        self._live_sky: SkyPlot | None = None
        self._live_elev: ElevationPlot | None = None
        self._live_badge: Gtk.Label | None = None
        self._live_label: Gtk.Label | None = None
        self._live_progress: Gtk.ProgressBar | None = None
        self._live_source: int | None = None
        self.shown = 250
        self.elapsed = 0.0
        self.busy = False
        self._has_location = self.config.get("lat") is not None and self.config.get("lon") is not None
        self._calc_timer: int | None = None
        self._calc_pending = False
        self._status_loading = False

        self.set_default_size(1280, 840)
        self.set_size_request(980, 640)
        self.set_title("PasoOrbital")

        self._build_ui()
        self._apply_config()
        self._connect_filter_signals()
        GLib.idle_add(self._initial_load)
        GLib.idle_add(self._load_statuses)
        GLib.timeout_add_seconds(10, self._tick)

    # ================================================================ UI
    def _build_ui(self) -> None:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        if ASTRO_FILE.exists():
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                str(ASTRO_FILE), 34, 34, True
            )
            astro = Gtk.Picture.new_for_pixbuf(pixbuf)
            astro.set_can_shrink(False)
            astro.set_size_request(34, 34)
            astro.set_valign(Gtk.Align.CENTER)
            astro.set_tooltip_text("Astro, mascota de PasoOrbital")
            brand.append(astro)
        brand.append(
            Adw.WindowTitle(title="PasoOrbital", subtitle="Pasos de satélites para escucha")
        )
        header.set_title_widget(brand)
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

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(380)
        paned.set_resize_start_child(False)
        paned.set_shrink_start_child(False)

        paned.set_start_child(self._build_sidebar())

        self.notify_btn = Gtk.ToggleButton(label="Avisos")
        self.notify_btn.set_tooltip_text("Avisar 5 minutos antes")
        self.notify_btn.add_css_class("flat")
        self.notify_btn.set_active(self.notify_row.get_active())
        self.notify_btn.connect("toggled", self._on_notify_btn_toggled)
        header.pack_start(self.notify_btn)

        paned.set_end_child(self._build_content())
        toolbar.add_top_bar(header)
        toolbar.set_content(paned)
        self.set_content(toolbar)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)

    def _on_key_pressed(self, _controller, keyval, _keycode, state) -> bool:
        if keyval == Gdk.KEY_f and state & Gdk.ModifierType.CONTROL_MASK:
            self.search_entry.grab_focus()
            return True
        if keyval == Gdk.KEY_F5:
            self.refresh_tle()
            return True
        return False

    def _build_sidebar(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        page.set_vexpand(True)

        location = Adw.PreferencesGroup(title="Ubicación")
        self.address_row = Adw.EntryRow(title="Dirección")
        self.address_row.set_text(fmt.short_address(self._address_full))
        self.address_row.set_position(0)
        self.address_row.set_tooltip_text(self._address_full)
        self.address_row.set_show_apply_button(False)
        self.address_row.connect("apply", lambda *_: self.geocode())
        self.search_btn = Gtk.Button(label="Buscar")
        self.search_btn.set_valign(Gtk.Align.CENTER)
        self.search_btn.add_css_class("flat")
        self.search_btn.set_tooltip_text("Buscar la dirección escrita")
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
        self.alt_row.add_css_class("alt-row")
        self.alt_row.set_subtitle("Fuente: Open-Meteo (terreno)\nEdificio: manual")
        self.alt_row.set_subtitle_lines(2)
        self.alt_btn = Gtk.Button(label="Obtener")
        self.alt_btn.set_tooltip_text(
            "Obtener automáticamente la altitud del terreno con Open-Meteo"
        )
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

        self.only_freq_check = Adw.SwitchRow(title="Solo con frecuencia conocida")
        self.only_freq_check.set_subtitle("Oculta los satélites sin frecuencia registrada")
        self.only_freq_check.set_active(True)
        prediction.add(self.only_freq_check)

        self.notify_row = Adw.SwitchRow(title="Avisar 5 min antes")
        self.notify_row.set_active(True)
        self.notify_row.set_tooltip_text("Notificación del escritorio al acercarse un paso")
        self.notify_row.connect("notify::active", lambda *_: self._save_config())
        self.notify_row.connect("notify::active", self._on_notify_row_changed)
        prediction.add(self.notify_row)

        calc_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        calc_box.set_margin_top(6)
        calc_box.set_halign(Gtk.Align.END)
        self.calc_btn = Gtk.Button(label="Calcular pasos")
        self.calc_btn.add_css_class("suggested-action")
        self.calc_btn.set_tooltip_text(
            "Recalcular ahora. Los cambios de días, elevación y grupos se aplican automáticamente."
        )
        self.calc_btn.connect("clicked", lambda *_: self.calculate())
        calc_box.append(self.calc_btn)
        prediction.add(calc_box)

        filter_hint = Gtk.Label(
            label="Días, elevación y grupos se recalculan automáticamente."
        )
        filter_hint.set_xalign(0)
        filter_hint.set_wrap(True)
        filter_hint.add_css_class("caption")
        filter_hint.add_css_class("filter-hint")
        prediction.add(filter_hint)

        page.add(prediction)

        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bottom.set_margin_top(10)
        bottom.set_margin_bottom(12)
        bottom.set_margin_start(14)
        bottom.set_margin_end(14)

        self.status = Gtk.Label(label="")
        self.status.set_xalign(0)
        self.status.set_wrap(True)
        self.status.add_css_class("caption")
        self.status.add_css_class("dim-label")
        bottom.append(self.status)

        tle_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        self.tle_icon = Gtk.Image.new_from_icon_name("dialog-question-symbolic")
        self.tle_icon.set_pixel_size(14)
        self.tle_icon.set_valign(Gtk.Align.CENTER)
        self.tle_icon.set_tooltip_text(
            "TLE: elementos orbitales. Cuanto más recientes, mejor la predicción."
        )
        self.tle_label = Gtk.Label(label="TLE: —")
        self.tle_label.set_xalign(0)
        self.tle_label.add_css_class("caption")
        self.tle_label.add_css_class("tle-label")
        self.tle_label.set_tooltip_text(
            "TLE: elementos orbitales del satélite. CelesTrak se actualiza cada 6 h; "
            "una edad menor significa una predicción más precisa."
        )
        tle_box.append(self.tle_icon)
        tle_box.append(self.tle_label)
        bottom.append(tle_box)

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
        self.meta_label = Gtk.Label(
            label="Configura tu ubicación y pulsa «Calcular pasos»."
        )
        self.meta_label.set_xalign(0)
        self.meta_label.set_wrap(True)
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
        if ASTRO_FILE.exists():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    str(ASTRO_FILE), 256, 256, True
                )
                self.empty_page.set_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
            except GLib.Error:
                pass
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
        self.listbox.set_header_func(self._list_header)
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
            self.alt_row.set_subtitle(
                "Fuente: Open-Meteo (terreno)\nEdificio: manual"
            )
        else:
            self.alt_row.set_subtitle("Fuente: manual\nAltitud introducida a mano")

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
            self._address_full = str(cfg["label"])
            self.address_row.set_text(fmt.short_address(self._address_full))
            self.address_row.set_position(0)
            self.address_row.set_tooltip_text(self._address_full)

    def _groups(self) -> list[str]:
        return [group_id for group_id, switch in self.switches.items() if switch.get_active()]

    # ---------------------------------------------------------- reactividad
    def _connect_filter_signals(self) -> None:
        self.only_freq_check.connect("notify::active", self._on_only_freq_changed)
        for switch in self.switches.values():
            switch.connect("toggled", self._on_filter_changed)
        self.days_row.connect("notify::selected", self._on_filter_changed)
        self.el_row.connect("notify::selected", self._on_filter_changed)

    def _on_only_freq_changed(self, *_args) -> None:
        self._save_config()
        if self.items:
            self._render_list()

    def _on_filter_changed(self, *_args) -> None:
        self._save_config()
        if not self._groups():
            self._show_no_groups()
            return
        if self.items:
            self._render_list()
        self._schedule_recalculate()

    def _schedule_recalculate(self) -> None:
        if not self._has_location:
            return
        if self._calc_timer is not None:
            GLib.source_remove(self._calc_timer)
        self._calc_timer = GLib.timeout_add(300, self._run_scheduled_calc)

    def _run_scheduled_calc(self) -> bool:
        self._calc_timer = None
        if self.busy:
            self._calc_pending = True
            return False
        self.calculate()
        return False

    def _maybe_run_pending(self) -> None:
        if not self._calc_pending:
            return
        self._calc_pending = False
        self._schedule_recalculate()

    def _show_no_groups(self) -> None:
        if self._calc_timer is not None:
            GLib.source_remove(self._calc_timer)
            self._calc_timer = None
        self._calc_pending = False
        self.items = []
        self.filtered = []
        self.shown = 250
        self.empty_page.set_title("Sin grupos")
        self.empty_page.set_description("Selecciona al menos un grupo de satélites.")
        self.meta_label.set_text("")
        self.stack.set_visible_child_name("empty")

    # ------------------------------------------------------- estado SATCAT
    def _load_statuses(self, force: bool = False) -> bool:
        if self._status_loading:
            return False
        self._status_loading = True

        def work() -> None:
            try:
                self.data.load_statuses(force=force)
            except Exception:  # noqa: BLE001
                pass
            GLib.idle_add(self._on_statuses_loaded)

        threading.Thread(target=work, daemon=True).start()
        return False

    def _on_statuses_loaded(self) -> None:
        self._status_loading = False
        if not self.get_visible():
            return
        if self.items:
            self._render_list()

    def _status_badge(self, norad: int) -> Gtk.Label | None:
        status = self.data.status_for(norad)
        if status is None:
            return None
        badge = Gtk.Label(label=status.short)
        badge.add_css_class("status-badge")
        badge.add_css_class(f"status-{status.slug}")
        badge.set_tooltip_text(status.tooltip())
        return badge

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
        self._maybe_run_pending()

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
            self.tle_label.set_tooltip_text(
                "Sin datos de TLE. Pulsa actualizar para descargarlos."
            )
            self.tle_icon.set_from_icon_name("dialog-question-symbolic")
            self.tle_icon.set_tooltip_text("Sin datos de TLE")
            return
        errors = [s for s in self.data.tle_status if s.get("error")]
        age = self.data.tle_age_seconds()
        suffix = " · caché" if errors else ""
        self.tle_label.set_text(f"TLE: {fmt.fmt_age(age)}{suffix}")
        if errors:
            detail = "No se pudo actualizar; se usa la copia en caché."
            icon = "dialog-warning-symbolic"
        elif age > 6 * 3600:
            detail = "El TLE tiene más de 6 horas; la predicción puede perder precisión."
            icon = "dialog-warning-symbolic"
        else:
            detail = "TLE reciente; buena precisión para los próximos pasos."
            icon = "emblem-ok-symbolic"
        tooltip = (
            f"{detail}\n"
            "TLE = elementos orbitales del satélite. CelesTrak se actualiza cada 6 h."
        )
        self.tle_label.set_tooltip_text(tooltip)
        self.tle_icon.set_from_icon_name(icon)
        self.tle_icon.set_tooltip_text(detail)

    # =============================================================== cálculo
    def calculate(self) -> None:
        if self._calc_timer is not None:
            GLib.source_remove(self._calc_timer)
            self._calc_timer = None
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
        self._has_location = True
        self._save_config()
        self._set_busy(True)
        self.stack.set_visible_child_name("loading")

        def work():
            self.data.load_catalog(groups)
            # Se calculan todos los pasos; «Solo con frecuencia conocida» se
            # aplica en la lista para que el cambio sea inmediato.
            return self.data.find_passes(lat, lon, alt, days, min_el, groups, False)

        self._run_bg(work, self._on_passes_ready)

    def _on_passes_ready(self, result: object) -> None:
        items, elapsed = result  # type: ignore[misc]
        self.items = items
        self.elapsed = elapsed
        self.shown = 250
        self._set_busy(False)
        self._update_tle_status()
        self.search_entry.set_text("")
        if not self._groups():
            self._show_no_groups()
            self._maybe_run_pending()
            return
        if not items:
            self.empty_page.set_title("No hay pasos")
            self.empty_page.set_description("Prueba con más días o una elevación mínima menor.")
            self.meta_label.set_text("")
            self.stack.set_visible_child_name("empty")
            self._maybe_run_pending()
            return
        self._render_list()
        self._consume_pending_detail()
        self._maybe_run_pending()

    # ================================================================ lista
    def _show_more(self) -> None:
        self.shown += 250
        self._render_list()

    def _filter_reasons(
        self,
        query: str,
        only_freq: bool,
        selected_groups: set[str],
        min_el: int,
    ) -> list[str]:
        reasons: list[str] = []
        if query:
            reasons.append(f'texto «{query[:24]}»')
        if only_freq:
            reasons.append("frecuencia conocida")
        if selected_groups and len(selected_groups) < len(self.switches):
            label = "grupo" if len(selected_groups) == 1 else "grupos"
            reasons.append(f"{len(selected_groups)} {label}")
        if min_el > 0:
            reasons.append(f"≥{min_el}°")
        return reasons

    def _render_list(self) -> None:
        child = self.listbox.get_first_child()
        while child is not None:
            self.listbox.remove(child)
            child = self.listbox.get_first_child()
        self._row_widgets.clear()
        self._row_meta.clear()

        query = self.search_entry.get_text().strip().lower()
        only_freq = self.only_freq_check.get_active()
        selected_groups = set(self._groups())
        min_el = MIN_EL[self.el_row.get_selected()]
        days = DAYS[self.days_row.get_selected()]
        limit = time.time() + days * 86400.0
        self.filtered = filter_passes(
            self.items,
            query=query,
            only_freq=only_freq,
            groups=selected_groups,
            min_el=min_el,
            limit=limit,
        )
        if not self.filtered:
            if not selected_groups:
                self._show_no_groups()
                return
            if only_freq and not query:
                self.empty_page.set_title("Ningún paso con frecuencia conocida")
                self.empty_page.set_description(
                    "Desactiva «Solo con frecuencia conocida» para ver todos los pasos."
                )
            elif query:
                self.empty_page.set_title("Ningún paso coincide")
                self.empty_page.set_description("Prueba con otro nombre o borra el filtro.")
            else:
                self.empty_page.set_title("Ningún paso con estos filtros")
                self.empty_page.set_description(
                    "Prueba con más días, una elevación mínima menor u otro grupo."
                )
            self.meta_label.set_text(
                f"0 de {len(self.items)} pasos calculados · revisa los filtros"
            )
            self.stack.set_visible_child_name("empty")
            self.more_btn.set_visible(False)
            return

        self.stack.set_visible_child_name("results")
        for item in self.filtered[: self.shown]:
            row = self._make_row(item)
            self.listbox.append(row)
            self._row_widgets[self._pass_key(item)] = row

        reasons = self._filter_reasons(query, only_freq, selected_groups, min_el)
        detail = f" · {' · '.join(reasons)}" if reasons else ""
        self.meta_label.set_text(
            f"{len(self.filtered)}/{len(self.items)} calculados{detail}"
        )
        self.meta_label.set_tooltip_text(
            "Pasos mostrados / pasos calculados"
            + (f". Filtros: {', '.join(reasons)}." if reasons else ".")
            + f" Tiempo de cálculo: {self.elapsed:.1f} s."
        )
        remaining = len(self.filtered) - self.shown
        self.more_btn.set_visible(remaining > 0)
        if remaining > 0:
            self.more_btn.set_label(f"Mostrar más ({remaining} restantes)")
        self._tick()

    def _list_header(self, row: Gtk.ListBoxRow, before: Gtk.ListBoxRow | None) -> None:
        meta = self._row_meta.get(row)
        if meta is None:
            row.set_header(None)
            return
        day, aos = meta
        before_meta = self._row_meta.get(before) if before is not None else None
        if before_meta is not None and before_meta[0] == day:
            row.set_header(None)
            return
        label = Gtk.Label(label=fmt.relative_day(aos).capitalize())
        label.set_xalign(0)
        label.add_css_class("section-heading")
        label.set_margin_top(10)
        label.set_margin_bottom(2)
        label.set_margin_start(4)
        row.set_header(label)

    def _make_row(self, item: PassItem) -> Gtk.Widget:
        now = time.time()
        live = item.aos <= now <= item.los
        subtitle = (
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
        if item.max_el >= 60.0:
            row.add_css_class("high-pass")
            high_badge = Gtk.Label(label="60°+")
            high_badge.add_css_class("high-pass-badge")
            high_badge.set_tooltip_text(
                "Paso de elevación alta (≥60°): mejor señal y menos obstáculos"
            )
            row.add_suffix(high_badge)
        self._row_meta[row] = (
            time.strftime("%Y-%m-%d", time.localtime(item.aos)),
            item.aos,
        )

        time_label = Gtk.Label(label=fmt.fmt_time(item.aos))
        time_label.set_valign(Gtk.Align.CENTER)
        time_label.add_css_class("pass-time")
        row.add_prefix(time_label)

        suffix = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        suffix.set_valign(Gtk.Align.CENTER)
        status_badge = self._status_badge(item.sat.norad)
        if status_badge is not None:
            status_badge.set_halign(Gtk.Align.END)
            suffix.append(status_badge)
        freq = Gtk.Label(label=fmt.fmt_freq(item.freq_hz))
        freq.set_xalign(1)
        freq.add_css_class("mono")
        freq.add_css_class("pass-freq")
        suffix.append(freq)
        if item.doppler_max_hz is not None:
            dop = Gtk.Label(label=f"±{abs(item.doppler_max_hz) / 1000:.1f} kHz".replace(".", ","))
            dop.set_xalign(1)
            dop.add_css_class("caption")
            dop.add_css_class("pass-meta")
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
        for item in self.filtered:
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

    @staticmethod
    def _pass_detail_key(item: PassItem) -> str:
        return f"{item.sat.norad}:{int(item.aos)}"

    def show_pass_by_key(self, key: str) -> None:
        for item in self.items:
            if self._pass_detail_key(item) == key:
                self._pending_pass_key = None
                self.show_detail(item)
                return
        self._pending_pass_key = key

    def _consume_pending_detail(self) -> None:
        if not self._pending_pass_key:
            return
        key = self._pending_pass_key
        for item in self.items:
            if self._pass_detail_key(item) == key:
                self._pending_pass_key = None
                self.show_detail(item)
                return

    def _on_notify_btn_toggled(self, button: Gtk.ToggleButton) -> None:
        if self.notify_row.get_active() != button.get_active():
            self.notify_row.set_active(button.get_active())

    def _on_notify_row_changed(self, row: Adw.SwitchRow, _pspec) -> None:
        if not hasattr(self, "notify_btn"):
            return
        if self.notify_btn.get_active() != row.get_active():
            self.notify_btn.set_active(row.get_active())
        self.notify_btn.set_tooltip_text(
            "Avisos activados: 5 minutos antes"
            if row.get_active()
            else "Avisos desactivados"
        )

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
        key = self._pass_detail_key(item)
        note.set_default_action_and_target("app.show-pass", GLib.Variant("s", key))
        self.app.send_notification(
            f"pass-{item.sat.norad}-{int(item.aos)}", note
        )

    # ================================================================ detalle
    def show_detail(self, item: PassItem, tab: str = "summary") -> None:
        self._stop_live()
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

        page = stack.add_titled(self._detail_summary_page(item, stack), "summary", "Resumen")
        page.set_icon_name("view-list-symbolic")
        page = stack.add_titled(self._detail_radio_page(item), "radio", "Radio")
        page.set_icon_name("audio-headphones-symbolic")
        page = stack.add_titled(self._detail_sky_page(item), "sky", "Cielo")
        page.set_icon_name("applications-science-symbolic")
        page = stack.add_titled(self._detail_listen_page(item), "listen", "Escucha")
        page.set_icon_name("media-playback-start-symbolic")
        stack.set_visible_child_name(tab)
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
        if self._live_item is not None:
            self._update_listen()
            self._live_source = GLib.timeout_add_seconds(1, self._live_tick)

    # ============================================================ modo escucha
    @staticmethod
    def _fmt_countdown(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        hours, rest = divmod(total, 3600)
        minutes, secs = divmod(rest, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def _detail_listen_page(self, item: PassItem) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.set_margin_top(20)
        box.set_margin_bottom(18)
        box.set_margin_start(24)
        box.set_margin_end(24)

        self._listen_phase = Gtk.Label(label="Preparación")
        self._listen_phase.set_xalign(0)
        self._listen_phase.set_halign(Gtk.Align.START)
        self._listen_phase.add_css_class("badge")
        box.append(self._listen_phase)

        self._listen_countdown = Gtk.Label(label="")
        self._listen_countdown.set_xalign(0)
        self._listen_countdown.add_css_class("listen-countdown")
        box.append(self._listen_countdown)

        self._listen_now = Gtk.Label(label="")
        self._listen_now.set_xalign(0)
        self._listen_now.set_wrap(True)
        self._listen_now.add_css_class("caption")
        self._listen_now.add_css_class("dim-label")
        box.append(self._listen_now)

        status = self.data.status_for(item.sat.norad)
        if status is not None:
            caveat = Gtk.Label(
                label=(
                    f"{status.label} · {status.source}. "
                    "El estado del catálogo no garantiza que esté transmitiendo."
                )
            )
            caveat.set_xalign(0)
            caveat.set_wrap(True)
            caveat.add_css_class("caption")
            caveat.add_css_class("dim-label")
            box.append(caveat)

        box.append(self._heading("Horario"))
        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(10)
        grid.set_column_homogeneous(True)
        cards = [
            ("AOS", fmt.fmt_time(item.aos), f"UTC {fmt.fmt_utc(item.aos)}"),
            ("Punto más alto", fmt.fmt_time(item.tca), f"UTC {fmt.fmt_utc(item.tca)}"),
            ("LOS", fmt.fmt_time(item.los), f"UTC {fmt.fmt_utc(item.los)}"),
            ("Duración", fmt.fmt_dur(item.duration_s), f"Altura máx. {item.max_el:.0f}°"),
        ]
        for index, (key, value, small) in enumerate(cards):
            grid.attach(self._stat_card(key, value, small), index % 2, index // 2, 1, 1)
        box.append(grid)

        channels = item.sat.channels
        if channels:
            box.append(self._heading("Frecuencia"))
            for channel in channels:
                box.append(self._channel_card(channel))
            self._listen_doppler = Gtk.Label(label="Doppler actual: —")
            self._listen_doppler.set_xalign(0)
            self._listen_doppler.set_wrap(True)
            self._listen_doppler.add_css_class("caption")
            self._listen_doppler.add_css_class("dim-label")
            box.append(self._listen_doppler)
        else:
            self._listen_doppler = None
            hint = Gtk.Label(label="Sin frecuencia registrada para este satélite.")
            hint.set_xalign(0)
            hint.set_wrap(True)
            hint.add_css_class("dim-label")
            box.append(hint)

        box.append(self._heading("Antes de empezar"))
        checklist = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for text in (
            "Antena conectada y con vista despejada",
            "SDR con ganancia manual y PPM ajustado",
            "SatDump listo con el pipeline correcto",
            "Empezar a grabar 2 minutos antes del AOS",
        ):
            checklist.append(Gtk.CheckButton(label=text))
        box.append(checklist)

        if channels:
            box.append(self._heading("Comando"))
            box.append(self._command_card(channels[0], item))

        hint = Gtk.Label(
            label="Este modo prepara la escucha; no graba ni controla el SDR."
        )
        hint.set_xalign(0)
        hint.set_wrap(True)
        hint.add_css_class("caption")
        hint.add_css_class("dim-label")
        box.append(hint)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(box)
        scroll.set_vexpand(True)
        return scroll

    def _update_listen(self, now: float | None = None) -> None:
        item = self._live_item
        if (
            item is None
            or self._listen_phase is None
            or self._listen_countdown is None
            or self._listen_now is None
        ):
            return
        now = time.time() if now is None else now
        if now < item.aos:
            self._listen_phase.set_text("PREPARACIÓN")
            self._listen_countdown.set_text(
                f"AOS en {self._fmt_countdown(item.aos - now)}"
            )
            self._listen_now.set_text(
                f"El paso empieza a las {fmt.fmt_time(item.aos)}. "
                f"TCA a las {fmt.fmt_time(item.tca)} · altura máxima {item.max_el:.0f}°."
            )
            if self._listen_doppler is not None:
                self._listen_doppler.set_text("Doppler actual: —")
        elif now <= item.los:
            self._listen_phase.set_text("EN VIVO")
            self._listen_countdown.set_text(
                f"Quedan {self._fmt_countdown(item.los - now)}"
            )
            look = look_at(item.sat.satrec, item.obs, now)
            if look is None:
                self._listen_now.set_text("No se pudo calcular la posición actual.")
            else:
                az, el, rng, rate = look
                self._listen_now.set_text(
                    f"az {az:.0f}° · el {el:.0f}° · {rng:.0f} km"
                )
                if self._listen_doppler is not None and item.freq_hz:
                    shift = -rate / C_KM_S * item.freq_hz
                    self._listen_doppler.set_text(
                        f"Frecuencia actual: {fmt.fmt_freq(round(item.freq_hz + shift))} "
                        f"· {fmt.fmt_dop(shift)}"
                    )
        else:
            self._listen_phase.set_text("TERMINADO")
            self._listen_countdown.set_text("Paso completado")
            self._listen_now.set_text(
                f"El paso terminó a las {fmt.fmt_time(item.los)}."
            )
            if self._listen_doppler is not None:
                self._listen_doppler.set_text("Doppler actual: —")

    def _stop_live(self) -> None:
        source = self._live_source
        self._live_source = None
        if source is not None:
            GLib.source_remove(source)
        self._live_item = None
        self._live_points = []
        self._live_sky = None
        self._live_elev = None
        self._live_badge = None
        self._live_label = None
        self._live_progress = None
        self._listen_phase = None
        self._listen_countdown = None
        self._listen_now = None
        self._listen_doppler = None

    def _live_tick(self) -> bool:
        item = self._live_item
        sky = self._live_sky
        elev = self._live_elev
        badge = self._live_badge
        label = self._live_label
        progress = self._live_progress
        dialog = self._detail_dialog
        if (
            item is None
            or sky is None
            or elev is None
            or badge is None
            or label is None
            or progress is None
            or dialog is None
            or not dialog.get_mapped()
        ):
            self._live_source = None
            self._stop_live()
            return False

        now = time.time()
        self._update_listen(now)
        if now < item.aos:
            sky.set_now(None)
            elev.set_now(None)
            badge.set_text("PRÓXIMO")
            minutes = max(1, round((item.aos - now) / 60.0))
            label.set_text(
                f"Empieza en {minutes} min · {fmt.fmt_time(item.aos)}"
                if minutes < 60
                else f"Empieza {fmt.relative_day(item.aos)} a las {fmt.fmt_time(item.aos)}"
            )
            progress.set_fraction(0.0)
            return True
        if now > item.los:
            sky.set_now(None)
            elev.set_now(None)
            badge.set_text("TERMINADO")
            label.set_text("El paso ya terminó.")
            progress.set_fraction(1.0)
            self._live_source = None
            return False

        sky.set_now(now)
        elev.set_now(now)
        current = sample_track(self._live_points, now)
        if current is None:
            return True
        _t, az, el, rng, rate = current
        fraction = min(1.0, max(0.0, (now - item.aos) / max(1.0, item.los - item.aos)))
        doppler = ""
        if item.freq_hz:
            shift = -rate / C_KM_S * item.freq_hz
            doppler = f" · {fmt.fmt_dop(shift)}"
        badge.set_text("EN VIVO")
        label.set_text(
            f"az {az:.0f}° · el {el:.0f}° · {rng:.0f} km{doppler} · "
            f"{fraction * 100:.0f}% del paso"
        )
        progress.set_fraction(fraction)
        return True

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
        badges = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        badges.append(badge)
        status_badge = self._status_badge(item.sat.norad)
        if status_badge is not None:
            badges.append(status_badge)
        box.append(badges)

        summary = Gtk.Label()
        summary.set_markup(fmt.summary(item))
        summary.set_wrap(True)
        summary.set_xalign(0)
        summary.add_css_class("summary")
        box.append(summary)

        status = self.data.status_for(item.sat.norad)
        if status is not None:
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            card.add_css_class("status-card")

            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            badge = self._status_badge(item.sat.norad)
            if badge is not None:
                header.append(badge)
            title = Gtk.Label(label=status.label)
            title.set_xalign(0)
            title.add_css_class("status-title")
            header.append(title)
            card.append(header)

            source = Gtk.Label(
                label=(
                    f"{status.source}"
                    + (
                        f" · {fmt.fmt_age(max(0.0, time.time() - status.fetched_at))}"
                        if status.fetched_at
                        else ""
                    )
                )
            )
            source.set_xalign(0)
            source.set_wrap(True)
            source.add_css_class("caption")
            source.add_css_class("dim-label")
            card.append(source)

            caveat = Gtk.Label(
                label="El estado del catálogo no garantiza que el satélite esté transmitiendo."
            )
            caveat.set_xalign(0)
            caveat.set_wrap(True)
            caveat.add_css_class("caption")
            caveat.add_css_class("dim-label")
            card.append(caveat)

            if status.decay_date:
                decay = Gtk.Label(label=f"Fecha de decaimiento: {status.decay_date}")
                decay.set_xalign(0)
                decay.set_wrap(True)
                decay.add_css_class("caption")
                decay.add_css_class("dim-label")
                card.append(decay)

            box.append(card)

        box.append(self._heading("Horario"))
        box.append(self._stats_grid(item))

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        listen = Gtk.Button(label="Modo escucha")
        listen.add_css_class("suggested-action")
        listen.connect("clicked", lambda *_: stack.set_visible_child_name("listen"))
        actions.append(listen)
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

        now = time.time()
        live_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        live_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._live_badge = Gtk.Label(label="—")
        self._live_badge.set_xalign(0)
        self._live_badge.set_halign(Gtk.Align.START)
        self._live_badge.add_css_class("badge")
        self._live_label = Gtk.Label(label="")
        self._live_label.set_xalign(0)
        self._live_label.set_wrap(True)
        self._live_label.set_hexpand(True)
        self._live_label.add_css_class("caption")
        self._live_label.add_css_class("dim-label")
        live_top.append(self._live_badge)
        live_top.append(self._live_label)
        self._live_progress = Gtk.ProgressBar()
        self._live_progress.set_show_text(False)
        live_box.append(live_top)
        live_box.append(self._live_progress)
        box.append(live_box)

        points = self.data.track(item)
        self._live_points = points
        self._live_item = item
        self._live_sky = SkyPlot(points, item)
        self._live_elev = ElevationPlot(points, item)
        if item.aos <= now <= item.los:
            self._live_badge.set_text("EN VIVO")
            self._live_label.set_text("Actualizando posición…")
            self._live_progress.set_fraction(
                min(1.0, max(0.0, (now - item.aos) / max(1.0, item.los - item.aos)))
            )
        elif now < item.aos:
            self._live_badge.set_text("PRÓXIMO")
            minutes = max(1, round((item.aos - now) / 60.0))
            self._live_label.set_text(
                f"Empieza en {minutes} min · {fmt.fmt_time(item.aos)}"
                if minutes < 60
                else f"Empieza {fmt.relative_day(item.aos)} a las {fmt.fmt_time(item.aos)}"
            )
            self._live_progress.set_fraction(0.0)
        else:
            self._live_badge.set_text("TERMINADO")
            self._live_label.set_text("El paso ya terminó.")
            self._live_progress.set_fraction(1.0)

        plots = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        plots.set_halign(Gtk.Align.CENTER)
        plots.set_valign(Gtk.Align.CENTER)
        plots.set_vexpand(True)
        plots.append(self._live_sky)
        plots.append(self._live_elev)
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
        typed = self.address_row.get_text().strip()
        display = fmt.short_address(self._address_full)
        query = self._address_full if self._address_full and typed == display else typed
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
        self._address_full = result["name"]
        self.config["label"] = self._address_full
        self.address_row.set_text(fmt.short_address(self._address_full))
        self.address_row.set_tooltip_text(self._address_full)
        self.address_row.set_position(0)
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
        self.alt_row.set_subtitle("Fuente: manual\nAltitud introducida a mano")
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
            self.alt_row.set_subtitle(
                "Fuente: Open-Meteo (terreno)\nEdificio: manual"
            )
        else:
            self.config["alt_source"] = "manual"
            self.alt_row.set_subtitle("Fuente: manual\nAltitud introducida a mano")
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
            artists=["Astro, mascota de PasoOrbital"],
            copyright="© 2026 Marcos Matamala Fernandez",
            version=__version__,
            license_type=Gtk.License.MIT_X11,
            comments="Predicción de pasos de satélites para escucha radio.",
            website="https://github.com/asterion/pasoorbital",
            issue_url="https://github.com/asterion/pasoorbital/issues",
        )
        about.present(self)
