# Desarrollo de PasoOrbital Desktop

> Documento de continuidad del repositorio.
> Última actualización: 1 de noviembre de 2026 (versión 1.10.0).

## 1. Alcance

Este repositorio está dedicado exclusivamente a **PasoOrbital Desktop**, una
aplicación GTK4/libadwaita para Linux/GNOME.

No contiene el servidor web, el frontend web ni el CLI que existieron en etapas
anteriores. Esos archivos permanecen en el historial de Git y en el tag
`v1.9.2`, pero no forman parte del árbol actual.

El motor `pasoorbital/` se conserva porque Desktop lo necesita para:

- descargar y cachear TLE;
- calcular pasos con SGP4;
- consultar frecuencias;
- geocodificar direcciones y altitud;
- consultar el estado SATCAT de CelesTrak.

## 2. Estructura

```text
pasoorbital/
├── pasoorbital/              motor interno
│   ├── tle.py
│   ├── passes.py
│   ├── freqs.py
│   ├── geo.py
│   ├── satstatus.py
│   └── __init__.py
├── desktop/
│   ├── pasoorbital_gui/
│   │   ├── app.py
│   │   ├── location.py
│   │   ├── window.py
│   │   ├── data.py
│   │   ├── format.py
│   │   ├── skyplot.py
│   │   ├── style.css
│   │   └── assets/
│   ├── build_deb.sh
│   ├── build_rpm.sh
│   ├── pasoorbital.spec
│   ├── io.github.asterion.PasoOrbital.*
│   ├── pasoorbital-gui.1
│   └── README.md
├── tests/
├── docs/
├── .github/workflows/
│   ├── deb.yml
│   └── tests.yml
├── run.sh
├── pyproject.toml
├── requirements.txt
├── README.md
└── DESARROLLO.md
```

## 3. Arquitectura

```text
Gtk.Application / Adw.Application
        │
        ▼
PasoOrbitalWindow
├── panel lateral: ubicación, predicción, filtros y avisos
├── lista de pasos agrupada por día
├── detalle: Resumen, Radio, Cielo y Escucha
└── temporizador GLib: avisos, cielo en vivo y cuenta atrás
        │
        ▼
PasoOrbitalData
├── Catalogue → CelesTrak + caché de TLE
├── FrequencyDB → frecuencias por NORAD
├── Geocoder → Nominatim/Photon + Open-Meteo
├── StatusDB → CelesTrak SATCAT
└── passes.find_passes / track / look_at
```

### Archivos principales

| Archivo | Responsabilidad |
| --- | --- |
| `desktop/pasoorbital_gui/app.py` | `Adw.Application`, acciones, CSS y arranque. |
| `desktop/pasoorbital_gui/location.py` | Ubicación del sistema con GeoClue2. |
| `desktop/pasoorbital_gui/window.py` | Ventana, panel, lista, detalle, filtros, avisos y modo escucha. |
| `desktop/pasoorbital_gui/data.py` | Catálogo, pasos, filtros de vista y estado por satélite. |
| `desktop/pasoorbital_gui/format.py` | Fechas, direcciones, frecuencias, comandos e ICS. |
| `desktop/pasoorbital_gui/skyplot.py` | Gráfico polar y de elevación con Cairo. |
| `desktop/pasoorbital_gui/style.css` | Estilos sobre libadwaita. |
| `pasoorbital/tle.py` | Descarga, caché y parseo de TLE. |
| `pasoorbital/passes.py` | SGP4 y geometría topocéntrica. |
| `pasoorbital/freqs.py` | Base de frecuencias. |
| `pasoorbital/geo.py` | Geocodificación y altitud. |
| `pasoorbital/satstatus.py` | SATCAT de CelesTrak con caché de 24 h. |
| `desktop/build_deb.sh` | Genera el `.deb`. |
| `desktop/build_rpm.sh` | Genera el `.rpm` con `rpmbuild`. |

## 4. Flujo de cálculo

1. El usuario configura ubicación, días, elevación mínima y grupos.
2. `PasoOrbitalData.find_passes()` carga el catálogo y calcula los pasos.
3. La vista aplica filtros de texto, frecuencia conocida y grupos.
4. La lista se agrupa por fecha y muestra hora, satélite, duración, altura,
   dirección, frecuencia y Doppler.
5. El detalle abre una pestaña con la información del paso.
6. El temporizador de la ventana actualiza avisos, cielo en vivo y modo escucha.

## 5. Estado SATCAT

- Fuente: `https://celestrak.org/pub/satcat.csv`.
- Caché: `~/.cache/pasoorbital/status/satcat.csv`.
- Edad máxima normal: 24 h.
- Si no hay red, se usa la copia anterior.
- El estado es informativo: no garantiza que el transmisor esté activo.

## 6. Datos y privacidad

- Configuración: `~/.config/pasoorbital/config.json`.
- Caché: `~/.cache/pasoorbital/`.
- TLE: CelesTrak.
- Direcciones: Nominatim y Photon.
- Altitud: Open-Meteo.
- Sin cuentas, telemetría ni servidor propio.

## 7. Pruebas

```bash
python3 -m unittest discover -s tests -v
```

Las pruebas cubren:

- TLE y geometría;
- pasos y Doppler;
- frecuencias;
- geocodificación y altitud con red simulada;
- filtros de lista;
- formato de direcciones y decimales;
- estado SATCAT.

La interfaz se prueba manualmente:

```bash
PYTHONPATH=.:desktop python3 -m pasoorbital_gui.app
```

## 8. Empaquetado

```bash
cd desktop
./build_deb.sh
./build_rpm.sh
```

El workflow `packages` construye ambos paquetes y los publica en el GitHub
Release cuando se sube un tag `v*`.

## 9. Convenciones

- Tiempo interno en UTC; la interfaz muestra hora local.
- Frecuencias y Doppler con coma decimal en la interfaz.
- Los comandos técnicos conservan el punto decimal.
- El estado del catálogo siempre lleva fuente y fecha.
- No se ocultan satélites por estado.
- La lógica orbital vive en `pasoorbital/`, no en la interfaz.

## 10. Deuda pendiente

- Notificaciones con la aplicación cerrada.
- Favoritos y avisos por satélite.
- Persistencia de la checklist del modo escucha.
- Más pruebas de interfaz.
- Revisión de accesibilidad con teclado y lector de pantalla.
- Migración futura del catálogo a OMM si CelesTrak lo requiere.

## 11. Historial del repositorio

La web local, el CLI y la validación con Skyfield fueron retirados del árbol
actual. Siguen disponibles en el historial:

```bash
git log --all -- app.py
git show v1.9.2:app.py
git show v1.9.2:pasoorbital/cli.py
```
