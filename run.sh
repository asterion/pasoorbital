#!/usr/bin/env bash
# Lanza PasoOrbital Desktop desde el código fuente.
set -euo pipefail
cd "$(dirname "$0")"

exec env PYTHONPATH=.:desktop python3 -m pasoorbital_gui.app "$@"
