"""The console must not call a finished session "live".

The coach attaches to the newest Power.log on the machine, which is what makes
reviewing a game after the fact possible. But it printed that line as
"live-coaching <path>" whatever the file's age, so the very first launch on a
machine that had played before announced an 18-hour-old session as live while
the overlay (correctly) sat on its welcome state — the console and the window
disagreed, and the console was wrong (2026-10-03, first run).

These tests pin the note that says so, and its absence when the session really
is live.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import live  # noqa: E402

NOW = 1_800_000_000.0


class TestLogAgeNote(unittest.TestCase):
    def _log(self, td, age_seconds):
        path = os.path.join(td, "Power.log")
        with open(path, "w", encoding="utf-8") as f:
            f.write("x\n")
        stamp = NOW - age_seconds
        os.utime(path, (stamp, stamp))
        return path

    def test_a_live_session_gets_no_note(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(live.log_age_note(self._log(td, 5), now=NOW))

    def test_the_recent_window_is_the_boundary(self):
        """Inside LIVE_RECENT is live; at or beyond it is not."""
        with tempfile.TemporaryDirectory() as td:
            recent = int(os.environ.get("LIVE_RECENT", "600"))
            self.assertIsNone(live.log_age_note(self._log(td, recent - 1),
                                                now=NOW))
            self.assertIsNotNone(live.log_age_note(self._log(td, recent),
                                                   now=NOW))

    def test_a_finished_session_is_named_as_one(self):
        with tempfile.TemporaryDirectory() as td:
            note = live.log_age_note(self._log(td, 18 * 3600), now=NOW)
            self.assertIn("18 h", note)
            self.assertIn("last game", note)
            self.assertIn("waiting for a new game", note)

    def test_the_age_reads_in_units_a_person_uses(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIn("45 min", live.log_age_note(self._log(td, 45 * 60),
                                                      now=NOW))
            self.assertIn("3 d", live.log_age_note(self._log(td, 3 * 86400),
                                                   now=NOW))

    def test_no_log_means_no_note(self):
        """The caller prints its own "waiting for a Power.log" line there."""
        self.assertIsNone(live.log_age_note(None, now=NOW))


if __name__ == "__main__":
    unittest.main()
