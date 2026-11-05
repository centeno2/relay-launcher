"""Instalación aislada por usuario: Wine, DXVK, Plutonium y prefijo único."""
from __future__ import annotations
import hashlib
import ipaddress
import json
import os
import platform
from pathlib import Path
from datetime import datetime
import re
import shutil
import socket
import subprocess
import tarfile
import tempfile
from urllib.parse import urlencode
import urllib.request
import urllib.error
from typing import Callable
from .platforms import IS_WINDOWS, app_paths, windows_client_dir, windows_steam_paths, windows_processes
from . import __version__

APP = "bo2-zombies-linux"
DATA, CONFIG, STATE, CACHE = app_paths()
PREFIX = DATA / "prefix"
WINE_DIR = DATA / "runtime" / "wine"
DXVK_DIR = DATA / "runtime" / "dxvk"
PLUTONIUM_DIR = DATA / "plutonium"
PLUTONIUM = PLUTONIUM_DIR / "plutonium.exe"

# Manifiesto de versión: fijar artefactos y verificar al menos el hash publicado.
WINE_VER = "11.19"
WINE_FILE = f"wine-{WINE_VER}-staging-amd64-wow64.tar.xz"
WINE_URL = f"https://github.com/Kron4ek/Wine-Builds/releases/download/{WINE_VER}/{WINE_FILE}"
WINE_SHA256 = "c89f69cf22f6664e3791210fa3b40c6e9e6d2e27a9aaa466f5a26d9c56664a09"
DXVK_VER = "2.6.2"
DXVK_FILE = f"dxvk-{DXVK_VER}.tar.gz"
DXVK_URL = f"https://github.com/doitsujin/dxvk/releases/download/v{DXVK_VER}/{DXVK_FILE}"
# MD5 de la ficha mantenida por Bottles: es control de integridad, no autenticación criptográfica fuerte.
DXVK_MD5 = "3f9d9360b8c223a32234840c544c555a"
PLUTONIUM_URL = "https://cdn.plutonium.pw/updater/plutonium.exe"
SERVERS_API = "https://gameserve.rs/api/v1/servers"  # Servicio comunitario, no oficial de Plutonium.
BOOTSTRAPPER_EXE = "plutonium-bootstrapper-win32.exe"

Reporter = Callable[[str], None]

def ensure_dirs() -> None:
    for p in (DATA, CONFIG, STATE, WINE_DIR.parent, DXVK_DIR.parent, PLUTONIUM_DIR):
        p.mkdir(parents=True, exist_ok=True)

def config_path() -> Path:
    return CONFIG / "config.json"

def load_config() -> dict:
    try:
        obj = json.loads(config_path().read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}

def save_config(**kwargs) -> None:
    ensure_dirs()
    data = load_config()
    data.update(kwargs)
    tmp = config_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(config_path())

def steam_library_paths() -> list[Path]:
    bases = windows_steam_paths() if IS_WINDOWS else [
        Path.home() / ".steam/steam",
        Path.home() / ".local/share/Steam",
        Path.home() / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
    ]
    found = []
    for base in bases:
        found.append(base)
        vdf = base / "steamapps/libraryfolders.vdf"
        if vdf.is_file():
            try:
                raw = vdf.read_text(encoding="utf-8", errors="replace")
                for entry in re.findall(r'"path"\s+"([^"\n]+)"', raw):
                    found.append(Path(entry.replace("\\\\", "\\")))
            except OSError:
                pass
    # Mantener orden y no escanear discos completos.
    return list(dict.fromkeys(p.expanduser() for p in found))

def is_game_dir(p: Path) -> bool:
    """Recognize both Steam BO2 and Plutonium-style game-data directories.

    The traditional ``pluto_t6_full_game`` distribution stores the game assets
    without t6zm.exe: Plutonium supplies its own game binary in the Wine prefix.
    This is a *layout check*, not an integrity/authenticity verification.
    """
    if not p.is_dir() or not (p / "zone").is_dir():
        return False
    if (p / "t6zm.exe").is_file():
        return True
    return all((p / item).is_file() for item in (
        "binkw32.dll", "localization_zm.txt", "zone/all/zm_transit.ff"
    ))

def find_game() -> Path | None:
    cfg = load_config().get("game_dir")
    if isinstance(cfg, str) and is_game_dir(Path(cfg)):
        return Path(cfg)
    for base in steam_library_paths():
        steamapps = base / "steamapps"
        # Appmanifest_212910 confirma que Steam registró el modo Zombies.
        manifest = steamapps / "appmanifest_212910.acf"
        if manifest.exists():
            try:
                content = manifest.read_text(encoding="utf-8", errors="replace")
                match = re.search(r'"installdir"\s+"([^"\n]+)"', content)
                name = match.group(1) if match else "Call of Duty Black Ops II"
                p = steamapps / "common" / name
                if is_game_dir(p):
                    return p
            except OSError:
                pass
        guess = steamapps / "common" / "Call of Duty Black Ops II"
        if is_game_dir(guess):
            return guess
    return None

def _safe_extract(tf: tarfile.TarFile, dest: Path) -> None:
    """Evitar rutas absolutas, traversal y vínculos de escape en archivos externos."""
    resolved = dest.resolve()
    members = tf.getmembers()
    for m in members:
        name = Path(m.name)
        if name.is_absolute() or ".." in name.parts or not name.parts:
            raise ValueError(f"Ruta peligrosa en archivo: {m.name}")
        target = (resolved / name).resolve(strict=False)
        if not target.is_relative_to(resolved):
            raise ValueError(f"Archivo escapa del directorio: {m.name}")
        if m.issym() or m.islnk():
            link = Path(m.linkname)
            if link.is_absolute():
                raise ValueError(f"Enlace absoluto no admitido: {m.name}")
            # Los hardlinks se definen respecto a la raíz del tar.
            link_target = (resolved / (link if m.islnk() else name.parent / link)).resolve(strict=False)
            if not link_target.is_relative_to(resolved):
                raise ValueError(f"Enlace fuera del destino: {m.name}")
        if not (m.isfile() or m.isdir() or m.issym() or m.islnk()):
            raise ValueError(f"Tipo no admitido: {m.name}")
    tf.extractall(resolved, members=members, filter="data")

def download(url: str, dest: Path, digest: str | None, algorithm: str, log: Reporter) -> None:
    if not url.startswith("https://"):
        raise ValueError("Solo permitimos descargas HTTPS")
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest_path = dest.with_name(dest.name + ".part")
    h = hashlib.new(algorithm)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"Relay/{__version__}"})
        with urllib.request.urlopen(req, timeout=60) as resp, digest_path.open("wb") as f:
            total = int(resp.headers.get("Content-Length", 0))
            got = 0
            last_pct = -1
            while True:
                part = resp.read(1024 * 1024)
                if not part:
                    break
                f.write(part)
                h.update(part)
                got += len(part)
                if total:
                    pct = int(got * 100 / total)
                    if pct // 10 != last_pct // 10:
                        log(f"Descarga: {pct}% ({got // 1048576} MiB)")
                        last_pct = pct
        if digest and h.hexdigest().lower() != digest.lower():
            raise ValueError(f"Falló la verificación {algorithm.upper()} del archivo {dest.name}")
        digest_path.replace(dest)
    except Exception:
        digest_path.unlink(missing_ok=True)
        raise

def wine_path() -> Path | None:
    return next((p for p in WINE_DIR.glob("*/bin/wine") if p.is_file()), None)

def wine_env() -> dict:
    env = os.environ.copy()
    env["WINEPREFIX"] = str(PREFIX)
    env.setdefault("WINEDEBUG", "-all")
    env["WINEDLLOVERRIDES"] = "winemenubuilder.exe=d"
    env["DXVK_LOG_PATH"] = str(STATE)
    if load_config().get("force_nvidia"):
        env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
        env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
        env["VK_LAYER_NV_optimus"] = "NVIDIA_only"
    w = wine_path()
    if w:
        env["PATH"] = str(w.parent) + os.pathsep + env.get("PATH", "")
    return env

def setup_wine(log: Reporter) -> None:
    if wine_path():
        log("✓ Wine privado ya está instalado")
        return
    ensure_dirs()
    log(f"Descargando Wine Staging {WINE_VER} (WoW64)…")
    archive = DATA / "cache" / WINE_FILE
    download(WINE_URL, archive, WINE_SHA256, "sha256", log)
    WINE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wine-extract-", dir=WINE_DIR.parent) as temp:
        log("Extrayendo runtime Wine…")
        with tarfile.open(archive, "r:xz") as tf:
            _safe_extract(tf, Path(temp))
        dirs = [p for p in Path(temp).iterdir() if (p / "bin/wine").is_file()]
        if len(dirs) != 1:
            raise RuntimeError("El paquete Wine no contiene exactamente un ejecutable esperado")
        shutil.move(str(dirs[0]), str(WINE_DIR / dirs[0].name))
    log("✓ Wine instalado en carpeta independiente")

def setup_prefix(log: Reporter) -> None:
    if (PREFIX / "system.reg").exists():
        log("✓ Prefijo Wine existente (se conserva)")
        return
    wine = wine_path()
    if wine is None:
        raise RuntimeError("Instala primero el runtime Wine")
    PREFIX.mkdir(parents=True, exist_ok=True)
    env = wine_env()
    env["WINEARCH"] = "win64"
    log("Inicializando entorno Windows propio (sin tocar ~/.wine)…")
    subprocess.run([str(wine.parent / "wineboot"), "-u"], env=env, check=True, timeout=240)
    log("Configurando Windows 10…")
    subprocess.run([str(wine.parent / "winecfg"), "-v", "win10"], env=env, check=True, timeout=60)
    log("✓ Prefijo independiente creado")

def setup_dxvk(log: Reporter) -> None:
    wine = wine_path()
    if not wine or not (PREFIX / "system.reg").exists():
        raise RuntimeError("Instala Wine y crea su prefijo antes de DXVK")
    stamp = CONFIG / f"dxvk-{DXVK_VER}.installed"
    if stamp.exists():
        log("✓ DXVK ya configurado")
        return
    archive = DATA / "cache" / DXVK_FILE
    log(f"Descargando DXVK {DXVK_VER}…")
    download(DXVK_URL, archive, DXVK_MD5, "md5", log)
    with tempfile.TemporaryDirectory(prefix="dxvk-extract-", dir=DXVK_DIR.parent) as temp:
        with tarfile.open(archive, "r:gz") as tf:
            _safe_extract(tf, Path(temp))
        folders = [p for p in Path(temp).iterdir() if (p / "x32/d3d9.dll").is_file()]
        if len(folders) != 1:
            raise RuntimeError("Formato inesperado del archivo DXVK")
        folder = folders[0]
        system32 = PREFIX / "drive_c/windows/system32"
        syswow64 = PREFIX / "drive_c/windows/syswow64"
        for arch_dir, target_dir in (("x64", system32), ("x32", syswow64)):
            target_dir.mkdir(parents=True, exist_ok=True)
            for dll in (folder / arch_dir).glob("*.dll"):
                shutil.copy2(dll, target_dir / dll.name)
        if DXVK_DIR.exists():
            shutil.rmtree(DXVK_DIR)
        shutil.copytree(folder, DXVK_DIR)
    overrides = ("d3d8", "d3d9", "d3d10core", "d3d11", "dxgi")
    for dll in overrides:
        subprocess.run([str(wine), "reg", "add", r"HKCU\Software\Wine\DllOverrides", "/v", dll, "/t", "REG_SZ", "/d", "native", "/f"], env=wine_env(), check=True, timeout=45)
    stamp.touch()
    log("✓ DXVK instalado (32 y 64 bits) en el prefijo privado")

def setup_plutonium(log: Reporter, refresh: bool = False) -> None:
    if PLUTONIUM.exists() and not refresh:
        log("✓ Plutonium ya descargado; se actualizará desde su launcher oficial")
        return
    log("Descargando el lanzador original de Plutonium…")
    # El distribuidor actualiza este .exe sin un SHA256 fijo públicamente documentado.
    dest = PLUTONIUM_DIR / "plutonium-new.exe"
    download(PLUTONIUM_URL, dest, None, "sha256", log)
    with dest.open("rb") as f:
        if f.read(2) != b"MZ" or dest.stat().st_size < 100_000:
            dest.unlink(missing_ok=True)
            raise ValueError("La descarga no parece ser un ejecutable Windows válido")
    dest.replace(PLUTONIUM)
    log("✓ Cliente oficial descargado desde cdn.plutonium.pw")

def preflight() -> list[tuple[str, bool, str]]:
    if IS_WINDOWS:
        return [
            ("Windows x64", platform.machine().lower() in ("amd64", "x86_64"), "Windows 10/11 x64"),
            ("Archivos BO2 Zombies", find_game() is not None, "Elige la carpeta del juego"),
            ("Plutonium", PLUTONIUM.is_file(), "Se descarga del servidor oficial"),
            ("Motor T6", bootstrapper_path() is not None, "Actualizar componentes"),
        ]
    checks = []
    checks.append(("Linux x86_64", platform.system() == "Linux" and platform.machine() == "x86_64", "Arquitectura compatible"))
    checks.append(("Steam instalado", bool(shutil.which("steam")) or (Path.home() / ".steam/steam").exists(), "Para obtener archivos originales de BO2"))
    vulkan_ok = False
    if shutil.which("vulkaninfo"):
        try:
            vulkan_ok = subprocess.run(["vulkaninfo", "--summary"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    checks.append(("Vulkan funcional", vulkan_ok, "Revisa vulkan-tools y los controladores gráficos"))
    checks.append(("Archivos BO2 Zombies", find_game() is not None, "Steam App 212910 o elegir carpeta manualmente"))
    checks.append(("Wine privado", wine_path() is not None, "Se puede descargar automáticamente"))
    checks.append(("Prefijo privado", (PREFIX / "system.reg").exists(), "Se crea automáticamente"))
    checks.append(("DXVK", (CONFIG / f"dxvk-{DXVK_VER}.installed").exists(), "Se instala automáticamente"))
    checks.append(("Plutonium", PLUTONIUM.exists(), "Se descarga del servidor oficial"))
    return checks

def run_setup(log: Reporter) -> None:
    if IS_WINDOWS:
        if platform.machine().lower() not in ("amd64", "x86_64"):
            raise RuntimeError("Se requiere Windows x64")
        ensure_dirs()
        setup_plutonium(log)
        log("✓ Plutonium preparado para Windows. Usa Actualizar componentes y abre la sesión oficial.")
        return
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("Se requiere Linux x86_64")
    ensure_dirs()
    setup_wine(log)
    setup_prefix(log)
    setup_dxvk(log)
    setup_plutonium(log)
    if shutil.which("winetricks"):
        install_windows_deps(log)
        log("✓ Entorno y runtimes Windows preparados")
    else:
        log("⚠ No se encontró winetricks. El launcher está preparado, pero faltan redistribuibles Windows.")
        log("Instala winetricks y cabextract con el gestor de paquetes de tu distribución; después usa Librerías Windows.")

def install_windows_deps(log: Reporter) -> None:
    """Winetricks del sistema instala los redistribuibles al prefijo privado.
    Paquete Linux opcional: el script NO pide sudo ni altera ~/.wine.
    """
    if IS_WINDOWS:
        raise RuntimeError("Consulta los requisitos de Windows en https://plutonium.pw/docs/system-requirements/")
    if not shutil.which("winetricks"):
        raise RuntimeError("Instala winetricks y cabextract con el gestor de paquetes de tu distribución")
    if not wine_path() or not (PREFIX / "system.reg").exists():
        raise RuntimeError("Prepara primero Wine y el prefijo")
    stamp = CONFIG / "winetricks-runtimes-v1.installed"
    if stamp.exists():
        log("✓ Redistribuibles Windows ya instalados")
        return
    recipes = ("corefonts", "d3dcompiler_47", "d3dcompiler_43", "d3dx9", "d3dx10", "msasn1", "vcrun2005", "vcrun2012", "vcrun2019", "xact", "xinput")
    log("Instalando bibliotecas Windows con Winetricks. Esto puede abrir ventanas de configuración…")
    env = wine_env()
    env["WINE"] = str(wine_path())
    for recipe in recipes:
        log(f"Winetricks: {recipe}")
        subprocess.run(["winetricks", "-q", recipe], env=env, check=True, timeout=900)
    stamp.touch()
    log("✓ Redistribuibles de Windows instalados")

def bootstrapper_path() -> Path | None:
    """Busca los ejecutables que el actualizador oficial instaló en el prefijo."""
    if IS_WINDOWS:
        exe = windows_client_dir() / "bin" / BOOTSTRAPPER_EXE
        return exe if exe.is_file() and exe.stat().st_size > 0 else None
    users = PREFIX / "drive_c" / "users"
    if not users.is_dir():
        return None
    candidates = [
        p for p in users.glob(f"*/AppData/Local/Plutonium/bin/{BOOTSTRAPPER_EXE}")
        if p.is_file() and p.stat().st_size > 0
    ]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def plutonium_client_dir() -> Path | None:
    exe = bootstrapper_path()
    return exe.parent.parent if exe else None


OFFICIAL_T6ZM_URI = "plutonium://play/t6zm"

def official_game_launcher_path() -> Path | None:
    """Localiza el cliente oficial que soporta la URI play/t6zm.

    No es el bootstrapper: el cliente gestiona la autenticación online.
    No accede al contenido de config.json ni a tokens de sesión.
    """
    if IS_WINDOWS:
        exe = windows_client_dir() / "bin/plutonium-launcher-win32.exe"
        return exe if exe.is_file() and exe.stat().st_size > 0 else None
    users = PREFIX / "drive_c" / "users"
    if not users.is_dir():
        return None
    candidates = [
        p for p in users.glob("*/AppData/Local/Plutonium/bin/plutonium-launcher-win32.exe")
        if p.is_file() and p.stat().st_size > 0
    ]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def _game_path_in_prefix(game: Path) -> str:
    """Resolve a native game folder through an actual drive mapping of OUR prefix.

    No assumption that Z: exists: users can disable it in winecfg.
    This deliberately does not invoke the provider's executable or read tokens.
    """
    game = game.resolve(strict=True)
    if IS_WINDOWS:
        return str(game)
    dosdevices = PREFIX / "dosdevices"
    candidates = []
    if dosdevices.is_dir():
        for drive in dosdevices.iterdir():
            if not re.fullmatch(r"[A-Za-z]:", drive.name) or not drive.is_symlink():
                continue
            try:
                mapped = drive.resolve(strict=True)
                relative = game.relative_to(mapped)
            except (OSError, ValueError):
                continue
            # Prefer the most specific mapped location. Wine's usual Z: -> / works.
            candidates.append((len(mapped.parts), drive.name.upper(), relative))
    if not candidates:
        raise RuntimeError(
            "La carpeta BO2 no es accesible desde las unidades del prefijo Wine. "
            "Comprueba la unidad Z: en winecfg (debe apuntar a /).")
    _depth, letter, relative = max(candidates, key=lambda item: (item[0], item[1] != 'Z:'))
    return letter + "\\" + "\\".join(relative.parts) if relative.parts else letter + "\\"


def official_config_path() -> Path | None:
    """The installation matched to the official launcher is the only one edited."""
    exe = official_game_launcher_path()
    if exe is None:
        return None
    directory = exe.parent.parent
    if directory.is_symlink():
        raise RuntimeError("La carpeta de configuración del cliente es un enlace simbólico")
    return directory / "config.json"


def official_game_path_status(game: Path) -> str:
    """Only inspect the t6Path property; never return login/session content."""
    config = official_config_path()
    if config is None:
        return "pendiente-cliente"
    if not config.exists():
        return "pendiente-ruta"
    if config.is_symlink():
        return "configuracion-insegura"
    try:
        saved = json.loads(config.read_text(encoding="utf-8"))
        expected = _game_path_in_prefix(game)
        return "sincronizado" if isinstance(saved, dict) and saved.get('t6Path', '').casefold().rstrip('\\') == expected.casefold().rstrip('\\') else "pendiente-ruta"
    except (OSError, ValueError, AttributeError):
        return "configuracion-invalida"


def official_client_running(proc_root: Path = Path("/proc")) -> bool:
    """Prevent racing writes against the provider's own settings manager."""
    wanted = {"plutonium-launcher-win32.exe", "plutonium.exe"}
    if IS_WINDOWS:
        # Conservatively block config edits if a matching client cannot be inspected.
        return any(str(row.get("name") or "").lower() in wanted for row in windows_processes())
    token = ("WINEPREFIX=" + str(PREFIX)).encode("utf-8")
    try:
        entries = proc_root.iterdir()
    except OSError:
        return False
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().split(b"\0")
            if not any(arg.decode("utf-8", errors="ignore").replace("\\", "/").rsplit("/", 1)[-1].lower() in wanted for arg in cmdline if arg):
                continue
            environ = (entry / "environ").read_bytes().split(b"\0")
            if token in environ:
                return True
        except OSError:
            continue
    return False


def sync_official_game_path(game: Path) -> bool:
    """Sync the documented t6Path key with the selected BO2 folder.

    Existing config keys (including account/session fields) are preserved and are
    NEVER logged. Originals are backed up with private mode before replacement.
    Returns True if updated, False if already matching. Never changes game files.
    """
    if not is_game_dir(game):
        raise RuntimeError("La carpeta de BO2 seleccionada no contiene los archivos requeridos")
    if game_process_alive() or official_client_running():
        raise RuntimeError("Cierra BO2 y la ventana oficial antes de sincronizar la ruta, para evitar conflictos")
    config = official_config_path()
    if config is None:
        raise RuntimeError("El cliente oficial todavía no está instalado; inicializa la cuenta online")
    windows_path = _game_path_in_prefix(game)
    if config.is_symlink():
        raise RuntimeError("No se modificará config.json porque es un enlace simbólico")
    if config.exists() and not config.is_file():
        raise RuntimeError("config.json no es un archivo normal")
    if config.exists():
        try:
            original = config.read_bytes()
            document = json.loads(original.decode('utf-8-sig'))
        except (OSError, UnicodeError, ValueError) as exc:
            raise RuntimeError("La configuración del cliente no es JSON válido. Se dejó intacta") from exc
        if not isinstance(document, dict):
            raise RuntimeError("La configuración del cliente tiene un formato no compatible; no se modificó")
    else:
        original = None
        document = {}
    if document.get("t6Path") == windows_path:
        return False
    # Before writing, keep an exact, mode-0600 copy of the previous configuration.
    config.parent.mkdir(parents=True, exist_ok=True)
    if original is not None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = config.with_name(f"config.json.bak-ruta-{stamp}")
        index = 1
        while dest.exists():
            dest = config.with_name(f"config.json.bak-ruta-{stamp}-{index}")
            index += 1
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(original)
        except Exception:
            dest.unlink(missing_ok=True)
            raise
    document["t6Path"] = windows_path
    encoded = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode('utf-8')
    fd, temporary_name = tempfile.mkstemp(prefix=".config-bo2-", dir=config.parent)
    tmp = Path(temporary_name)
    try:
        if not IS_WINDOWS:
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(encoded)
        tmp.replace(config)
    finally:
        tmp.unlink(missing_ok=True)
    return True


def build_online_command(game: Path) -> list[str]:
    """Entrada online soportada por el cliente, sin tokens extraídos ni inventados.

    La carpeta del juego también debe estar configurada en el cliente oficial.
    """
    wine = wine_path()
    if not IS_WINDOWS and (wine is None or not (PREFIX / "system.reg").is_file()):
        raise RuntimeError("Wine todavía no está configurado")
    if not is_game_dir(game):
        raise RuntimeError("Selecciona una carpeta válida de BO2 Zombies")
    launcher = official_game_launcher_path()
    if launcher is None:
        raise RuntimeError("Falta el cliente oficial; abre la sesión oficial para instalarlo")
    return ([str(wine)] if not IS_WINDOWS else []) + [str(launcher), OFFICIAL_T6ZM_URI]


def launch_online_game() -> tuple[subprocess.Popen, str]:
    """Online: usar la URI oficial; si falta el cliente, abrir login/configuración.

    El modo 'setup' NO indica que BO2 esté ejecutándose, solo abre el cliente.
    """
    game = find_game()
    if game is None:
        raise RuntimeError("Selecciona una carpeta válida de BO2 Zombies")
    launcher = official_game_launcher_path()
    if launcher is None:
        return launch_plutonium(), "setup"
    # Plutonium uses its own config.json, not our app's config.json.
    # Always repair the documented t6Path before asking for T6ZM.
    sync_official_game_path(game)
    return _spawn_wine(build_online_command(game), cwd=launcher.parent.parent, logfile="game.log"), "uri"



def account_session_paths() -> list[Path]:
    """Encuentra solo configuraciones del proveedor en este prefijo (sin leer secretos)."""
    if IS_WINDOWS:
        config = windows_client_dir() / "config.json"
        return [config] if config.is_file() and not config.is_symlink() else []
    users = PREFIX / "drive_c" / "users"
    if not users.is_dir():
        return []
    return sorted(
        p for p in users.glob("*/AppData/Local/Plutonium/config.json")
        if p.is_file() and not p.is_symlink()
    )


def backup_online_session() -> list[Path]:
    """Aparta la sesión antigua para reautenticar; conserva copia recuperable.

    Nunca elimina perfiles, partidas, caché, binarios ni el prefijo completo.
    Solo debe llamarse después de confirmar que los procesos del cliente
    oficial están cerrados. Los respaldos pueden contener tokens: modo 0600.
    """
    if game_process_alive() or official_client_running():
        raise RuntimeError("Cierra BO2 y el cliente oficial antes de reparar la sesión")
    backups = []
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for src in account_session_paths():
        dest = src.with_name(f"config.json.bak-{timestamp}")
        index = 1
        while dest.exists():
            dest = src.with_name(f"config.json.bak-{timestamp}-{index}")
            index += 1
        src.rename(dest)
        dest.chmod(0o600)
        backups.append(dest)
    return backups


def _process_is_t6(cmdline: bytes, comm: bytes = b"") -> bool:
    """Detect Wine-hosted T6ZM *including the Plutonium bootstrapper process*.

    On Linux the Windows game can run inside plutonium-bootstrapper-win32.exe
    instead of a standalone t6zm.exe, so checking only t6zm.exe was wrong.
    Matching `t6zm` explicitly prevents mistaking multiplayer or the updater
    for a Zombies session. `comm` is truncated to 15 bytes by Linux.
    """
    parts = [a.decode("utf-8", "replace").replace("\\", "/").lower()
             for a in cmdline.split(b"\0") if a]
    names = {part.rsplit("/", 1)[-1] for part in parts}
    direct_names = {"t6zm.exe", "plutonium-t6zm.exe", "plutonium_t6zm.exe"}
    if names & direct_names:
        return True
    if comm.decode("utf-8", "replace").strip().lower() in direct_names:
        return True
    bootstrap = any("plutonium-bootstrapper-win32.exe" in part for part in parts)
    return bootstrap and "t6zm" in names and "t6mp" not in names


def game_process_alive(proc_root: Path = Path("/proc")) -> bool:
    """Recognize Zombies processes in our own Wine prefix, not any wineserver.

    Linux exposes Wine processes under different executable names depending on
    the build. Compare cmdline and comm, and require this exact WINEPREFIX.
    """
    if IS_WINDOWS:
        for row in windows_processes():
            args = row.get("cmdline") or []
            cmdline = b"\0".join(str(arg).encode("utf-8") for arg in args)
            if _process_is_t6(cmdline, str(row.get("name") or "").encode("utf-8")):
                return True
        return False
    token = ("WINEPREFIX=" + str(PREFIX)).encode("utf-8")
    try:
        processes = proc_root.iterdir()
    except OSError:
        return False
    for pid in processes:
        if not pid.name.isdigit():
            continue
        try:
            args = (pid / "cmdline").read_bytes()
            comm_path = pid / "comm"
            comm = comm_path.read_bytes() if comm_path.exists() else b""
            if not _process_is_t6(args, comm):
                continue
            env_vars = (pid / "environ").read_bytes().split(b"\0")
            if token in env_vars:
                return True
        except OSError:
            continue
    return False


def game_console_visible() -> bool:
    """Fallback for the T6 game living in a detached Wine child on Niri.

    This is a display-only indicator, not proof the player authenticated.
    Crucially this does not close or terminate the game's required console.
    """
    if IS_WINDOWS or not os.environ.get("NIRI_SOCKET") or not shutil.which("niri"):
        return False
    try:
        result = subprocess.run(
            ["niri", "msg", "--json", "windows"], capture_output=True,
            text=True, timeout=2, check=True)
        windows = json.loads(result.stdout)
        if not isinstance(windows, list):
            return False
        return any(isinstance(w, dict) and
                   re.fullmatch(r"Plutonium r[0-9]+", str(w.get("title") or ""))
                   for w in windows)
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError, ValueError):
        return False


def game_session_visible() -> bool:
    """Best-effort live indicator; never infer a session just from Wine PID."""
    return game_process_alive() or game_console_visible()

def wine_game_path(path: Path) -> str:
    """Convierte una ruta POSIX a la representación Windows del mismo prefijo."""
    if IS_WINDOWS:
        return str(path.resolve())
    exe = wine_path()
    if exe is None:
        raise RuntimeError("No se encontró Wine privado")
    winepath = exe.parent / "winepath"
    if winepath.is_file():
        try:
            result = subprocess.run(
                [str(winepath), "-w", str(path.resolve())],
                env=wine_env(), capture_output=True, text=True, timeout=15, check=True,
            )
            result_path = result.stdout.strip().splitlines()
            if result_path and re.match(r"^[a-zA-Z]:[\\/]", result_path[-1]):
                return result_path[-1]
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
    # Z: apunta a / en los prefijos Wine por defecto. Si fue eliminado, se
    # requiere restaurarlo mediante winecfg -> Drives.
    return "Z:" + str(path.resolve()).replace("/", "\\")


def validate_server_address(value: str) -> str:
    """Acepta únicamente direcciones IP (no opciones de línea de comandos)."""
    if not isinstance(value, str) or len(value) > 100 or not value.strip():
        raise ValueError("Dirección de servidor vacía o incorrecta")
    value = value.strip()
    if value.startswith("["):
        match = re.fullmatch(r"\[([^]]+)\]:(\d{1,5})", value)
        if not match:
            raise ValueError("Formato IPv6 inválido")
        host, port = match.groups()
        ipaddress.IPv6Address(host)
        normalized_host = f"[{host}]"
    else:
        match = re.fullmatch(r"(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})", value)
        if not match:
            raise ValueError("Se requiere una dirección IPv4:puerto")
        host, port = match.groups()
        ipaddress.IPv4Address(host)
        normalized_host = host
    if not 1 <= int(port) <= 65535:
        raise ValueError("Puerto fuera de rango")
    return f"{normalized_host}:{int(port)}"


def build_game_command(game: Path, *, lan: bool = False, server: str | None = None,
                       player_name: str = "Player") -> list[str]:
    """El bootstrapper oficial inicia BO2 sin abrir primero su launcher web."""
    exe = bootstrapper_path()
    wine = wine_path()
    if not IS_WINDOWS and (wine is None or not (PREFIX / "system.reg").is_file()):
        raise RuntimeError("Wine no está configurado. Ejecuta Instalar componentes.")
    if exe is None:
        raise RuntimeError(
            "Falta el bootstrapper de Plutonium. Usa 'Inicializar Plutonium' "
            "una vez para descargar el cliente oficial e iniciar sesión."
        )
    if not is_game_dir(game):
        raise RuntimeError("La carpeta de BO2 Zombies no es válida. Revísala en Configuración.")
    if not isinstance(player_name, str) or not 1 <= len(player_name.strip()) <= 24 or re.search(r'[\r\n"\x00]', player_name):
        raise ValueError("El nombre de jugador no es válido (1-24 caracteres sin comillas)")
    args = ([str(wine)] if not IS_WINDOWS else []) + [str(exe), "t6zm", wine_game_path(game), "+name", player_name.strip()]
    if lan:
        args.append("-lan")
    if server:
        if lan:
            raise ValueError("Para entrar a servidores públicos, desactiva el modo LAN")
        # La consola de T6 admite connect ip:puerto. La ejecución automática
        # vía +connect depende de la versión de Plutonium; también se muestra
        # el comando manual en la interfaz.
        args += ["+connect", validate_server_address(server)]
    return args


def _spawn_wine(cmd: list[str], *, cwd: Path, logfile: str) -> subprocess.Popen:
    """Launch natively on Windows and in the private prefix on Linux."""
    ensure_dirs()
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if IS_WINDOWS else {"start_new_session": True}
    with (STATE / logfile).open("ab") as out:
        return subprocess.Popen(
            cmd, cwd=str(cwd), env=os.environ.copy() if IS_WINDOWS else wine_env(), stdout=out,
            stderr=subprocess.STDOUT, **options,
        )


def launch_game(*, lan: bool = False, server: str | None = None,
                player_name: str = "Player") -> subprocess.Popen:
    game = find_game()
    if game is None:
        raise RuntimeError("Selecciona primero una carpeta válida de BO2 Zombies")
    exe = bootstrapper_path()
    cmd = build_game_command(game, lan=lan, server=server, player_name=player_name)
    return _spawn_wine(cmd, cwd=exe.parent.parent, logfile="game.log")


def launch_plutonium(*, update_only: bool = False) -> subprocess.Popen:
    """Primer inicio/autenticación o mantenimiento del updater oficial."""
    if not PLUTONIUM.exists() or not runtime_ready():
        raise RuntimeError("Instala los componentes antes de continuar")
    cmd = ([str(wine_path())] if not IS_WINDOWS else []) + [str(PLUTONIUM)]
    if update_only:
        cmd.append("-update-only")
    return _spawn_wine(cmd, cwd=PLUTONIUM_DIR, logfile="plutonium.log")




def check_connections(log: Reporter) -> None:
    """Diagnostica la conectividad del anfitrión sin credenciales ni cambios al DNS.

    No garantiza que .NET/WinHTTP dentro de Wine pueda negociar TLS. Un
    código HTTP 4xx prueba conectividad HTTPS, no autenticación válida.
    """
    endpoints = (
        ("Portal", "plutonium.pw", "https://plutonium.pw/"),
        ("Descargas", "cdn.plutonium.pw", "https://cdn.plutonium.pw/updater/plutonium.exe"),
        ("Cuenta online", "platform.plutonium.pw", "https://platform.plutonium.pw/"),
    )
    failed = []
    log("Diagnóstico de red desde " + platform.system() + ":")
    for title, hostname, url in endpoints:
        try:
            records = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
            ipv4 = {r[4][0] for r in records if r[0] == socket.AF_INET}
            ipv6 = {r[4][0] for r in records if r[0] == socket.AF_INET6}
            log(f"  {title}: DNS OK · IPv4={len(ipv4)} · IPv6={len(ipv6)}")
        except OSError as exc:
            failed.append(title)
            log(f"  {title}: DNS FALLÓ ({type(exc).__name__}: {exc})")
            continue
        # HEAD no descarga el binario y nos permite comprobar la ruta TLS.
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "BO2-Launcher/0.8"})
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                log(f"  {title}: HTTPS OK (HTTP {response.status})")
        except urllib.error.HTTPError as exc:
            # 403/404/405 no equivalen a host inaccesible.
            log(f"  {title}: HTTPS accesible (HTTP {exc.code}; acceso o método restringido)")
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            failed.append(title)
            log(f"  {title}: HTTPS FALLÓ ({type(exc).__name__}: {exc})")
    if failed:
        log("⚠ Conexión fallida con: " + ", ".join(failed))
        log("Revisa DNS, conexión, proxy y firewall del sistema.")
    else:
        log("✓ El sistema puede acceder a los servicios comprobados.")
        log("La conectividad no confirma que la cuenta de Plutonium esté autenticada.")


def runtime_ready() -> bool:
    return IS_WINDOWS or bool(wine_path() and (PREFIX / "system.reg").is_file())


def component_status() -> list[tuple[str, bool]]:
    checks = [] if IS_WINDOWS else [
        ("Wine", wine_path() is not None),
        ("entorno Wine", (PREFIX / "system.reg").is_file()),
        ("DXVK", (CONFIG / f"dxvk-{DXVK_VER}.installed").is_file()),
    ]
    return checks + [("Plutonium", PLUTONIUM.is_file())]


def update_engine(log: Reporter) -> None:
    """Run the official updater, optionally using a virtual display on Linux."""
    if not runtime_ready():
        raise RuntimeError("Instala los componentes antes de actualizar el cliente.")
    if game_process_alive() or official_client_running():
        raise RuntimeError("Cierra BO2 y el cliente oficial antes de actualizar.")
    log("Descargando el ejecutable oficial más reciente por HTTPS…")
    setup_plutonium(log, refresh=True)
    ensure_dirs()
    command = ([str(wine_path())] if not IS_WINDOWS else []) + [str(PLUTONIUM), "-update-only"]
    update_env = os.environ.copy() if IS_WINDOWS else wine_env()
    virtual = not IS_WINDOWS and all(shutil.which(name) for name in ("xvfb-run", "Xvfb", "xauth"))
    if virtual:
        command = [shutil.which("xvfb-run"), "-a", "-s", "-screen 0 1280x720x24 -nolisten tcp"] + command
        update_env.pop("WAYLAND_DISPLAY", None)
        update_env["XDG_SESSION_TYPE"] = "x11"
        log("Actualizando el cliente en una pantalla virtual…")
    else:
        log("Actualizando el cliente oficial; puede aparecer su ventana de progreso…")
    with (STATE / "updater.log").open("ab") as out:
        out.write(b"\n=== Relay: official update-only ===\n")
        try:
            finished = subprocess.run(
                command, cwd=str(PLUTONIUM_DIR), env=update_env,
                stdout=out, stderr=subprocess.STDOUT, timeout=420, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("El actualizador no terminó a tiempo. Revisa Actividad y updater.log.") from exc
    if finished.returncode != 0:
        raise RuntimeError(
            f"El proceso de actualización finalizó con código {finished.returncode}. "
            f"Consulta {STATE / 'updater.log'}."
        )
    if bootstrapper_path() is None:
        raise RuntimeError(
            "El actualizador terminó, pero falta el motor de BO2. Revisa updater.log "
            "o usa Abrir sesión oficial en Configuración."
        )
    log("✓ El actualizador terminó y el ejecutable de BO2 está disponible.")
    log("La cuenta online se autentica desde la ventana oficial de Plutonium.")


def fetch_servers() -> list[dict]:
    """Consulta lista comunitaria HTTPS; sin credenciales y fuera del hilo Qt."""
    url = SERVERS_API + "?" + urlencode({"game": "T6ZM", "limit": "100"})
    request = urllib.request.Request(url, headers={"User-Agent": "BO2-Launcher/0.8"})
    with urllib.request.urlopen(request, timeout=15) as response:
        # Limita el tamaño del JSON procedente del proveedor externo.
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise RuntimeError("Respuesta de servidores demasiado grande")
    doc = json.loads(raw)
    items = doc.get("data", {}).get("servers", [])
    if not isinstance(items, list):
        raise RuntimeError("La API cambió el formato de los servidores")
    output = []
    for item in items:
        if not isinstance(item, dict):
            continue
        address = item.get("address", "")
        # El usuario también puede consultar servidores sin IP válida, pero
        # sólo los comprobados habilitan la acción de conectar.
        try:
            address = validate_server_address(address)
        except (ValueError, ipaddress.AddressValueError):
            address = ""
        raw_players = item.get("players") or {}
        raw_map = item.get("map") or {}
        if not isinstance(raw_players, dict):
            raw_players = {}
        if not isinstance(raw_map, dict):
            raw_map = {}
        output.append({
            "name": str(item.get("name") or "Servidor sin nombre")[:150],
            "map": str(raw_map.get("display") or raw_map.get("name") or "—")[:80],
            "players": f"{raw_players.get('current', 0)}/{raw_players.get('max', '?')}",
            "address": address,
        })
    return output
