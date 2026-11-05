"""BO2 Launcher v0.11. Native Qt launcher with direct BO2 Zombies startup.

The artwork is fetched from Steam on the player's computer, not bundled.
Existing Wine prefix, game data and settings are preserved.
"""
from __future__ import annotations
import sys
import time
import os
from pathlib import Path
# Reduce ruido de Qt en Niri sin silenciar avisos de Wine, Vulkan ni del proveedor.
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.wayland.textinput=false")
from PySide6.QtCore import Qt, QRect, QSize, QThread, Signal, QUrl, QTimer
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
    QTableWidget, QTableWidgetItem, QAbstractItemView,
)
from . import backend as b
from . import artwork
from . import niri_integration as ni

CSS = """
* { font-family: 'Inter', 'Noto Sans', 'DejaVu Sans', sans-serif; }
QMainWindow, QWidget#root, QWidget#page { background-color: #101114; color: #f0f0f1; }
QLabel { background: transparent; color: #efeff1; }
QLabel#brand { font-size: 15px; font-weight: 750; }
QLabel#heading { font-size: 29px; font-weight: 750; }
QLabel#gameSubtitle { font-size: 13px; font-weight: 550; color: #b5b6bd; }
QLabel#caption { font-size: 12px; color: #9699a4; }
QLabel#hint { font-size: 12px; color: #9699a4; }
QLabel#rowTitle { font-size: 15px; font-weight: 700; }
QFrame#divider { background-color: #303137; max-height: 1px; min-height: 1px; }
QFrame#gameCard { background-color: rgba(13, 15, 21, 152); border: 1px solid rgba(184, 103, 66, 115); border-radius: 12px; }
QWidget#homeContent { background: transparent; }
QLabel#heroEyebrow { color: #f1a46f; font-size: 12px; font-weight: 800; }
QLabel#heroTitle { color: #ffffff; font-size: 40px; font-weight: 850; }
QLabel#heroNote { color: #d5d4d4; font-size: 13px; }
QLabel#statusOK { color: #9fe3b3; font-size: 14px; font-weight: 700; }
QFrame#setting { background-color: #1a1c22; border: 1px solid #30323c; border-radius: 9px; }
QPushButton { background-color: #262931; color: #e7e7ec; border: 1px solid #383b45;
              border-radius: 6px; padding: 10px 16px; font-size: 13px; font-weight: 600; }
QPushButton:hover { background-color: #333741; border-color: #4b4d5b; }
QPushButton:pressed { background-color: #414551; }
QPushButton:disabled { color: #777982; background-color: #1e2026; border-color: #30313a; }
QPushButton#play { background-color: #e56e2b; border: 1px solid #ed8a4d; color: #151313;
                   font-size: 15px; font-weight: 800; padding: 12px 24px; border-radius: 6px; }
QPushButton#play:hover { background-color: #f08748; }
QPushButton#play:disabled { background-color: #6f4737; color: #bca99e; }
QPushButton#link { background: transparent; border: none; color: #b6b8c1; padding: 6px 8px; }
QPushButton#link:hover { color: #ffffff; background-color: #282b32; }
QPushButton#tab { background: transparent; border: none; border-bottom: 2px solid transparent;
                  border-radius: 0; padding: 12px 8px; color: #9699a2; }
QPushButton#tabActive { background: transparent; border: none; border-bottom: 2px solid #ef8544;
                        border-radius: 0; padding: 12px 8px; color: #f1f2f5; }
QLineEdit { background: #111318; border: 1px solid #40434f; padding: 11px;
            border-radius: 6px; font-size: 12px; color: #f2f2f4; }
QLineEdit:focus { border-color: #d18459; }
QPlainTextEdit { background: #111318; color: #dddfe5; border: 1px solid #32343e;
                 border-radius: 6px; padding: 12px; font: 11px 'JetBrains Mono', monospace; }
QCheckBox { color: #d5d5da; spacing: 9px; }
QProgressBar { background: #252830; border: none; border-radius: 2px; max-height: 5px; }
QProgressBar::chunk { background: #e4793b; }
QScrollArea { border: none; background: transparent; }
QTableWidget { background-color: #15171c; color: #e9e9ee; border: 1px solid #30323c;
               gridline-color: #282b34; selection-background-color: #454452;
               selection-color: #ffffff; alternate-background-color: #1d2027; }
QHeaderView::section { background-color: #252831; color: #e1e1e6; border: none;
                       padding: 9px 6px; font-weight: 600; }
QScrollBar:vertical { background: #14151a; width: 8px; }
QScrollBar::handle:vertical { background: #3b3d49; border-radius: 3px; }
"""


def label(content: str, name: str = "", wrap=False) -> QLabel:
    w = QLabel(content)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


def button(content: str, callback, kind: str = "") -> QPushButton:
    w = QPushButton(content)
    if kind:
        w.setObjectName(kind)
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    w.clicked.connect(callback)
    return w


def rule() -> QFrame:
    return QFrame(objectName="divider")


class HomeBackdrop(QWidget):
    """Steam Zombies hero art with cinematic black/orange scrim and offline fallback."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pix = QPixmap()
        self.load(artwork.cached_image("hero"))

    def load(self, path):
        self.pix = QPixmap(str(path)) if path else QPixmap()
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QLinearGradient, QRadialGradient
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        full = self.rect()
        painter.fillRect(full, QColor("#0d1119"))
        if not self.pix.isNull():
            scaled = self.pix.scaled(full.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                     Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(full, scaled, QRect((scaled.width() - full.width()) // 2,
                                                   (scaled.height() - full.height()) // 2,
                                                   full.width(), full.height()))
        fade = QLinearGradient(0, 0, self.width(), self.height())
        fade.setColorAt(0.0, QColor(5, 7, 12, 90))
        fade.setColorAt(0.45, QColor(9, 9, 13, 130))
        fade.setColorAt(1.0, QColor(8, 10, 15, 180))
        painter.fillRect(full, fade)
        glow = QRadialGradient(self.width() * .83, self.height() * .28, self.width() * .7)
        glow.setColorAt(0.0, QColor(204, 83, 27, 42))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(full, glow)
        painter.end()


class Artwork(QWidget):
    """Simple rectangular cover, not an AI-generated illustration or fake painting."""
    def __init__(self, kind="poster", parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setMinimumWidth(210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pix = QPixmap()
        self.load(artwork.cached_image(kind))

    def load(self, filename):
        self.pix = QPixmap(str(filename)) if filename else QPixmap()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        full = QRect(0, 0, self.width(), self.height())
        painter.fillRect(full, QColor("#202127"))
        if not self.pix.isNull():
            # A store header is landscape; letterbox it rather than crop its logo.
            keep = (Qt.AspectRatioMode.KeepAspectRatio if self.pix.width() > self.pix.height() else
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding)
            scaled = self.pix.scaled(full.size(), keep, Qt.TransformationMode.SmoothTransformation)
            if keep == Qt.AspectRatioMode.KeepAspectRatio:
                painter.drawPixmap((full.width() - scaled.width()) // 2,
                                   (full.height() - scaled.height()) // 2, scaled)
            else:
                x = (scaled.width() - full.width()) // 2
                y = (scaled.height() - full.height()) // 2
                painter.drawPixmap(full, scaled, QRect(x, y, full.width(), full.height()))
        else:
            painter.setPen(QColor("#bebfc5"))
            font = painter.font()
            font.setPixelSize(23)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(full, Qt.AlignmentFlag.AlignCenter, "BLACK OPS II\nZOMBIES")
        painter.end()


class Worker(QThread):
    line = Signal(str)
    succeeded = Signal()
    failed = Signal(str)
    def __init__(self, task):
        super().__init__()
        self.task = task
    def run(self):
        try:
            self.task(self.line.emit)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.succeeded.emit()


class ServerWorker(QThread):
    loaded = Signal(list)
    failed = Signal(str)

    def run(self):
        try:
            self.loaded.emit(b.fetch_servers())
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class Launcher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BO2 Launcher")
        self.resize(970, 620)
        self.setMinimumSize(800, 530)
        self.worker = None
        self.server_worker = None
        self.server_rows = []
        self.game_process = None
        self.launch_started_at = None
        self.launch_method = None
        self.seen_game = False
        self.launcher_exit_logged = False
        self.tabs = []
        self.fetcher = artwork.ArtworkFetcher(self)
        self.fetcher.changed.connect(self.art_received)
        icon_file = artwork.cached_image("icon")
        self.setWindowIcon(QIcon(str(icon_file)) if icon_file else QIcon.fromTheme("applications-games"))
        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 10, 24, 18)
        outer.setSpacing(4)
        outer.addWidget(self.topbar())
        outer.addWidget(rule())
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        self.make_home()
        self.make_settings()
        self.make_activity()
        self.make_servers()
        self.goto(0)
        self.refresh()
        # A selected folder must also exist in the provider's independent config.
        # Do this once on startup, not periodically while a client is in use.
        try:
            game = b.find_game()
            if game and b.official_game_launcher_path():
                changed = b.sync_official_game_path(game)
                if changed:
                    self.write_log("Ruta de BO2 sincronizada automáticamente con el cliente oficial.")
        except (OSError, RuntimeError) as exc:
            self.write_log("Ruta oficial pendiente: " + str(exc))
        self.update_path_status()
        QShortcut(QKeySequence("Ctrl+,"), self, activated=lambda: self.goto(1))
        QShortcut(QKeySequence("Escape"), self, activated=lambda: self.goto(0))
        self.fetcher.fetch("poster")
        self.fetcher.fetch("hero")
        self.fetcher.fetch("icon")
        self.game_timer = QTimer(self)
        self.game_timer.setInterval(3500)
        self.game_timer.timeout.connect(self.check_game)
        self.game_timer.start()

    def topbar(self):
        line = QWidget()
        row = QHBoxLayout(line)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(22)
        name = label("BO2 LAUNCHER", "brand")
        row.addWidget(name)
        row.addStretch()
        for idx, text in ((0, "Jugar"), (3, "Servidores"), (1, "Configuración"), (2, "Actividad")):
            tab = button(text, lambda _=False, n=idx: self.goto(n), "tab")
            self.tabs.append((idx, tab))
            row.addWidget(tab)
        return line

    def make_home(self):
        page = HomeBackdrop()
        self.home_background = page
        bg_custom = b.load_config().get("background_image")
        if isinstance(bg_custom, str) and bg_custom and not QPixmap(bg_custom).isNull():
            page.load(bg_custom)
        lay = QVBoxLayout(page)
        lay.setContentsMargins(12, 24, 12, 10)
        lay.setSpacing(15)
        game = QFrame(objectName="gameCard")
        g = QHBoxLayout(game)
        g.setSpacing(0)
        g.setContentsMargins(0, 0, 0, 0)
        self.cover = Artwork("poster")
        self.cover.setMinimumWidth(220)
        self.cover.setMaximumWidth(310)
        g.addWidget(self.cover, 3)
        content = QWidget(objectName="homeContent")
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        c = QVBoxLayout(content)
        c.setContentsMargins(31, 31, 28, 29)
        c.setSpacing(8)
        c.addWidget(label("CALL OF DUTY  /  BLACK OPS II", "heroEyebrow"))
        c.addWidget(label("ZOMBIES", "heroTitle"))
        c.addWidget(label("T6  ·  EDICIÓN PC  ·  NIRI / ARCH", "heroNote"))
        c.addSpacing(12)
        c.addWidget(rule())
        c.addSpacing(8)
        self.game_state = label("Comprobando…", "rowTitle")
        c.addWidget(self.game_state)
        self.game_detail = label("", "hint", True)
        c.addWidget(self.game_detail)
        c.addStretch()
        ctas = QHBoxLayout()
        ctas.setSpacing(10)
        self.play = button("JUGAR", self.play_or_setup, "play")
        self.play.setMinimumWidth(190)
        ctas.addWidget(self.play)
        self.servers_button = button("Abrir servidores", self.open_servers)
        ctas.addWidget(self.servers_button)
        ctas.addStretch()
        c.addLayout(ctas)
        g.addWidget(content, 6)
        lay.addWidget(game, 1)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 3, 0, 0)
        bottom.setSpacing(15)
        bottom.addWidget(button("Archivos del juego", lambda: self.goto(1), "link"))
        bottom.addWidget(button("Componentes", lambda: self.goto(1), "link"))
        bottom.addWidget(button("Cambiar fondo", self.change_background, "link"))
        bottom.addStretch()
        bottom.addWidget(label("BO2 Launcher  ·  0.11", "caption"))
        lay.addLayout(bottom)
        self.pages.addWidget(page)

    def scroll_page(self):
        page = QScrollArea()
        page.setWidgetResizable(True)
        area = QWidget(objectName="page")
        lay = QVBoxLayout(area)
        lay.setContentsMargins(0, 18, 8, 18)
        lay.setSpacing(13)
        page.setWidget(area)
        self.pages.addWidget(page)
        return lay

    def setting_group(self, title, description=None):
        box = QFrame(objectName="setting")
        l = QVBoxLayout(box)
        l.setContentsMargins(19, 17, 19, 19)
        l.setSpacing(10)
        l.addWidget(label(title, "rowTitle"))
        if description:
            l.addWidget(label(description, "hint", True))
        return box, l

    def make_settings(self):
        lay = self.scroll_page()
        lay.addWidget(label("Configuración", "heading"))
        game, g = self.setting_group("Black Ops II", "Selecciona tu carpeta de BO2 Zombies (Steam o pluto_t6_full_game).")
        self.path = QLineEdit()
        self.path.setPlaceholderText("Carpeta de Black Ops II Zombies")
        self.path.returnPressed.connect(self.save_game)
        g.addWidget(self.path)
        buttons = QHBoxLayout()
        buttons.addWidget(button("Buscar carpeta", self.browse))
        buttons.addWidget(button("Steam", lambda: QDesktopServices.openUrl(QUrl("steam://install/212910"))))
        buttons.addStretch()
        buttons.addWidget(button("Guardar ruta", self.save_game))
        g.addLayout(buttons)
        self.path_status = label("Ruta del cliente: pendiente de comprobar", "hint")
        g.addWidget(self.path_status)
        lay.addWidget(game)

        engine, e = self.setting_group("Entorno aislado", "Todos los componentes se guardan en un entorno separado, sin modificar ~/.wine.")
        self.runtime = label("Comprobando componentes…", "hint")
        e.addWidget(self.runtime)
        self.nvidia = QCheckBox("Usar la GPU NVIDIA dedicada (PRIME)")
        self.nvidia.setChecked(bool(b.load_config().get("force_nvidia", False)))
        self.nvidia.toggled.connect(lambda enabled: b.save_config(force_nvidia=enabled))
        e.addWidget(self.nvidia)
        self.hide_console = QCheckBox("Ocultar consola técnica del juego en Niri")
        try:
            self.hide_console.setChecked(ni.is_enabled())
        except OSError:
            pass
        self.hide_console.toggled.connect(self.toggle_console_visibility)
        e.addWidget(self.hide_console)
        e.addWidget(label("La consola seguirá ejecutándose; solo se vuelve invisible en Niri. "
                          "Puedes desactivar esta opción para verla y depurar.", "hint", True))
        user_row = QHBoxLayout()
        user_row.addWidget(label("Nombre de jugador:", "caption"))
        self.player_name = QLineEdit()
        self.player_name.setMaxLength(24)
        self.player_name.setText(str(b.load_config().get("player_name", "Centeno")))
        self.player_name.editingFinished.connect(lambda: b.save_config(player_name=self.player_name.text().strip()))
        user_row.addWidget(self.player_name)
        e.addLayout(user_row)
        self.lan = QCheckBox("Modo LAN / sin conexión (no permite servidores públicos)")
        self.lan.setChecked(bool(b.load_config().get("lan_mode", False)))
        self.lan.toggled.connect(lambda enabled: b.save_config(lan_mode=enabled))
        e.addWidget(self.lan)
        e.addWidget(label("Online: JUGAR utiliza el acceso oficial a Zombies con cuenta autenticada. "
                          "LAN: inicia el motor directamente sin abrir el cliente de sesión. "
                          "La primera autenticación siempre se realiza en el cliente oficial.", "hint", True))
        row = QHBoxLayout()
        self.setup_button = button("Instalar componentes", lambda: self.run_task(b.run_setup), "play")
        self.deps_button = button("Librerías Windows", lambda: self.run_task(b.install_windows_deps))
        row.addWidget(self.setup_button)
        row.addWidget(self.deps_button)
        row.addStretch()
        e.addLayout(row)
        service_actions = QHBoxLayout()
        service_actions.addWidget(button("Actualizar componentes", self.update_plutonium))
        service_actions.addWidget(button("Comprobar conexión", lambda: self.run_task(b.check_connections)))
        service_actions.addStretch()
        e.addLayout(service_actions)
        self.advanced_button = button("▸ Opciones avanzadas / cuenta online", self.toggle_advanced, "link")
        e.addWidget(self.advanced_button)
        self.advanced_panel, ap = self.setting_group(
            "Sesión oficial y recuperación",
            "El cliente que inicia el juego es de Plutonium Project, un tercero. "
            "Para jugar online puede ser necesaria su autenticación oficial. "
            "Por seguridad, BO2 Launcher no solicita ni guarda contraseñas."
        )
        ap.addWidget(button("Abrir sesión oficial (ventana externa)", self.init_plutonium))
        ap.addWidget(button("Reparar error 401 (respaldar sesión anterior)", self.repair_session))
        ap.addWidget(label("Si la sesión guardada dejó de ser válida, puedes apartar config.json "
                           "con respaldo y volver a iniciar sesión de forma oficial. "
                           "Cierra las ventanas del cliente antes de reparar.", "hint", True))
        ap.addWidget(label("El acceso oficial requiere una ventana visible. "
                           "BO2 Launcher nunca solicita ni almacena tus contraseñas.", "hint", True))
        self.advanced_panel.setVisible(False)
        e.addWidget(self.advanced_panel)
        lay.addWidget(engine)

        art, a = self.setting_group("Arte del juego", "Se utiliza arte oficial descargado desde Steam o una imagen local elegida por ti.")
        art_buttons = QHBoxLayout()
        art_buttons.addWidget(button("Elegir imagen", self.change_art))
        art_buttons.addWidget(button("Restaurar arte oficial", self.reset_art))
        art_buttons.addWidget(button("SteamGridDB", lambda: QDesktopServices.openUrl(QUrl("https://www.steamgriddb.com/game/2077"))))
        art_buttons.addStretch()
        a.addLayout(art_buttons)
        a.addWidget(label("Fondo cinematográfico", "rowTitle"))
        bg_buttons = QHBoxLayout()
        bg_buttons.addWidget(button("Elegir fondo", self.change_background))
        bg_buttons.addWidget(button("Restaurar fondo de BO2", self.reset_background))
        bg_buttons.addStretch()
        a.addLayout(bg_buttons)
        lay.addWidget(art)
        lay.addStretch()

    def make_activity(self):
        lay = self.scroll_page()
        lay.addWidget(label("Actividad", "heading"))
        logframe, l = self.setting_group("Registro de operaciones")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(250)
        l.addWidget(self.log)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        l.addWidget(self.progress)
        lay.addWidget(logframe)
        row = QHBoxLayout()
        row.addWidget(button("Abrir carpeta de registros", lambda: self.open_folder(b.STATE)))
        row.addWidget(button("Volver", lambda: self.goto(0)))
        row.addStretch()
        lay.addLayout(row)
        lay.addStretch()

    def make_servers(self):
        lay = self.scroll_page()
        lay.addWidget(label("Servidores · BO2 Zombies", "heading"))
        lay.addWidget(label("Listado externo proporcionado por GameServe.rs (no oficial de Plutonium).", "caption"))
        bar = QHBoxLayout()
        self.server_filter = QLineEdit()
        self.server_filter.setPlaceholderText("Buscar nombre o mapa...")
        self.server_filter.textChanged.connect(self.filter_servers)
        bar.addWidget(self.server_filter, 1)
        self.server_refresh = button("Actualizar lista", self.refresh_servers)
        bar.addWidget(self.server_refresh)
        lay.addLayout(bar)
        self.server_table = QTableWidget(0, 4)
        self.server_table.setHorizontalHeaderLabels(("Servidor", "Mapa", "Jugadores", "Dirección"))
        self.server_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.server_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.server_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.server_table.verticalHeader().hide()
        self.server_table.horizontalHeader().setStretchLastSection(True)
        self.server_table.setColumnWidth(0, 295)
        self.server_table.setColumnWidth(1, 145)
        self.server_table.setColumnWidth(2, 85)
        self.server_table.doubleClicked.connect(lambda _index: self.join_server())
        lay.addWidget(self.server_table, 1)
        self.server_status = label("Pulsa Actualizar lista para consultar servidores.", "hint", True)
        lay.addWidget(self.server_status)
        actions = QHBoxLayout()
        actions.addWidget(button("Jugar en servidor seleccionado", self.join_server, "play"))
        actions.addWidget(button("Copiar connect IP:puerto", self.copy_server))
        actions.addStretch()
        lay.addLayout(actions)
        lay.addWidget(label("Si la conexión automática no funciona: entra al juego, abre la consola y escribe 'connect IP:puerto'.", "hint", True))

    def refresh_servers(self):
        if self.server_worker and self.server_worker.isRunning():
            return
        self.server_status.setText("Consultando servidores de BO2 Zombies...")
        self.server_refresh.setEnabled(False)
        self.server_worker = ServerWorker(self)
        self.server_worker.loaded.connect(self.show_servers)
        self.server_worker.failed.connect(self.server_error)
        self.server_worker.finished.connect(lambda: self.server_refresh.setEnabled(True))
        self.server_worker.start()

    def show_servers(self, rows):
        self.server_rows = rows
        self.filter_servers()
        self.server_status.setText(f"{len(rows)} servidores recibidos · Datos de GameServe.rs; no garantizan disponibilidad.")

    def server_error(self, message):
        self.server_status.setText("No se pudo consultar la lista. Comprueba Internet o usa el navegador dentro del juego.")
        self.write_log("Error consultando servidores: " + message)

    def filter_servers(self, _text=None):
        phrase = self.server_filter.text().casefold().strip()
        filtered = [r for r in self.server_rows if phrase in (r["name"] + " " + r["map"]).casefold()]
        self.server_table.setRowCount(len(filtered))
        self.server_table.setAlternatingRowColors(True)
        for i, row in enumerate(filtered):
            for j, key in enumerate(("name", "map", "players", "address")):
                self.server_table.setItem(i, j, QTableWidgetItem(row[key] or "—"))

    def selected_server(self):
        index = self.server_table.currentRow()
        if index < 0 or not self.server_table.item(index, 3):
            QMessageBox.information(self, "Servidores", "Selecciona primero un servidor de la tabla.")
            return None
        value = self.server_table.item(index, 3).text()
        try:
            return b.validate_server_address(value)
        except ValueError:
            QMessageBox.warning(self, "Servidor no disponible", "Este servidor no tiene una IP:puerto válida para conectar.")
            return None

    def copy_server(self):
        address = self.selected_server()
        if address:
            QApplication.clipboard().setText("connect " + address)
            self.server_status.setText("Comando copiado. Puedes pegarlo en la consola de BO2.")

    def join_server(self):
        address = self.selected_server()
        if not address:
            return
        if self.lan.isChecked():
            QMessageBox.information(self, "Modo LAN", "Desactiva el modo LAN en Configuración para acceder a servidores públicos.")
            return
        self.start_game(server=address)

    def toggle_console_visibility(self, enabled):
        try:
            ni.set_enabled(enabled)
            self.write_log("Consola técnica en Niri: " + ("oculta" if enabled else "visible") +
                           ". La ventana seguirá ejecutándose.")
        except Exception as exc:
            self.hide_console.blockSignals(True)
            self.hide_console.setChecked(not enabled)
            self.hide_console.blockSignals(False)
            QMessageBox.warning(self, "Integración con Niri", str(exc))

    def toggle_advanced(self):
        show = not self.advanced_panel.isVisible()
        self.advanced_panel.setVisible(show)
        self.advanced_button.setText(("▾" if show else "▸") + " Opciones avanzadas / cuenta online")

    def init_plutonium(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Operación en curso", "Termina primero la operación actual.")
            return
        if b.game_process_alive() or (self.game_process and self.game_process.poll() is None):
            QMessageBox.information(self, "BO2", "Cierra el proceso de inicio antes de gestionar la cuenta online.")
            return
        try:
            proc = b.launch_plutonium()
            self.write_log(f"Cliente oficial abierto para gestionar la cuenta (PID {proc.pid}).")
            self.game_detail.setText("Completa la autenticación oficial. Después vuelve a este launcher para jugar.")
        except Exception as exc:
            QMessageBox.warning(self, "Sesión online", str(exc))

    def repair_session(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Operación en curso", "Finaliza la operación actual primero.")
            return
        if (self.game_process and self.game_process.poll() is None) or b.game_process_alive():
            QMessageBox.information(self, "Juego abierto", "Cierra BO2 y sus ventanas antes de reparar la sesión.")
            return
        question = ("El error HTTP 401 puede indicar una sesión caducada.\n\n"
                    "Esta reparación RENOMBRA únicamente el config.json de la cuenta "
                    "en el prefijo privado, conserva un respaldo y abre la sesión oficial "
                    "para que puedas entrar de nuevo.\n\n"
                    "Cierra primero cualquier ventana del cliente original. "
                    "¿Quieres continuar?")
        confirm = QMessageBox.question(self, "Recuperar sesión online", question,
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            backups = b.backup_online_session()
            if backups:
                self.write_log(f"Sesión anterior apartada con respaldo ({len(backups)} archivo(s)).")
            else:
                self.write_log("No se encontró config.json de la cuenta. Se abrirá igualmente el inicio de sesión oficial.")
            proc = b.launch_plutonium()
            self.write_log(f"Inicio de sesión oficial abierto (PID {proc.pid}).")
            self.game_detail.setText("Completa el inicio de sesión oficial y vuelve a JUGAR.")
        except Exception as exc:
            QMessageBox.warning(self, "Recuperación de sesión", str(exc))

    def update_plutonium(self):
        if self.game_process and self.game_process.poll() is None:
            QMessageBox.information(self, "Actualizar", "Cierra BO2 antes de actualizar los componentes.")
            return
        self.run_task(b.update_engine)

    def start_game(self, server=None):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Preparación en curso", "Deja que termine la instalación o actualización antes de iniciar BO2.")
            return
        if b.game_session_visible() or (self.game_process and self.game_process.poll() is None):
            QMessageBox.information(self, "BO2", "Ya hay una sesión de juego o inicio activo.")
            return
        try:
            self.launch_started_at = time.monotonic()
            self.seen_game = False
            self.launcher_exit_logged = False
            if self.lan.isChecked():
                self.game_process = b.launch_game(lan=True, player_name=self.player_name.text().strip())
                self.launch_method = "lan"
            else:
                self.game_process, self.launch_method = b.launch_online_game()
                self.update_path_status()
            self.write_log(f"Inicio ({self.launch_method}) PID {self.game_process.pid}."
                           + (f" Servidor elegido: {server}" if server else ""))
            if self.launch_method == "setup":
                self.game_state.setText("Preparar cuenta online")
                self.game_detail.setText("El cliente oficial está abierto para iniciar sesión. "
                                         "Nuestro launcher sincroniza la ruta de BO2 al tener el cliente instalado.")
                self.play.setText("CONFIGURANDO CUENTA")
            elif self.launch_method == "uri":
                self.game_state.setText("Iniciando desde tu cuenta oficial...")
                self.game_detail.setText("Se ha solicitado BO2 Zombies mediante la URI oficial. "
                                         "Si aparece la pantalla de sesión, autentícate allí.")
                self.play.setText("ABRIENDO ZOMBIES...")
            else:
                self.game_state.setText("Iniciando Zombies (LAN)...")
                self.game_detail.setText("Inicio local sin servidores públicos.")
                self.play.setText("INICIANDO...")
            self.play.setEnabled(False)
            if server:
                QApplication.clipboard().setText("connect " + server)
                self.write_log("URI oficial abre T6ZM; copia el comando connect desde el portapapeles y "
                               "pégalo en la consola del juego cuando inicie.")
            QTimer.singleShot(2400, self.check_game)
        except Exception as exc:
            self.write_log("No se pudo iniciar BO2: " + str(exc))
            QMessageBox.warning(self, "No se pudo iniciar BO2", str(exc))

    def check_game(self):
        # Online: the provider's launcher starts a DETACHED Windows child and exits.
        # Its successful exit is NOT a game failure. Detect Wine T6 or console instead.
        actual_game = b.game_session_visible()
        if actual_game:
            self.seen_game = True
            self.game_state.setText("ZOMBIES  ·  EN PARTIDA")
            self.game_detail.setText("El motor de BO2 está abierto. ¡Disfruta la partida!")
            self.play.setText("●  JUGANDO")
            self.play.setEnabled(False)
            return
        if self.seen_game:
            # User closed BO2: restore the normal JUGAR state, not REINTENTAR.
            self.game_process = None
            self.launch_started_at = None
            self.launch_method = None
            self.seen_game = False
            self.refresh()
            self.game_state.setText("Partida finalizada")
            self.game_detail.setText("El juego se cerró normalmente. Puedes volver a jugar.")
            self.play.setText("▶  JUGAR")
            self.play.setEnabled(True)
            return
        if self.game_process is None:
            return
        code = self.game_process.poll()
        elapsed = time.monotonic() - (self.launch_started_at or time.monotonic())
        # The URI launcher can exit immediately after handing T6 to the bootstrapper.
        # Give Wine enough time to start the child even when the initial PID exits.
        if self.launch_method == "uri" and elapsed < 70:
            self.game_state.setText("Iniciando Zombies...")
            self.game_detail.setText("El cliente oficial entregó el inicio al motor T6. "
                                     "Esperando que aparezca su proceso o consola.")
            self.play.setText("INICIANDO...")
            self.play.setEnabled(False)
            if code is not None and not self.launcher_exit_logged:
                self.launcher_exit_logged = True
                self.write_log(f"Cliente online terminó código {code}; esperando motor independiente.")
            return
        if code is None and self.launch_method == "setup":
            self.game_state.setText("Configura la cuenta online")
            self.game_detail.setText("Termina el inicio de sesión en la ventana oficial.")
            self.play.setText("CONFIGURANDO CUENTA")
            self.play.setEnabled(False)
            return
        if code is None and elapsed < 70:
            self.game_state.setText("Iniciando Zombies...")
            self.game_detail.setText("Esperando al motor T6...")
            self.play.setText("INICIANDO...")
            self.play.setEnabled(False)
            return
        if code is None:
            self.game_state.setText("Arranque sin confirmar")
            self.game_detail.setText("Wine sigue abierto. Comprueba si BO2 está abierto y revisa Actividad.")
            self.play.setText("ESPERANDO JUEGO")
            self.play.setEnabled(False)
            return
        self.write_log(f"No se detectó el motor tras iniciar el cliente ({code}). Registros en Actividad.")
        self.game_process = None
        self.launch_started_at = None
        self.launch_method = None
        self.refresh()
        self.game_state.setText("No se confirmó el arranque")
        self.game_detail.setText("Puedes intentar nuevamente o revisar el registro.")
        self.play.setText("▶  JUGAR")
        self.play.setEnabled(True)

    def goto(self, idx: int):
        self.pages.setCurrentIndex(idx)
        for page_idx, w in self.tabs:
            w.setObjectName("tabActive" if page_idx == idx else "tab")
            w.style().unpolish(w)
            w.style().polish(w)
        if idx == 1:
            self.refresh()
        if idx == 3 and not self.server_rows:
            self.refresh_servers()

    def art_received(self, kind: str, path: str):
        if kind == "hero" and not b.load_config().get("background_image"):
            self.home_background.load(path)
        elif kind == "poster" and not b.load_config().get("cover_image"):
            self.cover.load(path)
        elif kind == "icon":
            self.setWindowIcon(QIcon(path))
            self.install_desktop_icon(path)

    def install_desktop_icon(self, path):
        # Use the game's real Steam icon, never an AI-made app logo.
        try:
            pix = QPixmap(path)
            if pix.isNull():
                return
            folder = Path.home() / ".local/share/icons/hicolor/256x256/apps"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / "bo2-launcher.png"
            pix.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation).save(str(target), "PNG")
            desktop = Path.home() / ".local/share/applications/bo2-launcher.desktop"
            if desktop.is_file():
                raw = desktop.read_text(encoding="utf-8")
                if "Name=BO2 Launcher" in raw and "Icon=applications-games" in raw:
                    desktop.write_text(raw.replace("Icon=applications-games", "Icon=bo2-launcher"),
                                       encoding="utf-8")
        except OSError:
            return

    def refresh(self):
        game = b.find_game()
        wine = bool(b.wine_path())
        prefix = (b.PREFIX / "system.reg").is_file()
        plutonium = b.PLUTONIUM.is_file()
        dxvk = (b.CONFIG / f"dxvk-{b.DXVK_VER}.installed").is_file()
        bootstrapper = b.bootstrapper_path()
        prepared = bool(game and wine and prefix and plutonium and dxvk)
        ready = bool(prepared and bootstrapper)
        busy = self.worker is not None and self.worker.isRunning()
        playing = b.game_session_visible()
        pending = bool(self.game_process and (self.game_process.poll() is None or
                       (self.launch_method == "uri" and self.launch_started_at is not None and
                        time.monotonic() - self.launch_started_at < 70)))
        self.play.setEnabled(not busy and not playing and not pending)
        self.setup_button.setEnabled(not busy)
        self.deps_button.setEnabled(not busy)
        if ready:
            self.game_state.setText("Listo para jugar")
            self.game_detail.setText("Inicia Zombies directamente desde esta aplicación.")
            self.play.setText("▶  JUGAR")
        elif prepared and not bootstrapper:
            self.game_state.setText("Falta preparar el motor de juego")
            self.game_detail.setText("Actualiza los componentes en Configuración. "
                                     "Para jugar online, la cuenta también debe estar autenticada.")
            self.play.setText("PREPARAR JUEGO")
        elif not game:
            self.game_state.setText("Faltan archivos del juego")
            self.game_detail.setText("Selecciona tu carpeta de Black Ops II en Configuración.")
            self.play.setText("CONFIGURAR")
        else:
            self.game_state.setText("Instalación pendiente")
            self.game_detail.setText("Prepara Wine y los componentes desde Configuración.")
            self.play.setText("CONFIGURAR")
        self.runtime.setText("Componentes listos" if (wine and prefix and plutonium and dxvk) else
                             "Pendientes: " + ", ".join(n for n, ok in (("Wine", wine), ("prefijo", prefix), ("DXVK", dxvk), ("cliente de juego", plutonium)) if not ok))
        if playing:
            self.game_state.setText("BO2 Zombies detectado")
            self.play.setText("JUEGO DETECTADO")
        elif pending:
            self.game_state.setText("Inicio solicitado (sin confirmar)")
            self.play.setText("INICIANDO...")
        if game and not self.path.isModified():
            self.path.setText(str(game))
        return ready

    def browse(self):
        directory = QFileDialog.getExistingDirectory(self, "Carpeta del juego", self.path.text() or str(Path.home()))
        if directory:
            self.path.setText(directory)
            self.save_game()

    def save_game(self):
        raw = self.path.text().strip()
        path = Path(raw).expanduser() if raw else None
        if not path or not b.is_game_dir(path):
            QMessageBox.warning(self, "Carpeta incorrecta", "Selecciona la carpeta que contiene zone/ y los datos de BO2 Zombies.")
            return
        b.save_config(game_dir=str(path.resolve()))
        self.path.setModified(False)
        self.write_log("Carpeta del juego guardada: " + str(path))
        try:
            if b.official_game_launcher_path():
                changed = b.sync_official_game_path(path)
                self.write_log("Ruta oficial de BO2 " + ("sincronizada." if changed else "ya estaba sincronizada."))
            else:
                self.write_log("La carpeta quedó guardada; se sincronizará cuando esté instalado el cliente online.")
        except (OSError, RuntimeError) as exc:
            self.write_log("No se pudo sincronizar la carpeta con el cliente: " + str(exc))
            QMessageBox.warning(self, "Ruta online pendiente", str(exc))
        self.refresh()
        self.update_path_status()

    def update_path_status(self):
        game = b.find_game()
        if game is None:
            self.path_status.setText("Ruta de BO2: falta seleccionar carpeta válida")
            return
        try:
            state = b.official_game_path_status(game)
        except (OSError, RuntimeError) as exc:
            self.path_status.setText("No se pudo comprobar la ruta online: " + str(exc))
            return
        messages = {
            "sincronizado": "✓ Carpeta de BO2 sincronizada con el cliente online",
            "pendiente-ruta": "La carpeta online se sincronizará al pulsar JUGAR",
            "pendiente-cliente": "Carpeta guardada. El cliente online aún no está instalado",
            "configuracion-insegura": "La configuración oficial requiere revisión manual",
            "configuracion-invalida": "No se pudo leer la configuración oficial; comprueba Actividad",
        }
        self.path_status.setText(messages.get(state, "Ruta de BO2 por comprobar"))

    def change_background(self):
        path, _ = QFileDialog.getOpenFileName(self, "Elegir fondo del launcher", str(Path.home()), "Imágenes (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        if QPixmap(path).isNull():
            QMessageBox.warning(self, "Imagen no válida", "No se pudo abrir ese fondo.")
            return
        b.save_config(background_image=path)
        self.home_background.load(path)

    def reset_background(self):
        b.save_config(background_image="")
        self.home_background.load(artwork.cached_image("hero"))
        if artwork.cached_image("hero") is None:
            self.fetcher.fetch("hero")

    def change_art(self):
        path, _ = QFileDialog.getOpenFileName(self, "Elegir imagen del juego", str(Path.home()), "Imágenes (*.png *.jpg *.jpeg *.webp)")
        if path:
            p = QPixmap(path)
            if p.isNull():
                QMessageBox.warning(self, "Imagen no válida", "No se puede abrir este archivo.")
                return
            b.save_config(cover_image=path)
            self.cover.load(path)

    def reset_art(self):
        b.save_config(cover_image="")
        self.cover.load(artwork.cached_image("poster"))
        if artwork.cached_image("poster") is None:
            self.fetcher.fetch("poster")

    def write_log(self, content: str):
        self.log.appendPlainText(content)
        try:
            b.ensure_dirs()
            with (b.STATE / "launcher.log").open("a", encoding="utf-8") as handle:
                handle.write(content + "\n")
        except OSError:
            pass

    def run_task(self, fn):
        if self.worker and self.worker.isRunning():
            return
        if b.game_process_alive() or (self.game_process and self.game_process.poll() is None):
            QMessageBox.information(self, "Proceso activo", "Cierra el juego o el proceso de inicio antes de modificar componentes.")
            return
        self.goto(2)
        self.write_log("\n--- Nueva operación ---")
        self.worker = Worker(fn)
        self.worker.line.connect(self.write_log)
        self.worker.succeeded.connect(lambda: self.complete_task(None))
        self.worker.failed.connect(self.complete_task)
        self.progress.setRange(0, 0)
        self.setup_button.setEnabled(False)
        self.deps_button.setEnabled(False)
        self.play.setEnabled(False)
        self.worker.start()

    def complete_task(self, error):
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if not error else 0)
        if error:
            self.write_log("ERROR: " + error)
            QMessageBox.warning(self, "Error de instalación", error)
        else:
            self.write_log("Proceso terminado")
        self.refresh()

    def play_or_setup(self):
        if self.worker and self.worker.isRunning():
            return
        if not self.refresh():
            self.goto(1)
            if b.find_game() and b.PLUTONIUM.is_file() and b.wine_path() and (b.PREFIX / "system.reg").is_file() and not b.bootstrapper_path():
                self.write_log("Falta el ejecutable de inicio. Usa 'Actualizar componentes'. "
                               "Si necesitas iniciar sesión, abre Opciones avanzadas.")
            return
        self.start_game()

    def open_servers(self):
        self.goto(3)

    def closeEvent(self, event):
        # El acceso HTTPS es acotado (15 s). Evitar destruir un QThread vivo.
        if self.server_worker and self.server_worker.isRunning():
            self.server_worker.wait(16000)
        super().closeEvent(event)

    def open_folder(self, path):
        b.ensure_dirs()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("BO2 Launcher")
    app.setDesktopFileName("bo2-launcher")
    app.setStyle("Fusion")
    app.setStyleSheet(CSS)
    win = Launcher()
    custom = b.load_config().get("cover_image")
    if custom and QPixmap(custom).isNull() is False:
        win.cover.load(custom)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
