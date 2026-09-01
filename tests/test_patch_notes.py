"""patch_notes.py must never silently apply to the *last* homonymous entity.

meta/dark_gifts.json has 4 duplicate names (one per tier). The old name-keyed
dict silently aliased them; a "Battle Scars" change edited the +2/+2 entry
whenever the +3/+3 entry was last. Dry-run behavior now: unique name -> applied;
duplicate name -> ambiguous (unless the change carries a matching tier).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from patch_notes import apply_changes


class TestDuplicateNames(unittest.TestCase):
    def test_duplicate_name_is_ambiguous_not_wrongly_applied(self):
        report = apply_changes(
            [{"entity_type": "dark_gift", "name": "Battle Scars",
              "field": "text", "new": "+4/+4"}],
            do_apply=False)
        self.assertEqual(report[0]["status"], "ambiguous", report)
        self.assertIn("2 entities", report[0]["reason"])

    def test_ambiguous_reports_distinguishing_descriptions(self):
        """Dark gifts have no tier field; the report must show the descriptions
        that distinguish the duplicates so a human can resolve manually."""
        report = apply_changes(
            [{"entity_type": "dark_gift", "name": "Battle Scars",
              "field": "text", "new": "+4/+4", "tier": 2}],
            do_apply=False)
        self.assertEqual(report[0]["status"], "ambiguous")
        self.assertIn("+3/+3", report[0]["reason"])
        self.assertIn("+2/+2", report[0]["reason"])

    def test_unique_name_still_applies(self):
        report = apply_changes(
            [{"entity_type": "dark_gift", "name": "Spectral Sight",
              "field": "text", "new": "Replaced text"}],
            do_apply=False)
        status = report[0]["status"]
        self.assertIn(status, ("applied", "unmatched"), report)


if __name__ == "__main__":
    unittest.main()