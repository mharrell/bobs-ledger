"""The macOS launcher: format and structure invariants only.

The Windows twin is exercised for real - this machine has cmd.exe, so
test_launcher_args.py actually runs it. Nothing here can do that for the
.command: the packaging machine has no bash and no WSL distro, so this file
has never been parsed by a shell, let alone run. These tests pin what is
checkable from Python (byte format, ordering, the mistakes the Windows
launcher already made once) and CANNOT catch a runtime bug. Only a Mac can.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import config        # noqa: E402
import privacy_scan  # noqa: E402

LAUNCHER = os.path.join(ROOT, "Start Bob's Ledger.command")


def _bytes():
    with open(LAUNCHER, "rb") as f:
        return f.read()


def _text():
    with open(LAUNCHER, encoding="utf-8", newline="") as f:
        return f.read()


@unittest.skipUnless(os.path.exists(LAUNCHER), "no macOS launcher")
class TestLauncherFormat(unittest.TestCase):
    def test_it_is_the_registered_launcher_name(self):
        self.assertIn(os.path.basename(LAUNCHER), config.LAUNCHERS)

    def test_lf_only(self):
        """One CR makes bash die with "$'\\r': command not found" - the exact
        mirror of the CRLF rule the .cmd has to obey."""
        self.assertNotIn(b"\r", _bytes())

    def test_pure_ascii(self):
        _bytes().decode("ascii")

    def test_shebang(self):
        self.assertTrue(_text().startswith("#!/bin/bash\n"))

    def test_no_bash4_only_syntax(self):
        """macOS /bin/bash is still 3.2: no associative arrays, no mapfile,
        no ${var,,} case folding, no ;& fallthrough."""
        text = _text()
        for bash4 in ("declare -A", "mapfile", "${BASH_SOURCE[0],,}",
                      ";;&", ";&", "${!PASS", "${PASS,,}"):
            self.assertNotIn(bash4, text)

    def test_empty_array_expansion_is_guarded(self):
        """`set -u` plus bash 3.2 makes an empty ${arr[@]} an unbound-variable
        error, so the pass-through has to be length-guarded."""
        text = _text()
        self.assertIn("set -u", text)
        self.assertIn("${#PASS[@]}", text)

    def test_every_read_survives_end_of_input(self):
        """set -u and a closed stdin would otherwise kill the launcher at its
        last prompt, after the coach had already run."""
        for line in _text().splitlines():
            if "read -r" in line:
                self.assertIn("||", line, f"unguarded read: {line.strip()}")


@unittest.skipUnless(os.path.exists(LAUNCHER), "no macOS launcher")
class TestLauncherBehaviour(unittest.TestCase):
    """Ordering claims, checked against the text. The Windows launcher got
    two of these wrong in ways only a real double-click revealed."""

    def test_it_runs_from_its_own_folder(self):
        """A double-click starts it wherever Finder feels like, and the coach
        is found relative to this file."""
        self.assertIn('cd "$(dirname "$0")"', _text())

    def test_the_missing_program_check_comes_first(self):
        """Telling someone to install Python when the real problem is an
        unextracted zip wastes their time."""
        text = _text()
        self.assertLess(text.index("app/live.py\" ]"),
                        text.index("command -v python3"))

    def test_check_never_starts_the_coach(self):
        """--check silently STARTING the coach was a real bug in the Windows
        launcher, so the reporting branch must exit before the run."""
        text = _text()
        check_at = text.index("--check*)")
        live_at = text.index("app/live.py\" --open")
        self.assertLess(check_at, live_at)
        self.assertIn("exit 0", text[check_at:live_at])

    def test_check_matches_a_prefix(self):
        """A shell handing over "--check=" missed the exact match once and
        started the coach instead of reporting."""
        self.assertIn("--check*)", _text())

    def test_it_asks_before_installing_and_before_editing(self):
        text = _text()
        self.assertGreaterEqual(text.count("[y/N]"), 3,
                                "expected a prompt for Python, pip and "
                                "log.config")
        self.assertIn("app/requirements.txt", text)
        self.assertIn("setup_logging.py", text)
        self.assertIn("--apply", text)

    def test_dependencies_go_into_a_venv(self):
        """Homebrew's Python refuses a system-wide pip install (PEP 668), and
        the venv is also where the Windows launcher looks first."""
        text = _text()
        self.assertIn("-m venv", text)
        self.assertIn(".venv/bin/python3", text)

    def test_macos_paths_and_no_windows_leftovers(self):
        text = _text()
        self.assertIn("/Applications/Hearthstone/Logs", text)
        self.assertIn("Library/Preferences/Blizzard/Hearthstone", text)
        for windows in ("%LOCALAPPDATA%", "OneDrive", "tasklist", ".lnk",
                        "powershell"):
            self.assertNotIn(windows, text)

    def test_it_says_it_is_unverified(self):
        """The file has never been run. Anyone reading it deserves to know
        before they trust it with their log.config."""
        self.assertIn("NOT YET VERIFIED ON A MAC", _text())

    def test_the_privacy_gate_scans_it_clean(self):
        """find() returns a mapping of findings, so an empty mapping is the
        clean result - the launcher is the most-copied file in the project."""
        findings = privacy_scan.find(_text())
        self.assertFalse(findings, f"the launcher carries personal data: "
                                   f"{findings}")


@unittest.skipUnless(os.path.exists(LAUNCHER), "no macOS launcher")
class TestGitPreservesTheLineEndings(unittest.TestCase):
    """The byte-format rules above are only real if version control keeps
    them. core.autocrlf is true on the machine that wrote this, and the first
    commit warned that a checkout would hand macOS a CRLF `.command` - which
    bash rejects on the first line. `.gitattributes` is what prevents that, so
    both launcher rules are load-bearing and are pinned here."""

    def _rules(self):
        with open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8") as f:
            return [line.split("#")[0].strip() for line in f]

    def test_the_macos_launcher_stays_lf_through_a_checkout(self):
        self.assertIn("*.command text eol=lf", self._rules())

    def test_the_windows_launcher_stays_crlf_through_a_checkout(self):
        self.assertIn("*.cmd text eol=crlf", self._rules())


if __name__ == "__main__":
    unittest.main()
