"""The release stamp bottom-right of the overlay.

A field report or a screenshot should name the release — the question every
bug report starts with — without anyone digging for it. The stamp is the
page's own "release: <version>", carried by EVERY payload (live, welcome,
game-over), read from `update.local_version()`, and the wording is a pure
function the suite runs under node, exactly like freshnessLine().
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
sys.path.insert(0, HERE)

import coach_ui  # noqa: E402
import update  # noqa: E402
import test_live_view  # noqa: E402  (the realistic analysis fixture)


def _function(name):
    m = re.search(rf"function {name}\(.*?\n\}}", coach_ui._HTML, re.S)
    return m.group(0) if m else None


class TestThePayloadCarriesTheRelease(unittest.TestCase):

    def test_the_welcome_payload_names_the_release(self):
        p = json.loads(coach_ui.welcome_payload())
        self.assertEqual(p["release"], update.local_version())

    def test_the_live_payload_names_the_release(self):
        out = coach_ui.render_json(test_live_view._analysis())
        self.assertEqual(out["release"], update.local_version())

    def test_the_analysis_itself_is_never_touched(self):
        """The same wall share sits behind: the stamp is a PAGE field, and
        the analysis is what decision_log.record() writes — the report
        whitelist refuses any key it does not name."""
        a = test_live_view._analysis()
        coach_ui.render_json(a)
        self.assertNotIn("release", a)

    def test_the_stamp_is_fed_by_both_render_paths(self):
        """A stamp fed by only one payload kind would vanish the moment the
        other kind is on screen — the share control needed both too."""
        calls = coach_ui._HTML.count("renderRelease(a.release)")
        self.assertGreaterEqual(calls, 2, "renderRelease is not called from "
                                          "both render paths")

    def test_the_page_has_the_element_and_its_css(self):
        self.assertIn('<div id="release-tag" hidden></div>', coach_ui._HTML)
        m = re.search(r"#release-tag \{[^}]*\}", coach_ui._HTML)
        self.assertIsNotNone(m, "the stamp's CSS is gone")
        self.assertIn("position:fixed", m.group(0))
        self.assertIn("pointer-events:none", m.group(0),
                      "the stamp is information, not a control — it must "
                      "take no clicks")


class TestTheWording(unittest.TestCase):
    """The page's own JS, run for real (skipped without node)."""

    def setUp(self):
        if shutil.which("node") is None:
            self.skipTest("node is not installed, so the page's script cannot "
                          "be executed")
        source = _function("releaseTag")
        self.assertIsNotNone(
            source, "releaseTag() is no longer a function in the page — the "
                    "wording has to stay testable")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        driver = os.path.join(self.tmp.name, "drive.js")
        with open(driver, "w", encoding="utf-8") as f:
            f.write(f"{source}\n"
                    f"const cases = {json.dumps(['33456e1', '', None])};\n"
                    "console.log(JSON.stringify("
                    "cases.map(v => releaseTag(v))));\n")
        proc = subprocess.run(["node", driver], capture_output=True,
                              text=True, timeout=30)
        self.assertEqual(proc.returncode, 0,
                         f"node could not run the page's JS: "
                         f"{proc.stderr[:300]}")
        self.out = json.loads(proc.stdout)

    def test_a_version_is_named_with_the_prefix(self):
        self.assertFalse(self.out[0]["hidden"])
        self.assertEqual(self.out[0]["text"], "release: 33456e1")

    def test_no_version_hides_the_stamp(self):
        for out in self.out[1:]:
            self.assertTrue(out["hidden"])
            self.assertEqual(out["text"], "")


if __name__ == "__main__":
    unittest.main()
