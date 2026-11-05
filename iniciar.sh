#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
command -v python3 >/dev/null || { echo 'Instala Python 3.12 o posterior para abrir Relay.' >&2; exit 1; }
exec python3 "$ROOT/start.py" "$@"
