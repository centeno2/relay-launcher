"""Both T6 modes use the proper files, official URI and native/Wine entry point."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from bo2launcher import backend as b


class MultiplayerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.game = self.root / 'Black Ops II'
        (self.game / 'zone/all').mkdir(parents=True)
        self.config = {'game_dir': str(self.game), 'game_mode': 't6mp'}
        patch = mock.patch.object(b, 'load_config', side_effect=lambda: self.config)
        patch.start()
        self.addCleanup(patch.stop)
        for file in ('binkw32.dll', 'localization_mp.txt', 'zone/all/mp_la.ff'):
            (self.game / file).touch()

    def test_mode_specific_assets_and_legacy_shared_folder(self):
        self.assertEqual(b.find_game(), self.game)
        self.config['game_mode'] = 't6zm'
        self.assertFalse(b.is_game_dir(self.game))
        for file in ('localization_zm.txt', 'zone/all/zm_transit.ff'):
            (self.game / file).touch()
        self.assertEqual(b.find_game(), self.game)
        (self.game / 'localization_mp.txt').unlink()
        self.config['game_mode'] = 't6mp'
        self.assertFalse(b.is_game_dir(self.game))

    def test_steam_multiplayer_manifest_and_executable(self):
        folder = self.root / 'steamapps/common/custom install'
        (folder / 'zone').mkdir(parents=True)
        (folder / 't6mp.exe').touch()
        (self.root / 'steamapps/appmanifest_202990.acf').write_text('"installdir" "custom install"')
        self.config.pop('game_dir')
        with mock.patch.object(b, 'steam_library_paths', return_value=[self.root]):
            self.assertEqual(b.find_game(), folder)

    def test_online_and_lan_modes_on_both_platforms(self):
        for file in ('localization_zm.txt', 'zone/all/zm_transit.ff'):
            (self.game / file).touch()
        (self.root / 'system.reg').touch()
        launcher = self.root / 'bin/launcher.exe'
        exe = self.root / 'bin/bootstrapper.exe'
        for windows in (True, False):
            for mode in ('t6mp', 't6zm'):
                self.config['game_mode'] = mode
                with self.subTest(windows=windows, mode=mode), \
                     mock.patch.object(b, 'IS_WINDOWS', windows), \
                     mock.patch.object(b, 'PREFIX', self.root), \
                     mock.patch.object(b, 'wine_path', return_value=self.root / 'wine'), \
                     mock.patch.object(b, 'official_game_launcher_path', return_value=launcher), \
                     mock.patch.object(b, 'bootstrapper_path', return_value=exe), \
                     mock.patch.object(b, 'sync_official_game_path') as sync, \
                     mock.patch.object(b, '_spawn_wine', return_value='process') as spawn:
                    self.assertEqual(b.launch_online_game(), ('process', 'uri'))
                    self.assertEqual(spawn.call_args.args[0][-1], 'plutonium://play/' + mode)
                    sync.assert_called_once_with(self.game)
                    b.launch_game(lan=True)
                    args = spawn.call_args.args[0]
                    self.assertEqual(args[1 if windows else 2], mode)
                    self.assertEqual(args[-1], '-lan')
                    self.assertEqual(args[0], str(exe if windows else self.root / 'wine'))

    def test_server_query_uses_provider_game_id(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'data': {'servers': []}}).encode()
        with mock.patch.object(b.urllib.request, 'urlopen', return_value=response) as request:
            b.fetch_servers('t6mp')
            self.assertIn('game=T6&', request.call_args.args[0].full_url)
            b.fetch_servers('t6zm')
            self.assertIn('game=T6ZM&', request.call_args.args[0].full_url)

    def test_invalid_saved_mode_falls_back_to_zombies(self):
        for invalid in ('other', '../t6mp', [], None):
            self.config['game_mode'] = invalid
            self.assertEqual(b.selected_game_mode(), 't6zm')
