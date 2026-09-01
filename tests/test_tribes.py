"""Golden tests for tribes.py — the canonical tribe vocabulary."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tribes import ALL_TRIBES, DISPLAY_TRIBES, canon, is_banned, normalize


class TestNormalize(unittest.TestCase):
    def test_raw_log_values(self):
        self.assertEqual(normalize("ELEMENTAL"), "Elemental")
        self.assertEqual(normalize("MECHANICAL"), "Mech")
        self.assertEqual(normalize("QUILBOAR"), "Quilboar")

    def test_already_canonical_is_idempotent(self):
        for t in DISPLAY_TRIBES:
            self.assertEqual(normalize(t), t)

    def test_legacy_plural_forms(self):
        # The pre-canonicalization comps.json vocabulary must still normalize.
        self.assertEqual(normalize("Elementals"), "Elemental")
        self.assertEqual(normalize("Mechs"), "Mech")
        self.assertEqual(normalize("Murlocs"), "Murloc")

    def test_compound(self):
        self.assertEqual(normalize("DEMON/QUILBOAR"), "Demon/Quilboar")
        self.assertEqual(normalize("Demon/Dragon"), "Demon/Dragon")
        self.assertEqual(normalize("Mech/Murloc"), "Mech/Murloc")

    def test_never_banned_markers_and_none(self):
        self.assertIsNone(normalize("All"))
        self.assertIsNone(normalize("ALL"))
        self.assertIsNone(normalize("Neutral"))
        self.assertIsNone(normalize("NEUTRAL"))
        self.assertIsNone(normalize(None))
        self.assertIsNone(normalize(""))


class TestCanon(unittest.TestCase):
    def test_mech_special_case(self):
        self.assertEqual(canon("MECHANICAL"), "Mech")

    def test_round_trip_over_all_tribes(self):
        for t in ALL_TRIBES:
            self.assertEqual(canon(t), t.title() if t != "MECHANICAL" else "Mech")

    def test_all_tribes_map_to_display(self):
        self.assertEqual(sorted(DISPLAY_TRIBES),
                         sorted(canon(t) for t in ALL_TRIBES))


class TestIsBanned(unittest.TestCase):
    def test_allowed_tribe_not_banned(self):
        self.assertFalse(is_banned("ELEMENTAL", ["Elemental", "Beast"]))
        self.assertFalse(is_banned("Elemental", ["Beast", "Elemental"]))

    def test_banned_tribe(self):
        self.assertTrue(is_banned("ELEMENTAL", ["Beast", "Mech"]))

    def test_compound_either_half_allowed(self):
        self.assertFalse(is_banned("Demon/Quilboar", ["Quilboar"]))
        self.assertTrue(is_banned("Demon/Quilboar", ["Beast"]))

    def test_fail_open_on_unknown_and_no_info(self):
        self.assertFalse(is_banned(None, ["Beast"]))
        self.assertFalse(is_banned("Elemental", None))   # no ban info
        self.assertFalse(is_banned("WEIRDRACE", ["Beast"]))


if __name__ == "__main__":
    unittest.main()