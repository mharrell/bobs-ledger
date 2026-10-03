"""Two startup-path fixes that were found by reading output, not code.

Both were silent: `logquery.py` ran every query against the newest log no
matter which path you gave it, and `warn_stale_meta` cried wolf on a current
DB. Neither raised, so neither had a test. These pin them.
"""
import argparse
import contextlib
import datetime
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import live  # noqa: E402
import logquery  # noqa: E402


class TestLogqueryArguments(unittest.TestCase):
    """A path may come before OR after the options, and must be honoured."""

    def test_reorder_accepts_either_order(self):
        want = ["stats", "C:/x.log", "--turn", "5"]
        self.assertEqual(logquery._reorder(["stats", "C:/x.log", "--turn", "5"]),
                         want)
        self.assertEqual(logquery._reorder(["stats", "--turn", "5", "C:/x.log"]),
                         want)

    def test_reorder_keeps_an_option_with_its_value(self):
        # `--turn 5` must not be mistaken for the path.
        self.assertEqual(
            logquery._reorder(["stats", "--game", "2", "--turn", "5",
                               "C:/x.log"]),
            ["stats", "C:/x.log", "--game", "2", "--turn", "5"])
        self.assertEqual(logquery._reorder(["games", "--top", "5"]),
                         ["games", "--top", "5"])

    def test_latest_is_an_option_not_a_positional_value(self):
        # argparse reads any --token as an option, so `board --latest` could
        # never have been a positional value.
        self.assertEqual(logquery._reorder(["board", "--latest"]),
                         ["board", "--latest"])
        args = logquery._build_parser().parse_args(["board", "--latest"])
        self.assertTrue(args.latest)
        self.assertIsNone(args.log)

    def test_the_path_actually_reaches_args(self):
        """The bug: the positional was declared twice, the empty second one
        parsed last and wiped the path, so every query silently used the
        newest log."""
        args = logquery._build_parser().parse_args(
            logquery._reorder(["stats", "--turn", "5", "C:/x.log"]))
        self.assertEqual(args.log, "C:/x.log")

    def test_there_is_exactly_one_log_positional(self):
        parser = logquery._build_parser()
        positionals = [a for a in parser._actions
                       if not a.option_strings and a.dest == "log"]
        self.assertEqual(len(positionals), 1,
                         "duplicate `log` positionals share a dest and the "
                         "last one wins")


class TestStaleMetaWarning(unittest.TestCase):
    """The roster decides; the patch-check latch is only a fallback."""

    def _meta(self, roster=None, latch=None):
        d = tempfile.mkdtemp()
        if roster is not None:
            with open(os.path.join(d, "pool_roster.json"), "w",
                      encoding="utf-8") as f:
                json.dump(roster, f)
        if latch is not None:
            with open(os.path.join(d, ".patch_state.json"), "w",
                      encoding="utf-8") as f:
                json.dump(latch, f)
        return d

    def _warn(self, meta_dir):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            live.warn_stale_meta(meta_dir)
        return buf.getvalue()

    def _days_ago(self, days):
        return (datetime.date.today()
                - datetime.timedelta(days=days)).isoformat()

    def test_a_current_roster_is_silent_even_with_a_stale_latch(self):
        d = self._meta(roster={"patch": "36.6.1", "built": self._days_ago(0)},
                       latch={"last_checked": self._days_ago(40),
                              "last_title": "36.4.2 Patch Notes"})
        self.assertEqual(self._warn(d), "",
                         "the stale latch made the warning fire on a "
                         "current DB")

    def test_an_old_roster_warns_and_names_the_patch(self):
        d = self._meta(roster={"patch": "36.6.1", "built": self._days_ago(30)})
        out = self._warn(d)
        self.assertIn("NOTE:", out)
        self.assertIn("36.6.1", out)
        self.assertIn("30 days ago", out)

    def test_the_latch_is_used_when_no_roster_exists(self):
        d = self._meta(latch={"last_checked": self._days_ago(30),
                              "last_title": "36.4.2 Patch Notes"})
        self.assertIn("NOTE:", self._warn(d))

    def test_no_meta_at_all_is_silent(self):
        self.assertEqual(self._warn(self._meta()), "")


if __name__ == "__main__":
    unittest.main()
