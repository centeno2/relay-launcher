"""UI layout source checks to run even when Qt is unavailable in CI."""
from pathlib import Path
import ast
import unittest

CODE = (Path(__file__).resolve().parents[1] / 'bo2launcher' / 'gui.py').read_text(encoding='utf-8')

class TestHomeRedesign(unittest.TestCase):
    def test_ui_is_valid_python(self):
        ast.parse(CODE)

    def test_no_full_screen_opaque_home_card(self):
        tree = ast.parse(CODE)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Launcher')
        make_home = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'make_home')
        segment = ast.get_source_segment(CODE, make_home)
        self.assertNotIn('gameCard', segment)
        self.assertNotIn('Artwork("poster")', segment)
        self.assertIn('HomeBackdrop()', segment)
        self.assertIn('homeStatus', segment)

    def test_cover_management_and_play_callback_preserved(self):
        self.assertIn('self.cover = Artwork("poster")', CODE)
        self.assertIn('self.cover.load(path)', CODE)
        self.assertIn('self.play_or_setup', CODE)
        self.assertIn('self.check_game', CODE)
        self.assertIn('self.home_background.load(path)', CODE)

    def test_quick_access_dock_is_actionable(self):
        tree = ast.parse(CODE)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Launcher')
        make_home = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'make_home')
        segment = ast.get_source_segment(CODE, make_home)
        self.assertIn('quick_tile(', segment)
        for title in ('"SERVIDORES"', '"CONFIGURACIÓN"', '"ACTIVIDAD"'):
            self.assertIn(title, segment)
        self.assertIn('self.open_servers', segment)
        self.assertIn('lambda: self.goto(1)', segment)
        self.assertIn('lambda: self.goto(2)', segment)

    def test_hero_uses_personal_art_without_requiring_owning_it(self):
        self.assertIn('self.home_background = page', CODE)
        self.assertIn('background_image', CODE)
        self.assertIn('self.change_background', CODE)
        self.assertIn('self.game_state = label(', CODE)
        self.assertIn('self.play_or_setup', CODE)

if __name__ == '__main__':
    unittest.main()
