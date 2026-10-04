"""What the overlay tells the player when the advice stops changing.

This line is the README's answer to "is this advice live or stale?" — "The overlay
says how long ago it was written, so you can tell stale advice from live advice."
It answered wrongly: advice older than 8 seconds was reported as

    Advice from 1 min ago — is live.py still running? (it is frozen, not live)

and the gap between buy phases is a **median 81 seconds** over 13 real buy phases
(10 of 12 gaps over the threshold). So for most of the time a tester had the
overlay open it accused a working coach of being wedged — and when the coach
really did stop, the identical sentence appeared, which made the line carry no
information at all and name an internal file at the player.

The rule now lives in one pure function, `freshnessLine()`, so it can be RUN
instead of read: these tests extract it from the served page and execute it with
node. Values come from the page's own constants, so changing the thresholds
changes what is tested. If node is not installed the tests skip and say why.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed

import coach_ui  # noqa: E402

#: (age of the advice in seconds, seconds since the coach last answered)
CASES = ((3, 0), (30, 0), (90, 0), (200, 0), (900, 0), (0, 10), (90, 10))


def _const(name):
    m = re.search(rf"const {name} = (\d+);", coach_ui._HTML)
    return int(m.group(1)) if m else None


def _function(name):
    m = re.search(rf"function {name}\(.*?\n\}}", coach_ui._HTML, re.S)
    return m.group(0) if m else None


class TestTheFreshnessRule(unittest.TestCase):
    """The page's own JS, run for real."""

    def setUp(self):
        if shutil.which("node") is None:
            self.skipTest("node is not installed, so the page's script cannot "
                          "be executed")
        source = _function("freshnessLine")
        self.assertIsNotNone(
            source, "freshnessLine() is no longer a function in the page — the "
                    "rule has to stay testable")
        for name in ("STALE_AFTER", "LOST_AFTER"):
            self.assertIsNotNone(_const(name), f"const {name} is gone")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        driver = os.path.join(self.tmp.name, "drive.js")
        with open(driver, "w", encoding="utf-8") as f:
            f.write(f"const STALE_AFTER = {_const('STALE_AFTER')};\n"
                    f"const LOST_AFTER = {_const('LOST_AFTER')};\n"
                    f"{source}\n"
                    f"const cases = {json.dumps(CASES)};\n"
                    "console.log(JSON.stringify("
                    "cases.map(c => freshnessLine(c[0], c[1]))));\n")
        proc = subprocess.run(["node", driver], capture_output=True, text=True,
                              timeout=30)
        self.assertEqual(proc.returncode, 0,
                         f"node could not run the page's JS: {proc.stderr[:300]}")
        self.lines = json.loads(proc.stdout)
        self.by_case = dict(zip(CASES, self.lines))

    def test_fresh_advice_says_nothing(self):
        line = self.by_case[(3, 0)]
        self.assertFalse(line["alarm"])
        self.assertEqual(line["text"], "")

    def test_old_advice_is_stated_not_accused(self):
        """The measured false alarm: 90 seconds of combat is NORMAL."""
        line = self.by_case[(90, 0)]
        self.assertFalse(line["alarm"],
                         "a healthy coach mid-combat must not be reported as "
                         "frozen")
        self.assertIn("next shop", line["text"])

    def test_only_a_silent_coach_alarms(self):
        """No answer at all is the one thing that means the coach is gone."""
        line = self.by_case[(90, 10)]
        self.assertTrue(line["alarm"])
        self.assertIn("Lost contact", line["text"])

    def test_a_coach_that_never_answered_alarms_too(self):
        line = self.by_case[(0, 10)]
        self.assertTrue(line["alarm"])

    def test_the_players_screen_never_names_an_internal_file(self):
        for case, line in self.by_case.items():
            with self.subTest(case=case):
                self.assertNotIn("live.py", line["text"])
                self.assertNotIn("frozen", line["text"])

    def test_the_age_is_readable(self):
        self.assertEqual(self.by_case[(30, 0)]["text"].count("30s"), 1)
        self.assertIn("1 min", self.by_case[(90, 0)]["text"])
        self.assertIn("3 min", self.by_case[(200, 0)]["text"])


if __name__ == "__main__":
    unittest.main()
