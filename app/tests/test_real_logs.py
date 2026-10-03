"""The rule that decides which real log the machine-dependent tests use.

This is the fix for a suite that failed (and crawled) while Hearthstone was
open: the tests took the newest log on the machine, which is a file the game
was still writing. The rule itself is worth pinning, so it is tested here with
temp files rather than by hoping a real log happens to exist.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import real_logs  # noqa: E402


def _log(directory, name, size=10, mtime=None):
    path = os.path.join(directory, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class TestNewestSettled(unittest.TestCase):
    def test_the_newest_finished_session_wins(self):
        with tempfile.TemporaryDirectory() as td:
            old = _log(td, os.path.join("Logs", "Hearthstone_a", "Power.log"),
                       mtime=1000)
            newer = _log(td, os.path.join("Logs", "Hearthstone_b", "Power.log"),
                         mtime=2000)
            with mock.patch.object(real_logs, "HS_LOG_GLOBS",
                                   (os.path.join(td, "Logs", "Hearthstone_*",
                                                 "Power.log"),)), \
                    mock.patch.object(real_logs, "SETTLE_SECONDS", 180):
                # Both are long finished relative to now.
                self.assertEqual(real_logs.newest_settled(), newer)
                self.assertNotEqual(real_logs.newest_settled(), old)

    def test_a_log_being_written_right_now_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            live = _log(td, os.path.join("Logs", "Hearthstone_live",
                                         "Power.log"))
            with mock.patch.object(real_logs, "HS_LOG_GLOBS",
                                   (os.path.join(td, "Logs", "Hearthstone_*",
                                                 "Power.log"),)):
                self.assertIsNone(real_logs.newest_settled())
                self.assertIn("still being written", real_logs.why_none())

    def test_a_small_settled_log_is_preferred_over_a_huge_one(self):
        with tempfile.TemporaryDirectory() as td:
            huge = _log(td, os.path.join("Logs", "Hearthstone_huge",
                                         "Power.log"),
                        size=50, mtime=2000)
            _log(td, os.path.join("Logs", "Hearthstone_small", "Power.log"),
                 size=10, mtime=1000)
            with mock.patch.object(real_logs, "HS_LOG_GLOBS",
                                   (os.path.join(td, "Logs", "Hearthstone_*",
                                                 "Power.log"),)), \
                    mock.patch.object(real_logs, "MAX_BYTES", 20):
                chosen = real_logs.newest_settled()
            self.assertNotEqual(chosen, huge)
            self.assertIn("Hearthstone_small", chosen)

    def test_a_huge_log_is_still_used_when_it_is_the_only_one(self):
        with tempfile.TemporaryDirectory() as td:
            huge = _log(td, os.path.join("Logs", "Hearthstone_huge",
                                         "Power.log"),
                        size=50, mtime=1000)
            with mock.patch.object(real_logs, "HS_LOG_GLOBS",
                                   (os.path.join(td, "Logs", "Hearthstone_*",
                                                 "Power.log"),)), \
                    mock.patch.object(real_logs, "MAX_BYTES", 20):
                self.assertEqual(real_logs.newest_settled(), huge)

    def test_no_logs_at_all_says_so(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(real_logs, "HS_LOG_GLOBS",
                                   (os.path.join(td, "nope", "*.log"),)):
                self.assertEqual(real_logs.all_logs(), [])
                self.assertIsNone(real_logs.newest_settled())
                self.assertIn("no Hearthstone session log", real_logs.why_none())

    def test_both_known_shapes_are_searched(self):
        """A Mac may write a flat Logs/Power.log, so the search cannot be the
        session-directory pattern alone."""
        with tempfile.TemporaryDirectory() as td:
            flat = _log(td, os.path.join("Logs", "Power.log"), mtime=1000)
            with mock.patch.object(real_logs, "HS_LOG_GLOBS",
                                   (os.path.join(td, "Logs", "Hearthstone_*",
                                                 "Power.log"),
                                    os.path.join(td, "Logs", "Power.log"))):
                self.assertEqual(real_logs.all_logs(), [flat])


if __name__ == "__main__":
    unittest.main()
