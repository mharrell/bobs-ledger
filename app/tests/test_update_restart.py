"""The restart after an update must survive a path with spaces in it.

live.py used to restart itself with os.execv(sys.executable, [sys.executable,
os.path.abspath(__file__)] + sys.argv[1:]). On Windows the execv family joins
that argument list with spaces and NO quoting at all, so an install under
C:\\Users\\<name with a space>\\Downloads\\Bob's Ledger was restarted with the
path truncated at the first space:

    C:\\Python312\\python.exe: can't open file 'C:\\Users\\Silver':
    [Errno 2] No such file or directory

The player saw that on every update, and because the update itself had applied
correctly, the next launch found nothing to do and simply worked - which is why
it looked like "I have to start the coach several times" (2026-10-04). This is
the shape of test the launcher's own bugs get: the behaviour cannot be exercised
without a real update, so the invariant that prevents it is pinned instead.
"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

LIVE = os.path.join(HERE, "live.py")


class TestTheUpdateRestart(unittest.TestCase):
    def setUp(self):
        with open(LIVE, encoding="utf-8") as f:
            self.text = f.read()

    def test_it_does_not_use_the_exec_family(self):
        """Nothing in live.py may use os.exec*, on any platform: the reason is
        Windows quoting, and a future call would read as harmless."""
        for name in ("os.execv", "os.execve", "os.execl", "os.execvp",
                     "os.spawnv"):
            self.assertNotIn(name, self.text, f"{name} does not quote its "
                                             f"arguments on Windows")

    def test_it_restarts_through_subprocess_with_a_list(self):
        self.assertIn("subprocess.run([sys.executable, os.path.abspath(__file__)]",
                      self.text)

    def test_the_mechanism_actually_survives_a_space(self):
        """Proof that the replacement is the right one, run for real: an
        argument containing spaces arrives intact through subprocess, which is
        the whole point of the change."""
        spaced = os.path.join(os.sep, "Users", "A Name With Spaces", "x.py")
        proc = subprocess.run(
            [sys.executable, "-c", "import sys; print(sys.argv[1])", spaced],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.stdout.strip(), spaced)


if __name__ == "__main__":
    unittest.main()
