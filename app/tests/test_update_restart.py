"""The restart after an update must survive a path with spaces in it.

live.py used to restart itself through os.execv, passing the interpreter and
this file's absolute path as a list. On Windows the execv family joins that list
with spaces and no quoting, so an install inside a user folder whose name
contains a space was restarted with the path cut short at the first space, and
Python answered:

    can't open file '<the path up to the first space>': [Errno 2] No such file
    or directory

The player saw it on every update, and because the update itself HAD applied,
the next launch found nothing to do and simply worked. That is why it looked
like "I have to start the coach several times" (2026-10-04).

The real behaviour cannot be exercised without a real update, so this pins the
invariant instead. The check reads the module's AST rather than its text: the
first version grepped for "os.execv" and failed on the COMMENT that explains why
os.execv is not used, which is a test measuring prose.
"""
import ast
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

LIVE = os.path.join(HERE, "live.py")


def _calls_in_live():
    """Every attribute name live.py actually CALLS, comments excluded."""
    with open(LIVE, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)
    return called


class TestTheUpdateRestart(unittest.TestCase):
    def test_nothing_uses_the_exec_or_spawn_family(self):
        """Those do not quote their arguments on Windows, and a future call
        would read as harmless. Comments and docstrings are excluded on
        purpose: they are where the reason is written down."""
        called = _calls_in_live()
        for name in ("execv", "execve", "execl", "execlp", "execvp", "execle",
                     "spawnv", "spawnl", "system", "popen"):
            self.assertNotIn(name, called, f"{name}() does not quote its "
                                           f"arguments on Windows")

    def test_it_restarts_through_subprocess_with_a_list(self):
        with open(LIVE, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("subprocess.run([sys.executable, os.path.abspath(__file__)]",
                      text)

    def test_an_argument_from_a_folder_with_spaces_arrives_intact(self):
        """The mechanism the fix relies on, run for real: a spaced path handed
        to subprocess as one list element comes back whole. This is what the
        exec family failed to do, so it is worth one subprocess to prove."""
        spaced = os.sep.join([os.sep + "Users", "A Name With Spaces", "x.py"])
        proc = subprocess.run(
            [sys.executable, "-c", "import sys; print(sys.argv[1])", spaced],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.stdout.strip(), spaced)


if __name__ == "__main__":
    unittest.main()
