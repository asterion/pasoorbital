# PasoOrbital — documento de desarrollo y continuidad

> **Para retomar el proyecto sin perder contexto.**
> Autores: Marcos Matamala Fernandez y DeepSeek Harness (deepseek-flash).
> Última actualización: 17 de octubre de 2026 · Versión: 1.3 (altitud automática)

---

## 1. Qué es PasoOrbital

Aplicación local (servidor Python + interfaz web) que calcula **qué satélites pasan por una ubicación**, con hora, elevación, azimut, duración, frecuencia de escucha y efecto Doppler. Está orientada a radioaficionados, cazadores de satélites meteorológicos y cualquier persona que quiera saber cuándo y dónde sintonizar un satélite.

**Stack:** Python 3.10+ (`sgp4`, `numpy`, `http.server` de la stdlib), frontend en HTML/CSS/JavaScript sin build step. Datos TLE de CelesTrak; geocodificación con Nominatim/Photon.

---

## 2. Estado actual

### Verificación

| Comprobación | Resultado |
| --- | --- |
| Pruebas unitarias | 18/18 OK (`tests/test_pasoorbital.py`) |
| Sintaxis JS | OK (`node --check static/app.js`) |
| Validación contra Skyfield | peor diferencia: 0,0037° azimut, 0,0013° elevación, 0,0003 km/s |
| Rendimiento | 2 días × 182 satélites ≈ 1,2 s; 7 días × 243 satélites ≈ 2,6 s (con tope de 2000 pasos) |
| Navegador | Chrome headless sin errores de consola; escritorio 1440 px y móvil 390 px revisados |
| Escritorio | GTK4 4.22 + libadwaita 1.9 probados vía Broadway; `.deb` construido y validado con `lintian` |

### Funcionalidades implementadas

- [x] Ubicación por dirección, coordenadas o GPS del navegador.
- [x] Predicción de 1, 2, 3 o 7 días (la API acepta hasta 14), con elevación mínima configurable.
- [x] Catálogo de CelesTrak por grupos: `stations`, `weather`, `amateur`, `cubesat`.
- [x] Caché de TLE en disco (6 h) y en memoria; refresco manual.
- [x] Pasos con AOS/TCA/LOS, duración, elevación máxima, azimut, distancia y velocidad radial.
- [x] Frecuencias de escucha (bajada, subida, tono, modo) con base integrada y override local.
- [x] Doppler calculado en AOS/TCA/LOS y máximo.
- [x] Tabla filtrable, próximo paso con cuenta atrás y calendario `.ics`.
- [x] Detalle con resumen en lenguaje llano, gráfico polar y gráfico elevación/Doppler.
- [x] Comandos de escucha para copiar (`rtl_fm` + `sox`, `noaa-apt`, `SatDump`).
- [x] Guía «Cómo leer esta tabla», glosario contextual (16 términos) y botones «?».
- [x] Tabla sin siglas: Aparece (con fecha «hoy», «mañana» o día de la semana), Duración en minutos, Altura, Dirección con nombre completo, Frecuencia y Desvío (sin columna LOS; se deduce de Aparece + Duración).
- [x] CLI: `python -m pasoorbital.cli`.
- [x] Aplicación de escritorio GTK4/libadwaita y paquete `.deb` (`desktop/`).
- [x] Altitud del terreno automática con Open-Meteo al buscar dirección o usar GPS; caché y ajuste manual del edificio.

---

## 3. Puesta en marcha

```bash
cd satelites
./run.sh                      # crea .venv, instala y abre http://127.0.0.1:8765
```

Opciones del servidor:

```bash
.venv/bin/python app.py --port 9000 --no-browser
.venv/bin/python app.py --refresh          # fuerza descarga de TLE
.venv/bin/python app.py --host 0.0.0.0     # solo detrás de proxy y con protección
```

CLI y pruebas:

```bash
.venv/bin/python -m pasoorbital.cli --lat -33.4489 --lon -70.6693 --days 2 --min-el 10
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
```

Validación opcional contra Skyfield (dependencia de desarrollo):

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python tools/validar_skyfield.py
```

---

## 4. Arquitectura

```
Navegador (static/)
   │  fetch JSON
   ▼
app.py (http.server, ThreadingHTTPServer)
   ├── pasoorbital/tle.py     → CelesTrak + caché en data/tle/
   ├── pasoorbital/passes.py  → SGP4 + geometría topocéntrica
   ├── pasoorbital/freqs.py   → base de frecuencias
   ├── pasoorbital/geo.py     → Nominatim/Photon + Open-Meteo + caché
   └── pasoorbital/cli.py     → interfaz de terminal
```

### Archivos y responsabilidades

| Archivo | Responsabilidad |
| --- | --- |
| `app.py` | Servidor HTTP, rutas `/api/*`, validación de entrada, serialización, arranque y puerto. |
| `pasoorbital/tle.py` | Descarga y caché de TLE, parseo, época, inclinación, período, altura; `Catalogue.load()`. |
| `pasoorbital/passes.py` | `Observer`, conversión TEME→ECEF, az/el/distancia/velocidad radial, `find_passes()`, `track()`, `look_at()`. |
| `pasoorbital/freqs.py` | `CHANNELS` por NORAD, `NAME_RULES`, `FrequencyDB` (merge con `data/frequencies.json`). |
| `pasoorbital/geo.py` | `Geocoder.search()` (Nominatim/Photon, caché 30 días) y `Geocoder.elevation()` (Open-Meteo, caché 1 año). |
| `pasoorbital/cli.py` | Tabla por terminal y salida JSON. |
| `static/index.html` | Estructura, panel de ayuda, glosario, modales. |
| `static/style.css` | Tema oscuro, layout responsive, estilos de ayuda. |
| `static/app.js` | Estado, API, tabla, próximo paso, detalle, gráficos, ICS, glosario y resumen. |
| `tests/test_pasoorbital.py` | TLE, geometría, pasos, Doppler, frecuencias y CLI. |
| `tools/validar_skyfield.py` | Comparación independiente con Skyfield. |
| `run.sh` | Entorno virtual y arranque. |
| `data/tle/` | TLE cacheados por grupo (fuente offline). |
| `data/cache/` | Caché de geocodificación y datos temporales. |
| `data/frequencies.json` | Opcional: sobreescribe frecuencias por NORAD. |

### Flujo de una petición de pasos

1. El navegador envía `POST /api/passes` con lat/lon/alt, días, elevación mínima y grupos.
2. `app.api_passes()` carga el catálogo (caché o CelesTrak), filtra satélites no visibles por latitud y descarta geoestacionarios.
3. `passes.find_passes()` muestrea la elevación, detecta cruces, refina AOS/LOS por bisección y TCA por parábola.
4. Se calcula el Doppler con la frecuencia principal de cada satélite.
5. Se devuelven los pasos ordenados por AOS (máximo 2000) y metadatos de cálculo.

---

## 5. API

| Método | Ruta | Cuerpo / query | Respuesta |
| --- | --- | --- | --- |
| GET | `/api/health` | — | `{ok, uptime_s}` |
| GET | `/api/catalog` | `groups=a,b`, `refresh=1` | `{satellites[], groups[], now}` |
| GET | `/api/geocode` | `q=dirección` | `{query, results[]}` |
| GET | `/api/elevation` | `lat=…&lon=…` | `{lat, lon, alt_m, source, approx}` |
| POST | `/api/passes` | `{lat, lon, alt_m, days, min_el, groups, start}` | `{passes[], meta}` |
| POST | `/api/track` | `{norad, lat, lon, alt_m, aos, los}` | `{points{t,az,el,rng,rate}, channels[]}` |

### Campos de un paso

`norad`, `name`, `aos_ts`, `tca_ts`, `los_ts`, `aos`, `tca`, `los`, `duration_s`, `max_el`, `az_aos`, `az_tca`, `az_los`, `range_tca`, `rate_aos`, `rate_tca`, `rate_los`, `rate_max`, `partial_start`, `partial_end`, `tle_age_days`, `freq_hz`, `mode`, `label`, `doppler_aos_hz`, `doppler_los_hz`, `doppler_max_hz`.

### Campos de un satélite

`norad`, `name`, `groups`, `epoch_ts`, `tle_age_days`, `incl_deg`, `period_min`, `alt_km`, `channels[]`.

Canal: `freq_hz`, `mode`, `label`, `note`, `uplink_hz`, `tone_hz`.

### Ejemplo

```bash
curl -s -X POST http://127.0.0.1:8765/api/passes \
  -H 'Content-Type: application/json' \
  -d '{"lat":-33.4489,"lon":-70.6693,"alt_m":570,"days":2,"min_el":10,"groups":["stations","weather","amateur"]}'
```

---

## 6. Convenciones y decisiones

- **Tiempo:** internamente todo en UTC (segundos Unix). El navegador muestra la hora local; la casilla UTC cambia la visualización.
- **Doppler:** `Δf = -v_radial · f / c`; positivo al acercarse, negativo al alejarse. La velocidad radial positiva significa alejamiento.
- **Geometría:** TEME→ECEF con GMST; sin refracción atmosférica ni movimiento polar. Error despreciable para apuntar antenas.
- **Geoestacionarios:** se excluyen si el período supera 1200 min (no tienen “pasos”).
- **Caché TLE:** 6 h; CelesTrak actualiza cada 2 h. El servidor hace 4 peticiones por refresco, independientemente del número de usuarios.
- **Caché de direcciones:** 30 días, con límite de 1 req/s y respaldo Photon.
- **Frontend sin build:** HTML/CSS/JS servidos directamente; no hay npm ni bundler.
- **Sin base de datos:** todo es ficheros en `data/`; el estado del usuario vive en `localStorage` (`pasoorbital.cfg.v1`, `pasoorbital.helpSeen`).
- **Frecuencias:** base integrada orientativa; `data/frequencies.json` tiene prioridad.
- **Privacidad:** no se guardan ubicaciones ni peticiones; solo la caché de direcciones consultadas.
- **UI:** textos en español, tono directo y sin siglas en la tabla. Los nombres técnicos (AOS, LOS, TCA, Doppler) viven en el glosario y en el detalle; si se añade un concepto, debe entrar en el glosario.
- **Tabla:** solo las columnas necesarias. AOS se muestra como «Aparece»; LOS no se muestra porque se obtiene con «Aparece» + «Duración»; TCA aparece en el detalle como «Punto más alto».

---

## 7. Limitaciones conocidas y deuda técnica

### Datos y precisión

- [ ] **TLE de 5 dígitos:** el parser usa `line1[2:7]`. Desde julio de 2026 hay objetos con catálogo ≥100000 que **no se pueden representar en TLE**; CelesTrak recomienda OMM/CSV/JSON o Alpha-5. Migrar es la tarea P0.
- [ ] **CelesTrak es un redistribuidor**, no la fuente oficial; su política limita la frecuencia y puede bloquear IPs. Ya se cachea, pero conviene añadir un `User-Agent` con contacto y manejo de `Retry-After`.
- [ ] **Sin refracción atmosférica** (afecta a elevaciones < 5°).
- [ ] **Sin maniobras:** si el satélite maniobra después de la época del TLE, la predicción se degrada.
- [ ] **Cobertura de frecuencias limitada:** solo ~20 satélites; la mayoría de CubeSats no tiene frecuencia.
- [ ] **NOAA 15/18/19** figuran en la base pero ya no están en el catálogo actual.

### Backend

- [ ] `ThreadingHTTPServer` de un solo proceso; el cálculo es CPU-bound y bloquea el hilo. Para uso público: pool de procesos o precomputación.
- [ ] Sin límite de peticiones ni protección anti-abuso.
- [ ] Sin compresión gzip: una respuesta de 2 días puede pesar ~770 KB.
- [ ] `POST /api/passes` no es cacheable por CDN; valorar `GET` con query params.
- [ ] Sin autenticación, sin HTTPS, sin cabeceras de seguridad (CSP, HSTS).
- [ ] Sin logs estructurados ni métricas.
- [ ] `data/cache/geocode.json` crece sin límite; añadir poda.
- [ ] Sin Docker ni CI.

### Frontend

- [ ] Sin i18n (solo español).
- [ ] Sin PWA ni service worker; no funciona offline salvo el backend local.
- [ ] Sin trampa de foco en los modales (accesibilidad).
- [ ] Sin tests de interfaz automatizados.
- [ ] La tabla oculta la columna de dirección en móvil (el detalle sí la muestra).
- [ ] Sin notificaciones ni favoritos.

---

## 8. Roadmap priorizado

### P0 — Corrección y futuro de los datos

- [ ] **Migrar el catálogo a OMM/JSON o CSV** (CCSDS 502.0-B-3), con soporte de números de 9 dígitos. Mantener TLE como respaldo.
- [ ] Soporte **Alpha-5** si se conserva TLE.
- [ ] Añadir prueba con un objeto de catálogo ≥100000.
- [ ] Manejo explícito de `429/503` y `Retry-After` de CelesTrak.
- [ ] Añadir `User-Agent` con contacto y versión.

### P1 — Producto

- [ ] **Alertas** de pasos por email/Telegram/push (requiere backend de tareas).
- [ ] **Favoritos** y lista de satélites personalizada.
- [ ] **Multilocalización** (casa, club, observatorio).
- [ ] **URL compartible** con lat/lon/días/elevación (`?lat=…&lon=…`).
- [ ] **PWA** con caché del shell y de los últimos resultados.
- [ ] **Flatpak** de la aplicación de escritorio, además del `.deb`.
- [ ] **Inglés** como segundo idioma.
- [ ] **Importar frecuencias de SatNOGS** o de un CSV comunitario.
- [ ] **Suscripción webcal** al calendario (en lugar de descargar el .ics).
- [ ] **Máscara de horizonte** configurable (edificios, montañas).

### P2 — Integración con la escucha

- [ ] **Control de rotor** (Hamlib/`rotctld`) o exportación de la pista para Gpredict.
- [ ] **Grabación con corrección Doppler**: script que siga el paso y ajuste `rtl_fm` en tiempo real.
- [ ] Presets por modo (FM, SSB, APT, LRPT) con comandos verificados para GQRX/SatDump.
- [ ] Exportación a **SatNOGS/TinyGS**.
- [ ] API pública con tokens y cuotas.

### P3 — Servicio público

- [ ] Sustituir `http.server` por FastAPI/uvicorn o Go; pool de procesos y cola.
- [ ] Caché compartida (Redis/S3) y CDN.
- [ ] Geocodificador propio o de pago (Mapbox/LocationIQ); no depender de Nominatim público.
- [ ] Límite de peticiones, WAF y observabilidad.
- [ ] Privacidad, cookies, aviso legal y consentimiento de anuncios.
- [ ] Modelo de negocio: afiliación + premium + B2B (ver apéndice A).

---

## 9. Backlog detallado (tickets)

| ID | Tarea | Archivos | Criterio de aceptación |
| --- | --- | --- | --- |
| SP-01 | Parsear OMM/JSON de CelesTrak | `pasoorbital/tle.py` | Catálogo con objetos ≥100000 y prueba unitaria |
| SP-02 | Alpha-5 en TLE | `pasoorbital/tle.py` | NORAD alfanumérico convertido a entero |
| SP-03 | URL con estado | `static/app.js` | Compartir enlace reproduce ubicación y filtros |
| SP-04 | Exportar pista para Gpredict | `app.py`, `static/app.js` | Descarga `.txt` con az/el/tiempo |
| SP-05 | Alertas Telegram | nuevo `pasoorbital/alerts.py`, `app.py` | Aviso X minutos antes del AOS |
| SP-06 | Caché de pasos por celda | `app.py` | Misma lat/lon redondeada responde < 100 ms |
| SP-07 | gzip en API | `app.py` | Respuesta comprimida si `Accept-Encoding` |
| SP-08 | Modo básico/avanzado | `static/*` | Oculta TLE, distancia y Doppler |
| SP-09 | Tests de API | `tests/test_api.py` | Cobertura de rutas y errores |
| SP-10 | Docker + CI | `Dockerfile`, `.github/workflows` | Imagen y tests en cada push |

---

## 10. Guías de extensión

### Añadir una frecuencia

1. Añade el NORAD a `CHANNELS` en `pasoorbital/freqs.py`:

```python
12345: [
    {"freq_hz": 437_500_000, "mode": "FM", "label": "Telemetría",
     "note": "Baliza AX.25.", "uplink_hz": None}
],
```

2. O crea `data/frequencies.json` (tiene prioridad, requiere reiniciar):

```json
{"12345": [{"freq_hz": 437500000, "mode": "FM", "label": "Telemetría"}]}
```

3. Comprueba con `.venv/bin/python -m pasoorbital.cli --lat … --norad 12345`.

### Añadir un grupo de satélites

1. Añade la clave y etiqueta a `GROUPS` en `pasoorbital/tle.py`.
2. Comprueba que CelesTrak acepta `GROUP=<clave>`.
3. Si debe salir por defecto, añádelo a `DEFAULT_GROUPS` y a los grupos marcados en `renderGroups()` de `static/app.js`.

### Añadir un término al glosario

1. Añade `{id, term, sub, text}` a `GLOSSARY` en `static/app.js`.
2. Enlázalo desde la UI con `<button class="help-dot" data-term="id">?</button>`.
3. El término aparecerá automáticamente en la ventana de glosario.

### Añadir un dato a la tabla

1. Calcula el campo en `passes.py` o `app.py` (`pass_public`).
2. Añade la columna en `static/index.html` y el `<td>` en `renderTable()`.
3. Ajusta el CSS responsive (`az-col`, `num-col`).
4. Si es un concepto nuevo, añade glosario y una línea en el resumen (`passSummary`).

### Cambiar los textos de ayuda

- Guía inicial: `#help-panel` en `static/index.html`.
- Glosario: `GLOSSARY` en `static/app.js`.
- Resumen del paso: `passSummary()` en `static/app.js`.
- Pistas sueltas: `#calc-hint`, `.hint` en HTML y notas del modal.

---

## 11. Pruebas y validación

Antes de dar por bueno un cambio:

```bash
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
```

Prueba manual mínima:

1. `./run.sh` y abrir la URL.
2. Geocodificar una dirección: debe rellenar la altitud del terreno y calcular. Probar también el botón «Calcular altitud del terreno» con coordenadas manuales.
3. Abrir un paso, revisar resumen, gráficos y comandos.
4. Probar el glosario desde la cabecera y desde un «?».
5. Exportar el `.ics` y comprobar que tiene eventos.
6. Reducir a 390 px y revisar que no se rompe.

Validación de precisión (opcional, requiere `requirements-dev.txt`):

```bash
.venv/bin/python tools/validar_skyfield.py
```

Criterio actual: azimut/elevación < 0,05°, velocidad radial < 0,01 km/s.

---

## 12. Despliegue y operación

### Local (estado actual)

`./run.sh` en `127.0.0.1:8765`. No exponer a internet sin proxy, TLS y límites.

### VPS / servidor

```ini
# /etc/systemd/system/pasoorbital.service
[Unit]
Description=PasoOrbital
After=network.target

[Service]
WorkingDirectory=/opt/pasoorbital
ExecStart=/opt/pasoorbital/.venv/bin/python app.py --no-browser --host 127.0.0.1 --port 8765
Restart=on-failure
User=pasoorbital
Group=pasoorbital

[Install]
WantedBy=multi-user.target
```

```caddy
# Caddy delante, con HTTPS automático
pasoorbital.example.com {
    reverse_proxy 127.0.0.1:8765
    encode gzip
}
```

- El usuario `pasoorbital` necesita permisos de escritura sobre `data/` (caché de TLE y de direcciones).
- Copia de seguridad: `data/tle/` y, si existe, `data/frequencies.json` (la caché de geocodificación es prescindible).
- Refresco de TLE: el servidor lo hace solo cada 6 h; para forzarlo, `--refresh` o el botón ⟳.
- Monitorización mínima: `/api/health`, logs del servicio y espacio en disco.

### Antes de abrir al público

- [ ] HTTPS y cabeceras de seguridad.
- [ ] Límite de peticiones y protección anti-abuso.
- [ ] Geocodificador propio o de pago.
- [ ] Política de privacidad, aviso legal y consentimiento de cookies si hay anuncios.
- [ ] Aviso de precisión: predicciones orientativas, no para uso crítico.
- [ ] Atribución a CelesTrak y OpenStreetMap.

---

## 13. Decisiones abiertas

1. **¿Local, público o ambos?** El código actual es local; el salto a servicio implica P0 de datos y P3 de infraestructura.
2. **¿Python o reescritura?** Para un servicio con mucho tráfico, Go/Rust o un pool de procesos; para el uso actual, Python es suficiente.
3. **¿Idioma?** El español es el diferencial; el inglés duplica mercado pero exige i18n.
4. **¿Público objetivo?** Radioaficionados/SDR (frecuencias y Doppler) o astronomía (trazas e interferencias). El producto actual apunta al primero.
5. **¿Monetización?** Publicidad sola no sostiene el proyecto; ver el análisis de afiliación, premium y B2B.
6. **¿Precisión o simplicidad?** La UI ya explica; el siguiente paso es un modo básico/avanzado.

---

## 14. Registro de cambios

| Fecha | Cambio |
| --- | --- |
| Oct 2026 | Corregido el comando de escucha LRPT de SatDump: el primer argumento es el pipeline (`meteor_m2-x_lrpt`), el segundo la carpeta de salida. |
| Oct 2026 | Tabla: fechas relativas («hoy», «mañana», «Lunes 19 oct»), duración sin segundos y direcciones con nombre completo («Sur → Noreste»). |
| Oct 2026 | Tabla simplificada: AOS pasa a «Aparece», se elimina la columna LOS (basta con Aparece + Duración) y el detalle usa «Punto más alto», «Termina» y «Dirección». |
| Oct 2026 | Mascota **Astro** (zorro de Darwin) en SVG y PNG, con avatar y especificación de marca en `docs/astro.yaml`. |
| Oct 2026 | Versión 1.3: altitud del terreno automática con Open-Meteo en web y escritorio, con caché y ajuste manual del edificio. |
| Oct 2026 | Versión de escritorio GTK4/libadwaita y paquete `.deb` 1.2.0 (`desktop/`). |
| Oct 2026 | Versión 1.1: guía «Cómo leer esta tabla», glosario contextual, cabeceras en lenguaje claro, resumen en lenguaje llano, pista de elevación mínima, ayuda UTC. |
| Oct 2026 | Optimización: `look_at` escalar sin numpy, TCA por parábola (4,5 s → 1,2 s). |
| Oct 2026 | Corrección de frecuencias (AO-85, AO-95, Meteor-M2-2), regla ISS, exclusión de geoestacionarios. |
| Oct 2026 | Versión 1.0: cálculo SGP4, API, UI, frecuencia/Doppler, gráficos, ICS, CLI y tests. |

---

## 15. Referencias

- CelesTrak, política de uso: <https://celestrak.org/usage-policy.php>
- CelesTrak, formatos GP: <https://celestrak.org/NORAD/documentation/gp-data-formats.php>
- Space-Track: <https://www.space-track.org/>
- CCSDS 502.0-B-3 (OMM): <https://public.ccsds.org/Pubs/502x0b3e1.pdf>
- python-sgp4: <https://github.com/brandon-rhodes/python-sgp4>
- Skyfield: <https://rhodesmill.org/skyfield/>
- Nominatim, política de uso: <https://operations.osmfoundation.org/policies/nominatim/>
- OSM, atribución: <https://osmfoundation.org/wiki/Licence/Attribution_Guidelines>
- Documentación de usuario: [README.md](README.md)

---

## 16. Retomar en 10 minutos

1. `cd satelites && ./run.sh`.
2. Abre <http://127.0.0.1:8765>, calcula un paso y revisa la ayuda.
3. Lee la sección 4 (arquitectura) y la 7 (deuda técnica).
4. Ejecuta las pruebas de la sección 11.
5. Elige una tarea de la sección 8 (P0 si vas a tocar datos; P1 si vas a producto).
6. Antes de publicar, revisa la sección 12.

---

## 17. Aplicación de escritorio (GTK4)

La carpeta `desktop/` contiene una aplicación nativa que reutiliza el motor de
PasoOrbital sin navegador ni servidor HTTP.

| Archivo | Responsabilidad |
| --- | --- |
| `desktop/pasoorbital_gui/app.py` | `Adw.Application`, acciones, CSS y arranque. |
| `desktop/pasoorbital_gui/window.py` | Ventana principal, panel lateral, lista de pasos, detalle, geocodificación e hilos. |
| `desktop/pasoorbital_gui/data.py` | `PasoOrbitalData`: catálogo, cálculo de pasos y pista para el gráfico. |
| `desktop/pasoorbital_gui/format.py` | Fechas relativas, duración, resumen, comandos e ICS. |
| `desktop/pasoorbital_gui/skyplot.py` | Gráfico polar con Cairo. |
| `desktop/pasoorbital_gui/style.css` | Estilos sobre libadwaita. |
| `desktop/build_deb.sh` | Genera `desktop/dist/pasoorbital_1.3.0-1_all.deb`. |
| `desktop/pasoorbital.desktop`, icono, metainfo y manpage | Integración con GNOME. |

- **Dependencias del paquete:** `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`,
  `python3-numpy`, `python3-sgp4` (en Ubuntu, `universe`).
- **Desarrollo:** `PYTHONPATH=.:desktop .venv-gui/bin/python -m pasoorbital_gui.app`.
- **Datos:** configuración en `~/.config/pasoorbital/config.json`; TLE y caché de
  direcciones y altitudes en `~/.cache/pasoorbital/`.
- **Pruebas:** se validó la interfaz con `gtk4-broadwayd` y Chrome headless;
  no hay Xvfb en el entorno de desarrollo.
- **Limitaciones:** sin geolocalización automática, sin glosario contextual en
  la app, sin notificaciones, sin Flatpak y sin tests de interfaz automatizados.
  El paquete es `Architecture: all` y depende de `python3-sgp4` (compilado para
  la arquitectura).

---

## Apéndice A. Contexto de producto (resumen)

- **Público actual:** radioaficionados y usuarios de SDR que quieren escuchar; el producto prioriza frecuencias, Doppler y comandos.
- **Chile:** la demanda de TLE se concentra en astronomía (trazas e interferencias: ALMA, ESO, NOIRLab/Rubin, Carnegie), CubeSats universitarios (SPEL/U. de Chile, USACH, PUCV, U. de Antofagasta, UACh), el programa estatal (CEN, SNSat, FACh) y estaciones terrenas. El mercado doméstico es pequeño; el nicho exportable son observatorios y redes de estaciones.
- **Monetización:** la publicidad sola no sostiene el proyecto; la combinación realista es afiliación de hardware + premium (alertas, API, listas) + B2B (clubes, colegios, observatorios).
- **Diferenciadores:** español, enfoque de escucha (no solo pasos), modo local/offline y explicaciones para principiantes.

---

## Apéndice B. Siglas

| Sigla | Significado |
| --- | --- |
| AOS | *Acquisition of Signal*: inicio del paso. |
| TCA | *Time of Closest Approach*: culminación. |
| LOS | *Loss of Signal*: fin del paso. |
| TLE | *Two-Line Element set*: elementos orbitales en dos líneas. |
| GP | *General Perturbations*: datos orbitales medios (TLE/OMM). |
| SGP4 | Modelo de propagación orbital usado por el catálogo. |
| OMM | *Orbit Mean-Elements Message*: formato CCSDS alternativo al TLE. |
| SSA | *Space Situational Awareness*: vigilancia del entorno espacial. |
| LEO / MEO / GEO / HEO | Órbita baja / media / geoestacionaria / muy elíptica. |
| RFI | Interferencia de radiofrecuencia. |
| TT&C | Telemetría, seguimiento y comando. |
| GSaaS | *Ground Station as a Service*: estación terrena como servicio. |
