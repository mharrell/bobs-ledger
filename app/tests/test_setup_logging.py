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


class TestTheCliContract(unittest.TestCase):
    """The launcher decides whether to ask by the exit code, so it is part of
    the interface."""

    def test_check_exits_zero_when_logging_is_on(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(setup_logging, "hearthstone_running",
                                   lambda: False):
                setup_logging.apply(os.path.join(td, "log.config"))
                with mock.patch("sys.argv", ["setup_logging.py", "--check",
                                             "--path", td]):
                    with mock.patch("sys.stdout", new_callable=__import__("io").StringIO):
                        self.assertEqual(setup_logging.main(), 0)

    def test_check_exits_one_when_logging_is_off(self):
        import io
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("sys.argv", ["setup_logging.py", "--check",
                                         "--path", td]):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                    self.assertEqual(setup_logging.main(), 1)
        self.assertIn("file logging is OFF", out.getvalue())

    def test_apply_exits_one_when_hearthstone_is_running(self):
        import io
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(setup_logging, "hearthstone_running",
                                   lambda: True):
                with mock.patch("sys.argv", ["setup_logging.py", "--apply",
                                             "--path", td]):
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                        self.assertEqual(setup_logging.main(), 1)
        self.assertIn("Close Hearthstone", out.getvalue())


if __name__ == "__main__":
    unittest.main()
