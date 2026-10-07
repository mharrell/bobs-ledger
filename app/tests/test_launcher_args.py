"""The launcher must survive a plain double-click.

Regression (2026-10-02, shipped in b42b652): `set "ARG1=%~1"` DELETES the
variable when the launcher is given no arguments, and cmd then mangles the
undefined variable in the `"%ARG1:~0,8%"` prefix test into

    The syntax of the command is incorrect.

which aborts the batch on the spot. The window died right after
"Dependencies: ok", so the one path every player takes - double-clicking the
file - was the only broken one. Every test up to this point passed a flag
(`--check`, `--no-update`), which defines ARG1 and hides it completely.

These cases pull the REAL argument-handling lines out of the shipped .cmd and
run them in a thrown-together batch, so what is tested is the text that ships.
They also pin the file-format invariants cmd.exe needs: CRLF endings (an
LF-only .cmd mis-parses, labels included) and pure ASCII (a stray UTF-8 byte
renders as garbage in a cp437 console).
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # app/
#: The launcher sits one level ABOVE the code: a player's folder is the
#: launcher, the README, the licence, docs/ and app/ (2026-10-02).
ROOT = os.path.dirname(HERE)
LAUNCHER = os.path.join(ROOT, "Start Bob's Ledger.cmd")

WIN_ONLY = unittest.skipUnless(sys.platform == "win32", "cmd.exe only")


def _arg_lines():
    """The launcher's argument handling, exactly as shipped.

    TWO spans, because the handling is in two places for a reason: ARG1 and the
    `CHECK` flag are read at the top of the file, before the sections that write
    (recognising `--check` only at the shortcut step is what let `--check`
    install a package and edit Hearthstone's own log.config while reporting that
    it had written nothing), while the dispatch that consumes the flag sits with
    the shortcut prompt it falls through to. Running the two spans together is
    still the real code: anchoring on text the file really contains means this
    test fails loudly if either span is restructured, instead of quietly testing
    nothing.
    """
    with open(LAUNCHER, encoding="ascii") as f:
        lines = f.read().splitlines()

    def index(predicate, start=0):
        for i in range(start, len(lines)):
            if predicate(lines[i]):
                return i
        return None

    head_start = index(lambda ln: not ln.startswith("rem")
                       and ln.strip().startswith('if "%~1"=="" (set "ARG1='))
    head_stop = index(lambda ln: ln.strip().startswith('set "CHECK=0"'),
                      head_start or 0)
    tail_start = index(lambda ln: not ln.startswith("rem")
                       and 'if /i "%ARG1%"=="--check" goto :report' in ln)
    tail_stop = index(lambda ln: ln.startswith('set "WANT_SHORTCUT='),
                      tail_start or 0)
    if None in (head_start, head_stop, tail_start, tail_stop):
        raise AssertionError(
            "could not find the argument-handling spans in the launcher - this "
            "test needs updating, not deleting")
    # head runs up to and including the last CHECK line (the substring test).
    head_stop += 1
    return lines[head_start:head_stop] + lines[tail_start:tail_stop]


def _script(arg_lines):
    body = "\r\n".join(arg_lines)
    return (
        "@echo off\r\n"
        "setlocal EnableExtensions\r\n"
        f"{body}\r\n"
        "echo REACHED-END\r\n"
        "exit /b 0\r\n"
        ":report\r\n"
        "echo REPORT-BRANCH\r\n"
        "exit /b 0\r\n"
    )


def _run(args):
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "args.cmd")
        with open(path, "w", encoding="ascii", newline="\r\n") as f:
            f.write(_script(_arg_lines()))
        return subprocess.run(["cmd.exe", "/c", path] + list(args),
                              capture_output=True, text=True, timeout=60)


@WIN_ONLY
class TestLauncherArguments(unittest.TestCase):
    def test_no_arguments_does_not_kill_the_batch(self):
        """The double-click path. Before the fix this exited with a syntax
        error and nothing else."""
        r = _run([])
        self.assertNotIn("syntax of the command", r.stderr.lower())
        self.assertIn("REACHED-END", r.stdout)
        self.assertNotIn("REPORT-BRANCH", r.stdout)

    def test_check_still_reports_and_does_not_start_the_coach(self):
        r = _run(["--check"])
        self.assertNotIn("syntax of the command", r.stderr.lower())
        self.assertIn("REPORT-BRANCH", r.stdout)

    def test_check_with_a_value_still_reports(self):
        """The prefix case, which is why the substring test exists at all: a
        shell once handed over '--check=' and the coach started silently."""
        r = _run(["--check=whatever"])
        self.assertNotIn("syntax of the command", r.stderr.lower())
        self.assertIn("REPORT-BRANCH", r.stdout)

    def test_unrelated_flag_falls_through_to_starting(self):
        r = _run(["--no-update"])
        self.assertNotIn("syntax of the command", r.stderr.lower())
        self.assertIn("REACHED-END", r.stdout)


class TestLauncherFileFormat(unittest.TestCase):
    """cmd.exe needs CRLF; it mis-parses LF-only batch files (labels and
    `goto` especially). A stray non-ASCII byte renders as garbage in the
    console and is invisible in review."""

    def test_crlf_and_ascii(self):
        with open(LAUNCHER, "rb") as f:
            raw = f.read()
        bare_lf = raw.count(b"\n") - raw.count(b"\r\n")
        self.assertEqual(bare_lf, 0, "launcher has LF-only line endings")
        self.assertEqual(raw.count(b"\r\n"), len(raw.split(b"\r\n")) - 1)
        non_ascii = [b for b in raw if b > 127]
        self.assertEqual(non_ascii, [], "launcher contains non-ASCII bytes")

    def test_still_names_the_icon_shortcut(self):
        """The shortcut is the only way the .cmd gets an icon, so the label
        and the CreateShortcut call must both survive edits."""
        with open(LAUNCHER, encoding="ascii") as f:
            text = f.read()
        self.assertIn(":make_lnk", text)
        self.assertIn("CreateShortcut", text)


class TestInterruptedUpdateRecovery(unittest.TestCase):
    """The launcher puts a half-applied update back before anything else runs.

    Pinned by reading the file rather than running it: reaching this branch in
    a test means building an install whose update was killed, and the launcher
    then carries on into the Python and dependency checks — so running it
    would test the whole first-run flow, not this branch. `update.recover()`
    is the tested implementation; this batch step is the pre-Python best
    effort, and its worst case is doing nothing at all.
    """

    def setUp(self):
        with open(LAUNCHER, encoding="ascii") as f:
            self.text = f.read()

    def test_it_runs_before_the_program_check(self):
        # A killed commit shows up as a missing app\\live.py (the move took the
        # old tree away), so the restore has to come first — otherwise the
        # player is told to re-extract the zip they already extracted.
        self.assertIn(".staging\\APPLYING", self.text)
        self.assertLess(self.text.index(".staging\\APPLYING"),
                        self.text.index('app\\live.py" goto'))

    def test_a_finished_update_is_never_undone(self):
        self.assertNotIn(".staging\\APPLIED", self.text)

    def test_it_restores_from_the_set_aside_copies(self):
        self.assertIn('xcopy /E /Y /I /Q "%~dp0.staging\\old\\*" "%~dp0"',
                      self.text)

    def test_it_leaves_the_marker_for_update_py(self):
        """Deleting the marker here would hide the interrupted state from the
        precise recovery, which is the one that also removes the files the new
        version added."""
        start = self.text.index("An earlier update was interrupted")
        end = self.text.index(":update_recovery_done", start)
        self.assertNotIn("del ", self.text[start:end])


class TestTheShortcutStepSpeaks(unittest.TestCase):
    """Answering Y to the shortcut prompt used to produce nothing at all.

    The helper printed only on FAILURE, so a player who asked for a shortcut
    could not tell whether they had one - and the first run is exactly when
    they are looking for it. Pinned by reading the file, like the recovery
    step, because running this branch means creating real shortcuts on the
    machine that runs the tests.
    """

    def setUp(self):
        with open(LAUNCHER, encoding="ascii") as f:
            self.text = f.read()

    def test_a_created_shortcut_is_confirmed(self):
        self.assertIn("if not errorlevel 1 echo Created:", self.text)

    def test_the_failure_path_still_speaks_too(self):
        self.assertIn("Could not create a shortcut", self.text)


@WIN_ONLY
class TestCheckModeWritesNothing(unittest.TestCase):
    """`--check` is the README's "look without touching", and it used to touch.

    Measured 2026-10-04, on the shipped launcher: `--check` installed a Python
    package, created a `.venv`, turned Hearthstone's file logging on — editing
    the game's own `log.config`, which lives outside the install folder — and
    then printed "nothing was started, nothing was written". The sentence was
    false every time it mattered.

    So this runs the REAL launcher end to end with the game's config folder
    redirected, having answered "yes" to every prompt it might ask. In check mode
    it must not ask at all, and the folder must still be empty afterwards. The
    "yes" is what makes this a regression test rather than a smoke test: without
    a guarded `--check`, feeding Y is exactly how the write happened.
    """

    def test_check_mode_leaves_the_games_config_alone(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = os.path.join(td, "hearthstone-config")
            os.makedirs(cfg)
            env = dict(os.environ, HEARTHSTONE_CONFIG_DIR=cfg)
            r = subprocess.run(f'cmd.exe /c ""{LAUNCHER}" --check"',
                               cwd=ROOT, capture_output=True, text=True,
                               timeout=300, input="Y\r\n" * 4, env=env)
            self.assertIn("nothing was written", r.stdout,
                          f"the launcher did not reach its report: {r.stdout[-400:]}")
            self.assertEqual(
                os.listdir(cfg), [],
                "--check wrote into Hearthstone's own config folder, which is "
                "outside the install folder and is not its to change")


if __name__ == "__main__":
    unittest.main()
