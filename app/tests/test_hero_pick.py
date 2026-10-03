"""The hero pick panel must always show what a hero DOES.

Two cases drove this: the 36.6.1 heroes (Drest'agath, Kith'ix) have no hsreplay
pick rate yet but are guaranteed in every game until 2026-10-06, so the player
meets them constantly; and `_rank_heroes` used to return an empty reason for any
hero without a rate, leaving the panel's power column blank exactly when the
player has nothing else to go on.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import choices  # noqa: E402
import meta  # noqa: E402


def _heroes():
    return {h["name"]: h for h in (meta._raw("heroes.json") or [])}


class TestNewHeroesInTheDb(unittest.TestCase):
    def test_both_36_6_1_heroes_are_present_with_power_text(self):
        db = _heroes()
        for name, power in (("Drest'agath",
                             "Discard a card to get a random Aberration."),
                            ("Kith'ix",
                             "Get 2 random minions. When you play one, discard "
                             "the other.")):
            self.assertIn(name, db)
            self.assertEqual(db[name]["hero_power"], power)

    def test_they_carry_no_invented_pick_rate(self):
        db = _heroes()
        for name in ("Drest'agath", "Kith'ix"):
            self.assertIsNone(db[name]["pick_rate"],
                              "no population data exists — must stay null")


class TestUnrankedHeroesStillExplainThemselves(unittest.TestCase):
    def test_new_hero_is_unranked_but_shows_its_power(self):
        ranked = dict((n, (s, w)) for n, _c, s, w in choices._rank_heroes(
            [("Drest'agath", "BG36_HERO_000")]))
        score, why = ranked["Drest'agath"]
        self.assertIsNone(score)
        self.assertIn("random Aberration", why)

    def test_a_rated_hero_outranks_an_unrated_one_but_both_show_text(self):
        out = choices._rank_heroes([("Drest'agath", "BG36_HERO_000"),
                                    ("Reno Jackson", "TB_BaconShop_HERO_41")])
        self.assertEqual(out[0][0], "Reno Jackson")
        self.assertIsNotNone(out[0][2])
        for _name, _cid, _score, why in out:
            self.assertTrue(why, "every ranked hero must carry its power text")

    def test_an_unknown_hero_keeps_the_empty_row(self):
        out = choices._rank_heroes([("No Such Hero", "BG00_HERO_000")])
        self.assertEqual(out, [("No Such Hero", "BG00_HERO_000", None, "")])


if __name__ == "__main__":
    unittest.main()
