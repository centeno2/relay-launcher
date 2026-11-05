"""Filesystem and process conventions, with no desktop or game side effects."""
from __future__ import annotations

import os
from pathlib import Path
import sys

IS_WINDOWS = sys.platform == "win32"


def app_paths(*, windows: bool = IS_WINDOWS) -> tuple[Path, Path, Path, Path]:
    if windows:
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        return local / "Relay", roaming / "Relay", local / "Relay/logs", local / "Relay/cache"
    # Keep the original locations: upgrades must preserve Wine and user settings.
    app = "bo2-zombies-linux"
    return (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / app,
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / app,
        Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / app,
        Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "bo2-launcher",
    )


def windows_client_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Plutonium"


def windows_steam_paths() -> list[Path]:
    paths = []
    if IS_WINDOWS:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                paths.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            pass
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        if os.environ.get(env):
            paths.append(Path(os.environ[env]) / "Steam")
    return list(dict.fromkeys(paths))


def windows_processes() -> list[dict]:
    """Use the native process API through psutil; never launch a shell or WMIC."""
    import psutil
    rows = []
    for proc in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            rows.append(proc.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return rows
