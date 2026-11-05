"""Create a local environment once, then open Relay on Linux or Windows."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import venv


def prepare_environment(root: Path) -> Path:
    env = root / ".venv"
    python = env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.is_file():
        print("Relay · Preparando el entorno Python…", flush=True)
        venv.EnvBuilder(with_pip=True).create(env)
    requirements = root / "requirements.txt"
    fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
    stamp = env / ".relay-requirements"
    installed = stamp.read_text().strip() if stamp.is_file() else ""
    check = subprocess.run([str(python), "-c", "import PySide6, psutil"], capture_output=True)
    if installed != fingerprint or check.returncode:
        print("Relay · Instalando dependencias (solo la primera vez o al actualizar)…", flush=True)
        subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check",
                        "-r", str(requirements)], check=True)
        stamp.write_text(fingerprint, encoding="utf-8")
    return python


def main() -> int:
    if sys.version_info < (3, 12):
        print("Relay necesita Python 3.12 o posterior.", file=sys.stderr)
        return 1
    if sys.platform not in ("linux", "win32"):
        print("Relay está disponible para Linux y Windows.", file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parent
    try:
        python = prepare_environment(root)
        if "--install-only" in sys.argv:
            return 0
        return subprocess.call([str(python), "-m", "bo2launcher.gui", *sys.argv[1:]], cwd=root)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"No se pudo preparar Relay: {exc}", file=sys.stderr)
        print("Comprueba tu conexión y que Python tenga pip y venv instalados. Vuelve a ejecutar el mismo comando.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
