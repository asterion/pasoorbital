#!/usr/bin/env bash
# Arranca PasoOrbital: crea el entorno virtual si hace falta y abre la interfaz.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if [ ! -d .venv ]; then
  echo "Creando entorno virtual en .venv…"
  "$PYTHON" -m venv .venv
fi

if ! .venv/bin/python -c "import sgp4, numpy" >/dev/null 2>&1; then
  echo "Instalando dependencias…"
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi

exec .venv/bin/python app.py "$@"
