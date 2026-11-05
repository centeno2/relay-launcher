#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
DATA_BASE="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_BASE/bo2-zombies-linux/app"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$DATA_BASE/applications"
if [[ "${1:-}" == "--prefix" && -n "${2:-}" && $# -eq 2 ]]; then
  APP_DIR="$2/share/relay/app"
  BIN_DIR="$2/bin"
  APPS_DIR="$2/share/applications"
elif [[ $# -ne 0 ]]; then
  echo 'Uso: ./instalar.sh [--prefix /ruta/absoluta]' >&2
  exit 2
fi
if [[ "$APP_DIR" != /* ]]; then
  echo 'El directorio de instalación debe ser una ruta absoluta.' >&2
  exit 2
fi
command -v python3 >/dev/null || { echo 'Instala Python 3.12 o posterior.' >&2; exit 1; }
mkdir -p "$APP_DIR/bo2launcher" "$BIN_DIR" "$APPS_DIR"
cp -a "$ROOT/bo2launcher/." "$APP_DIR/bo2launcher/"
cp "$ROOT/requirements.txt" "$ROOT/start.py" "$APP_DIR/"
python3 "$APP_DIR/start.py" --install-only
for entry in relay-launcher bo2-launcher bo2-zombies-linux; do
  printf '#!/usr/bin/env bash\ncd -- %q\nexec %q -m bo2launcher.gui "$@"\n' \
    "$APP_DIR" "$APP_DIR/.venv/bin/python" > "$BIN_DIR/$entry"
  chmod 755 "$BIN_DIR/$entry"
done
printf '#!/usr/bin/env bash\ncd -- %q\nexec %q -m bo2launcher.diagnostico "$@"\n' \
  "$APP_DIR" "$APP_DIR/.venv/bin/python" > "$BIN_DIR/bo2-diagnostico"
chmod 755 "$BIN_DIR/bo2-diagnostico"
python3 - "$APPS_DIR/bo2-launcher.desktop" "$BIN_DIR/relay-launcher" "$APP_DIR/bo2launcher/assets/relay.svg" <<'PY'
from pathlib import Path
import sys

def quoted(value):
    # Desktop Entry escaping is applied before Exec command-line unquoting.
    for char in ('\\', '"', '`', '$'):
        value = value.replace(char, '\\' + char)
    return '"' + value.replace('\\', '\\\\').replace('%', '%%') + '"'

Path(sys.argv[1]).write_text('\n'.join([
    '[Desktop Entry]', 'Type=Application', 'Name=Relay',
    'GenericName=BO2 Zombies Launcher', 'Comment=Tu próxima ronda empieza aquí.',
    'Exec=' + quoted(sys.argv[2]), 'Icon=' + sys.argv[3],
    'Terminal=false', 'Categories=Game;', 'StartupNotify=true',
    'StartupWMClass=bo2-launcher', '',
]), encoding='utf-8')
PY
if command -v update-desktop-database >/dev/null; then
  update-desktop-database "$APPS_DIR" || true
fi
echo 'Relay instalado. Ábrelo desde el menú de aplicaciones.'
echo "También puedes ejecutar: $BIN_DIR/relay-launcher"
echo 'Tu configuración, Wine y archivos del juego se conservaron.'
