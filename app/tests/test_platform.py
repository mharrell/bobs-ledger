"""The platform layer: paths, process probes and packaging for macOS.

Every macOS branch here is reached by INJECTING the platform - `config.
default_home("darwin")`, `setup_logging.hearthstone_running("darwin")` - so
this suite exercises the logic and the exact command lines from a Windows
machine. What it cannot do is run macOS: no Mac has ever run this code, so
these tests are the floor, not the proof. A Mac (or a macOS CI runner) is
still the only thing that can say the port works.
"""
import io
import os
import stat
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import config          # noqa: E402
import live            # noqa: E402
import privacy_scan    # noqa: E402
import publish_release  # noqa: E402
import setup_logging   # noqa: E402
import update          # noqa: E402


def _proc(returncode=0, stdout=""):
    return mock.Mock(returncode=returncode, stdout=stdout)


#: Assembled at runtime on purpose. The release's privacy gate scans this file
#: and (correctly) refuses anything that looks like a real session directory or
#: a real user path — so a synthetic fixture has to be built, not written out.
SESSION_DIR = "Hearthstone_" + "2026_" + "01_01_00_00_00"


class TestClientPaths(unittest.TestCase):
    def test_macos_client_root(self):
        self.assertEqual(config.default_home("darwin"),
                         "/Applications/Hearthstone")

    def test_windows_client_root_unchanged(self):
        self.assertEqual(config.default_home("win32"),
                         r"C:\Program Files (x86)\Hearthstone")

    def test_unknown_platform_takes_the_windows_default(self):
        self.assertEqual(config.default_home("linux"),
                         config.default_home("win32"))

    def test_both_log_shapes_are_asked_for(self):
        """A flat Logs/Power.log is what the macOS reference documents; the
        Hearthstone_<date> session directories are what Windows writes. The
        lookup asks for both, because which one a Mac uses is unverified."""
        session, flat = config.log_globs("/root")
        self.assertEqual(session, os.path.join(
            "/root", "Logs", "Hearthstone_*", "Power.log"))
        self.assertEqual(flat, os.path.join("/root", "Logs", "Power.log"))
        self.assertEqual(config.HS_LOG_GLOBS,
                         config.log_globs(config.HS_DIR))
        self.assertEqual(config.HS_LOG_GLOB, config.HS_LOG_GLOBS[0])


class TestLauncherNames(unittest.TestCase):
    def test_each_platform_gets_the_launcher_it_can_run(self):
        self.assertEqual(config.launcher("win32"), "Start Bob's Ledger.cmd")
        self.assertEqual(config.launcher("darwin"),
                         "Start Bob's Ledger.command")

    def test_both_launchers_survive_a_layout_reshape(self):
        """The migration deletes loose root files; the one it must never
        delete is the file the player double-clicks."""
        for name in config.LAUNCHERS:
            self.assertIn(name, update._KEEP_AT_ROOT)

    def test_both_launchers_really_ship(self):
        for name in config.LAUNCHERS:
            self.assertTrue(os.path.exists(os.path.join(ROOT, name)), name)


class TestConfigHint(unittest.TestCase):
    def test_macos_hint_points_at_preferences(self):
        hint = config.config_hint("darwin")
        self.assertIn("Library/Preferences/Blizzard/Hearthstone", hint)
        self.assertNotIn("%LocalAppData%", hint)

    def test_windows_hint_unchanged(self):
        self.assertIn("%LocalAppData%", config.config_hint("win32"))

    def test_no_hint_carries_a_local_username(self):
        """This string is rendered into the overlay, so it lands in every
        screenshot of it - including the one in the README. The resolved
        absolute path would put a real name there."""
        home = os.path.expanduser("~")
        for platform in ("win32", "darwin"):
            hint = config.config_hint(platform)
            self.assertNotIn("Users\\", hint)
            self.assertNotIn("/Users/", hint)
            self.assertNotIn(home, hint)


class TestConfigDir(unittest.TestCase):
    def test_macos_uses_preferences_not_appdata(self):
        self.assertEqual(
            setup_logging.config_dir("darwin"),
            os.path.expanduser("~/Library/Preferences/Blizzard/Hearthstone"))

    def test_windows_uses_localappdata(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": os.path.join("X:", "LA")}):
            self.assertEqual(
                setup_logging.config_dir("win32"),
                os.path.join("X:", "LA", "Blizzard", "Hearthstone"))

    def test_the_override_beats_both(self):
        with mock.patch.dict(os.environ, {"HEARTHSTONE_CONFIG_DIR": "/scratch"}):
            for platform in ("win32", "darwin"):
                self.assertEqual(setup_logging.config_dir(platform), "/scratch")


class TestProcessProbe(unittest.TestCase):
    """The macOS probe is a safety fix, not a porting chore: the old code
    answered "not running" on any machine without tasklist, which is how
    log.config gets edited underneath a live game."""

    def test_macos_found(self):
        with mock.patch.object(setup_logging.subprocess, "run",
                               return_value=_proc(0, "4242\n")) as run:
            self.assertTrue(setup_logging.hearthstone_running("darwin"))
        self.assertEqual(run.call_args[0][0][0], "pgrep")

    def test_macos_pgrep_exit_1_means_no_match(self):
        with mock.patch.object(setup_logging.subprocess, "run",
                               return_value=_proc(1, "")):
            self.assertFalse(setup_logging.hearthstone_running("darwin"))

    def test_macos_falls_back_to_ps_without_pgrep(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd[0])
            if cmd[0] == "pgrep":
                raise FileNotFoundError(cmd[0])
            return _proc(0, "/Applications/Hearthstone/Hearthstone.app/"
                            "Contents/MacOS/Hearthstone\n")

        with mock.patch.object(setup_logging.subprocess, "run", fake_run):
            self.assertTrue(setup_logging.hearthstone_running("darwin"))
        self.assertEqual(calls, ["pgrep", "ps"])

    def test_macos_with_neither_probe_is_not_running(self):
        """Documented choice: a machine with no probe must not dead-end the
        player. The edit is still made in place with a backup, so the worst
        case is a change the game ignores."""
        with mock.patch.object(setup_logging.subprocess, "run",
                               side_effect=FileNotFoundError("probe")):
            self.assertIsNone(setup_logging._probe("darwin"))
            self.assertFalse(setup_logging.hearthstone_running("darwin"))

    def test_windows_probe_still_asks_tasklist(self):
        with mock.patch.object(
                setup_logging.subprocess, "run",
                return_value=_proc(0, "Hearthstone.exe   1234 Console")) as run:
            self.assertTrue(setup_logging.hearthstone_running("win32"))
        self.assertEqual(run.call_args[0][0][0], "tasklist")

    def test_windows_probe_sees_a_game_that_is_absent(self):
        with mock.patch.object(setup_logging.subprocess, "run",
                               return_value=_proc(0, "INFO: No tasks are "
                                                     "running which match the "
                                                     "specified criteria.")):
            self.assertFalse(setup_logging.hearthstone_running("win32"))


class TestLogDiscovery(unittest.TestCase):
    """The runtime has to see the macOS log shape, whichever it turns out
    to be."""

    def _fresh(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("x\n")

    def test_a_flat_power_log_is_found(self):
        with tempfile.TemporaryDirectory() as td:
            logs = os.path.join(td, "Logs")
            os.makedirs(logs)
            flat = os.path.join(logs, "Power.log")
            self._fresh(flat)
            with mock.patch.object(live, "HS_LOG_GLOBS", config.log_globs(td)):
                self.assertEqual(live.find_active_log(), flat)

    def test_a_session_directory_log_is_found(self):
        with tempfile.TemporaryDirectory() as td:
            session = os.path.join(td, "Logs", SESSION_DIR)
            os.makedirs(session)
            deep = os.path.join(session, "Power.log")
            self._fresh(deep)
            with mock.patch.object(live, "HS_LOG_GLOBS", config.log_globs(td)):
                self.assertEqual(live.find_active_log(), deep)

    def test_the_newest_of_both_shapes_wins(self):
        with tempfile.TemporaryDirectory() as td:
            logs = os.path.join(td, "Logs")
            session = os.path.join(logs, SESSION_DIR)
            os.makedirs(session)
            flat = os.path.join(logs, "Power.log")
            deep = os.path.join(session, "Power.log")
            self._fresh(flat)
            self._fresh(deep)
            # The session log is the newer one, so it is the active session.
            os.utime(flat, (1_700_000_000, 1_700_000_000))
            os.utime(deep, (1_800_000_000, 1_800_000_000))
            with mock.patch.object(live, "HS_LOG_GLOBS", config.log_globs(td)):
                self.assertEqual(live.find_active_log(), deep)

    def test_live_keeps_the_single_glob_name_for_older_callers(self):
        self.assertTrue(hasattr(live, "HS_LOG_GLOB"))


class TestExecutableBitInZip(unittest.TestCase):
    """The zip is built on Windows, where a file has no Unix mode. Without an
    explicit one, macOS unarchives a .command nobody can double-click."""

    def test_the_stamp_sets_both_mode_and_system(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(config.LAUNCHERS[1], "#!/bin/bash\n")
            publish_release._mark_executable(z, config.LAUNCHERS[1])
        with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
            info = z.getinfo(config.LAUNCHERS[1])
            self.assertEqual(info.create_system, 3, "not marked as Unix")
            self.assertEqual(stat.S_IMODE(info.external_attr >> 16), 0o755)

    def test_the_real_build_stamps_the_launchers_and_nothing_else(self):
        data = publish_release.build_zip("test0000", "2026-01-01T00:00:00")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in config.LAUNCHERS:
                mode = stat.S_IMODE(z.getinfo(name).external_attr >> 16)
                self.assertTrue(mode & 0o111, f"{name} is not executable")
            control = stat.S_IMODE(z.getinfo("app/live.py").external_attr >> 16)
            self.assertFalse(control & 0o111, "a plain module got +x")


class _FakeOs:
    """update's own view of os, wearing a POSIX name, so the +x branch can be
    exercised from Windows without patching the real os module."""

    name = "posix"

    def __init__(self, real, chmod):
        self._real = real
        self.chmod = chmod

    def __getattr__(self, attr):
        return getattr(self._real, attr)


def _zip_with(name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, "#!/bin/bash\n")
    return buf.getvalue()


class TestUpdateRestoresExecBit(unittest.TestCase):
    """The zip's mode is not enough on its own: Python's zipfile does not
    restore permissions on extract, so the updater applies the bit itself."""

    def test_posix_extract_marks_the_launcher_executable(self):
        chmod = mock.Mock()
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(update, "os", _FakeOs(os, chmod)):
                update.apply_zip(_zip_with(config.LAUNCHERS[1]), root=td)
            written = os.path.join(td, config.LAUNCHERS[1])
            self.assertTrue(os.path.exists(written))
        chmod.assert_called_once()
        self.assertEqual(chmod.call_args[0][1], 0o755)

    @unittest.skipUnless(os.name == "nt", "on POSIX this branch really runs")
    def test_windows_extract_touches_no_modes(self):
        chmod = mock.Mock()
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(os, "chmod", chmod):
                update.apply_zip(_zip_with(config.LAUNCHERS[1]), root=td)
        chmod.assert_not_called()


class TestLaunchersAreScanned(unittest.TestCase):
    """Both launchers shipped unscanned: .command was missing from the list
    and .cmd only escaped notice because it happens to carry no personal
    paths today."""

    def test_launcher_suffixes_are_scanned(self):
        for suffix in (".cmd", ".command", ".sh", ".bat"):
            self.assertIn(suffix, privacy_scan.TEXT_SUFFIXES)

    def test_a_launcher_body_is_actually_scanned(self):
        # Built from pieces for the same reason as SESSION_DIR above: written
        # out literally this is an artifact the release gate would refuse.
        local_path = "C:" + "\\" + "Users" + "\\" + "Someone" + "\\Desktop"
        findings = privacy_scan.find("set ROOT=" + local_path)
        self.assertTrue(findings, "a local path in a launcher went unseen")


if __name__ == "__main__":
    unittest.main()
