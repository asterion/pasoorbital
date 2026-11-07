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

from gi.repository import Pango  # noqa: E402

from . import __version__, format as fmt  # noqa: E402
from .data import (  # noqa: E402
    SORT_MODES,
    PassItem,
    PasoOrbitalData,
    filter_passes,
    sort_passes,
)
from pasoorbital import passes  # noqa: E402
from pasoorbital.passes import C_KM_S, look_at  # noqa: E402
from .antenna import AntennaPlot, CoverageBar, marcas_de_paso  # noqa: E402
from .location import GeoClue, GeoClueError  # noqa: E402
from .skyplot import (  # noqa: E402
    ElevationPlot,
    ProgressWithMarks,
    SkyPlot,
    sample_track,
)

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
APP_ID = "io.github.asterion.PasoOrbital"

#: Elementos de la lista de comprobación del modo escucha.
CHECKLIST = (
    "Antena conectada y con vista despejada",
    "SDR con ganancia manual y PPM ajustado",
    "SatDump listo con el pipeline correcto",
    "Empezar a grabar 2 minutos antes de que aparezca",
    "Comprobar que el satélite está transmitiendo",
)


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
        self._detail_page: Adw.Dialog | None = None
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
        self._sort_mode = str(self.config.get("sort", "time"))
        self._high_only = bool(self.config.get("high_only", False))
        self._checklist_open = bool(self.config.get("checklist_open", False))
        self._antenna_mount = str(self.config.get("antenna_mount", "fixed"))
        self._antenna_beam = int(self.config.get("antenna_beam", 60))
        self._ant_item = None
        self._ant_plot: AntennaPlot | None = None
        self._ant_bar: CoverageBar | None = None
        self._ant_labels: dict[str, Gtk.Label] = {}
        self._geo_busy = False
        self._geo_source = ""
        self._row_items: dict[Gtk.ListBoxRow, PassItem] = {}
        self._listen_channel = 0
        self._listen_progress: ProgressWithMarks | None = None
        self._listen_freq_value: Gtk.Label | None = None
        self._listen_extra: Gtk.Label | None = None
        self._listen_selector: Adw.ComboRow | None = None
        self._listen_checklist: Gtk.Expander | None = None
        self._listen_checklist_title: str = "Checklist"

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
        grupo = Gio.SimpleActionGroup()
        accion_orden = Gio.SimpleAction.new_stateful(
            "sort", GLib.VariantType.new("s"), GLib.Variant("s", self._sort_mode)
        )
        accion_orden.connect("activate", self._on_sort_action)
        grupo.add_action(accion_orden)
        self.insert_action_group("win", grupo)

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

        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(paned)
        toolbar.add_top_bar(header)
        toolbar.set_content(self.toast_overlay)
        self.set_content(toolbar)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)

    def _tamano_detalle(self) -> tuple[int, int]:
        """Tamaño del diálogo ajustado a la ventana, sin desbordarla.

        En ventanas pequeñas ocupa prácticamente todo el espacio disponible, que
        es el comportamiento que pide el rediseño para texto grande.
        """
        ancho_ventana = self.get_width() or 1280
        alto_ventana = self.get_height() or 840
        return (
            max(520, min(960, ancho_ventana - 48)),
            max(400, min(600, alto_ventana - 48)),
        )

    def close_detail(self) -> None:
        if self._detail_page is not None:
            self._detail_page.close()
        self._detail_page = None
        self._stop_live()


    def _toast(self, texto: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast(title=texto, timeout=5))

    def _set_empty(self, titulo: str, descripcion: str, acciones: bool = False) -> None:
        self.empty_page.set_title(titulo)
        self.empty_page.set_description(descripcion)
        self._empty_box.set_visible(acciones)

    def _construir_menu_orden(self) -> Gio.Menu:
        menu = Gio.Menu()
        for modo, etiqueta in SORT_MODES.items():
            item = Gio.MenuItem.new(etiqueta, None)
            item.set_action_and_target_value("win.sort", GLib.Variant("s", modo))
            menu.append_item(item)
        return menu

    def _on_sort_action(self, accion: Gio.SimpleAction, parametro: GLib.Variant) -> None:
        modo = parametro.get_string()
        if modo not in SORT_MODES:
            return
        accion.set_state(GLib.Variant("s", modo))
        self._sort_mode = modo
        self._save_config()
        if self.items:
            self._render_list()

    def _on_high_only_toggled(self, boton: Gtk.ToggleButton) -> None:
        self._high_only = bool(boton.get_active())
        self._save_config()
        if self.items:
            self._render_list()

    def _on_row_activated(self, _lista: Gtk.ListBox, fila: Gtk.ListBoxRow) -> None:
        item = self._row_items.get(fila)
        if item is not None:
            self.show_detail(item)

    # ------------------------------------------------------------- ubicación
    def _use_my_location(self) -> None:
        if self._geo_busy:
            return
        self._geo_busy = True
        self.locate_row.set_sensitive(False)
        self.status.set_text("Consultando la ubicación del sistema…")

        def trabajo():
            try:
                return GeoClue(APP_ID).locate()
            except GeoClueError as exc:  # se muestra como toast, no como error
                return exc

        self._run_bg(trabajo, self._on_location)

    def _on_location(self, resultado: object) -> None:
        self._geo_busy = False
        self.locate_row.set_sensitive(True)
        self.status.set_text("")
        if isinstance(resultado, GeoClueError):
            self._toast(str(resultado))
            return
        lat, lon, alt = resultado  # type: ignore[misc]
        self._confirmar_ubicacion(float(lat), float(lon), float(alt))

    def _confirmar_ubicacion(self, lat: float, lon: float, alt: float) -> None:
        dialogo = Adw.AlertDialog(
            heading="¿Usar esta ubicación?",
            body=(
                f"El sistema informa de {fmt.fmt_coords(lat, lon)} y "
                f"{round(alt)} m de altitud.\n\nSe usarán para calcular los pasos."
            ),
        )
        dialogo.add_response("cancelar", "Cancelar")
        dialogo.add_response("usar", "Usar esta ubicación")
        dialogo.set_response_appearance("usar", Adw.ResponseAppearance.SUGGESTED)
        dialogo.set_default_response("usar")
        dialogo.set_close_response("cancelar")

        def al_responder(_dialogo, respuesta: str) -> None:
            if respuesta != "usar":
                return
            self.lat_row.set_value(lat)
            self.lon_row.set_value(lon)
            self.alt_row.set_value(round(alt))
            self.config["alt_source"] = "geoclue"
            self._address_full = ""
            self.address_row.set_text("")
            self._has_location = True
            self._save_config()
            self.calculate()

        dialogo.connect("response", al_responder)
        dialogo.present(self)

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
        self.geo_spinner = Gtk.Spinner()
        self.geo_spinner.set_valign(Gtk.Align.CENTER)
        self.geo_spinner.set_visible(False)
        self.address_row.add_suffix(self.geo_spinner)
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

        self.locate_row = Adw.ButtonRow(title="Usar mi ubicación")
        self.locate_row.set_start_icon_name("mark-location-symbolic")
        self.locate_row.set_tooltip_text("Pide la posición al sistema con GeoClue2")
        self.locate_row.connect("activated", lambda *_: self._use_my_location())
        location.add(self.locate_row)
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

        # Resultados de geocodificación
        self.geo_popover = Gtk.Popover()
        self.geo_popover.set_parent(self.address_row)
        self.geo_list = Gtk.ListBox()
        self.geo_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.geo_list.add_css_class("geo-list")
        self.geo_list.connect("row-activated", self._on_geo_row_activated)
        self.geo_scroll = Gtk.ScrolledWindow()
        self.geo_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.geo_scroll.set_child(self.geo_list)
        self.geo_scroll.set_max_content_height(320)
        self.geo_scroll.set_propagate_natural_height(True)
        self.geo_scroll.set_propagate_natural_width(True)
        self.geo_source = Gtk.Label(label="")
        self.geo_source.set_xalign(0)
        self.geo_source.set_margin_top(4)
        self.geo_source.set_margin_bottom(6)
        self.geo_source.set_margin_start(12)
        self.geo_source.add_css_class("caption")
        self.geo_source.add_css_class("dim-label")
        self.geo_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.geo_box.append(self.geo_scroll)
        self.geo_box.append(Gtk.Separator())
        self.geo_box.append(self.geo_source)
        self.geo_popover.set_child(self.geo_box)
        return side


    def _build_content(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        head.set_margin_top(16)
        head.set_margin_bottom(8)
        head.set_margin_start(18)
        head.set_margin_end(18)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        titles.set_hexpand(True)
        title = Gtk.Label(label="Pasos")
        title.set_xalign(0)
        title.add_css_class("title-1")
        self.meta_label = Gtk.Label(
            label="Elige tu ubicación para empezar."
        )
        self.meta_label.set_xalign(0)
        self.meta_label.set_wrap(True)
        self.meta_label.add_css_class("caption")
        self.meta_label.add_css_class("dim-label")
        titles.append(title)
        titles.append(self.meta_label)
        head.append(titles)

        self.high_chip = Gtk.ToggleButton(label="Solo ≥60°")
        self.high_chip.set_valign(Gtk.Align.CENTER)
        self.high_chip.add_css_class("pill")
        self.high_chip.set_tooltip_text("Mostrar solo los pasos de 60° o más")
        self.high_chip.set_active(self._high_only)
        self.high_chip.connect("toggled", self._on_high_only_toggled)

        self.sort_btn = Gtk.MenuButton()
        self.sort_btn.set_icon_name("view-sort-descending-symbolic")
        self.sort_btn.set_valign(Gtk.Align.CENTER)
        self.sort_btn.add_css_class("flat")
        self.sort_btn.set_tooltip_text(
            f"Ordenar los pasos de cada día · {SORT_MODES.get(self._sort_mode, 'Por hora')}"
        )
        self.sort_btn.set_menu_model(self._construir_menu_orden())

        tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        tools.set_valign(Gtk.Align.CENTER)
        tools.append(self.high_chip)
        tools.append(self.sort_btn)
        head.append(tools)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_placeholder_text("Filtrar por satélite…")
        self.search_entry.set_halign(Gtk.Align.END)
        self.search_entry.set_max_width_chars(22)
        self.search_entry.set_sensitive(False)
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

        self._empty_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._empty_actions.set_halign(Gtk.Align.CENTER)
        usar = Gtk.Button(label="Usar mi ubicación")
        usar.add_css_class("suggested-action")
        usar.add_css_class("pill")
        usar.connect("clicked", lambda *_: self._use_my_location())
        escribir = Gtk.Button(label="Escribir una dirección")
        escribir.add_css_class("pill")
        escribir.connect("clicked", lambda *_: self.address_row.grab_focus())
        self._empty_actions.append(usar)
        self._empty_actions.append(escribir)

        ayuda = Gtk.Label(
            label="Usa la ubicación del sistema (GeoClue) y pide confirmación antes de calcular."
        )
        ayuda.set_wrap(True)
        ayuda.set_justify(Gtk.Justification.CENTER)
        ayuda.add_css_class("caption")
        ayuda.add_css_class("dim-label")

        self._empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._empty_box.append(self._empty_actions)
        self._empty_box.append(ayuda)
        self.empty_page.set_child(self._empty_box)
        self._set_empty(
            "Sin pasos todavía",
            "Elige tu ubicación para calcular los próximos pasos.",
            acciones=True,
        )
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
        self.listbox.connect("row-activated", self._on_row_activated)
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
            "sort": self._sort_mode,
            "high_only": self._high_only,
            "checklist_open": self._checklist_open,
            "antenna_mount": self._antenna_mount,
            "antenna_beam": self._antenna_beam,
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
        fuente = cfg.get("alt_source")
        if fuente == "open-meteo":
            self.alt_row.set_subtitle("Fuente: Open-Meteo (terreno)\nEdificio: manual")
        elif fuente == "geoclue":
            self.alt_row.set_subtitle("Fuente: ubicación del sistema\nEdificio: manual")
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
        self.high_chip.set_active(self._high_only)

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
        self._set_empty("Sin grupos", "Selecciona al menos un grupo de satélites.")
        self.meta_label.set_text("")
        self.stack.set_visible_child_name("empty")
        self.search_entry.set_sensitive(False)

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
            self._set_empty(
                "No hay pasos",
                "Prueba con más días o una elevación mínima menor.",
            )
            self.meta_label.set_text("")
            self.stack.set_visible_child_name("empty")
            self.search_entry.set_sensitive(False)
            self._maybe_run_pending()
            return
        self._render_list()
        self._consume_pending_detail()
        self._maybe_run_pending()

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
        if self._high_only:
            reasons.append("≥60°")
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
        self._row_items.clear()

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
            high_only=self._high_only,
        )
        if not self.filtered:
            if not selected_groups:
                self._show_no_groups()
                return
            if self._high_only and not query:
                self._set_empty(
                    "Ningún paso de 60° o más",
                    "Desactiva «Solo ≥60°» para ver todos los pasos.",
                )
            elif only_freq and not query:
                self._set_empty(
                    "Ningún paso con frecuencia conocida",
                    "Desactiva «Solo con frecuencia conocida» para ver todos los pasos.",
                )
            elif query:
                self._set_empty(
                    "Ningún paso coincide",
                    "Prueba con otro nombre o borra el filtro.",
                )
            else:
                self._set_empty(
                    "Ningún paso con estos filtros",
                    "Prueba con más días, una elevación mínima menor u otro grupo.",
                )
            self.meta_label.set_text(
                f"0 de {len(self.items)} pasos calculados · revisa los filtros"
            )
            self.stack.set_visible_child_name("empty")
            self.more_btn.set_visible(False)
            self.search_entry.set_sensitive(False)
            return

        # Agrupa por día y ordena dentro de cada día, para no romper las
        # cabeceras «Hoy / Mañana / fecha».
        por_dia: dict[str, list[PassItem]] = {}
        for item in self.filtered:
            clave = time.strftime("%Y-%m-%d", time.localtime(item.aos))
            por_dia.setdefault(clave, []).append(item)
        ordenados: list[PassItem] = []
        for clave in sorted(por_dia):
            ordenados.extend(sort_passes(por_dia[clave], self._sort_mode))

        self.stack.set_visible_child_name("results")
        for item in ordenados[: self.shown]:
            fila = self._make_row(item)
            self._row_items[fila] = item
            self._row_meta[fila] = (
                time.strftime("%Y-%m-%d", time.localtime(item.aos)),
                item.aos,
            )
            self._row_widgets[self._pass_key(item)] = fila
            self.listbox.append(fila)

        reasons = self._filter_reasons(query, only_freq, selected_groups, min_el)
        detalle = f" · {' · '.join(reasons)}" if reasons else ""
        self.meta_label.set_text(
            f"{len(self.filtered)}/{len(self.items)} calculados{detalle}"
        )
        self.meta_label.set_tooltip_text(
            "Pasos mostrados / pasos calculados"
            + (f". Filtros: {', '.join(reasons)}." if reasons else ".")
            + f" Orden: {SORT_MODES.get(self._sort_mode, 'Por hora')}."
            + f" Tiempo de cálculo: {self.elapsed:.1f} s."
        )
        self.search_entry.set_sensitive(True)
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


    def _make_row(self, item: PassItem) -> Gtk.ListBoxRow:
        ahora = time.time()
        en_vivo = item.aos <= ahora <= item.los
        alto = item.max_el >= 60.0

        fila = Gtk.ListBoxRow()
        fila.set_activatable(True)
        fila.add_css_class("pass-row")
        if alto:
            fila.add_css_class("high-pass")
        if en_vivo:
            fila.add_css_class("live")

        rejilla = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        rejilla.add_css_class("pass-grid")

        hora = Gtk.Label(label=fmt.fmt_time(item.aos))
        hora.set_xalign(0)
        hora.set_valign(Gtk.Align.CENTER)
        hora.set_size_request(96, -1)
        hora.add_css_class("pass-time")
        rejilla.append(hora)

        textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        textos.set_valign(Gtk.Align.CENTER)
        textos.set_hexpand(True)

        cabecera = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        nombre = Gtk.Label(label=item.sat.name)
        nombre.set_xalign(0)
        nombre.set_ellipsize(Pango.EllipsizeMode.END)
        nombre.set_max_width_chars(32)
        nombre.add_css_class("pass-name")
        cabecera.append(nombre)
        if alto:
            chip = Gtk.Label(label="paso alto")
            chip.add_css_class("chip")
            chip.set_valign(Gtk.Align.CENTER)
            chip.set_tooltip_text("Paso de 60° o más: mejor señal y menos obstáculos")
            cabecera.append(chip)
        if en_vivo:
            vivo = Gtk.Label(label="en curso")
            vivo.add_css_class("chip")
            vivo.add_css_class("chip-live")
            vivo.set_valign(Gtk.Align.CENTER)
            cabecera.append(vivo)
        textos.append(cabecera)

        direccion = (
            f"{fmt.compass_word(item.az_aos).capitalize()} → "
            f"{fmt.compass_word(item.az_los).capitalize()}"
        )
        subtitulo = Gtk.Label(
            label=(
                f"{fmt.fmt_dur(item.duration_s)} · {fmt.fmt_deg(item.max_el, 0)} · "
                f"{direccion}"
            )
        )
        subtitulo.set_xalign(0)
        subtitulo.add_css_class("pass-sub")
        textos.append(subtitulo)
        rejilla.append(textos)

        datos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        datos.set_size_request(210, -1)
        datos.set_valign(Gtk.Align.CENTER)

        estado = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        estado.set_halign(Gtk.Align.END)
        info = self.data.status_for(item.sat.norad)
        if info is not None:
            punto = Gtk.Label(label="●")
            punto.add_css_class("status-dot")
            punto.add_css_class(f"status-dot-{info.slug}")
            texto_estado = Gtk.Label(label=info.short)
            texto_estado.add_css_class("pass-status")
            estado.append(punto)
            estado.append(texto_estado)
            estado.set_tooltip_text(info.tooltip())
        datos.append(estado)

        linea = fmt.fmt_freq(item.freq_hz)
        if item.doppler_max_hz is not None:
            desplazamiento = f"{abs(item.doppler_max_hz) / 1000:.1f}".replace(".", ",")
            linea += f" · ±{desplazamiento} kHz"
        valor = Gtk.Label(label=linea)
        valor.set_xalign(1)
        valor.add_css_class("pass-data")
        datos.append(valor)
        rejilla.append(datos)

        rejilla.append(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        fila.set_child(rejilla)
        return fila

    @staticmethod
    def _pass_key(item: PassItem) -> tuple[int, int]:
        return (item.sat.norad, int(round(item.aos)))


    def _tick(self) -> bool:
        """Resalta los pasos próximos y avisa 5 minutos antes."""
        now = time.time()
        lead = 5 * 60.0
        animaciones = bool(
            Gtk.Settings.get_default().get_property("gtk-enable-animations")
        )
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
            row.remove_css_class("soon-static")
            row.remove_css_class("live")
            if key in soon:
                row.add_css_class("soon" if animaciones else "soon-static")
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
        if self._detail_page is not None:
            self._detail_page.close()
            self._detail_page = None

        dialog = Adw.Dialog()
        ancho, alto = self._tamano_detalle()
        dialog.set_content_width(ancho)
        dialog.set_content_height(alto)
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

        grupo = Gio.SimpleActionGroup()
        accion_ics = Gio.SimpleAction.new("ics", None)
        accion_ics.connect("activate", lambda *_: self._save_ics(item))
        grupo.add_action(accion_ics)
        dialog.insert_action_group("detail", grupo)

        menu = Gio.Menu()
        menu.append("Guardar .ics", "detail.ics")
        menu_btn = Gtk.MenuButton(icon_name="view-more-symbolic")
        menu_btn.set_menu_model(menu)
        menu_btn.set_tooltip_text("Más acciones")
        header.pack_end(menu_btn)

        toolbar.add_top_bar(header)

        paginas = (
            ("summary", "Resumen", "view-list-symbolic",
             self._detail_summary_page(item, stack)),
            ("radio", "Radio", "audio-headphones-symbolic",
             self._detail_radio_page(item)),
            ("sky", "Cielo", "starred-symbolic",
             self._detail_sky_page(item)),
            ("listen", "Escucha", "media-playback-start-symbolic",
             self._detail_listen_page(item)),
            ("antenna", "Antena", "network-wireless-symbolic",
             self._detail_antenna_page(item)),
        )
        for nombre, titulo, icono, contenido in paginas:
            page = stack.add_titled(self._pagina_con_scroll(contenido), nombre, titulo)
            page.set_icon_name(icono)

        stack.set_visible_child_name(tab)
        stack.set_vexpand(True)
        toolbar.set_content(stack)

        dialog.set_child(toolbar)
        self._detail_page = dialog
        dialog.present(self)
        if self._live_item is not None:
            self._update_listen()
            self._live_source = GLib.timeout_add_seconds(1, self._live_tick)

    def _pagina_con_scroll(self, contenido: Gtk.Widget) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_child(contenido)
        scroll.add_css_class("detail-scroll")
        return scroll

    def _flow(self, maximo: int) -> Gtk.FlowBox:
        flujo = Gtk.FlowBox()
        flujo.set_selection_mode(Gtk.SelectionMode.NONE)
        flujo.set_homogeneous(True)
        flujo.set_column_spacing(10)
        flujo.set_row_spacing(10)
        flujo.set_max_children_per_line(maximo)
        flujo.set_min_children_per_line(2)
        flujo.set_valign(Gtk.Align.START)
        return flujo

    def _card_grande(self, titulo: str, valor: str, detalle: str = "") -> Gtk.Widget:
        tarjeta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        tarjeta.add_css_class("card")
        tarjeta.add_css_class("card-big")
        etiqueta = Gtk.Label(label=titulo)
        etiqueta.set_xalign(0)
        etiqueta.add_css_class("caption")
        etiqueta.add_css_class("dim-label")
        grande = Gtk.Label(label=valor)
        grande.set_xalign(0)
        grande.set_wrap(True)
        grande.add_css_class("card-value")
        tarjeta.append(etiqueta)
        tarjeta.append(grande)
        if detalle:
            pie = Gtk.Label(label=detalle)
            pie.set_xalign(0)
            pie.set_wrap(True)
            pie.add_css_class("caption")
            pie.add_css_class("dim-label")
            tarjeta.append(pie)
        return tarjeta

    def _channel_selector(self, channels: list[dict], titulo: str = "Escuchar en",
                          on_change=None) -> Adw.ComboRow:
        etiquetas = []
        for canal in channels:
            modo = canal.get("mode") or "sin modo"
            nombre = canal.get("label") or "canal"
            etiquetas.append(f"{fmt.fmt_freq(canal.get('freq_hz'))} · {modo} · {nombre}")
        fila = Adw.ComboRow(title=titulo)
        fila.set_model(Gtk.StringList.new(etiquetas))
        if on_change is not None:
            fila.connect("notify::selected", lambda *_: on_change(fila.get_selected()))
        return fila

    @staticmethod
    def _fmt_countdown(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        hours, rest = divmod(total, 3600)
        minutes, secs = divmod(rest, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"


    def _detail_listen_page(self, item: PassItem) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(24)
        box.set_margin_end(24)
        box.set_vexpand(True)

        # 1. franja de estado
        estado = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        izquierda = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        izquierda.set_hexpand(True)
        self._listen_phase = Gtk.Label(label="Preparación")
        self._listen_phase.set_xalign(0)
        self._listen_phase.set_halign(Gtk.Align.START)
        self._listen_phase.add_css_class("badge")
        self._listen_countdown = Gtk.Label(label="")
        self._listen_countdown.set_xalign(0)
        self._listen_countdown.add_css_class("listen-countdown")
        izquierda.append(self._listen_phase)
        izquierda.append(self._listen_countdown)
        estado.append(izquierda)

        derecha = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        derecha.set_size_request(340, -1)
        derecha.set_valign(Gtk.Align.CENTER)
        fraccion_tca = (item.tca - item.aos) / max(1.0, item.los - item.aos)
        self._listen_progress = ProgressWithMarks(
            [(0.0, "A"), (fraccion_tca, "T"), (1.0, "L")]
        )
        horario = Gtk.Label(
            label=(
                f"Aparece {fmt.fmt_time(item.aos)} · Punto más alto "
                f"{fmt.fmt_time(item.tca)} · Termina {fmt.fmt_time(item.los)}"
            )
        )
        horario.set_xalign(1)
        horario.set_wrap(True)
        horario.add_css_class("caption")
        horario.add_css_class("dim-label")
        derecha.append(self._listen_progress)
        derecha.append(horario)
        estado.append(derecha)
        box.append(estado)

        self._listen_extra = Gtk.Label(label="")
        self._listen_extra.set_xalign(0)
        self._listen_extra.set_wrap(True)
        self._listen_extra.add_css_class("listen-extra")
        box.append(self._listen_extra)

        # 2. tarjeta de canal
        canales = item.sat.channels
        self._listen_channel = 0
        tarjeta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        tarjeta.add_css_class("card")
        tarjeta.add_css_class("channel-card")
        izquierda2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        izquierda2.set_hexpand(True)
        comando = ""
        if canales:
            self._listen_selector = self._channel_selector(
                canales, on_change=self._on_listen_channel
            )
            izquierda2.append(self._listen_selector)
            self._listen_channel_note = Gtk.Label(
                label=self._channel_note(canales[0], len(canales))
            )
            self._listen_channel_note.set_xalign(0)
            self._listen_channel_note.add_css_class("caption")
            self._listen_channel_note.add_css_class("dim-label")
            izquierda2.append(self._listen_channel_note)
            comando = fmt.command_for(canales[0], item)
        else:
            self._listen_selector = None
            self._listen_channel_note = None
            aviso = Gtk.Label(label="Sin frecuencia registrada para este satélite.")
            aviso.set_xalign(0)
            aviso.set_wrap(True)
            aviso.add_css_class("dim-label")
            izquierda2.append(aviso)

        derecha2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        derecha2.set_halign(Gtk.Align.END)
        derecha2.set_valign(Gtk.Align.CENTER)
        etiqueta = Gtk.Label(label="Frecuencia actual")
        etiqueta.set_xalign(1)
        etiqueta.add_css_class("caption")
        etiqueta.add_css_class("dim-label")
        self._listen_freq_value = Gtk.Label(
            label=fmt.fmt_freq(canales[0]["freq_hz"]) if canales else "—"
        )
        self._listen_freq_value.set_xalign(1)
        self._listen_freq_value.add_css_class("listen-freq")
        self._listen_doppler = Gtk.Label(label="(Doppler —)")
        self._listen_doppler.set_xalign(1)
        self._listen_doppler.add_css_class("caption")
        self._listen_doppler.add_css_class("dim-label")
        derecha2.append(etiqueta)
        derecha2.append(self._listen_freq_value)
        derecha2.append(self._listen_doppler)
        tarjeta.append(izquierda2)
        tarjeta.append(derecha2)
        box.append(tarjeta)

        # 3. tarjeta de comando
        cabecera = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        cabecera.append(self._heading("Comando"))
        relleno = Gtk.Box()
        relleno.set_hexpand(True)
        cabecera.append(relleno)
        self._listen_copy_btn = Gtk.Button(label="Copiar")
        self._listen_copy_btn.add_css_class("suggested-action")
        self._listen_copy_btn.set_sensitive(bool(comando))
        self._listen_copy_btn.connect(
            "clicked", lambda *_: self._copy(self._listen_command_label.get_text(),
                                             self._listen_copy_btn)
        )
        cabecera.append(self._listen_copy_btn)
        box.append(cabecera)

        tarjeta_cmd = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        tarjeta_cmd.add_css_class("command")
        self._listen_command_label = Gtk.Label(label=comando)
        self._listen_command_label.set_xalign(0)
        self._listen_command_label.set_wrap(True)
        self._listen_command_label.set_selectable(True)
        self._listen_command_label.add_css_class("mono")
        tarjeta_cmd.append(self._listen_command_label)
        box.append(tarjeta_cmd)

        # 4. pie: checklist plegable + estado del catálogo
        relleno_vertical = Gtk.Box()
        relleno_vertical.set_vexpand(True)
        box.append(relleno_vertical)
        pie = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        pie.set_valign(Gtk.Align.CENTER)
        self._check_buttons = []
        self._listen_checklist = Gtk.Expander()
        self._listen_checklist.set_hexpand(True)
        self._listen_checklist.set_expanded(self._checklist_open)
        contenido = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        contenido.set_margin_top(6)
        for texto in CHECKLIST:
            check = Gtk.CheckButton(label=texto)
            check.connect("toggled", lambda *_: self._update_checklist_label())
            self._check_buttons.append(check)
            contenido.append(check)
        self._listen_checklist.set_child(contenido)
        self._listen_checklist.connect("notify::expanded", self._on_checklist_expanded)
        self._update_checklist_label()
        pie.append(self._listen_checklist)

        info = self.data.status_for(item.sat.norad)
        texto_estado = (
            f"{info.label} según {info.source}"
            if info is not None
            else "Estado del catálogo no disponible"
        )
        estado_sat = Gtk.Label(label=texto_estado)
        estado_sat.set_xalign(1)
        estado_sat.set_wrap(True)
        estado_sat.set_max_width_chars(28)
        estado_sat.add_css_class("caption")
        estado_sat.add_css_class("dim-label")
        pie.append(estado_sat)
        box.append(pie)
        return box

    def _channel_note(self, canal: dict, total: int) -> str:
        partes: list[str] = []
        if total > 1:
            restantes = total - 1
            partes.append(
                "1 canal más en el selector" if restantes == 1
                else f"{restantes} canales más en el selector"
            )
        if canal.get("uplink_hz"):
            partes.append(f"Subida {fmt.fmt_freq(canal['uplink_hz'])}")
        if canal.get("tone_hz"):
            tono = f"{canal['tone_hz']:.1f}".replace(".", ",")
            partes.append(f"Tono {tono} Hz")
        return " · ".join(partes) if partes else "Canal principal"

    def _on_listen_channel(self, indice: int) -> None:
        item = self._live_item
        if item is None or not item.sat.channels:
            return
        if not 0 <= indice < len(item.sat.channels):
            return
        self._listen_channel = indice
        canal = item.sat.channels[indice]
        if self._listen_channel_note is not None:
            self._listen_channel_note.set_text(
                self._channel_note(canal, len(item.sat.channels))
            )
        if self._listen_command_label is not None:
            self._listen_command_label.set_text(fmt.command_for(canal, item))
        self._update_listen()

    def _update_checklist_label(self) -> None:
        if self._listen_checklist is None:
            return
        hechos = sum(1 for boton in self._check_buttons if boton.get_active())
        self._listen_checklist.set_label(f"Checklist · {hechos} de {len(CHECKLIST)}")

    def _on_checklist_expanded(self, expander: Gtk.Expander, _pspec) -> None:
        self._checklist_open = bool(expander.get_expanded())
        self._save_config()


    def _update_listen(self, now: float | None = None) -> None:
        item = self._live_item
        if (
            item is None
            or self._listen_phase is None
            or self._listen_countdown is None
            or self._listen_extra is None
        ):
            return
        ahora = time.time() if now is None else now
        fraccion = min(1.0, max(0.0, (ahora - item.aos) / max(1.0, item.los - item.aos)))
        if self._listen_progress is not None:
            self._listen_progress.set_fraction(fraccion)

        canales = item.sat.channels
        base = None
        if canales and 0 <= self._listen_channel < len(canales):
            base = canales[self._listen_channel].get("freq_hz")

        actual = base
        desvio = None
        if ahora < item.aos:
            self._listen_phase.set_text("PREPARACIÓN")
            self._listen_countdown.set_text(
                f"Aparece en {self._fmt_countdown(item.aos - ahora)}"
            )
            extra = (
                f"{fmt.fmt_deg(item.az_aos, 0)} al aparecer · hasta "
                f"{fmt.fmt_deg(item.max_el)} · {fmt.fmt_dur(item.duration_s)}"
            )
        elif ahora <= item.los:
            self._listen_phase.set_text("EN VIVO")
            self._listen_countdown.set_text(
                f"Quedan {self._fmt_countdown(item.los - ahora)}"
            )
            look = look_at(item.sat.satrec, item.obs, ahora)
            if look is None:
                extra = "No se pudo calcular la posición actual."
                actual = base
            else:
                az, el, rng, rate = look
                extra = (
                    f"{az:.0f}° · {el:.0f}° sobre el horizonte · {fmt.fmt_km(rng)} · "
                    f"{fraccion * 100:.0f} % del paso"
                )
                if base:
                    desvio = -rate / C_KM_S * base
                    actual = base + desvio
                else:
                    actual = None
        else:
            self._listen_phase.set_text("TERMINADO")
            self._listen_countdown.set_text("Paso completado")
            extra = f"Terminó a las {fmt.fmt_time(item.los)}."
            actual = base

        self._listen_extra.set_text(extra)
        if self._listen_freq_value is not None:
            self._listen_freq_value.set_text(
                fmt.fmt_freq(round(actual)) if actual else "—"
            )
        if self._listen_doppler is not None:
            self._listen_doppler.set_text(
                f"(Doppler {fmt.fmt_dop(desvio)})" if desvio is not None else "(Doppler —)"
            )


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
        self._listen_extra = None
        self._listen_doppler = None
        self._listen_progress = None
        self._listen_freq_value = None
        self._listen_selector = None
        self._listen_checklist = None
        self._listen_command_label = None
        self._listen_channel_note = None
        self._listen_freq_value = None
        self._check_buttons = []
        self._listen_channel = 0
        self._ant_item = None
        self._ant_plot = None
        self._ant_bar = None

    def _live_tick(self) -> bool:
        item = self._live_item
        sky = self._live_sky
        elev = self._live_elev
        badge = self._live_badge
        label = self._live_label
        progress = self._live_progress
        pagina = self._detail_page
        if (
            item is None
            or sky is None
            or elev is None
            or badge is None
            or label is None
            or progress is None
            or pagina is None
            or not pagina.get_mapped()
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
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(24)
        box.set_margin_end(24)
        box.set_vexpand(True)

        ahora = time.time()
        if item.aos <= ahora <= item.los:
            estado = "En curso"
        elif ahora < item.aos:
            minutos = max(1, round((item.aos - ahora) / 60.0))
            estado = (
                f"Empieza en {minutos} min"
                if minutos < 60
                else f"Empieza {fmt.relative_day(item.aos)} a las {fmt.fmt_time(item.aos)}"
            )
        else:
            estado = "Pasado"
        badge = Gtk.Label(label=estado)
        badge.set_xalign(0)
        badge.set_valign(Gtk.Align.CENTER)
        badge.add_css_class("badge")
        badges = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        badges.append(badge)
        status_badge = self._status_badge(item.sat.norad)
        if status_badge is not None:
            badges.append(status_badge)
        box.append(badges)

        texto = Gtk.Label(label=fmt.summary(item))
        texto.set_wrap(True)
        texto.set_xalign(0)
        texto.add_css_class("summary-text")
        box.append(texto)

        direccion = (
            f"{fmt.compass_word(item.az_aos).capitalize()} → "
            f"{fmt.compass_word(item.az_los).capitalize()}"
        )
        tarjetas = self._flow(3)
        tarjetas.append(self._card_grande(
            "Cuándo",
            f"{fmt.fmt_time(item.aos)} → {fmt.fmt_time(item.los)}",
            f"{fmt.fmt_dur(item.duration_s)} · más alto a las {fmt.fmt_time(item.tca)}",
        ))
        tarjetas.append(self._card_grande(
            "Por dónde",
            direccion,
            f"hasta {fmt.fmt_deg(item.max_el)} · {fmt.pass_quality(item.max_el)}",
        ))
        if item.freq_hz:
            valor = fmt.fmt_freq(item.freq_hz)
            if item.mode:
                valor += f" · {item.mode}"
            if item.doppler_max_hz is not None:
                desvio = f"{abs(item.doppler_max_hz) / 1000:.1f}".replace(".", ",")
                detalle = f"Doppler ±{desvio} kHz"
            else:
                detalle = "sin datos de Doppler"
        else:
            valor = "Sin frecuencia"
            detalle = "no hay frecuencia registrada"
        tarjetas.append(self._card_grande("Con qué", valor, detalle))
        box.append(tarjetas)

        box.append(self._heading("Más datos"))
        box.append(self._stats_grid(item))

        acciones = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        listen = Gtk.Button(label="Modo escucha")
        listen.add_css_class("suggested-action")
        listen.connect("clicked", lambda *_: stack.set_visible_child_name("listen"))
        acciones.append(listen)
        radio = Gtk.Button(label="Ver radio")
        radio.add_css_class("flat")
        radio.connect("clicked", lambda *_: stack.set_visible_child_name("radio"))
        acciones.append(radio)
        cielo = Gtk.Button(label="Ver cielo")
        cielo.add_css_class("flat")
        cielo.connect("clicked", lambda *_: stack.set_visible_child_name("sky"))
        acciones.append(cielo)
        box.append(acciones)

        estado_sat = self.data.status_for(item.sat.norad)
        if estado_sat is not None:
            cuando = (
                f" · {fmt.fmt_age(max(0.0, time.time() - estado_sat.fetched_at))}"
                if estado_sat.fetched_at
                else ""
            )
            fuente = Gtk.Label(
                label=(
                    f"{estado_sat.label} según {estado_sat.source}{cuando}. "
                    "El catálogo no garantiza que esté transmitiendo."
                )
            )
            fuente.set_xalign(0)
            fuente.set_wrap(True)
            fuente.add_css_class("caption")
            fuente.add_css_class("dim-label")
            box.append(fuente)
        return box


    def _detail_radio_page(self, item: PassItem) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
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
            selector = self._channel_selector(channels, titulo="Frecuencia")
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
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(24)
        box.set_margin_end(24)
        box.set_vexpand(True)

        hint = Gtk.Label(
            label="Centro: cenit · borde: horizonte. El tramo punteado está por recorrer."
        )
        hint.set_xalign(0)
        hint.set_wrap(True)
        hint.add_css_class("caption")
        hint.add_css_class("dim-label")
        box.append(hint)

        ahora = time.time()
        live_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        live_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._live_badge = Gtk.Label(label="—")
        self._live_badge.set_xalign(0)
        self._live_badge.set_halign(Gtk.Align.START)
        self._live_badge.set_valign(Gtk.Align.CENTER)
        self._live_badge.add_css_class("badge")
        self._live_label = Gtk.Label(label="")
        self._live_label.set_xalign(0)
        self._live_label.set_wrap(True)
        self._live_label.set_hexpand(True)
        self._live_label.add_css_class("caption")
        self._live_label.add_css_class("dim-label")
        live_top.append(self._live_badge)
        live_top.append(self._live_label)

        fraccion_tca = (item.tca - item.aos) / max(1.0, item.los - item.aos)
        self._live_progress = ProgressWithMarks(
            [(0.0, "A"), (fraccion_tca, "T"), (1.0, "L")]
        )
        live_box.append(live_top)
        live_box.append(self._live_progress)
        box.append(live_box)

        points = self.data.track(item)
        self._live_points = points
        self._live_item = item
        self._live_sky = SkyPlot(points, item)
        self._live_elev = ElevationPlot(points, item)

        tarjeta_polar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tarjeta_polar.add_css_class("card")
        tarjeta_polar.set_hexpand(True)
        tarjeta_polar.append(self._live_sky)
        tarjeta_altura = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        tarjeta_altura.add_css_class("card")
        tarjeta_altura.set_hexpand(True)
        tarjeta_altura.append(self._live_elev)
        plots = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        plots.set_vexpand(True)
        plots.append(tarjeta_polar)
        plots.append(tarjeta_altura)
        box.append(plots)

        leyenda = Gtk.Label(
            label=(
                "A · aparece · T · punto más alto · L · se va · "
                "Centro: cenit · borde: horizonte"
            )
        )
        leyenda.set_xalign(0)
        leyenda.set_wrap(True)
        leyenda.add_css_class("caption")
        leyenda.add_css_class("dim-label")
        box.append(leyenda)

        if item.aos <= ahora <= item.los:
            self._live_badge.set_text("EN VIVO")
            self._live_label.set_text("Actualizando posición…")
            self._live_progress.set_fraction(
                min(1.0, max(0.0, (ahora - item.aos) / max(1.0, item.los - item.aos)))
            )
        elif ahora < item.aos:
            self._live_badge.set_text("PRÓXIMO")
            minutos = max(1, round((item.aos - ahora) / 60.0))
            self._live_label.set_text(
                f"Empieza en {minutos} min · {fmt.fmt_time(item.aos)}"
                if minutos < 60
                else f"Empieza {fmt.relative_day(item.aos)} a las {fmt.fmt_time(item.aos)}"
            )
            self._live_progress.set_fraction(0.0)
        else:
            self._live_badge.set_text("TERMINADO")
            self._live_label.set_text("El paso ya terminó.")
            self._live_progress.set_fraction(1.0)
        return box


    # ------------------------------------------------------------- antena
    def _detail_antenna_page(self, item: PassItem) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(24)
        box.set_margin_end(24)
        box.set_vexpand(True)

        self._ant_item = item
        self._ant_labels = {}

        # fila de controles
        fila = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        etiqueta = Gtk.Label(label="Recomendación para este paso")
        etiqueta.set_xalign(0)
        etiqueta.set_hexpand(True)
        etiqueta.add_css_class("caption")
        etiqueta.add_css_class("dim-label")
        fila.append(etiqueta)
        fila.append(self._segmented(
            (("fixed", "Fija"), ("manual", "A mano")),
            self._antenna_mount, self._on_antenna_mount,
        ))
        fila.append(self._segmented(
            (("30", "30°"), ("60", "60°"), ("90", "90°")),
            str(self._antenna_beam), self._on_antenna_beam,
        ))
        box.append(fila)

        # tarjeta principal: brújula + cifras
        tarjeta = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        tarjeta.add_css_class("card")
        self._ant_plot = AntennaPlot([], [], {}, None, self._antenna_beam)
        self._ant_plot.set_size_request(340, 280)
        self._ant_plot.set_hexpand(False)
        self._ant_plot.set_halign(Gtk.Align.FILL)
        tarjeta.append(self._ant_plot)

        datos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        datos.set_hexpand(True)
        datos.set_valign(Gtk.Align.CENTER)

        self._ant_labels["titulo"] = self._caption("Apunta la antena a")
        datos.append(self._ant_labels["titulo"])

        valor_az = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self._ant_labels["az"] = self._grande("—", "antenna-value")
        self._ant_labels["az_hint"] = self._caption("")
        valor_az.append(self._ant_labels["az"])
        valor_az.append(self._ant_labels["az_hint"])
        datos.append(valor_az)

        valor_el = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._ant_labels["el"] = self._grande("—", "antenna-value-small")
        self._ant_labels["el_hint"] = self._caption("")
        valor_el.append(self._ant_labels["el"])
        valor_el.append(self._ant_labels["el_hint"])
        datos.append(valor_el)

        datos.append(Gtk.Separator())

        cobertura = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._ant_labels["cov_titulo"] = self._caption("Cubre")
        self._ant_labels["cov_titulo"].set_hexpand(True)
        self._ant_labels["cov_pct"] = self._grande("", "antenna-pct")
        cobertura.append(self._ant_labels["cov_titulo"])
        cobertura.append(self._ant_labels["cov_pct"])
        datos.append(cobertura)

        self._ant_labels["cov"] = Gtk.Label(label="")
        self._ant_labels["cov"].set_xalign(0)
        self._ant_labels["cov"].add_css_class("antenna-cov")
        datos.append(self._ant_labels["cov"])

        self._ant_bar = CoverageBar([], item.aos, item.los, item.tca)
        datos.append(self._ant_bar)

        self._ant_labels["nota"] = Gtk.Label(label="")
        self._ant_labels["nota"].set_xalign(0)
        self._ant_labels["nota"].set_wrap(True)
        self._ant_labels["nota"].add_css_class("caption")
        self._ant_labels["nota"].add_css_class("dim-label")
        datos.append(self._ant_labels["nota"])

        tarjeta.append(datos)
        box.append(tarjeta)

        # tarjeta de guía temporal
        guia = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        guia.add_css_class("card")
        cabecera = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._ant_labels["guia_titulo"] = self._caption("Si puedes mover la antena")
        self._ant_labels["guia_titulo"].set_hexpand(True)
        cabecera.append(self._ant_labels["guia_titulo"])
        self._ant_labels["aviso"] = Gtk.Label(label="")
        self._ant_labels["aviso"].add_css_class("chip")
        self._ant_labels["aviso"].add_css_class("chip-warning")
        self._ant_labels["aviso"].set_visible(False)
        cabecera.append(self._ant_labels["aviso"])
        guia.append(cabecera)

        columnas = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        columnas.set_homogeneous(True)
        for clave, titulo, hora, detalle in (
            ("aos", "Empieza", fmt.fmt_time(item.aos),
             f"{round(item.az_aos)}° · aparece"),
            ("tca", "Punto más alto", fmt.fmt_time(item.tca),
             f"{round(item.az_tca)}° · {fmt.fmt_deg(item.max_el)} sobre el horizonte"),
            ("los", "Termina", fmt.fmt_time(item.los),
             f"{round(item.az_los)}° · se va"),
        ):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
            col.append(self._caption(titulo))
            valor = Gtk.Label(label=hora)
            valor.set_xalign(0)
            valor.add_css_class("antenna-time")
            col.append(valor)
            det = Gtk.Label(label=detalle)
            det.set_xalign(0)
            det.set_wrap(True)
            det.add_css_class("caption")
            det.add_css_class("dim-label")
            col.append(det)
            columnas.append(col)
        guia.append(columnas)
        box.append(guia)

        self._ant_labels["pie"] = Gtk.Label(label="")
        self._ant_labels["pie"].set_xalign(0)
        self._ant_labels["pie"].set_wrap(True)
        self._ant_labels["pie"].add_css_class("caption")
        self._ant_labels["pie"].add_css_class("dim-label")
        box.append(self._ant_labels["pie"])

        self._refresh_antenna()
        return box

    def _caption(self, texto: str) -> Gtk.Label:
        etiqueta = Gtk.Label(label=texto)
        etiqueta.set_xalign(0)
        etiqueta.add_css_class("caption")
        etiqueta.add_css_class("dim-label")
        return etiqueta

    def _grande(self, texto: str, clase: str) -> Gtk.Label:
        etiqueta = Gtk.Label(label=texto)
        etiqueta.set_xalign(0)
        etiqueta.add_css_class(clase)
        return etiqueta

    def _segmented(self, opciones, activo: str, al_cambiar) -> Gtk.Widget:
        caja = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        caja.add_css_class("linked")
        caja.set_valign(Gtk.Align.CENTER)
        grupo = None
        for valor, etiqueta in opciones:
            boton = Gtk.ToggleButton(label=etiqueta)
            boton.set_active(valor == activo)
            if grupo is None:
                grupo = boton
            else:
                boton.set_group(grupo)
            boton.connect("toggled", self._on_antenna_toggle, valor, al_cambiar)
            caja.append(boton)
        return caja

    def _on_antenna_toggle(self, boton: Gtk.ToggleButton, valor: str, al_cambiar) -> None:
        if boton.get_active():
            al_cambiar(valor)

    def _on_antenna_mount(self, valor: str) -> None:
        self._antenna_mount = valor
        self._save_config()
        self._refresh_antenna()

    def _on_antenna_beam(self, valor: str) -> None:
        try:
            self._antenna_beam = int(valor)
        except ValueError:
            return
        self._save_config()
        self._refresh_antenna()

    def _refresh_antenna(self) -> None:
        item = self._ant_item
        if item is None or self._ant_plot is None or self._ant_bar is None:
            return
        puntos = self.data.track(item, n=240)
        ts = [p[0] for p in puntos]
        az = [p[1] for p in puntos]
        el = [p[2] for p in puntos]

        fija = passes.best_fixed_pointing(ts, az, el, self._antenna_beam)
        arco = passes.az_arc(az)
        manual = self._antenna_mount == "manual"

        if manual:
            apuntado = (item.az_tca, item.max_el)
            self._ant_labels["titulo"].set_text("En el punto más alto")
            self._ant_labels["az"].set_text(f"{round(item.az_tca)}°")
            self._ant_labels["az_hint"].set_text(
                f"acimut · {fmt.compass_word(item.az_tca)}"
            )
            self._ant_labels["el"].set_text(fmt.fmt_deg(item.max_el))
            self._ant_labels["el_hint"].set_text("sobre el horizonte")
            self._ant_labels["cov_titulo"].set_text("Recorrido")
            self._ant_labels["cov"].set_text(
                f"Gira de {round(item.az_aos)}° a {round(item.az_los)}° durante "
                f"{fmt.fmt_dur(item.duration_s)}"
            )
            self._ant_labels["cov_pct"].set_text(f"{round(arco)}°")
            self._ant_labels["nota"].set_text(
                "Sigue la trayectoria con la antena; el cono marca el punto más alto."
            )
            self._ant_labels["guia_titulo"].set_text("Guía para moverla a mano")
            self._ant_bar.set_state([], item.aos, item.los, item.tca)
        else:
            apuntado = (fija["az"], fija["el"]) if fija else (item.az_tca, item.max_el)
            self._ant_labels["titulo"].set_text("Apunta la antena a")
            self._ant_labels["az"].set_text(f"{round(apuntado[0])}°")
            self._ant_labels["az_hint"].set_text(
                f"acimut · {fmt.compass_word(apuntado[0])}"
            )
            self._ant_labels["el"].set_text(fmt.fmt_deg(apuntado[1]))
            self._ant_labels["el_hint"].set_text("sobre el horizonte")
            self._ant_labels["cov_titulo"].set_text("Cubre")
            if fija:
                self._ant_labels["cov"].set_text(
                    f"{fmt.fmt_dur(fija['seconds'])} de {fmt.fmt_dur(item.duration_s)} "
                    f"dentro del haz"
                )
                self._ant_labels["cov_pct"].set_text(f"{round(fija['coverage'] * 100)} %")
                self._ant_labels["nota"].set_text(
                    f"Estimado para antena fija con un haz de {self._antenna_beam}°."
                )
                self._ant_bar.set_state(fija["intervals"], item.aos, item.los, item.tca)
            else:
                self._ant_labels["cov"].set_text("Sin datos de cobertura")
                self._ant_labels["cov_pct"].set_text("—")
                self._ant_labels["nota"].set_text("")
                self._ant_bar.set_state([], item.aos, item.los, item.tca)
            self._ant_labels["guia_titulo"].set_text("Si puedes mover la antena")
            self._ant_bar.set_state(
                fija["intervals"] if fija else [], item.aos, item.los, item.tca
            )

        # aviso de arco amplio, solo para antena fija
        aviso = self._ant_labels["aviso"]
        if not manual and arco > 120:
            aviso.set_text(f"Arco de {round(arco)}°: con antena fija pierdes los extremos")
            aviso.set_visible(True)
        else:
            aviso.set_visible(False)

        self._ant_plot.set_state(az, el, marcas_de_paso(item), apuntado, self._antenna_beam)

        canal = item.sat.channels[0] if item.sat.channels else {}
        polarizacion = fmt.polarization_label(canal.get("polarization"))
        pie = (
            f"Cálculo con TLE de {str(round(item.sat.tle_age_days, 1)).replace('.', ',')} días. "
            "No modela obstáculos ni el diagrama real de tu antena."
        )
        if polarizacion:
            pie += f" Antena {polarizacion} para este canal."
        self._ant_labels["pie"].set_text(pie)

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
        """Datos que no aparecen ya en las tres tarjetas del resumen."""
        grid = self._flow(3)

        dir_a = fmt.compass_word(item.az_aos).capitalize()
        dir_l = fmt.compass_word(item.az_los).capitalize()
        edad = f"{item.sat.tle_age_days:.1f}".replace(".", ",")
        cards = [
            ("Distancia en el punto más alto", fmt.fmt_km(item.range_tca), ""),
            ("Dirección", f"{dir_a} → {dir_l}",
             f"{round(item.az_aos)}° → {round(item.az_los)}°"),
            ("TLE", f"{edad} días", ""),
        ]
        for key, value, small in cards:
            grid.append(self._stat_card(key, value, small))
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
            self._toast("Escribe una dirección de al menos 3 caracteres.")
            return
        if self._geo_busy:
            return
        self._set_geo_busy(True)
        self._run_bg(lambda: self.data.geocoder.search(query), self._on_geo_results)

    def _set_geo_busy(self, busy: bool) -> None:
        self._geo_busy = busy
        self.address_row.set_sensitive(not busy)
        self.search_btn.set_sensitive(not busy)
        self.geo_spinner.set_visible(busy)
        if busy:
            self.geo_spinner.start()
            self.search_btn.set_label("Buscando…")
        else:
            self.geo_spinner.stop()
            self.search_btn.set_label("Buscar")

    def _on_geo_results(self, results: object) -> None:
        self._set_geo_busy(False)
        self._geo_results = list(results)  # type: ignore[arg-type]
        if not self._geo_results:
            self._toast("No se encontró esa dirección. Prueba con más detalle.")
            return

        child = self.geo_list.get_first_child()
        while child is not None:
            self.geo_list.remove(child)
            child = self.geo_list.get_first_child()

        for resultado in self._geo_results:
            self.geo_list.append(self._geo_row(resultado))

        fuente = self._geo_results[0].get("source") or "Nominatim"
        total = len(self._geo_results)
        plural = "" if total == 1 else "s"
        self.geo_source.set_text(f"Fuente: {fuente} · {total} resultado{plural}")
        self.geo_popover.popup()

    def _geo_row(self, resultado: dict) -> Gtk.ListBoxRow:
        fila = Gtk.ListBoxRow()
        caja = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        caja.set_margin_top(8)
        caja.set_margin_bottom(8)
        caja.set_margin_start(10)
        caja.set_margin_end(10)

        icono = Gtk.Image.new_from_icon_name(fmt.geo_icon(resultado.get("type")))
        icono.set_valign(Gtk.Align.START)
        caja.append(icono)

        textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        textos.set_hexpand(True)

        partes = [
            parte.strip()
            for parte in str(resultado.get("name", "")).split(",")
            if parte.strip()
        ]
        corto = partes[0] if partes else str(resultado.get("name", ""))

        linea1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        nombre = Gtk.Label(label=corto)
        nombre.set_xalign(0)
        nombre.set_ellipsize(Pango.EllipsizeMode.END)
        nombre.add_css_class("geo-name")
        linea1.append(nombre)
        etiqueta = fmt.type_label(resultado.get("type"))
        if etiqueta:
            tipo = Gtk.Label(label=etiqueta)
            tipo.add_css_class("chip")
            tipo.set_valign(Gtk.Align.CENTER)
            linea1.append(tipo)
        textos.append(linea1)

        if len(partes) > 1:
            jerarquia = Gtk.Label(label=" · ".join(partes[1:]))
            jerarquia.set_xalign(0)
            jerarquia.set_wrap(True)
            jerarquia.set_max_width_chars(52)
            jerarquia.add_css_class("caption")
            jerarquia.add_css_class("dim-label")
            textos.append(jerarquia)

        coordenadas = fmt.fmt_coords(float(resultado["lat"]), float(resultado["lon"]))
        distancia = resultado.get("distance_m")
        if distancia:
            coordenadas += f" · a {round(distancia)} m del anterior"
        ubicacion = Gtk.Label(label=coordenadas)
        ubicacion.set_xalign(0)
        ubicacion.add_css_class("mono")
        ubicacion.add_css_class("caption")
        textos.append(ubicacion)

        caja.append(textos)
        fila.set_child(caja)
        return fila

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
