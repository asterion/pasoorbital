# Cómo contribuir a PasoOrbital

Gracias por querer mejorar PasoOrbital. El proyecto es software libre bajo
licencia MIT y las contribuciones son bienvenidas.

## Antes de abrir un issue

- Comprueba que no exista uno parecido.
- Para fallos, indica sistema operativo, versión de PasoOrbital, pasos para
  reproducirlo y, si puedes, capturas o el mensaje de error.
- No publiques datos personales, direcciones exactas ni claves.

## Entorno de desarrollo

### Web

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Abre <http://127.0.0.1:8765/>.

### Escritorio

```bash
python3 -m venv --system-site-packages .venv-gui
.venv-gui/bin/pip install sgp4
PYTHONPATH=.:desktop .venv-gui/bin/python -m pasoorbital_gui.app
```

Para probar sin pantalla se puede usar Broadway:

```bash
mkdir -p /tmp/pasoorbital-runtime && chmod 700 /tmp/pasoorbital-runtime
XDG_RUNTIME_DIR=/tmp/pasoorbital-runtime gtk4-broadwayd -p 8085 :5
XDG_RUNTIME_DIR=/tmp/pasoorbital-runtime \
GDK_BACKEND=broadway BROADWAY_DISPLAY=:5 \
PYTHONPATH=.:desktop .venv-gui/bin/python -m pasoorbital_gui.app
```

## Pruebas

```bash
.venv/bin/python -m unittest discover -s tests -v
node --check static/app.js
```

Si no hay TLE cacheados, la prueba de CLI se omite; el resto no necesita red.

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
