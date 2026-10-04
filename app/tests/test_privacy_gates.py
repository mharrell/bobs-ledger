"""The two publish gates, and the categories they are made of.

Two holes, both measured on 2026-10-04:

* Deleting an ENTIRE category from privacy_scan passed all 1252 tests. No test in
  78 files named a category — every one asserted an empty result, and a detector
  that returns nothing always passes a test that expects nothing. The first test
  here names each category and asserts the NON-empty answer.
* publish_release's two gates were entered by no test at all: `privacy_gate` and
  `reproducibility_gate` are reachable only from `main()`, which nothing calls.
  They are the controls that decide whether a beta build ships, and they were
  themselves unverified. These tests call them directly, on zips built in memory.

What is NOT covered here, deliberately: `main()`'s own invocation, because the
reproducibility gate reads the real working tree and a developer with uncommitted
changes would see it fail. That is a run-it-by-hand check, not a test.
"""
import io
import os
import sys
import unittest
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed

import privacy_scan       # noqa: E402
import publish_release    # noqa: E402

#: Assembled at runtime, like test_friendly_player.py: this file ships, and a
#: handle-shaped literal or a real-looking session directory in it is exactly
#: what these gates flag. Both are obvious fakes at runtime and invisible to the
#: scanner as literals.
_HANDLE = "Stranger" + "#" + "9821"
_NAME = "Stranger" + "Name"
_PATH = "C:" + "\\Users\\" + "Somebody" + "\\Power.log"
_SESSION = "Hearthstone_" + "2026_10_04_11_36_38"
_ACCOUNT = "GameAccountId=[hi=" + "123456789" + " lo=" + "987654321]"

#: One fixture per category privacy_scan can report. The point is that each one
#: must come back NAMED — a category that silently stops firing has nothing else
#: in this suite to notice.
CATEGORY_CASES = (
    ("battletag", f"a tag: {_HANDLE}"),
    ("account_id", f"Player EntityID=11 PlayerID=4 {_ACCOUNT}"),
    ("user_path", f"loaded {_PATH}"),
    ("session_dir", f"session {_SESSION}"),
    ("player_name", f"PlayerName={_NAME}"),
    ("player_entity", f"TAG_CHANGE Entity={_NAME} tag=RESOURCES value=3"),
)


def _zip(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in entries.items():
            z.writestr(name, body)
    return buf.getvalue()


class TestEveryCategoryCanFire(unittest.TestCase):
    def test_each_category_is_reported_by_name(self):
        for category, text in CATEGORY_CASES:
            with self.subTest(category=category):
                found = privacy_scan.find(text)
                self.assertIn(category, found, f"{text!r} -> {found}")
                self.assertTrue(found[category],
                                f"{category} was reported but empty")

    def test_is_clean_disagrees_with_every_one(self):
        for category, text in CATEGORY_CASES:
            with self.subTest(category=category):
                self.assertFalse(privacy_scan.is_clean(text), category)

    def test_the_categories_the_gate_relies_on_are_all_covered(self):
        """Guard against this file drifting behind the detector."""
        fired = set()
        for _category, text in CATEGORY_CASES:
            fired |= set(privacy_scan.find(text))
        self.assertEqual(fired, {"battletag", "account_id", "user_path",
                                 "session_dir", "player_name", "player_entity"})


class TestThePublishGatesRun(unittest.TestCase):
    def test_the_privacy_gate_names_the_file_that_is_dirty(self):
        data = _zip({"notes.md": f"PlayerName={_NAME}\n",
                     "clean.md": "nothing personal here\n"})
        hits = publish_release.privacy_gate(data)
        self.assertEqual([name for name, _ in hits], ["notes.md"])
        self.assertIn("player_name", hits[0][1])

    def test_the_privacy_gate_passes_a_clean_zip(self):
        self.assertEqual(
            publish_release.privacy_gate(_zip({"a.md": "fine\n"})), [])

    def test_the_gate_scans_the_launchers(self):
        """The most-copied files in the project, and once unscanned.

        Both launchers were scannable only after `.cmd` and `.command` were added
        to the suffix list; they are the files a user is most likely to open.
        """
        for name in ("Start Bob's Ledger.cmd", "Start Bob's Ledger.command"):
            with self.subTest(name=name):
                self.assertEqual(
                    [n for n, _ in publish_release.privacy_gate(
                        _zip({name: f"rem {_HANDLE}\n"}))], [name])

    def test_the_reproducibility_gate_catches_an_untracked_entry(self):
        stray = publish_release.reproducibility_gate(
            _zip({"scratch_notes_not_in_git.md": "x"}))
        self.assertEqual(stray, ["scratch_notes_not_in_git.md"])

    def test_the_reproducibility_gate_accepts_a_tracked_file(self):
        self.assertEqual(
            publish_release.reproducibility_gate(_zip({"README.md": "x"})), [])

    def test_the_reproducibility_gate_accepts_the_generated_stamps(self):
        """VERSION and .update_state.json are written by the publish script."""
        entries = {name: "x" for name in publish_release.GENERATED}
        self.assertEqual(publish_release.reproducibility_gate(_zip(entries)), [])


if __name__ == "__main__":
    unittest.main()
