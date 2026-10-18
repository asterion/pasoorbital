# Seguridad

## Versiones soportadas

La rama principal y la última versión publicada (1.7.x) reciben correcciones
de seguridad.

## Cómo reportar

No abras un issue público para vulnerabilidades. Usa
[GitHub Security Advisories](https://github.com/asterion/pasoorbital/security/advisories/new)
o escribe a <asterion@users.noreply.github.com>.

Incluye una descripción, pasos para reproducir, impacto y, si es posible, una
propuesta de solución. Intentaremos responder en un plazo de 72 horas.

## Alcance

- La aplicación no tiene cuentas, telemetría ni servidor propio.
- Las direcciones se envían a Nominatim para geocodificarlas; las coordenadas se
  envían a Open-Meteo solo para calcular la altitud del terreno.
- Los TLE se descargan de CelesTrak.
- Las dependencias se declaran en `requirements.txt` y en el control del `.deb`.
