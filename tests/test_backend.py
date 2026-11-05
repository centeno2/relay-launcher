import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bo2launcher import backend as b


def setUpModule():
    from unittest.mock import patch
    temporary = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(temporary.cleanup)
    root = Path(temporary.name)
    for key in ("DATA", "CONFIG", "STATE", "CACHE", "PREFIX", "WINE_DIR", "DXVK_DIR", "PLUTONIUM_DIR"):
        patcher = patch.object(b, key, root / key.lower())
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)
    patcher = patch.object(b, "PLUTONIUM", b.PLUTONIUM_DIR / "plutonium.exe")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


class TestBackend(unittest.TestCase):
    def test_steam_game_dir_requires_exe_and_zone(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            self.assertFalse(b.is_game_dir(p))
            (p / 't6zm.exe').touch()
            self.assertFalse(b.is_game_dir(p))
            (p / 'zone').mkdir()
            self.assertTrue(b.is_game_dir(p))

    def test_plutonium_game_files_without_executable(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'zone/all').mkdir(parents=True)
            (p / 'binkw32.dll').touch()
            (p / 'localization_zm.txt').touch()
            self.assertFalse(b.is_game_dir(p))
            (p / 'zone/all/zm_transit.ff').touch()
            self.assertTrue(b.is_game_dir(p))

    def test_plutonium_dir_missing_localization_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'zone/all').mkdir(parents=True)
            (p / 'binkw32.dll').touch()
            (p / 'zone/all/zm_transit.ff').touch()
            self.assertFalse(b.is_game_dir(p))

    def test_tar_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode='w') as tf:
                info = tarfile.TarInfo('../outside')
                info.size = 1
                tf.addfile(info, io.BytesIO(b'x'))
            buffer.seek(0)
            with tarfile.open(fileobj=buffer, mode='r') as tf:
                with self.assertRaises(ValueError):
                    b._safe_extract(tf, Path(d))

    def test_no_game_found_without_known_files(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(b.is_game_dir(Path(d)))

# Tests de integración simulada del lanzador (no ejecutan Wine).
from unittest import mock


@unittest.skipIf(sys.platform == "win32", "Wine/Niri integration runs on Linux")
class TestLaunchAndServers(unittest.TestCase):
    def test_bootstrapper_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp)
            exe = prefix / 'drive_c/users/centeno/AppData/Local/Plutonium/bin/plutonium-bootstrapper-win32.exe'
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b'MZ')
            with mock.patch.object(b, 'PREFIX', prefix):
                self.assertEqual(b.bootstrapper_path(), exe)

    def test_windows_path_and_command_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            game = base / 'Call of Duty Black Ops II'
            (game / 'zone').mkdir(parents=True)
            (game / 't6zm.exe').touch()
            prefix = base / 'prefix'
            prefix.mkdir()
            (prefix / 'system.reg').touch()
            bootstrapper = base / 'bootstrapper.exe'
            bootstrapper.write_bytes(b'MZ')
            fakewine = base / 'wine'
            fakewine.touch()
            with mock.patch.object(b, 'PREFIX', prefix), \
                 mock.patch.object(b, 'bootstrapper_path', return_value=bootstrapper), \
                 mock.patch.object(b, 'wine_path', return_value=fakewine):
                args = b.build_game_command(game, player_name='Centeno')
                self.assertEqual(args[:3], [str(fakewine), str(bootstrapper), 't6zm'])
                self.assertTrue(args[3].startswith('Z:\\'))
                self.assertEqual(args[4:6], ['+name', 'Centeno'])
                self.assertNotIn('-lan', args)
                lan_args = b.build_game_command(game, lan=True)
                self.assertEqual(lan_args[-1], '-lan')
                conn = b.build_game_command(game, server='127.0.0.1:3074')
                self.assertEqual(conn[-2:], ['+connect', '127.0.0.1:3074'])
                with self.assertRaises(ValueError):
                    b.build_game_command(game, lan=True, server='127.0.0.1:3074')

    def test_reject_malicious_address(self):
        for address in ('8.8.8.8:65536', '999.1.1.1:80',
                        '127.0.0.1:3074 +quit', 'example.com:3074'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                b.validate_server_address(address)
        self.assertEqual(b.validate_server_address('1.2.3.4:03074'), '1.2.3.4:3074')

    def test_server_response_is_normalized(self):
        payload = json.dumps({'data': {'servers': [
            {'name': 'Zombies Test', 'map': {'display': 'Origins'},
             'players': {'current': 3, 'max': 8}, 'address': '1.2.3.4:3074'},
            {'name': 'Bad address', 'map': None, 'players': {}, 'address': 'evil'},
        ]}}).encode()
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): return None
            def read(self, limit): return payload
        with mock.patch('urllib.request.urlopen', return_value=FakeResponse()):
            rows = b.fetch_servers()
        self.assertEqual(rows[0]['map'], 'Origins')
        self.assertEqual(rows[0]['players'], '3/8')
        self.assertEqual(rows[0]['address'], '1.2.3.4:3074')
        self.assertEqual(rows[1]['address'], '')

    def test_launch_game_uses_plutonium_client_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / 'game'
            (game / 'zone').mkdir(parents=True)
            (game / 't6zm.exe').touch()
            prefix = root / 'prefix'
            prefix.mkdir()
            (prefix / 'system.reg').touch()
            client = root / 'AppData/Local/Plutonium'
            exe = client / 'bin/plutonium-bootstrapper-win32.exe'
            exe.parent.mkdir(parents=True)
            exe.touch()
            fakewine = root / 'wine'
            fakewine.touch()
            with mock.patch.object(b, 'PREFIX', prefix), \
                 mock.patch.object(b, 'bootstrapper_path', return_value=exe), \
                 mock.patch.object(b, 'wine_path', return_value=fakewine), \
                 mock.patch.object(b, 'find_game', return_value=game), \
                 mock.patch.object(b, '_spawn_wine', return_value='process') as spawn:
                result = b.launch_game(lan=True)
            self.assertEqual(result, 'process')
            command = spawn.call_args.args[0]
            self.assertIn('-lan', command)
            self.assertEqual(spawn.call_args.kwargs['cwd'], client)
            self.assertEqual(spawn.call_args.kwargs['logfile'], 'game.log')

@unittest.skipIf(sys.platform == "win32", "Wine/Niri integration runs on Linux")
class TestUpdateAndDiagnosis(unittest.TestCase):
    def test_update_without_virtual_display_uses_visible_wine(self):
        with mock.patch.object(b, 'runtime_ready', return_value=True), \
             mock.patch.object(b, 'wine_path', return_value=Path('/runtime/wine')), \
             mock.patch.object(b, 'setup_plutonium'), \
             mock.patch.object(b, 'bootstrapper_path', return_value=Path('/client/bootstrapper.exe')), \
             mock.patch.object(b.shutil, 'which', return_value=None), \
             mock.patch.object(b.subprocess, 'run', return_value=mock.Mock(returncode=0)) as run:
            b.update_engine(lambda _message: None)
        self.assertEqual(run.call_args.args[0], ['/runtime/wine', str(b.PLUTONIUM), '-update-only'])

    def test_updater_uses_virtual_display_and_disables_wayland(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pref = root / 'prefix'
            pref.mkdir()
            (pref / 'system.reg').touch()
            state = root / 'state'
            client = root / 'client'
            client.mkdir()
            fakewine = root / 'wine'
            fakewine.touch()
            seen = []
            with mock.patch.object(b, 'PREFIX', pref), \
                 mock.patch.object(b, 'STATE', state), \
                 mock.patch.object(b, 'PLUTONIUM_DIR', client), \
                 mock.patch.object(b, 'PLUTONIUM', client / 'plutonium.exe'), \
                 mock.patch.object(b, 'wine_path', return_value=fakewine), \
                 mock.patch.object(b, 'setup_plutonium') as setup, \
                 mock.patch.object(b, 'bootstrapper_path', return_value=root / 'bootstrapper.exe'), \
                 mock.patch.object(b.shutil, 'which', side_effect=lambda _name: '/usr/bin/' + _name), \
                 mock.patch.object(b, 'wine_env', return_value={'WAYLAND_DISPLAY': 'wayland-1'}), \
                 mock.patch.object(b.subprocess, 'run', return_value=mock.Mock(returncode=0)) as runner:
                b.update_engine(seen.append)
            self.assertTrue(setup.called)
            self.assertIn('xvfb-run', runner.call_args.args[0][0])
            self.assertNotIn('WAYLAND_DISPLAY', runner.call_args.kwargs['env'])
            self.assertEqual(runner.call_args.kwargs['env']['XDG_SESSION_TYPE'], 'x11')
            self.assertTrue(any('terminó' in msg for msg in seen))

    def test_updater_error_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pref = root / 'prefix'
            pref.mkdir()
            (pref / 'system.reg').touch()
            client = root / 'client'
            client.mkdir()
            with mock.patch.object(b, 'PREFIX', pref), \
                 mock.patch.object(b, 'STATE', root / 'logs'), \
                 mock.patch.object(b, 'PLUTONIUM_DIR', client), \
                 mock.patch.object(b, 'PLUTONIUM', client / 'plutonium.exe'), \
                 mock.patch.object(b, 'wine_path', return_value=root / 'wine'), \
                 mock.patch.object(b, 'setup_plutonium'), \
                 mock.patch.object(b.shutil, 'which', return_value='/usr/bin/fake'), \
                 mock.patch.object(b.subprocess, 'run', return_value=mock.Mock(returncode=8)):
                with self.assertRaisesRegex(RuntimeError, 'código 8'):
                    b.update_engine(lambda _message: None)

    def test_network_diagnostic_never_downloads_exe(self):
        logs = []
        class HeadResult:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return None
        with mock.patch.object(b.socket, 'getaddrinfo', return_value=[(b.socket.AF_INET, 1, 0, '', ('127.0.0.1', 443))]), \
             mock.patch.object(b.urllib.request, 'urlopen', return_value=HeadResult()) as urlopen:
            b.check_connections(logs.append)
        self.assertEqual(urlopen.call_count, 3)
        self.assertTrue(all(call.args[0].get_method() == 'HEAD' for call in urlopen.call_args_list))
        self.assertTrue(any('HTTPS OK' in line for line in logs))

    def test_diagnostic_redacts_tokens(self):
        from bo2launcher.diagnostico import redact
        self.assertNotIn('123secret', redact('Authorization: Bearer 123secret'))
        self.assertNotIn('abc123', redact('https://example.test?a=1&token=abc123'))




@unittest.skipIf(sys.platform == "win32", "Wine/Niri integration runs on Linux")
class TestSessionRecoveryAndGameState(unittest.TestCase):
    def test_session_backup_preserves_file_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / "prefix"
            account = prefix / "drive_c/users/centeno/AppData/Local/Plutonium/config.json"
            account.parent.mkdir(parents=True)
            account.write_text('{"access_token":"private"}')
            with mock.patch.object(b, 'PREFIX', prefix):
                backups = b.backup_online_session()
                self.assertEqual(len(backups), 1)
                self.assertFalse(account.exists())
                self.assertEqual(backups[0].read_text(), '{"access_token":"private"}')
                self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
                self.assertEqual(b.backup_online_session(), [])

    def test_game_process_requires_real_binary_and_matching_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = root / "proc"
            proc.mkdir()
            prefix = root / "prefix"
            prefix.mkdir()
            fake_proc = proc / "100"
            fake_proc.mkdir()
            (fake_proc / "cmdline").write_bytes(b'wine\0plutonium-bootstrapper-win32.exe\0t6zm\0')
            (fake_proc / "environ").write_bytes(('WINEPREFIX=' + str(prefix)).encode() + b'\0')
            with mock.patch.object(b, 'PREFIX', prefix):
                self.assertTrue(b.game_process_alive(proc))  # bootstrapper t6zm also hosts the engine
                (fake_proc / "cmdline").write_bytes(b'wine\0C:\\games\\t6zm.exe\0')
                self.assertTrue(b.game_process_alive(proc))
                (fake_proc / "environ").write_bytes(b'WINEPREFIX=/different\0')
                self.assertFalse(b.game_process_alive(proc))
                (fake_proc / "environ").write_bytes(('WINEPREFIX=' + str(prefix)).encode() + b'\0')
                (fake_proc / "cmdline").write_bytes(b'wine\0t6mp.exe\0')
                self.assertFalse(b.game_process_alive(proc))

    def test_game_scan_without_proc_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(b.game_process_alive(Path(tmp) / 'not-present'))


@unittest.skipIf(sys.platform == "win32", "Wine/Niri integration runs on Linux")
class TestOfficialOnlineLaunch(unittest.TestCase):
    def test_official_launcher_is_found_in_private_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / 'prefix'
            exe = prefix / 'drive_c/users/centeno/AppData/Local/Plutonium/bin/plutonium-launcher-win32.exe'
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b'MZ')
            with mock.patch.object(b, 'PREFIX', prefix):
                self.assertEqual(b.official_game_launcher_path(), exe)

    def test_online_uses_official_uri_not_bootstrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / 'game'
            (game / 'zone').mkdir(parents=True)
            (game / 't6zm.exe').touch()
            prefix = root / 'prefix'
            prefix.mkdir()
            (prefix / 'system.reg').touch()
            wine = root / 'wine'
            launcher = root / 'AppData/Local/Plutonium/bin/plutonium-launcher-win32.exe'
            launcher.parent.mkdir(parents=True)
            launcher.write_bytes(b'MZ')
            with mock.patch.object(b, 'PREFIX', prefix), \
                 mock.patch.object(b, 'wine_path', return_value=wine), \
                 mock.patch.object(b, 'official_game_launcher_path', return_value=launcher), \
                 mock.patch.object(b, 'bootstrapper_path', side_effect=AssertionError('Do not call bootstrapper')):
                self.assertEqual(b.build_online_command(game), [
                    str(wine), str(launcher), 'plutonium://play/t6zm'])

    def test_online_launch_uses_correct_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / 'game'
            launcher = root / 'Plutonium/bin/plutonium-launcher-win32.exe'
            with mock.patch.object(b, 'find_game', return_value=game), \
                 mock.patch.object(b, 'official_game_launcher_path', return_value=launcher), \
                 mock.patch.object(b, 'build_online_command', return_value=['wine', 'launcher', b.OFFICIAL_T6ZM_URI]), \
                 mock.patch.object(b, '_spawn_wine', return_value='process') as spawn, \
                 mock.patch.object(b, 'sync_official_game_path') as sync:
                result, mode = b.launch_online_game()
                self.assertEqual((result, mode), ('process', 'uri'))
                self.assertEqual(spawn.call_args.kwargs['cwd'], launcher.parent.parent)
                self.assertEqual(spawn.call_args.kwargs['logfile'], 'game.log')

    def test_missing_online_client_opens_official_setup(self):
        with mock.patch.object(b, 'find_game', return_value=Path('/tmp/gamedir')), \
             mock.patch.object(b, 'official_game_launcher_path', return_value=None), \
             mock.patch.object(b, 'launch_plutonium', return_value='setup_process') as setup:
            self.assertEqual(b.launch_online_game(), ('setup_process', 'setup'))
            setup.assert_called_once_with()

    def test_online_does_not_accept_lan_or_server_without_official_support(self):
        self.assertEqual(b.OFFICIAL_T6ZM_URI, 'plutonium://play/t6zm')


@unittest.skipIf(sys.platform == "win32", "Wine/Niri integration runs on Linux")
class TestAutomaticPlutoniumGamePath(unittest.TestCase):
    """Simulated Wine prefix. Never opens a real client or reads real sessions."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.prefix = self.root / 'prefix'
        dos = self.prefix / 'dosdevices'
        dos.mkdir(parents=True)
        (dos / 'z:').symlink_to('/')
        self.client = self.prefix / 'drive_c/users/centeno/AppData/Local/Plutonium'
        launcher = self.client / 'bin/plutonium-launcher-win32.exe'
        launcher.parent.mkdir(parents=True)
        launcher.write_bytes(b'MZ')
        self.game = self.root / 'games/Black Ops II'
        (self.game / 'zone').mkdir(parents=True)
        (self.game / 't6zm.exe').touch()
        patcher = mock.patch.object(b, 'PREFIX', self.prefix)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_sync_preserves_session_and_makes_private_backup(self):
        original = {"account": {"token": "SECRET_PRIVATE_123"}, "t6Path": "C:\\wrong", "other": [1, 2]}
        config = self.client / 'config.json'
        config.write_text(json.dumps(original), encoding='utf-8')
        self.assertTrue(b.sync_official_game_path(self.game))
        updated = json.loads(config.read_text())
        self.assertEqual(updated['account'], original['account'])
        self.assertEqual(updated['other'], [1, 2])
        self.assertEqual(updated['t6Path'], 'Z:' + str(self.game).replace('/', '\\'))
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        backups = list(self.client.glob('config.json.bak-ruta-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text()), original)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        self.assertFalse(b.sync_official_game_path(self.game))
        self.assertEqual(len(list(self.client.glob('config.json.bak-ruta-*'))), 1)
        self.assertEqual(b.official_game_path_status(self.game), 'sincronizado')

    def test_new_configuration_keeps_no_secret_data(self):
        config = self.client / 'config.json'
        self.assertTrue(b.sync_official_game_path(self.game))
        self.assertEqual(set(json.loads(config.read_text())), {'t6Path'})
        self.assertEqual(len(list(self.client.glob('config.json.bak-*'))), 0)

    def test_malformed_config_is_never_overwritten(self):
        config = self.client / 'config.json'
        config.write_bytes(b'{not-valid')
        with self.assertRaisesRegex(RuntimeError, 'JSON'):
            b.sync_official_game_path(self.game)
        self.assertEqual(config.read_bytes(), b'{not-valid')
        self.assertEqual(len(list(self.client.glob('config.json.bak-ruta-*'))), 0)

    def test_missing_dosdevices_is_actionable(self):
        (self.prefix / 'dosdevices/z:').unlink()
        with self.assertRaisesRegex(RuntimeError, 'Z:'):
            b.sync_official_game_path(self.game)
        self.assertFalse((self.client / 'config.json').exists())

    def test_windows_path_prefers_closest_mapped_drive(self):
        (self.prefix / 'dosdevices/d:').symlink_to(self.root)
        self.assertEqual(b._game_path_in_prefix(self.game), 'D:\\games\\Black Ops II')

    def test_symlink_config_is_not_edited(self):
        outside = self.root / 'outside.json'
        outside.write_text('{"other":"preserve"}')
        (self.client / 'config.json').symlink_to(outside)
        with self.assertRaisesRegex(RuntimeError, 'enlace simbólico'):
            b.sync_official_game_path(self.game)
        self.assertEqual(json.loads(outside.read_text()), {"other": "preserve"})

    def test_online_launch_syncs_before_starting_game(self):
        calls = []
        def sync(game):
            calls.append(('sync', game))
        def spawn(*args, **kwargs):
            calls.append(('spawn', args))
            return 'proc'
        with mock.patch.object(b, 'find_game', return_value=self.game), \
             mock.patch.object(b, 'sync_official_game_path', side_effect=sync), \
             mock.patch.object(b, 'build_online_command', return_value=['wine', 'client', 'plutonium://play/t6zm']), \
             mock.patch.object(b, '_spawn_wine', side_effect=spawn):
            self.assertEqual(b.launch_online_game(), ('proc', 'uri'))
        self.assertEqual(calls[0], ('sync', self.game))
        self.assertEqual(calls[1][0], 'spawn')

@unittest.skipIf(sys.platform == "win32", "Wine/Niri integration runs on Linux")
class TestOfficialClientRunning(unittest.TestCase):
    def test_sync_refuses_to_modify_settings_while_client_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / 'prefix'
            proc = Path(tmp) / 'proc/456'
            proc.mkdir(parents=True)
            (proc / 'cmdline').write_bytes(b'wine\0C:\\Plutonium\\bin\\plutonium-launcher-win32.exe\0')
            (proc / 'environ').write_bytes(('WINEPREFIX=' + str(prefix)).encode() + b'\0')
            with mock.patch.object(b, 'PREFIX', prefix):
                self.assertTrue(b.official_client_running(proc.parent))
                (proc / 'environ').write_bytes(b'WINEPREFIX=/another\0')
                self.assertFalse(b.official_client_running(proc.parent))

    def test_sync_aborts_before_reading_config_if_provider_running(self):
        with mock.patch.object(b, 'is_game_dir', return_value=True), \
             mock.patch.object(b, 'game_process_alive', return_value=False), \
             mock.patch.object(b, 'official_client_running', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'Cierra BO2'):
                b.sync_official_game_path(Path('/fake'))


@unittest.skipIf(sys.platform == "win32", "Wine/Niri integration runs on Linux")
class TestGameDetection2026(unittest.TestCase):
    def test_bootstrapper_with_zombies_token_counts(self):
        self.assertTrue(b._process_is_t6(b'wine\0plutonium-bootstrapper-win32.exe\0t6zm\0'))
        self.assertTrue(b._process_is_t6(b'wine\0Z:\\Plutonium\\bin\\plutonium-bootstrapper-win32.exe\0t6zm\0'))

    def test_other_wine_processes_not_zombies(self):
        self.assertFalse(b._process_is_t6(b'wine\0plutonium-launcher-win32.exe\0plutonium://play/t6zm\0'))
        self.assertFalse(b._process_is_t6(b'wine\0plutonium-bootstrapper-win32.exe\0t6mp\0'))
        self.assertFalse(b._process_is_t6(b'wineserver\0'))

    def test_game_process_comm_for_wine_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = root / 'proc' / '318'
            proc.mkdir(parents=True)
            (proc / 'comm').write_bytes(b't6zm.exe\n')
            (proc / 'cmdline').write_bytes(b'wine-preloader\0')
            prefix = root / 'prefix'
            (proc / 'environ').write_bytes(f'WINEPREFIX={prefix}'.encode()+b'\0')
            with mock.patch.object(b, 'PREFIX', prefix):
                self.assertTrue(b.game_process_alive(proc.parent))

    def test_niri_window_detects_engine_console(self):
        with mock.patch.dict(os.environ, {'NIRI_SOCKET': '/tmp/niri.sock'}), \
             mock.patch.object(b.shutil, 'which', return_value='/usr/bin/niri'), \
             mock.patch.object(b.subprocess, 'run', return_value=mock.Mock(stdout='[{"title": "Plutonium r5369"}]')):
            self.assertTrue(b.game_console_visible())
        with mock.patch.dict(os.environ, {'NIRI_SOCKET': '/tmp/niri.sock'}), \
             mock.patch.object(b.shutil, 'which', return_value='/usr/bin/niri'), \
             mock.patch.object(b.subprocess, 'run', return_value=mock.Mock(stdout='[{"title": "Plutonium Launcher"}]')):
            self.assertFalse(b.game_console_visible())


@unittest.skipIf(sys.platform == "win32", "Wine/Niri integration runs on Linux")
class TestNiriRule2026(unittest.TestCase):
    def test_can_enable_and_disable_with_backup(self):
        from bo2launcher import niri_integration as ni
        with tempfile.TemporaryDirectory() as td, mock.patch.object(ni, 'config_dir', return_value=Path(td)), \
             mock.patch.object(ni.shutil, 'which', return_value=None):
            cfg = Path(td)/'config.kdl'
            cfg.write_text('layout {}\n')
            self.assertTrue(ni.set_enabled(True))
            self.assertTrue(ni.is_enabled())
            self.assertIn('opacity 0.0', (Path(td)/'bo2-console.kdl').read_text())
            self.assertEqual(len(list(Path(td).glob('config.kdl.bo2-backup-*'))), 1)
            self.assertTrue(ni.set_enabled(False))
            self.assertFalse(ni.is_enabled())
            self.assertEqual(cfg.read_text(), 'layout {}\n')

    def test_niri_validate_failure_reverts(self):
        from bo2launcher import niri_integration as ni
        with tempfile.TemporaryDirectory() as td, mock.patch.object(ni, 'config_dir', return_value=Path(td)), \
             mock.patch.object(ni.shutil, 'which', return_value='/usr/bin/niri'), \
             mock.patch.object(ni.subprocess, 'run', return_value=mock.Mock(returncode=1, stderr='bad rule')):
            config = Path(td)/'config.kdl'
            config.write_text('layout {}\n')
            with self.assertRaises(RuntimeError):
                ni.set_enabled(True)
            self.assertEqual(config.read_text(), 'layout {}\n')
            self.assertFalse((Path(td)/'bo2-console.kdl').exists())


if __name__ == '__main__':
    unittest.main()
