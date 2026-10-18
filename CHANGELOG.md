# Historial de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
y versionado [SemVer](https://semver.org/lang/es/).

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
