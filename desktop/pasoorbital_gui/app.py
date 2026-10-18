"""Punto de entrada de PasoOrbital para GNOME."""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .data import PasoOrbitalData  # noqa: E402
from .window import PasoOrbitalWindow  # noqa: E402

APP_ID = "io.github.asterion.PasoOrbital"


class PasoOrbitalApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window: PasoOrbitalWindow | None = None
        self._css_loaded = False
        self._add_actions()

    def _add_actions(self) -> None:
        actions = {
            "about": self._on_about,
            "refresh": self._on_refresh,
            "quit": self._on_quit,
        }
        for name, callback in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("app.refresh", ["<Control>r"])

    def _on_about(self, *_args) -> None:
        if self.window is not None:
            self.window.show_about()

    def _on_refresh(self, *_args) -> None:
        if self.window is not None:
            self.window.refresh_tle()

    def _on_quit(self, *_args) -> None:
        self.quit()

    def _load_css(self) -> None:
        if self._css_loaded:
            return
        display = Gdk.Display.get_default()
        if display is None:
            return
        provider = Gtk.CssProvider()
        provider.load_from_path(str(Path(__file__).with_name("style.css")))
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self._css_loaded = True

    def do_activate(self) -> None:
        self._load_css()
        if self.window is None:
            config_dir = Path(GLib.get_user_config_dir()) / "pasoorbital"
            cache_dir = Path(GLib.get_user_cache_dir()) / "pasoorbital"
            data = PasoOrbitalData(config_dir, cache_dir)
            self.window = PasoOrbitalWindow(self, data)
        self.window.present()


def main(argv: list[str] | None = None) -> int:
    GLib.set_application_name("PasoOrbital")
    GLib.set_prgname("pasoorbital-gui")
    app = PasoOrbitalApplication()
    return app.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
