"""Turning Hearthstone's file logging on without breaking the file.

This is the one place the coach edits something it does not own, so the tests
are mostly about what must NOT change. The real `log.config` has six sections
([Achievements], [Arena], [FullScreenFX], [LoadingScreen], [Power], ...), each
with its own LogLevel/FilePrinting/ConsolePrinting/ScreenPrinting/Verbose —
handing a player a file to copy in would delete five of them for every Deck
Tracker user (2026-10-03).
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # app/
sys.path.insert(0, HERE)          # the code dir, wherever this runs from

import setup_logging  # noqa: E402

#: Mirrors the shape of a real log.config: six sections, the same five keys in
#: each, [Power] sitting in the middle. Values are invented except where the
#: test is about them.
REAL_SHAPED = """[Achievements]
ConsolePrinting=false
FilePrinting=false
LogLevel=0
ScreenPrinting=false
Verbose=false

[Arena]
ConsolePrinting=false
FilePrinting=false
LogLevel=0
ScreenPrinting=false
Verbose=false

[FullScreenFX]
ConsolePrinting=false
FilePrinting=false
LogLevel=0
ScreenPrinting=false
Verbose=false

[Power]
ConsolePrinting=false
FilePrinting=false
LogLevel=0
ScreenPrinting=false
Verbose=false

[LoadingScreen]
ConsolePrinting=false
FilePrinting=false
LogLevel=0
ScreenPrinting=false
Verbose=false

[Bob]
ConsolePrinting=false
FilePrinting=false
LogLevel=0
ScreenPrinting=false
Verbose=false
"""


def sections(text):
    """{section name: [body lines]} — so a test can compare the parts of the
    file the coach promised not to touch."""
    out, name, body = {}, None, []
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if name is not None:
                out[name] = body
            name, body = s[1:-1], []
        elif name is not None:
            body.append(line)
    if name is not None:
        out[name] = body
    return out


#: The shape of a real `client.config`: flat `name=value`, one client config
#: var per line, which is what the client's own `getvar`/`setvar` console
#: commands read and write. The limit line is the client's DEFAULT, so this is
#: exactly the file that closes a log at 10 MB.
REAL_SHAPED_CLIENT = """Aurora.Version.String=1.2.3
Log.FileSizeLimit.Int=10000
ShowFakeBreakingNews=true
"""


class LoggingFixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.path = os.path.join(self.dir, "log.config")
        # never look at the real machine during tests
        patcher = mock.patch.object(setup_logging, "hearthstone_running",
                                    lambda: False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, text):
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def read(self):
        with open(self.path, encoding="utf-8", newline="") as f:
            return f.read()

    def backup(self):
        return self.path + setup_logging.BACKUP_SUFFIX


class TestReadState(LoggingFixture):
    def test_no_file_is_missing(self):
        state, missing = setup_logging.read_state(self.path)
        self.assertEqual(state, "missing")
        self.assertEqual(missing, setup_logging.REQUIRED)

    def test_a_real_shaped_file_with_power_off_is_incomplete(self):
        self.write(REAL_SHAPED)
        state, missing = setup_logging.read_state(self.path)
        self.assertEqual(state, "incomplete")
        self.assertEqual(set(missing), {"LogLevel", "FilePrinting"})

    def test_an_already_correct_file_is_ok(self):
        self.write(REAL_SHAPED.replace("[Power]\nConsolePrinting=false\n"
                                       "FilePrinting=false\nLogLevel=0",
                                       "[Power]\nConsolePrinting=false\n"
                                       "FilePrinting=true\nLogLevel=1"))
        state, missing = setup_logging.read_state(self.path)
        self.assertEqual((state, missing), ("ok", {}))

    def test_a_file_without_a_power_section_is_incomplete(self):
        self.write("[Arena]\nLogLevel=0\n")
        state, _missing = setup_logging.read_state(self.path)
        self.assertEqual(state, "incomplete")


class TestNothingElseChanges(LoggingFixture):
    def test_the_other_five_sections_are_byte_identical(self):
        self.write(REAL_SHAPED)
        before = sections(self.read())
        setup_logging.apply(self.path)
        after = sections(self.read())
        self.assertEqual(sorted(before), sorted(after))
        for name in before:
            if name != "Power":
                self.assertEqual(before[name], after[name], f"[{name}] changed")

    def test_the_keys_inside_power_that_are_not_ours_are_kept(self):
        self.write(REAL_SHAPED)
        setup_logging.apply(self.path)
        power = "".join(sections(self.read())["Power"])
        self.assertIn("FilePrinting=true", power)
        self.assertIn("LogLevel=1", power)
        # ours are the only two that moved
        self.assertIn("ScreenPrinting=false", power)
        self.assertIn("Verbose=false", power)
        self.assertIn("ConsolePrinting=false", power)

    def test_only_the_config_and_its_backup_are_written(self):
        self.write(REAL_SHAPED)
        setup_logging.apply(self.path)
        self.assertEqual(sorted(os.listdir(self.dir)),
                         sorted(["log.config", "log.config.bobs-ledger-backup"]))

    def test_crlf_survives(self):
        self.write(REAL_SHAPED.replace("\n", "\r\n"))
        setup_logging.apply(self.path)
        text = self.read()
        # Every newline is part of a CRLF: the lines this rewrote must not be
        # the only ones left with a bare LF. (The first version of this test
        # replaced CRLF with two newlines and then asserted the result had no
        # blank lines — nonsense that could never pass.)
        self.assertEqual(text.count("\n"), text.count("\r\n"))
        power = "".join(sections(text)["Power"])
        self.assertIn("FilePrinting=true\r\n", power)
        self.assertIn("LogLevel=1\r\n", power)

    def test_a_file_without_trailing_newline_still_gets_a_clean_section(self):
        self.write(REAL_SHAPED.rstrip("\n"))
        setup_logging.apply(self.path)
        text = self.read()
        self.assertIn("\n[Power]\n", text.replace("\r\n", "\n"))
        self.assertEqual(setup_logging.read_state(self.path)[0], "ok")


class TestApplying(LoggingFixture):
    def test_a_missing_file_is_created_with_just_the_power_block(self):
        state, changed, note = setup_logging.apply(self.path)
        self.assertEqual(state, "missing")
        self.assertEqual(note, "created")
        self.assertEqual(setup_logging.read_state(self.path)[0], "ok")
        self.assertEqual(sections(self.read()).keys(), {"Power"})

    def test_the_original_is_backed_up_before_the_first_change(self):
        self.write(REAL_SHAPED)
        setup_logging.apply(self.path)
        with open(self.backup(), encoding="utf-8", newline="") as f:
            self.assertEqual(f.read(), REAL_SHAPED)

    def test_a_second_run_does_not_overwrite_the_first_backup(self):
        self.write(REAL_SHAPED)
        setup_logging.apply(self.path)
        setup_logging.apply(self.path)                      # already on
        with open(self.backup(), encoding="utf-8", newline="") as f:
            self.assertEqual(f.read(), REAL_SHAPED)

    def test_an_already_correct_file_is_left_alone(self):
        self.write(REAL_SHAPED.replace("FilePrinting=false\nLogLevel=0\n"
                                       "ScreenPrinting", "FilePrinting=true\n"
                                       "LogLevel=1\nScreenPrinting"))
        state, changed, note = setup_logging.apply(self.path)
        self.assertEqual((state, changed, note), ("ok", [], "already-on"))
        self.assertFalse(os.path.exists(self.backup()))

    def test_it_refuses_while_hearthstone_is_running(self):
        self.write(REAL_SHAPED)
        with mock.patch.object(setup_logging, "hearthstone_running",
                               lambda: True):
            state, changed, note = setup_logging.apply(self.path)
        self.assertEqual(note, "hearthstone-running")
        self.assertEqual(self.read(), REAL_SHAPED)          # untouched
        self.assertFalse(os.path.exists(self.backup()))

    def test_a_power_section_is_appended_when_absent(self):
        self.write("[Arena]\nLogLevel=0\n")
        setup_logging.apply(self.path)
        now = sections(self.read())
        self.assertEqual(now["Arena"], ["LogLevel=0\n"])    # untouched
        self.assertIn("FilePrinting=true", "".join(now["Power"]))


class TestTheLogSizeCap(unittest.TestCase):
    """The 10 MB wall, and the client variable that removes it.

    Hearthstone CLOSES a log once it reaches `Log.FileSizeLimit.Int` kilobytes,
    and the default is 10000. Measured on macOS 2026-10-15: a Battlegrounds game
    hit it, Power.log vanished from the client's open files, and the rest of the
    game -- its ending, the review, the saved replay, the placement -- was lost
    while the coach sat on a stale frame and said nothing. `-1` is the client's
    own "no limit", so `client.config` beside the game gets the same careful
    edit `log.config` gets: one key, everything else kept, original backed up.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self.path = os.path.join(self.dir, "client.config")
        p = mock.patch.object(setup_logging, "hearthstone_running",
                              lambda: False)
        p.start()
        self.addCleanup(p.stop)

    def write(self, text):
        with open(self.path, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def read(self):
        with open(self.path, encoding="utf-8", newline="") as f:
            return f.read()

    def backup(self):
        with open(self.path + setup_logging.BACKUP_SUFFIX, encoding="utf-8",
                  newline="") as f:
            return f.read()

    def test_no_file_is_missing(self):
        self.assertEqual(setup_logging.read_client_state(self.path)[0],
                         "missing")

    def test_the_clients_own_default_reads_incomplete(self):
        """10000KB is the documented default and the cap we measured, so a file
        that still carries it is not 'ok'."""
        self.write("Log.FileSizeLimit.Int=10000\n")
        state, missing = setup_logging.read_client_state(self.path)
        self.assertEqual(state, "incomplete")
        self.assertEqual(missing, {"Log.FileSizeLimit.Int": "-1"})

    def test_unlimited_reads_ok(self):
        self.write("Log.FileSizeLimit.Int=-1\n")
        self.assertEqual(setup_logging.read_client_state(self.path)[0], "ok")

    def test_a_missing_file_is_created_with_the_one_variable(self):
        state, changed, note = setup_logging.apply_client(self.path)
        self.assertEqual((state, note), ("missing", "created"))
        self.assertEqual(self.read(), "Log.FileSizeLimit.Int=-1\n")
        self.assertTrue(changed)

    def test_other_client_vars_survive_and_the_original_is_kept(self):
        """A player may already carry another tool's client config vars, or an
        event UID's. None of them are ours to drop."""
        self.write(REAL_SHAPED_CLIENT)
        state, changed, note = setup_logging.apply_client(self.path)
        self.assertEqual(note, "backed-up")
        out = self.read()
        self.assertIn("Log.FileSizeLimit.Int=-1", out)
        self.assertIn("Aurora.Version.String=1.2.3", out)
        self.assertIn("ShowFakeBreakingNews=true", out)
        self.assertEqual(self.backup(), REAL_SHAPED_CLIENT)

    def test_the_backup_stays_the_original_across_runs(self):
        self.write(REAL_SHAPED_CLIENT)
        setup_logging.apply_client(self.path)
        setup_logging.apply_client(self.path)
        self.assertEqual(self.backup(), REAL_SHAPED_CLIENT)

    def test_a_second_run_changes_nothing(self):
        setup_logging.apply_client(self.path)
        before = self.read()
        state, changed, note = setup_logging.apply_client(self.path)
        self.assertEqual((state, note), ("ok", "already-on"))
        self.assertEqual(changed, [])
        self.assertEqual(self.read(), before)

    def test_it_refuses_while_hearthstone_is_running(self):
        """The client reads this file at startup, so editing it under a live
        game is the same broken promise `log.config` refuses to make."""
        with mock.patch.object(setup_logging, "hearthstone_running",
                               lambda: True):
            state, changed, note = setup_logging.apply_client(self.path)
        self.assertEqual(note, "hearthstone-running")
        self.assertEqual(changed, [])
        self.assertFalse(os.path.exists(self.path),
                         "the client's config was edited under a live game")

    def test_an_unwritable_game_folder_is_reported_not_raised(self):
        """`client.config` lives in the GAME's folder.

        On Windows that is under Program Files, which a standard user may not be
        able to write. A raw PermissionError would surface as a traceback in the
        middle of the launcher's first-run flow; the launcher already knows how to
        turn a non-zero exit into advice, so the failure has to become a note.
        """
        ro = os.path.join(self.dir, "readonly")
        os.makedirs(ro)
        os.chmod(ro, 0o500)
        self.addCleanup(os.chmod, ro, 0o700)
        state, changed, note = setup_logging.apply_client(
            os.path.join(ro, "client.config"))
        self.assertTrue(note.startswith("not-writable"), note)
        self.assertEqual(changed, [])

    def test_crlf_is_preserved(self):
        self.write("Aurora.Version.String=1.2.3\r\n"
                   "Log.FileSizeLimit.Int=10000\r\n")
        setup_logging.apply_client(self.path)
        with open(self.path, "rb") as f:
            raw = f.read()
        self.assertEqual(raw, b"Aurora.Version.String=1.2.3\r\n"
                              b"Log.FileSizeLimit.Int=-1\r\n")


class TestTheCliContract(unittest.TestCase):
    """The launcher decides whether to ask by the exit code, so it is part of
    the interface."""

    def test_check_exits_zero_when_logging_is_on(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(setup_logging, "hearthstone_running",
                                   lambda: False):
                setup_logging.apply(os.path.join(td, "log.config"))
                setup_logging.apply_client(os.path.join(td, "client.config"))
                with mock.patch("sys.argv", ["setup_logging.py", "--check",
                                             "--path", td,
                                             "--client-path", td]):
                    with mock.patch("sys.stdout", new_callable=__import__("io").StringIO):
                        self.assertEqual(setup_logging.main(), 0)

    def test_check_exits_one_when_logging_is_off(self):
        import io
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("sys.argv", ["setup_logging.py", "--check",
                                         "--path", td,
                                         "--client-path", td]):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                    self.assertEqual(setup_logging.main(), 1)
        self.assertIn("file logging is OFF", out.getvalue())

    def test_check_exits_one_when_only_the_cap_is_left(self):
        """Logging on is no longer the whole answer: a session that hits the cap
        still loses the end of the game, so the launcher has to keep asking."""
        import io
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(setup_logging, "hearthstone_running",
                                   lambda: False):
                setup_logging.apply(os.path.join(td, "log.config"))
                with mock.patch("sys.argv", ["setup_logging.py", "--check",
                                             "--path", td,
                                             "--client-path", td]):
                    with mock.patch("sys.stdout",
                                    new_callable=io.StringIO) as out:
                        self.assertEqual(setup_logging.main(), 1)
            self.assertIn("log size cap STILL SET", out.getvalue())

    def test_apply_exits_one_when_hearthstone_is_running(self):
        import io
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(setup_logging, "hearthstone_running",
                                   lambda: True):
                with mock.patch("sys.argv", ["setup_logging.py", "--apply",
                                             "--path", td,
                                             "--client-path", td]):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                        self.assertEqual(setup_logging.main(), 1)
        self.assertIn("Close Hearthstone", out.getvalue())


if __name__ == "__main__":
    unittest.main()
