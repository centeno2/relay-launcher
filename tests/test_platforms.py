"""Native Windows behavior, also exercised with mocked processes on Linux."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from bo2launcher import backend as b
from bo2launcher.platforms import app_paths


class WindowsBackendTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="relay test ")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in ("DATA", "CONFIG", "STATE", "CACHE", "PREFIX", "WINE_DIR", "DXVK_DIR", "PLUTONIUM_DIR"):
            self.patch(name, self.root / name)
        self.patch("IS_WINDOWS", True)
        self.patch("PLUTONIUM", b.PLUTONIUM_DIR / "plutonium.exe")
        self.client = self.root / "Local AppData/Plutonium"
        self.patch("windows_client_dir", lambda: self.client)
        self.processes = self.patch("windows_processes", mock.Mock(return_value=[]))
        self.game = self.root / "Juegos/Black Ops II"
        (self.game / "zone").mkdir(parents=True)
        (self.game / "t6zm.exe").touch()
        (self.client / "bin").mkdir(parents=True)
        self.launcher = self.client / "bin/plutonium-launcher-win32.exe"
        self.launcher.write_bytes(b"MZ")
        self.bootstrapper = self.client / "bin" / b.BOOTSTRAPPER_EXE
        self.bootstrapper.write_bytes(b"MZ")

    def patch(self, name, value):
        patcher = mock.patch.object(b, name, value)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def test_windows_appdata_and_linux_legacy_locations(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "Local"), "APPDATA": str(self.root / "Roaming"),
                                         "XDG_DATA_HOME": str(self.root / "xdg")}):
            data, config, state, cache = app_paths(windows=True)
            self.assertEqual(data, self.root / "Local/Relay")
            self.assertEqual(config, self.root / "Roaming/Relay")
            self.assertEqual(state, data / "logs")
            self.assertEqual(cache, data / "cache")
            self.assertEqual(app_paths(windows=False)[0], self.root / "xdg/bo2-zombies-linux")

    def test_discovers_existing_native_installation(self):
        self.assertEqual(b.bootstrapper_path(), self.bootstrapper)
        self.assertEqual(b.official_game_launcher_path(), self.launcher)
        self.assertEqual(b.official_config_path(), self.client / "config.json")

    def test_native_commands_preserve_spaces_and_do_not_use_wine(self):
        self.assertEqual(b.build_online_command(self.game), [str(self.launcher), b.OFFICIAL_T6ZM_URI])
        self.assertEqual(b.build_game_command(self.game, lan=True, player_name="Test Player"), [
            str(self.bootstrapper), "t6zm", str(self.game.resolve()), "+name", "Test Player", "-lan"])

    def test_native_spawn_has_no_wine_environment_or_posix_session(self):
        b.ensure_dirs()
        with mock.patch.object(b.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True), \
             mock.patch.object(b.subprocess, "Popen") as spawn, \
             mock.patch.object(b, "wine_env", side_effect=AssertionError("No Wine on Windows")):
            b._spawn_wine([str(self.launcher)], cwd=self.client, logfile="test.log")
        self.assertEqual(spawn.call_args.kwargs["creationflags"], 512)
        self.assertNotIn("start_new_session", spawn.call_args.kwargs)
        self.assertEqual(spawn.call_args.kwargs["cwd"], str(self.client))

    def test_windows_setup_downloads_only_plutonium(self):
        with mock.patch.object(b.platform, "machine", return_value="AMD64"), \
             mock.patch.object(b, "setup_plutonium") as setup, \
             mock.patch.object(b, "setup_wine", side_effect=AssertionError("No Wine")), \
             mock.patch.object(b, "install_windows_deps", side_effect=AssertionError("No Winetricks")):
            b.run_setup(lambda _: None)
        setup.assert_called_once()

    def test_windows_updater_uses_native_exe_without_virtual_display(self):
        with mock.patch.object(b, "setup_plutonium"), \
             mock.patch.object(b.shutil, "which", side_effect=AssertionError("No Xvfb")), \
             mock.patch.object(b.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            b.update_engine(lambda _: None)
        self.assertEqual(run.call_args.args[0], [str(b.PLUTONIUM), "-update-only"])

    def test_config_sync_preserves_session_and_backups_without_fchmod(self):
        config = self.client / "config.json"
        original = {"account": {"token": "fixture-only"}, "t6Path": "old", "other": [1]}
        config.write_text(json.dumps(original), encoding="utf-8")
        with mock.patch.object(b.os, "fchmod", side_effect=AssertionError("Not available on Windows"), create=True):
            self.assertTrue(b.sync_official_game_path(self.game))
        current = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(current["account"], original["account"])
        self.assertEqual(current["t6Path"], str(self.game.resolve()))
        self.assertEqual(b.official_game_path_status(self.game), "sincronizado")
        backup, = self.client.glob("config.json.bak-ruta-*")
        self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), original)
        self.assertFalse(b.sync_official_game_path(self.game))

    def test_both_game_modes_count_but_launcher_does_not(self):
        for name, args, expected in (
            ("plutonium-launcher-win32.exe", [b.OFFICIAL_T6ZM_URI], False),
            (b.BOOTSTRAPPER_EXE, [str(self.bootstrapper), "t6mp"], True),
            (b.BOOTSTRAPPER_EXE, [str(self.bootstrapper), "t6zm"], True),
            ("t6zm.exe", [], True),
        ):
            with self.subTest(name=name, args=args):
                self.processes.return_value = [{"name": name, "cmdline": args}]
                self.assertEqual(b.game_process_alive(), expected)

    def test_running_client_blocks_config_edit_and_session_repair(self):
        self.processes.return_value = [{"name": "plutonium.exe", "cmdline": []}]
        with self.assertRaisesRegex(RuntimeError, "Cierra"):
            b.sync_official_game_path(self.game)
        with self.assertRaisesRegex(RuntimeError, "Cierra"):
            b.backup_online_session()
        self.assertFalse((self.client / "config.json").exists())

    def test_first_launch_opens_official_setup(self):
        self.launcher.unlink()
        self.patch("find_game", lambda: self.game)
        with mock.patch.object(b, "launch_plutonium", return_value="setup"):
            self.assertEqual(b.launch_online_game(), ("setup", "setup"))

    def test_native_steam_library_detection(self):
        library = self.root / "Steam Library"
        common = library / "steamapps/common/Call of Duty Black Ops II"
        (common / "zone").mkdir(parents=True)
        (common / "t6zm.exe").touch()
        with mock.patch.object(b, "windows_steam_paths", return_value=[library]):
            self.assertEqual(b.find_game(), common)


if __name__ == "__main__":
    unittest.main()
