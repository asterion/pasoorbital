# PasoOrbital para GNOME

![PasoOrbital para GNOME](../docs/desktop.png)

Aplicación de escritorio en **GTK4 + libadwaita** que reutiliza el motor de
PasoOrbital (`sgp4`, TLE de CelesTrak, frecuencias y geocodificación) sin depender
del navegador.

## Requisitos

- Ubuntu 24.10 o superior / Debian 13 o superior (libadwaita 1.6+).
- `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`, `python3-numpy`,
  `python3-sgp4` (este último está en el repositorio `universe` de Ubuntu).
- Para construir el `.deb`: `dpkg-deb` (paquete `dpkg-dev`).

## Construir el paquete

```bash
cd desktop
./build_deb.sh
```

El paquete queda en `desktop/dist/pasoorbital_1.2.0-1_all.deb`.

## Instalar

```bash
sudo apt install ./desktop/dist/pasoorbital_1.2.0-1_all.deb
```

Si `python3-sgp4` no está disponible, habilita `universe`:

```bash
sudo add-apt-repository universe
sudo apt update
```

Después, abre **PasoOrbital** desde el menú de aplicaciones o ejecuta:

```bash
pasoorbital-gui
```

## Ejecutar desde el código fuente

Con un entorno que tenga `sgp4` y acceso a `gi`:

```bash
python3 -m venv --system-site-packages .venv-gui
.venv-gui/bin/pip install sgp4
PYTHONPATH=.:desktop .venv-gui/bin/python -m pasoorbital_gui.app
```

## Dónde guarda los datos

- Configuración: `~/.config/pasoorbital/config.json`.
- TLE y caché de direcciones: `~/.cache/pasoorbital/`.
- Frecuencias propias: `~/.config/pasoorbital/frequencies.json` (mismo formato que
  el descrito en el README principal).

## Notas

- La primera ejecución descarga los TLE de CelesTrak; después los cachea 6 h.
- La geocodificación usa Nominatim con caché de 30 días.
- Las predicciones son orientativas; no las uses para navegación crítica.
- La metainformación apunta al repositorio del proyecto; cambia la URL si publicas
  en otra cuenta.
