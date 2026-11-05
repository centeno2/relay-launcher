#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$ROOT"
PYTHON="${XDG_DATA_HOME:-$HOME/.local/share}/bo2-zombies-linux/app/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo 'Primero instala el entorno Python con ./instalar.sh' >&2
  exit 1
fi
exec "$PYTHON" -m bo2launcher.gui "$@"
