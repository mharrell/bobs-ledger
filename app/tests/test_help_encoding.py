"""Every tool's --help must survive a redirected console.

Python writes through the locale codec when stdout is not a console, so a
parser description carrying a glyph that cp1252 lacks kills `--help` with
UnicodeEncodeError instead of printing a line (found 2026-10-03 on
parse_minions.py, whose union glyph sits in the docstring that IS its help
text). The remedy is the `sys.stdout.reconfigure(errors="replace")` guard the
review tools already carry.

This test exists because that guard was added to parse_minions.py and the file
still failed — it needed an `import sys` too, and nothing here ran the parser.
A fix is not a fix until something exercises it.

Only tools at risk are run — description from the docstring AND a glyph cp1252
cannot encode — because that is the whole failure condition, and running all
forty tools would cost minutes for no extra signal.
"""
import glob
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def _unencodable(text):
    """Characters in `text` that a cp1252 console cannot print."""
    found = set()
    for ch in set(text):
        try:
            ch.encode("cp1252")
        except UnicodeEncodeError:
            found.add(ch)
    return found


def _risky_tools():
    """Tools whose --help text can carry a glyph cp1252 cannot encode."""
    risky = []
    for path in sorted(glob.glob(os.path.join(HERE, "*.py"))):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if "description=__doc__" in text and _unencodable(text):
            risky.append(path)
    return risky


class TestHelpSurvivesARedirectedConsole(unittest.TestCase):
    def test_the_at_risk_set_is_not_empty(self):
        """If this ever fails, the sweep below stopped testing anything and the
        test — not the tools — is what needs revisiting."""
        self.assertTrue(_risky_tools(),
                        "no tool takes its description from the docstring any "
                        "more, so this file is measuring nothing")

    def test_every_at_risk_tools_help_prints_and_exits_zero(self):
        for path in _risky_tools():
            with self.subTest(tool=os.path.basename(path)):
                # A pipe on stdout is the condition that used to raise: on a
                # console, Python writes wide characters instead. Popen as a
                # context manager rather than run(), so the pipes are closed
                # deterministically instead of by the garbage collector.
                with subprocess.Popen([sys.executable, path, "--help"],
                                      stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE) as proc:
                    out, err = proc.communicate(timeout=300)
                self.assertEqual(proc.returncode, 0,
                                 err.decode("utf-8", "replace")[-600:])
                self.assertIn(b"usage:", out)


if __name__ == "__main__":
    unittest.main()
