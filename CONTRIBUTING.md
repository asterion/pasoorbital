# Cómo contribuir a PasoOrbital Desktop

Gracias por querer mejorar PasoOrbital. El proyecto es software libre bajo
licencia MIT.

## Antes de abrir un issue

- Comprueba que no exista uno parecido.
- Indica sistema operativo, versión de PasoOrbital Desktop, pasos para
  reproducir el fallo y, si puedes, capturas o el mensaje de error.
- No publiques datos personales, direcciones exactas ni claves.

## Ejecutar desde el código

Desde la raíz del repositorio:

```bash
PYTHONPATH=.:desktop python3 -m pasoorbital_gui.app
```

El Python del sistema debe tener `gi`, `sgp4` y `numpy`.

Si necesitas un entorno virtual con acceso a los paquetes del sistema:

```bash
python3 -m venv --system-site-packages .venv-gui
.venv-gui/bin/pip install sgp4
PYTHONPATH=.:desktop .venv-gui/bin/python -m pasoorbital_gui.app
```

## Pruebas

```bash
python3 -m unittest discover -s tests -v
```

Las pruebas no necesitan red.

Para probar la interfaz sin pantalla se puede usar Broadway, si está instalado:

```bash
mkdir -p /tmp/pasoorbital-runtime && chmod 700 /tmp/pasoorbital-runtime
XDG_RUNTIME_DIR=/tmp/pasoorbital-runtime gtk4-broadwayd -p 8085 :5
XDG_RUNTIME_DIR=/tmp/pasoorbital-runtime \
GDK_BACKEND=broadway BROADWAY_DISPLAY=:5 \
PYTHONPATH=.:desktop python3 -m pasoorbital_gui.app
```

## Estilo

- Interfaz y documentación en español claro; evita jerga sin explicar.
- Mantén la lógica orbital en `pasoorbital/`, no en la interfaz.
- Añade o actualiza una prueba cuando cambies el cálculo o el formato.
- No incluyas TLE, cachés, `.venv`, `.deb` ni secretos en los commits.

## Pull requests

1. Describe el problema y la solución.
2. Incluye pruebas y, si cambia la interfaz, una captura.
3. Mantén el cambio acotado; separa refactorizaciones de funcionalidades.
4. Acepta la licencia MIT para tu contribución.

Al participar aceptas el [Código de conducta](CODE_OF_CONDUCT.md).
