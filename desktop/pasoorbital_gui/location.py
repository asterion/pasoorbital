"""Ubicación del sistema mediante GeoClue2 (D-Bus del sistema).

La interfaz ofrece «Usar mi ubicación» sin obligar a teclear una dirección.
GeoClue2 es el servicio estándar de GNOME; puede no estar instalado, estar
desactivado en Ajustes › Privacidad o denegar el permiso.  En todos esos casos
se lanza :class:`GeoClueError` con un mensaje ya redactado para el usuario.

La consulta es **bloqueante** (con tiempos de espera acotados) porque la llama
la ventana desde un hilo de trabajo, igual que el resto de operaciones de red.
"""

from __future__ import annotations

import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

SERVICE = "org.freedesktop.GeoClue2"
MANAGER_PATH = "/org/freedesktop/GeoClue2/Manager"
MANAGER_IFACE = "org.freedesktop.GeoClue2.Manager"
CLIENT_IFACE = "org.freedesktop.GeoClue2.Client"
LOCATION_IFACE = "org.freedesktop.GeoClue2.Location"
PROPS_IFACE = "org.freedesktop.DBus.Properties"

_FLAGS = Gio.DBusCallFlags.NONE


class GeoClueError(RuntimeError):
    """No se pudo obtener la ubicación del sistema."""


def _mensaje(exc: Exception) -> str:
    texto = str(exc)
    bajo = texto.lower()
    if "accessdenied" in bajo and "disabled" in bajo:
        return "La ubicación del sistema está desactivada en Ajustes › Privacidad."
    if "accessdenied" in bajo:
        return "No hay permiso para usar la ubicación del sistema."
    if "servicenotfound" in bajo or "serviceunknown" in bajo or "not provided" in bajo:
        return "GeoClue no está disponible en este equipo."
    if "timeout" in bajo or "timed out" in bajo:
        return "La ubicación del sistema tardó demasiado en responder."
    return "No se pudo obtener la ubicación del sistema."


class GeoClue:
    """Cliente mínimo de GeoClue2: obtener una posición y soltar el cliente."""

    def __init__(self, desktop_id: str):
        self.desktop_id = desktop_id

    # ------------------------------------------------------------------
    def locate(self, timeout_s: float = 12.0) -> tuple[float, float, float]:
        """Devuelve ``(lat, lon, alt_m)`` o lanza :class:`GeoClueError`."""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error as exc:  # sin bus del sistema
            raise GeoClueError(_mensaje(exc)) from exc

        started = False
        try:
            client = self._new_client(bus)
            self._set_desktop_id(bus, client)
            self._start(bus, client)
            started = True
            path = self._wait_location(bus, client, timeout_s)
            if path in (None, "", "/"):
                raise GeoClueError("GeoClue no devolvió ninguna posición.")
            props = self._location_props(bus, path)
            lat = float(props["Latitude"])
            lon = float(props["Longitude"])
            alt = float(props.get("Altitude") or 0.0)
        except GLib.Error as exc:
            raise GeoClueError(_mensaje(exc)) from exc
        except KeyError as exc:
            raise GeoClueError("GeoClue devolvió una posición incompleta.") from exc
        finally:
            if started:
                self._stop(bus, client)

        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise GeoClueError("GeoClue devolvió coordenadas no válidas.")
        if not (-500.0 <= alt <= 9000.0):
            alt = 0.0
        return lat, lon, alt

    # ------------------------------------------------------------------
    @staticmethod
    def _new_client(bus: Gio.DBusConnection) -> str:
        res = bus.call_sync(
            SERVICE, MANAGER_PATH, MANAGER_IFACE, "GetClient", None,
            GLib.VariantType.new("(o)"), _FLAGS, 5000, None,
        )
        return res.unpack()[0]

    def _set_desktop_id(self, bus: Gio.DBusConnection, client: str) -> None:
        bus.call_sync(
            SERVICE, client, PROPS_IFACE, "Set",
            GLib.Variant("(ssv)", (CLIENT_IFACE, "DesktopId",
                                   GLib.Variant("s", self.desktop_id))),
            None, _FLAGS, 5000, None,
        )

    @staticmethod
    def _start(bus: Gio.DBusConnection, client: str) -> None:
        bus.call_sync(SERVICE, client, CLIENT_IFACE, "Start", None, None,
                      _FLAGS, 15000, None)

    @staticmethod
    def _stop(bus: Gio.DBusConnection, client: str) -> None:
        try:
            bus.call_sync(SERVICE, client, CLIENT_IFACE, "Stop", None, None,
                          _FLAGS, 3000, None)
        except GLib.Error:
            pass

    @staticmethod
    def _wait_location(bus: Gio.DBusConnection, client: str, timeout_s: float) -> str:
        limite = time.monotonic() + max(1.0, timeout_s)
        while True:
            res = bus.call_sync(
                SERVICE, client, PROPS_IFACE, "Get",
                GLib.Variant("(ss)", (CLIENT_IFACE, "Location")),
                GLib.VariantType.new("(v)"), _FLAGS, 5000, None,
            )
            path = res.unpack()[0]
            if path and path != "/":
                return str(path)
            if time.monotonic() >= limite:
                return ""
            time.sleep(0.3)

    @staticmethod
    def _location_props(bus: Gio.DBusConnection, path: str) -> dict:
        res = bus.call_sync(
            SERVICE, path, PROPS_IFACE, "GetAll",
            GLib.Variant("(s)", (LOCATION_IFACE,)),
            GLib.VariantType.new("(a{sv})"), _FLAGS, 5000, None,
        )
        return dict(res.unpack()[0])
