"""The one-command launcher must recover and avoid downloads on repeat starts."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import start


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="relay startup ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "requirements.txt").write_text("PySide6>=6.8,<7\npsutil>=6,<8\n")
        self.env = self.root / ".venv"
        self.python = self.env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        self.stamp = self.env / ".relay-requirements"

    def existing(self):
        self.python.parent.mkdir(parents=True)
        self.python.touch()
        self.stamp.write_text(hashlib.sha256((self.root / "requirements.txt").read_bytes()).hexdigest())

    def test_repeat_launch_needs_no_network(self):
        self.existing()
        with mock.patch.object(start.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertEqual(start.prepare_environment(self.root), self.python)
        self.assertEqual(run.call_count, 1)
        self.assertNotIn("pip", run.call_args.args[0])

    def test_changed_requirements_trigger_install(self):
        self.existing()
        (self.root / "requirements.txt").write_text("changed requirements\n")
        with mock.patch.object(start.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            start.prepare_environment(self.root)
        self.assertEqual(run.call_count, 2)
        self.assertIn("pip", run.call_args.args[0])
        self.assertTrue(run.call_args.kwargs["check"])

    def test_missing_packages_are_repaired_even_with_current_stamp(self):
        self.existing()
        with mock.patch.object(start.subprocess, "run", side_effect=[mock.Mock(returncode=1), mock.Mock(returncode=0)]) as run:
            start.prepare_environment(self.root)
        self.assertIn("pip", run.call_args.args[0])

    def test_failed_first_install_is_not_marked_complete(self):
        def create(path):
            self.python.parent.mkdir(parents=True)
            self.python.touch()
        with mock.patch.object(start.venv, "EnvBuilder") as builder, \
             mock.patch.object(start.subprocess, "run", side_effect=[mock.Mock(returncode=1), subprocess.CalledProcessError(1, "pip")]):
            builder.return_value.create.side_effect = create
            with self.assertRaises(subprocess.CalledProcessError):
                start.prepare_environment(self.root)
        self.assertFalse(self.stamp.exists())


if __name__ == "__main__":
    unittest.main()
