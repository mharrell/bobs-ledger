"""The patch-coverage gate: the change list vs the meta DB.

`check_meta.py` validates the meta DB against itself. This pins the OTHER
direction: every card the patch's change list labels must be reflected in the DB
(new/changed/returning present, removed in the registry), or be recorded as an
accepted gap with evidence.

The counts are asserted against the doc's own headings on purpose. The first run
of this tool parsed 34 of the 35 removed minions because the pair-packed table's
odd trailing row was not being read, and audited a shorter list than the change
list without saying so — a coverage tool that hides its blind spots is worse than
no tool. These assertions are what stop that happening silently again.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import check_patch_db  # noqa: E402

#: What analysis/patch_3661_changes.md's headings claim (reviewed by hand).
EXPECTED_COUNTS = {
    "new_minions": 38,
    "changed_minions": 7,
    "removed_minions": 35,
    "returning_minions": 25,
    "new_spells": 3,
    "removed_spells": 2,
    "returning_spells": 1,
    "new_heroes": 2,
}

ACCEPTED_GAP_NAMES = {"C'Thun", "Sha of Fear", "Greedy Conniver",
                      "Sewer Escapee"}


class TestPatchDbCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = check_patch_db.audit()

    def test_doc_was_found(self):
        self.assertTrue(os.path.basename(self.result["doc"]).startswith("patch_"))
        self.assertTrue(os.path.basename(self.result["doc"]).endswith(
            "_changes.md"))

    def test_no_unparsed_sections(self):
        """Every section must parse in full — a short list is a silent gap."""
        self.assertEqual(self.result["unparsed"], [])

    def test_every_section_matches_its_stated_count(self):
        for key, want in EXPECTED_COUNTS.items():
            self.assertIn(key, self.result["sections"])
            self.assertEqual(len(self.result["sections"][key]), want,
                             f"{key}: parsed {len(self.result['sections'][key])}"
                             f" of {want}")

    def test_no_unrecorded_gaps(self):
        self.assertEqual(self.result["problems"], [])

    def test_the_four_known_gaps_are_recorded_with_evidence(self):
        got = {name for name, _ in self.result["accepted"]}
        self.assertEqual(got, ACCEPTED_GAP_NAMES)
        for _name, entry in self.result["accepted"]:
            self.assertTrue(entry.get("reason"), "a gap needs a reason")
            self.assertTrue(entry.get("evidence"),
                            "a gap needs the evidence that closed the question")

    def test_seafood_stew_is_now_in_the_db(self):
        """The one returning spell that WAS missing (no id in any log).

        It was sourced from the local hearthstonejson cache instead: BG32_337,
        techLevel 3, cost 2. It must not regress to an accepted gap.
        """
        import meta
        names = {s["name"] for s in meta._raw("tavern_spells.json") or []}
        self.assertIn("Seafood Stew", names)
        self.assertNotIn("Seafood Stew",
                         {n for n, _ in self.result["accepted"]})


if __name__ == "__main__":
    unittest.main()
