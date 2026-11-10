"""Real Zombies imagery with provenance; optional Steam cache and personal images."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from . import backend as b
from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

ASSETS = Path(__file__).parent / "assets"


@dataclass(frozen=True)
class Scene:
    key: str
    title: str
    location: str
    filename: str

    @property
    def path(self) -> Path:
        return ASSETS / self.filename

    @property
    def source(self) -> str:
        return ('https://github.com/PlagueFPS/cod-zombies/blob/'
                '6f37bbde7ca51f52aa85d2fbc0b63e2b43885127/public/maps/' + self.filename)


SCENES = (
    Scene('tranzit', 'TranZit', 'Green Run', 'tranzit.webp'),
    Scene('mob', 'Mob of the Dead', 'Alcatraz', 'mob-of-the-dead.webp'),
    Scene('buried', 'Buried', 'Resolution 1295', 'buried.webp'),
)
BUNDLED_HERO = SCENES[0].path


def selected_scene(config: dict) -> Scene:
    return next((s for s in SCENES if s.key == config.get('scene')), SCENES[0])


def home_image(config: dict | None = None) -> Path | None:
    """Custom image first, explicit Steam selection second, real Zombies scene by default."""
    config = b.load_config() if config is None else config
    custom = config.get("background_image")
    if isinstance(custom, str) and custom and Path(custom).is_file() and not QPixmap(custom).isNull():
        return Path(custom)
    if config.get("background_source") == "steam":
        steam = cached_image("hero")
        if steam:
            return steam
    scene = selected_scene(config).path
    return scene if scene.is_file() else BUNDLED_HERO if BUNDLED_HERO.is_file() else None

ART_BASE = "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/212910/"
SOURCES = {
    "poster": [ART_BASE + "library_600x900_2x.jpg", ART_BASE + "library_600x900.jpg",
               ART_BASE + "portrait.png", ART_BASE + "header.jpg"],
    "hero": [
        "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/202970/library_hero.jpg",
        ART_BASE + "header.jpg",
    ],
    "icon": [
        "https://cdn.akamai.steamstatic.com/steamcommunity/public/images/apps/212910/abbc45872375bcf8ac6b67cae6ed9ddb6c75d350.jpg",
        ART_BASE + "header.jpg",
    ],
}


def cache_dir() -> Path:
    return b.CACHE / "art"


def cached_image(kind: str) -> Path | None:
    path = cache_dir() / f"{kind}.png"
    if path.is_file() and not QPixmap(str(path)).isNull():
        return path
    # Installed Steam often already contains real art. Use it even when offline.
    steam_roots = [root / "appcache/librarycache" for root in b.steam_library_paths()]
    file_names = {
        "poster": ("212910_library_600x900.jpg", "212910_library_600x900.png"),
        "hero": ("202970_library_hero.jpg", "212910_library_hero.jpg"),
        "icon": ("212910_icon.jpg",),
    }
    for root in steam_roots:
        for filename in file_names.get(kind, ()):
            candidate = root / filename
            if candidate.is_file() and not QPixmap(str(candidate)).isNull():
                return candidate
    return None


class ArtworkFetcher(QObject):
    changed = Signal(str, str)  # kind, path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.pending = {}

    def fetch(self, kind: str) -> None:
        if kind not in SOURCES or kind in self.pending or cached_image(kind):
            return
        self.pending[kind] = 0
        self._next(kind)

    def _next(self, kind: str):
        idx = self.pending.get(kind)
        if idx is None:
            return
        if idx >= len(SOURCES[kind]):
            self.pending.pop(kind, None)
            return
        url = SOURCES[kind][idx]
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", b"BO2-Launcher/0.5")
        request.setTransferTimeout(12000)
        reply = self.manager.get(request)
        reply.finished.connect(lambda r=reply, k=kind: self._finished(k, r))

    def _finished(self, kind: str, reply: QNetworkReply):
        ok = reply.error() == QNetworkReply.NetworkError.NoError
        body = bytes(reply.readAll()) if ok else b""
        reply.deleteLater()
        pixmap = QPixmap()
        if body and len(body) < 8_000_000 and pixmap.loadFromData(body):
            if 40 <= pixmap.width() <= 8192 and 40 <= pixmap.height() <= 8192:
                try:
                    folder = cache_dir()
                    folder.mkdir(parents=True, exist_ok=True)
                    path = folder / f"{kind}.png"
                    if pixmap.save(str(path), "PNG"):
                        self.pending.pop(kind, None)
                        self.changed.emit(kind, str(path))
                        return
                except OSError:
                    pass
        if kind in self.pending:
            self.pending[kind] += 1
            self._next(kind)
