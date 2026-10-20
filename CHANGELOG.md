# Historial de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y versionado [SemVer](https://semver.org/lang/es/).

## [1.9.1] - 2026-10-19

### Corregido

- Los filtros de la lista son reactivos: «Solo con frecuencia conocida» se aplica
  al instante y los cambios de días, elevación mínima y grupos actualizan y
  recalculan la lista automáticamente.
- Las notificaciones y el próximo paso respetan los filtros activos.

### Empaquetado

- Nuevos paquetes `.deb` y `.rpm` con la versión 1.9.1.

## [Sin publicar]

### Corregido

- El RPM instalaba los módulos en `/usr/lib/python3.13/site-packages`, una ruta
  ligada a la versión de Python del equipo que lo construía. En Fedora 43/44
  (Python 3.14) la app fallaba con `ModuleNotFoundError: No module named
  'pasoorbital_gui'`. Ahora se instalan en `/usr/lib/pasoorbital`, que no
  depende de la versión de Python, y los lanzadores añaden esa ruta a
  `sys.path`. El RPM pasa a ser `1.9.0-2`.

## [1.9.0] - 2026-10-18

### Añadido

- **Cielo en vivo**: marcador del satélite, estela recorrida, línea «ahora» en el
  gráfico de elevación y barra de progreso del paso.
- Actualización cada segundo solo mientras el paso está en curso y el detalle
  está abierto.

## [1.8.0] - 2026-10-18

### Añadido

- **Paquete RPM** instalable con `rpm -ivh` para Fedora, sin repositorio ni `dnf`.
- Script `desktop/build_rpm.sh` y especificación `desktop/pasoorbital.spec`.
- El workflow de release publica el `.rpm` junto al `.deb`.

### Cambiado

- `pyproject.toml` incluye los recursos de Astro en el paquete.

## [1.7.0] - 2026-10-18

### Añadido

- **Astro** en la cabecera de la ventana y en el estado vacío.
- Crédito de Astro en el diálogo **Acerca de**.

### Cambiado

- Comando LRPT para **SatDump 1.2.2**, con ganancia inicial de 30 dB.

## [1.6.0] - 2026-10-18

### Añadido

- **Tarjeta «Próximo paso»** en la pantalla principal, con cuenta atrás, datos
  clave y botón para abrir el detalle.
- **Campana de avisos** en la cabecera, siempre visible y sincronizada con el
  interruptor lateral.
- **La notificación abre el detalle del paso** concreto, no solo la ventana
  principal.
- Atajos **Ctrl+F** para buscar y **F5** para actualizar TLE.

## [1.5.1] - 2026-10-18

### Corregido

- Los iconos de las pestañas **Resumen**, **Radio** y **Cielo** aparecían como
  imágenes rotas. Ahora usan iconos simbólicos válidos de Adwaita.

## [1.5.0] - 2026-10-18

### Añadido

- **Detalle modal** con `Adw.Dialog` y pestañas **Resumen**, **Radio** y **Cielo**.
- El **Resumen** es la pestaña principal: estado del paso, explicación en lenguaje
  llano y ocho datos clave.
- **Radio:** selector de frecuencia si hay varios canales, Doppler calculado
  sobre el canal elegido y comando de escucha correspondiente.
- **Cielo:** gráfico polar y nuevo **gráfico de elevación** durante el paso.
- Acciones fijas **Guardar .ics** y **Cerrar**; sin scroll en la ventana.

### Cambiado

- El detalle deja de ser un `Adw.Window` con `ScrolledWindow` y pasa a un modal
  real de libadwaita.

## [1.4.0] - 2026-10-18

### Añadido

- **Aviso de escritorio 5 minutos antes** de cada paso, mediante
  `Gio.Notification`.
- **Resaltado de la fila** del paso que aparece en los próximos 5 minutos o que
  ya está en curso.
- Interruptor **«Avisar 5 min antes»** en el panel de predicción, con la
  preferencia guardada.
- Acción `app.present`: al pulsar la notificación se trae la ventana al frente.

### Notas

- Esta versión es solo para la app de escritorio; la web queda para una fase
  posterior.

## [1.3.0] - 2026-10-17

### Añadido

- **Altitud del terreno automática** al buscar una dirección o usar el GPS, con
  Open-Meteo (DEM Copernicus).
- Botón «Calcular altitud del terreno» para coordenadas introducidas a mano.
- Caché de altitudes y aviso para sumar la altura del edificio.
- Nuevo endpoint `GET /api/elevation?lat=…&lon=…`.

### Cambiado

- La app de escritorio y la web rellenan la altitud antes de calcular los pasos.
- Documentación de privacidad: las coordenadas se envían a Open-Meteo solo para
  consultar la altitud.

## [1.2.0] - 2026-10-17

### Añadido

- Aplicación de escritorio nativa **GTK4 + libadwaita** (`desktop/`).
- Paquete `.deb` para Ubuntu/Debian con `.desktop`, icono, metadatos
  AppStream y página de manual.
- Detalle de paso con resumen en lenguaje llano, frecuencias, Doppler,
  gráfico polar, comandos de escucha y exportación a `.ics`.
- CI para pruebas y construcción del `.deb`.

### Autoría

- Marcos Matamala Fernandez y DeepSeek Harness (deepseek-flash).

### Cambiado

- El proyecto pasa a llamarse **PasoOrbital** (antes SatPass), con App ID
  `io.github.asterion.PasoOrbital`.
- El panel de escritorio usa etiquetas amigables y un resumen del paso.

## [1.1.0] - 2026-10-17

### Añadido

- Guía «Cómo leer esta tabla», glosario contextual y ayuda en las cabeceras.
- Resumen en lenguaje llano de cada paso.
- Pista de elevación mínima y ayuda de zona horaria UTC.
- Cabeceras en lenguaje claro: Aparece, Duración, Altura, Dirección,
  Frecuencia y Desvío.

### Cambiado

- Se eliminó la columna LOS: la duración y la hora de aparición son suficientes.
- Direcciones con nombre completo (Norte, Noreste, Este…).

## [1.0.0] - 2026-10-17

### Añadido

- Primera versión: predicción de pasos, catálogo TLE, frecuencias, Doppler,
  gráficos, comandos de escucha y CLI.
