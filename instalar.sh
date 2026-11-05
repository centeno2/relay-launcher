#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$ROOT"
DATA_BASE="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_BASE/bo2-zombies-linux/app"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$DATA_BASE/applications"
command -v python3 >/dev/null || { echo 'ERROR: Falta Python 3' >&2; exit 1; }
mkdir -p "$APP_DIR" "$BIN_DIR" "$APPS_DIR" "$APP_DIR/bo2launcher"
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/python" -m pip install --disable-pip-version-check -r "$ROOT/requirements.txt"
cp -a "$ROOT/bo2launcher/." "$APP_DIR/bo2launcher/"
# Remove old AI illustration/assets left by previous versions. No game files are touched.
rm -f "$APP_DIR/assets/zombies-cinematic.png" "$APP_DIR/assets/zombies-cinematic.svg" \
      "$APP_DIR/assets/bo2-launcher.png" "$APP_DIR/assets/bo2-launcher.svg" 2>/dev/null || true
cat > "$BIN_DIR/bo2-launcher" <<EOF
#!/usr/bin/env bash
set -e
cd "${APP_DIR}"
exec "${APP_DIR}/.venv/bin/python" -m bo2launcher.gui "\$@"
EOF
chmod 755 "$BIN_DIR/bo2-launcher"
cat > "$BIN_DIR/bo2-zombies-linux" <<EOF
#!/usr/bin/env bash
exec "${BIN_DIR}/bo2-launcher" "\$@"
EOF
chmod 755 "$BIN_DIR/bo2-zombies-linux"
cat > "$BIN_DIR/bo2-diagnostico" <<EOF
#!/usr/bin/env bash
set -e
cd "${APP_DIR}"
exec "${APP_DIR}/.venv/bin/python" -m bo2launcher.diagnostico "\$@"
EOF
chmod 755 "$BIN_DIR/bo2-diagnostico"
cat > "$APPS_DIR/bo2-launcher.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=BO2 Launcher
GenericName=Zombies Launcher
Exec=${BIN_DIR}/bo2-launcher
Icon=applications-games
Terminal=false
Categories=Game;
StartupNotify=true
StartupWMClass=bo2-launcher
EOF
rm -f "$APPS_DIR/bo2-zombies-linux.desktop"
# Legacy cartoon icon from v0.4 must not override the real Steam game icon.
rm -f "$DATA_BASE/icons/hicolor/512x512/apps/bo2-launcher.png"
if [[ -n "${NIRI_SOCKET:-}" ]]; then
  if (cd "$APP_DIR" && "$APP_DIR/.venv/bin/python" -c 'from bo2launcher.niri_integration import set_enabled; set_enabled(True)'); then
    echo 'Niri: consola técnica oculta visualmente (proceso del juego intacto).'
  else
    echo 'AVISO: No se pudo activar la regla de Niri. Revísala desde Configuración del launcher.' >&2
  fi
fi
echo 'BO2 Launcher v0.11 instalado. Tu Wine, configuración y juego se conservaron.' 
if ! command -v xvfb-run >/dev/null || ! command -v xauth >/dev/null; then
  echo 'Opcional para actualizaciones sin ventanas en Niri: sudo pacman -S --needed xorg-server-xvfb xorg-xauth'
fi
echo "Abre el launcher con: ${BIN_DIR}/bo2-launcher"
echo "Diagnóstico desde cualquier carpeta: ${BIN_DIR}/bo2-diagnostico --red"
