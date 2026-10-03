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

    Anchored on the code that assigns ARG1 (the comments above it mention the
    variable, so they are skipped) and runs up to the line that consumes the
    result. Anchoring on text the file really contains means the test fails
    loudly if that block is ever restructured, instead of quietly testing
    nothing.
    """
    with open(LAUNCHER, encoding="ascii") as f:
        lines = f.read().splitlines()
    start = stop = None
    for i, line in enumerate(lines):
        if start is None and not line.startswith("rem") and "ARG1=" in line:
            start = i
        elif start is not None and line.startswith('set "WANT_SHORTCUT='):
            stop = i
            break
    if start is None or stop is None:
        raise AssertionError(
            "could not find the ARG1 block in the launcher - this test needs "
            "updating, not deleting")
    return lines[start:stop]


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


if __name__ == "__main__":
    unittest.main()
