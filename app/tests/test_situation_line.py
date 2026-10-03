"""The mortality clause must survive the situation line's 3-clause budget.

Two bugs from the 2026-09-22 morning session, both about the line the player
reads while deciding whether to stabilise:

- `situation_line` appends its danger clause LAST and then truncates to three
  clauses, so the one clause that changes the decision ("one bad fight ends it,
  buy board now") was dropped exactly when it was about to matter: game 1 t9 at
  7 HP rendered "Demons build — scaling · behind (100 vs ~166) · lost 3
  straight" and the player died in that fight.
- Its damage-cap branch was unreachable above 2 effective HP, because the parser
  only read the cap from the bare-numeric GameEntity spelling while the log
  escalates it on the named one (see tests/test_board_state.py for that half).
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import value  # noqa: E402


def _analysis(**kw):
    # target_comp is the comp NAME string ("<Tribe> - <variant>"), which is what
    # _tribe_of splits on.
    base = {"turn": 9, "target_comp": "Demons - Shop Buff",
            "target_state": "committing", "board_stats": 100,
            "opp_stats": 166, "loss_streak": 3, "health": 7, "armor": 0,
            "damage_cap": 15}
    base.update(kw)
    return base


class TestMortalitySurvivesTruncation(unittest.TestCase):
    def test_cap_clause_is_kept_when_it_would_be_fourth(self):
        line = value.situation_line(_analysis())
        self.assertIsNotNone(line)
        self.assertIn("one bad fight ends it", line)
        self.assertLessEqual(len(line.split(" · ")), 3)

    def test_dying_clause_is_kept_when_it_would_be_fourth(self):
        # No cap in play, so the eff-HP branch is the one that fires.
        line = value.situation_line(_analysis(damage_cap=None, health=9))
        self.assertIn("DYING at 9", line)

    def test_the_three_clause_budget_still_holds(self):
        line = value.situation_line(_analysis())
        self.assertEqual(len(line.split(" · ")), 3)

    def test_a_short_line_is_unchanged(self):
        line = value.situation_line({"turn": 5, "target_comp": None,
                                     "board_stats": 100, "opp_stats": 166,
                                     "health": 7, "armor": 0,
                                     "damage_cap": 15, "loss_streak": 0})
        self.assertEqual(line, "behind (100 vs 166) · 7 HP vs a 15 damage cap — "
                               "one bad fight ends it, buy board now")


class TestDamageCapBands(unittest.TestCase):
    def test_under_the_cap_is_the_lethal_warning(self):
        line = value.situation_line(_analysis(health=10, armor=5,
                                             damage_cap=15))
        self.assertIn("one bad fight ends it", line)

    def test_within_twice_the_cap_is_the_two_fight_warning(self):
        line = value.situation_line(_analysis(health=25, armor=0,
                                             damage_cap=15))
        self.assertIn("two lost fights end it", line)

    def test_a_stale_cap_of_two_used_to_hide_the_warning(self):
        """Regression guard for the parser bug this paired with.

        With the cap frozen at 2 the first band needs eff HP <= 2, so a 7 HP
        player fell through to the DYING branch (or, with lobby < 100, to no
        clause at all). A real cap of 15 must take the cap branch.
        """
        line = value.situation_line(_analysis(health=7, damage_cap=15))
        self.assertIn("vs a 15 damage cap", line)
        self.assertNotIn("DYING", line)
