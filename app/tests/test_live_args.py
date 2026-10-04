"""The coach's own command line.

`--poll 0.5` is the form `live.py`'s usage line and README:172 both document, and
it killed the coach at startup:

    IndexError: list index out of range   (live.py, main)

Splitting argv on the leading `--` put the VALUE in the positional list, so
"--poll" reached `float(o.split("=")[1])` with no "=" to split, and "0.5" was
then taken for the log path. Only `--poll=0.5` ever worked. Nothing in the suite
parsed a command line, which is why it survived from the day the flag was added
(found 2026-10-04).

Both halves are pure functions now, so they are tested rather than eyeballed.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed

import live  # noqa: E402


class TestParseArgv(unittest.TestCase):
    def test_the_documented_space_form_keeps_its_value(self):
        """`live.py <log> --poll 0.5` - the line that used to raise."""
        args, opts = live._parse_argv(["Power.log", "--poll", "0.5"])
        self.assertEqual(args, ["Power.log"])
        self.assertEqual(opts, ["--poll=0.5"])

    def test_the_equals_form_still_works(self):
        args, opts = live._parse_argv(["--poll=0.5"])
        self.assertEqual(args, [])
        self.assertEqual(opts, ["--poll=0.5"])

    def test_flags_and_paths_keep_their_order_independent_meanings(self):
        args, opts = live._parse_argv(
            ["--no-ui", "C:/logs/Power.log", "--poll", "2", "--no-share"])
        self.assertEqual(args, ["C:/logs/Power.log"])
        self.assertEqual(set(opts), {"--no-ui", "--no-share", "--poll=2"})

    def test_a_flag_after_the_value_is_not_swallowed(self):
        """`--poll` followed by another flag has no value to take."""
        args, opts = live._parse_argv(["--poll", "--no-ui"])
        self.assertEqual(args, [])
        self.assertEqual(opts, ["--poll", "--no-ui"])

    def test_an_empty_command_line_is_fine(self):
        self.assertEqual(live._parse_argv([]), ([], []))

    def test_a_path_containing_dashes_survives(self):
        """Only a LEADING `--` makes a flag."""
        args, _ = live._parse_argv(["C:/my-logs/--odd/Power.log"])
        self.assertEqual(args, ["C:/my-logs/--odd/Power.log"])


class TestPollSeconds(unittest.TestCase):
    def test_the_default_is_the_sub_second_cadence(self):
        self.assertEqual(live._poll_seconds([]), 0.3)

    def test_a_value_is_taken_from_either_spelling(self):
        self.assertEqual(live._poll_seconds(["--poll=0.5"]), 0.5)
        self.assertEqual(
            live._poll_seconds(live._parse_argv(["--poll", "2.5"])[1]), 2.5)

    def test_a_missing_value_says_what_it_wanted(self):
        """Not IndexError: this runs before the overlay exists, so a traceback
        here IS the whole first run."""
        with self.assertRaises(SystemExit) as caught:
            live._poll_seconds(["--poll"])
        self.assertIn("number of seconds", str(caught.exception))

    def test_a_value_that_is_not_a_number_says_so(self):
        with self.assertRaises(SystemExit) as caught:
            live._poll_seconds(["--poll=banana"])
        self.assertIn("banana", str(caught.exception))

    def test_zero_or_negative_is_refused(self):
        for bad in ("--poll=0", "--poll=-1"):
            with self.subTest(bad=bad):
                with self.assertRaises(SystemExit):
                    live._poll_seconds([bad])


if __name__ == "__main__":
    unittest.main()
