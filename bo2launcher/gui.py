"""Relay: a desktop-native home for BO2 Zombies on Linux and Windows."""
from __future__ import annotations
import sys
import time
import os
from pathlib import Path
# Reduce ruido de Qt en Niri sin silenciar avisos de Wine, Vulkan ni del proveedor.
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.wayland.textinput=false")
from PySide6.QtCore import Qt, QRect, QRectF, QSize, QThread, Signal, QUrl, QTimer
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap, QKeySequence, QShortcut, QPalette, QPen, QPainterPath, QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
    QTableWidget, QTableWidgetItem, QAbstractItemView,
)
from . import backend as b
from . import artwork
from . import APP_NAME, __version__, GAME_FILES_URL
from .theme import ThemeManager

ICON = Path(__file__).parent / "assets/relay.svg"
from . import niri_integration as ni



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
    """A quiet signal motif offline; user or Steam artwork when available."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pix = QPixmap()
        self.setMinimumHeight(220)
        self.load(artwork.cached_image("hero"))

    def load(self, path):
        self.pix = QPixmap(str(path)) if path else QPixmap()
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QLinearGradient
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        full = self.rect()
        palette = self.palette()
        base = palette.color(QPalette.ColorRole.Window)
        accent = palette.color(QPalette.ColorRole.Highlight)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(full), 14, 14)
        painter.setClipPath(clip)
        painter.fillRect(full, base)
        if not self.pix.isNull():
            scaled = self.pix.scaled(full.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                    Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(full, scaled, QRect((scaled.width() - full.width()) // 2,
                               (scaled.height() - full.height()) // 2, full.width(), full.height()))
            fade = QLinearGradient(0, 0, self.width(), 0)
            fade.setColorAt(0, base)
            fade.setColorAt(.49, QColor(base.red(), base.green(), base.blue(), 247))
            fade.setColorAt(1, QColor(base.red(), base.green(), base.blue(), 55))
            painter.fillRect(full, fade)
        else:
            # A relay signal, deliberately asymmetrical; no dependence on game art.
            cx, cy = self.width() * .84, self.height() * .48
            for index, radius in enumerate((58, 102, 146, 190, 234)):
                tone = QColor(accent)
                tone.setAlpha(90 - index * 15)
                painter.setPen(QPen(tone, 1.5))
                painter.drawArc(QRectF(cx-radius, cy-radius, radius*2, radius*2), 35*16, 285*16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawEllipse(QRectF(cx-6, cy-6, 12, 12))
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
        painter.fillRect(full, self.palette().color(QPalette.ColorRole.Base))
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
            painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
            font = painter.font()
            font.setPixelSize(23)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(full, Qt.AlignmentFlag.AlignCenter, "Black Ops II\nZombies")
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
    def __init__(self, theme=None):
        super().__init__()
        self.theme = theme or ThemeManager(QApplication.instance(), b.load_config().get("theme", "system"))
        self.setWindowTitle("Relay — BO2 Zombies")
        self.resize(1020, 700)
        self.setMinimumSize(760, 560)
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
        self.setWindowIcon(QIcon(str(ICON)))
        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(26, 14, 26, 16)
        outer.setSpacing(12)
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
        self.theme.changed.connect(self.update)
        self.game_timer = QTimer(self)
        self.game_timer.setInterval(3500)
        self.game_timer.timeout.connect(self.check_game)
        self.game_timer.start()

    def topbar(self):
        line = QWidget()
        row = QHBoxLayout(line)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(7)
        mark = QLabel()
        mark.setPixmap(QIcon(str(ICON)).pixmap(34, 34))
        mark.setAccessibleName("Relay")
        row.addWidget(mark)
        row.addSpacing(4)
        row.addWidget(label("Relay", "brand"))
        row.addStretch()
        for idx, text in ((0, "Jugar"), (3, "Servidores"), (1, "Configuración"), (2, "Actividad")):
            tab = button(text, lambda _=False, n=idx: self.goto(n), "tab")
            self.tabs.append((idx, tab))
            row.addWidget(tab)
        return line

    def make_home(self):
        page = QWidget(objectName="page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(18)
        hero = HomeBackdrop()
        self.home_background = hero
        bg_custom = b.load_config().get("background_image")
        if isinstance(bg_custom, str) and bg_custom and not QPixmap(bg_custom).isNull():
            hero.load(bg_custom)
        content = QVBoxLayout(hero)
        content.setContentsMargins(26, 24, 26, 24)
        content.setSpacing(2)
        content.addStretch()
        content.addWidget(label("Black Ops II", "gameSubtitle"))
        content.addWidget(label("Zombies", "heroTitle"))
        content.addSpacing(10)
        content.addWidget(label("Tu próxima ronda empieza aquí.", "heroNote"))
        content.addStretch()
        lay.addWidget(hero, 1)

        status = QFrame(objectName="homeStatus")
        row = QHBoxLayout(status)
        row.setContentsMargins(22, 22, 22, 22)
        row.setSpacing(22)
        text = QVBoxLayout()
        text.setSpacing(7)
        self.game_state = label("Comprobando…", "rowTitle", True)
        self.game_detail = label("", "hint", True)
        text.addWidget(self.game_state)
        text.addWidget(self.game_detail)
        row.addLayout(text, 1)
        self.play = button("Jugar", self.play_or_setup, "play")
        self.play.setMinimumWidth(180)
        row.addWidget(self.play)
        lay.addWidget(status)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(button("Carpeta del juego", self.browse))
        self.drive_button = button("Archivos en Drive", self.open_game_files)
        self.drive_button.setToolTip("Abrir la carpeta compartida del juego en tu navegador")
        actions.addWidget(self.drive_button)
        actions.addStretch()
        actions.addWidget(button("Cambiar fondo", self.change_background, "link"))
        lay.addLayout(actions)
        footer = QHBoxLayout()
        footer.addWidget(label("Hecho para tu escritorio.", "caption"))
        footer.addStretch()
        footer.addWidget(label(("Windows" if b.IS_WINDOWS else "Linux") + "  /  " + __version__, "caption"))
        lay.addLayout(footer)
        self.pages.addWidget(page)

    def open_game_files(self):
        QDesktopServices.openUrl(QUrl(GAME_FILES_URL))

    def change_theme(self):
        mode = self.theme_select.currentData()
        b.save_config(theme=mode)
        self.theme.apply(mode)
        self.home_background.update()

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
        appearance, appearance_layout = self.setting_group("A tu manera", "Relay puede seguir los colores de tu escritorio.")
        theme_row = QHBoxLayout()
        theme_label = label("Apariencia", "rowTitle")
        theme_row.addWidget(theme_label)
        theme_row.addStretch()
        self.theme_select = QComboBox()
        for title, value in (("Sistema", "system"), ("Claro", "light"), ("Oscuro", "dark")):
            self.theme_select.addItem(title, value)
        self.theme_select.setCurrentIndex(max(0, self.theme_select.findData(self.theme.mode)))
        self.theme_select.setAccessibleName("Apariencia")
        theme_label.setBuddy(self.theme_select)
        self.theme_select.setMinimumWidth(180)
        self.theme_select.currentIndexChanged.connect(self.change_theme)
        theme_row.addWidget(self.theme_select)
        appearance_layout.addLayout(theme_row)
        lay.addWidget(appearance)
        game, g = self.setting_group("Black Ops II", "Selecciona tu carpeta de BO2 Zombies (Steam o pluto_t6_full_game).")
        self.path = QLineEdit()
        self.path.setPlaceholderText("Carpeta de Black Ops II Zombies")
        self.path.returnPressed.connect(self.save_game)
        g.addWidget(self.path)
        buttons = QHBoxLayout()
        buttons.addWidget(button("Buscar carpeta", self.browse))
        buttons.addWidget(button("Archivos en Drive", self.open_game_files))
        buttons.addWidget(button("Steam", lambda: QDesktopServices.openUrl(QUrl("steam://install/212910"))))
        buttons.addStretch()
        buttons.addWidget(button("Guardar ruta", self.save_game))
        g.addLayout(buttons)
        self.path_status = label("Ruta del cliente: pendiente de comprobar", "hint")
        g.addWidget(self.path_status)
        lay.addWidget(game)

        engine, e = self.setting_group("Componentes del juego", "Plutonium se ejecuta directamente en Windows." if b.IS_WINDOWS else "Wine y DXVK tienen su propio entorno. Tu configuración actual se conserva.")
        self.runtime = label("Comprobando componentes…", "hint")
        e.addWidget(self.runtime)
        self.nvidia = QCheckBox("Usar la GPU NVIDIA dedicada (PRIME)")
        self.nvidia.setChecked(bool(b.load_config().get("force_nvidia", False)))
        self.nvidia.toggled.connect(lambda enabled: b.save_config(force_nvidia=enabled))
        e.addWidget(self.nvidia)
        self.nvidia.setVisible(not b.IS_WINDOWS)
        self.hide_console = QCheckBox("Ocultar consola técnica del juego en Niri")
        try:
            self.hide_console.setChecked(ni.is_enabled())
        except OSError:
            pass
        self.hide_console.toggled.connect(self.toggle_console_visibility)
        e.addWidget(self.hide_console)
        self.hide_console.setVisible(not b.IS_WINDOWS and bool(os.environ.get("NIRI_SOCKET")))
        user_row = QHBoxLayout()
        user_row.addWidget(label("Nombre de jugador:", "caption"))
        self.player_name = QLineEdit()
        self.player_name.setMaxLength(24)
        self.player_name.setText(str(b.load_config().get("player_name", "Player")))
        self.player_name.editingFinished.connect(lambda: b.save_config(player_name=self.player_name.text().strip()))
        user_row.addWidget(self.player_name)
        e.addLayout(user_row)
        self.lan = QCheckBox("Modo LAN / sin conexión (no permite servidores públicos)")
        self.lan.setChecked(bool(b.load_config().get("lan_mode", False)))
        self.lan.toggled.connect(lambda enabled: b.save_config(lan_mode=enabled))
        e.addWidget(self.lan)
        e.addWidget(label("Online: Jugar utiliza el acceso oficial a Zombies con cuenta autenticada. "
                          "LAN: inicia el motor directamente sin abrir el cliente de sesión. "
                          "La primera autenticación siempre se realiza en el cliente oficial.", "hint", True))
        row = QHBoxLayout()
        self.setup_button = button("Instalar componentes", lambda: self.run_task(b.run_setup), "play")
        self.deps_button = button("Librerías Windows", lambda: self.run_task(b.install_windows_deps))
        row.addWidget(self.setup_button)
        row.addWidget(self.deps_button)
        self.deps_button.setVisible(not b.IS_WINDOWS)
        if b.IS_WINDOWS:
            row.addWidget(button("Requisitos de Windows", lambda: QDesktopServices.openUrl(QUrl("https://plutonium.pw/docs/system-requirements/"))))
        row.addStretch()
        e.addLayout(row)
        service_actions = QHBoxLayout()
        service_actions.addWidget(button("Actualizar componentes", self.update_plutonium))
        service_actions.addWidget(button("Comprobar conexión", lambda: self.run_task(b.check_connections)))
        service_actions.addStretch()
        e.addLayout(service_actions)
        self.advanced_button = button("▸ Cuenta de Plutonium", self.toggle_advanced, "link")
        e.addWidget(self.advanced_button)
        self.advanced_panel, ap = self.setting_group(
            "Cuenta de Plutonium",
            "El cliente que inicia el juego es de Plutonium Project, un tercero. "
            "Para jugar online puede ser necesaria su autenticación oficial. "
            "Relay no solicita ni guarda contraseñas."
        )
        ap.addWidget(button("Abrir sesión oficial (ventana externa)", self.init_plutonium))
        ap.addWidget(button("Reparar error 401 (respaldar sesión anterior)", self.repair_session))
        ap.addWidget(label("Si la sesión guardada dejó de ser válida, puedes apartar config.json "
                           "con respaldo y volver a iniciar sesión de forma oficial. "
                           "Cierra las ventanas del cliente antes de reparar.", "hint", True))
        ap.addWidget(label("El acceso oficial requiere una ventana visible. "
                           "Relay nunca solicita ni almacena tus contraseñas.", "hint", True))
        self.advanced_panel.setVisible(False)
        e.addWidget(self.advanced_panel)
        lay.addWidget(engine)

        art, a = self.setting_group("Arte del juego", "Se utiliza arte oficial descargado desde Steam o una imagen local elegida por ti.")
        self.cover = Artwork("poster")
        self.cover.setFixedSize(140, 180)
        self.cover.setMinimumWidth(140)
        custom = b.load_config().get("cover_image")
        if isinstance(custom, str) and custom:
            self.cover.load(custom)
        a.addWidget(self.cover)
        art_buttons = QHBoxLayout()
        art_buttons.addWidget(button("Elegir imagen", self.change_art))
        art_buttons.addWidget(button("Restaurar arte oficial", self.reset_art))
        art_buttons.addWidget(button("SteamGridDB", lambda: QDesktopServices.openUrl(QUrl("https://www.steamgriddb.com/game/2077"))))
        art_buttons.addStretch()
        a.addLayout(art_buttons)
        a.addWidget(label("Fondo de inicio", "rowTitle"))
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
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
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
        self.advanced_button.setText(("▾" if show else "▸") + " Cuenta de Plutonium")

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
                    "del cliente oficial, conserva un respaldo y abre la sesión oficial "
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
            self.game_detail.setText("Completa el inicio de sesión oficial y vuelve a Jugar.")
        except Exception as exc:
            QMessageBox.warning(self, "Recuperación de sesión", str(exc))

    def update_plutonium(self):
        if b.game_process_alive() or b.official_client_running() or (self.game_process and self.game_process.poll() is None):
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
                self.play.setText("Abriendo cuenta…")
            elif self.launch_method == "uri":
                self.game_state.setText("Iniciando desde tu cuenta oficial...")
                self.game_detail.setText("Se ha solicitado BO2 Zombies mediante la URI oficial. "
                                         "Si aparece la pantalla de sesión, autentícate allí.")
                self.play.setText("Abriendo Zombies…")
            else:
                self.game_state.setText("Iniciando Zombies (LAN)...")
                self.game_detail.setText("Inicio local sin servidores públicos.")
                self.play.setText("Iniciando…")
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
            self.game_state.setText("Zombies en curso")
            self.game_detail.setText("El motor de BO2 está abierto. ¡Disfruta la partida!")
            self.play.setText("En partida")
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
            self.play.setText("Jugar Zombies")
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
            self.play.setText("Iniciando…")
            self.play.setEnabled(False)
            if code is not None and not self.launcher_exit_logged:
                self.launcher_exit_logged = True
                self.write_log(f"Cliente online terminó código {code}; esperando motor independiente.")
            return
        if code is None and self.launch_method == "setup":
            self.game_state.setText("Configura la cuenta online")
            self.game_detail.setText("Termina el inicio de sesión en la ventana oficial.")
            self.play.setText("Abriendo cuenta…")
            self.play.setEnabled(False)
            return
        if code is None and elapsed < 70:
            self.game_state.setText("Iniciando Zombies...")
            self.game_detail.setText("Esperando al motor T6...")
            self.play.setText("Iniciando…")
            self.play.setEnabled(False)
            return
        if code is None:
            self.game_state.setText("Arranque sin confirmar")
            self.game_detail.setText("El proceso sigue abierto. Comprueba el juego y revisa Actividad.")
            self.play.setText("Esperando juego")
            self.play.setEnabled(False)
            return
        self.write_log(f"No se detectó el motor tras iniciar el cliente ({code}). Registros en Actividad.")
        self.game_process = None
        self.launch_started_at = None
        self.launch_method = None
        self.refresh()
        self.game_state.setText("No se confirmó el arranque")
        self.game_detail.setText("Puedes intentar nuevamente o revisar el registro.")
        self.play.setText("Jugar Zombies")
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
    def refresh(self):
        game = b.find_game()
        components = b.component_status()
        prepared = bool(game and all(ok for _, ok in components))
        bootstrapper = b.bootstrapper_path()
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
            self.play.setText("Jugar Zombies")
        elif prepared and not bootstrapper:
            self.game_state.setText("Falta preparar el motor de juego")
            self.game_detail.setText("Actualiza los componentes en Configuración. "
                                     "Para jugar online, la cuenta también debe estar autenticada.")
            self.play.setText("Preparar juego")
        elif not game:
            self.game_state.setText("Faltan archivos del juego")
            self.game_detail.setText("Selecciona tu carpeta de Black Ops II en Configuración.")
            self.play.setText("Configurar juego")
        else:
            self.game_state.setText("Instalación pendiente")
            self.game_detail.setText("Instala los componentes desde Configuración.")
            self.play.setText("Configurar juego")
        missing = [name for name, ok in components if not ok]
        self.runtime.setText("Componentes listos" if not missing else "Pendientes: " + ", ".join(missing))
        if playing:
            self.game_state.setText("BO2 Zombies detectado")
            self.play.setText("En partida")
        elif pending:
            self.game_state.setText("Inicio solicitado (sin confirmar)")
            self.play.setText("Iniciando…")
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
            "pendiente-ruta": "La carpeta online se sincronizará al pulsar Jugar",
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
        if b.game_process_alive() or b.official_client_running() or (self.game_process and self.game_process.poll() is None):
            QMessageBox.information(self, "Proceso activo", "Cierra el juego o el proceso de inicio antes de modificar componentes.")
            return
        self.goto(2)
        self.write_log("\n--- Nueva operación ---")
        self.worker = Worker(fn)
        self.worker.line.connect(self.write_log)
        self.worker.succeeded.connect(lambda: self.complete_task(None))
        self.worker.failed.connect(self.complete_task)
        self.worker.finished.connect(self.refresh)
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
            if b.find_game() and b.PLUTONIUM.is_file() and b.runtime_ready() and not b.bootstrapper_path():
                self.write_log("Falta el ejecutable de inicio. Usa 'Actualizar componentes'. "
                               "Si necesitas iniciar sesión, abre Cuenta de Plutonium.")
            return
        self.start_game()

    def open_servers(self):
        self.goto(3)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "Operación en curso", "Espera a que termine la instalación o actualización antes de cerrar Relay.")
            event.ignore()
            return
        # El acceso HTTPS es acotado (15 s). Evitar destruir un QThread vivo.
        if self.server_worker and self.server_worker.isRunning():
            self.server_worker.wait(16000)
        super().closeEvent(event)

    def open_folder(self, path):
        b.ensure_dirs()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("bo2-launcher")
    theme = ThemeManager(app, b.load_config().get("theme", "system"))
    win = Launcher(theme)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
