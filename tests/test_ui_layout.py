"""Exercise real Qt controls offscreen without network, game files or user settings."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QCloseEvent, QPalette
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea
from PySide6.QtTest import QTest

from bo2launcher import GAME_FILES_URL, artwork, backend as b
from bo2launcher.gui import Launcher
from bo2launcher.theme import ThemeManager


class TestDesktopUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.theme = ThemeManager(cls.app, 'light')

    def patch(self, target, name, **kwargs):
        p = mock.patch.object(target, name, **kwargs)
        value = p.start()
        self.addCleanup(p.stop)
        return value

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ('DATA', 'CONFIG', 'STATE', 'CACHE', 'PREFIX', 'WINE_DIR', 'DXVK_DIR', 'PLUTONIUM_DIR'):
            self.patch(b, name, new=self.root / name)
        self.patch(b, 'PLUTONIUM', new=b.PLUTONIUM_DIR / 'plutonium.exe')
        self.patch(b, 'windows_client_dir', return_value=self.root / 'client')
        self.patch(b, 'find_game', return_value=None)
        self.patch(b, 'game_session_visible', return_value=False)
        self.patch(b, 'official_client_running', return_value=False)
        self.patch(artwork, 'cached_image', return_value=None)
        self.patch(artwork.ArtworkFetcher, 'fetch')
        self.theme.apply('light')
        self.window = Launcher(self.theme)
        self.window.show()
        self.app.processEvents()
        self.addCleanup(self.dispose)

    def dispose(self):
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_compact_home_keeps_all_actions_visible(self):
        self.window.resize(760, 560)
        self.app.processEvents()
        self.assertEqual(self.window.width(), 760)
        self.assertEqual(self.window.height(), 560)
        for control in [self.window.play, self.window.drive_button] + [tab for _, tab in self.window.tabs]:
            with self.subTest(text=control.text()):
                self.assertTrue(control.isVisible())
                top = control.mapTo(self.window, control.rect().topLeft())
                bottom = control.mapTo(self.window, control.rect().bottomRight())
                self.assertTrue(self.window.rect().contains(top))
                self.assertTrue(self.window.rect().contains(bottom))

    def test_sidebar_collapses_and_restores_navigation_labels(self):
        self.window.resize(760, 560)
        self.app.processEvents()
        self.assertEqual(self.window.sidebar.width(), 72)
        for _, tab in self.window.tabs:
            self.assertEqual(tab.text(), '')
            self.assertTrue(tab.accessibleName())
            self.assertFalse(tab.icon().isNull())
        self.window.resize(1180, 790)
        self.app.processEvents()
        self.assertEqual(self.window.sidebar.width(), 196)
        self.assertTrue(all(tab.text() for _, tab in self.window.tabs))

    def test_banner_is_available_without_network_or_steam(self):
        self.assertFalse(self.window.home_background.pix.isNull())
        self.assertEqual(artwork.home_image({}), artwork.BUNDLED_HERO)
        self.assertEqual(artwork.home_image({'background_image': '/missing/banner.png'}), artwork.BUNDLED_HERO)

    def test_custom_banner_survives_steam_response_and_can_reset(self):
        from PySide6.QtGui import QPixmap
        custom = QPixmap(30, 20)
        custom.fill('#793cc2')
        image = self.root / 'custom.png'
        custom.save(str(image))
        b.save_config(background_image=str(image), background_source='custom')
        self.window.home_background.load(artwork.home_image())
        self.window.art_received('hero', str(artwork.BUNDLED_HERO))
        self.assertEqual(self.window.home_background.pix.size(), custom.size())
        self.window.reset_background()
        self.assertEqual(b.load_config()['background_source'], 'relay')
        self.assertEqual(self.window.home_background.pix.size(), QPixmap(str(artwork.BUNDLED_HERO)).size())

    def test_mode_badge_follows_lan_setting(self):
        self.window.lan.setChecked(True)
        self.assertEqual(self.window.mode_badge.text(), 'Modo LAN')
        self.window.lan.setChecked(False)
        self.assertEqual(self.window.mode_badge.text(), 'Modo online')

    def test_server_shortcut_opens_server_page(self):
        with mock.patch.object(self.window, 'refresh_servers') as refresh:
            QTest.mouseClick(self.window.servers_button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.pages.currentIndex(), 3)
        refresh.assert_called_once()

    def test_drive_opens_exact_shared_folder(self):
        with mock.patch('bo2launcher.gui.QDesktopServices.openUrl') as open_url:
            QTest.mouseClick(self.window.drive_button, Qt.MouseButton.LeftButton)
        self.assertEqual(open_url.call_args.args[0].toString(), GAME_FILES_URL)

    def test_missing_game_primary_action_opens_settings(self):
        QTest.mouseClick(self.window.play, Qt.MouseButton.LeftButton)
        self.assertEqual(self.window.pages.currentIndex(), 1)
        self.assertIn('Faltan', self.window.game_state.text())

    def test_themes_persist_and_system_palette_is_restored(self):
        self.window.goto(1)
        for mode in ('dark', 'light', 'system'):
            self.window.theme_select.setCurrentIndex(self.window.theme_select.findData(mode))
            self.app.processEvents()
            color = self.app.palette().color(QPalette.ColorRole.Window)
            if mode == 'dark':
                self.assertLess(color.lightness(), 90)
            elif mode == 'light':
                self.assertGreater(color.lightness(), 200)
            else:
                self.assertEqual(color, self.theme.system_palette.color(QPalette.ColorRole.Window))
            self.assertEqual(b.load_config()['theme'], mode)

    def test_system_palette_change_updates_controls(self):
        self.theme.apply('system')
        palette = QPalette(self.theme.system_palette)
        palette.setColor(QPalette.ColorRole.Highlight, '#7755aa')
        self.app.setPalette(palette)
        self.app.processEvents()
        self.assertIn('#7755aa', self.app.styleSheet())

    def test_settings_scroll_without_horizontal_overflow(self):
        self.window.resize(760, 560)
        self.window.goto(1)
        self.app.processEvents()
        page = self.window.pages.currentWidget()
        self.assertIsInstance(page, QScrollArea)
        self.assertEqual(page.horizontalScrollBar().maximum(), 0)
        self.assertGreater(page.verticalScrollBar().maximum(), 0)

    def test_windows_readiness_does_not_require_wine_or_dxvk(self):
        with mock.patch.object(b, 'IS_WINDOWS', True), \
             mock.patch.object(b, 'find_game', return_value=self.root / 'game'), \
             mock.patch.object(b, 'bootstrapper_path', return_value=self.root / 'bootstrapper.exe'):
            b.PLUTONIUM.parent.mkdir(parents=True)
            b.PLUTONIUM.touch()
            self.assertTrue(self.window.refresh())
            self.assertTrue(self.window.play.isEnabled())
            self.assertEqual(self.window.play.text(), 'Jugar Zombies')
            self.assertEqual(self.window.runtime.text(), 'Componentes listos')

    def test_windows_controls_hide_linux_only_options(self):
        with mock.patch.object(b, 'IS_WINDOWS', True):
            other = Launcher(self.theme)
            try:
                self.assertTrue(other.nvidia.isHidden())
                self.assertTrue(other.hide_console.isHidden())
                self.assertTrue(other.deps_button.isHidden())
            finally:
                other.close()
                other.deleteLater()

    def test_active_installation_prevents_thread_destruction(self):
        self.window.worker = mock.Mock()
        self.window.worker.isRunning.return_value = True
        event = QCloseEvent()
        with mock.patch('bo2launcher.gui.QMessageBox.information'):
            self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.window.worker = None


if __name__ == '__main__':
    unittest.main()
