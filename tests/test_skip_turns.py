"""Golden tests for turn-structure hero powers (a power that skips opening turns).

The bug this pins down: the guard was

    if turn == 1 and "skip your first turn" in hp.lower():

which A. F. Kay's wording ("Skip your first **two** turns, then Discover...")
does not contain, so BOTH of her skipped turns rendered a full, unexecutable
plan — "1. LEVEL (access to tier 2) · 2. Buy Buzzing Vermin" on t1 and
"1. LEVEL (access to tier 2)" again on t3 (2026-09-21 A. F. Kay win, quoted from
the live decision log). A hardcoded `== 1` would have missed t2 even after a
substring fix, so the count is parsed from the curated power text.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import meta  # noqa: E402
import value  # noqa: E402


def _power(hero_name):
    for h in meta._raw("heroes.json") or []:
        if h.get("name") == hero_name:
            return h.get("hero_power")
    raise AssertionError(f"{hero_name} not in meta/heroes.json")


class TestSkippedTurnCount(unittest.TestCase):
    def test_worded_count(self):
        self.assertEqual(value._skipped_turn_count(
            "Skip your first two turns, then Discover a minion from Tier 3 "
            "and Tier 4."), 2)

    def test_bare_wording_means_one(self):
        self.assertEqual(value._skipped_turn_count(
            "Skip your first turn. Discover minions from Tiers 6, 4, and 2 to "
            "get at those Tiers."), 1)

    def test_digit_count(self):
        self.assertEqual(
            value._skipped_turn_count("Skip your first 3 turns."), 3)

    def test_other_powers_skip_nothing(self):
        self.assertEqual(value._skipped_turn_count(
            "Every 4 turns, Discover a minion with a Dark Gift. "
            "(3 turns left!)"), 0)

    def test_missing_text_is_zero_not_a_crash(self):
        self.assertEqual(value._skipped_turn_count(""), 0)
        self.assertEqual(value._skipped_turn_count(None), 0)

    def test_the_two_real_heroes(self):
        """Read the shipped DB, not the wording I chose in this file."""
        self.assertEqual(value._skipped_turn_count(_power("A. F. Kay")), 2)
        self.assertEqual(
            value._skipped_turn_count(_power("Ambassador Faelin")), 1)


class TestTopMovePassesTheSkippedTurns(unittest.TestCase):
    def _move(self, hero, turn):
        analysis = {"turn": turn, "hero": hero, "hero_power": _power(hero),
                    "tier": 1, "gold": None, "board": [], "shop": [], "hand": []}
        return value.top_move(analysis)

    def _line(self, hero, turn):
        move = self._move(hero, turn)
        return move[0] if isinstance(move, (list, tuple)) else move

    def test_af_kay_passes_both_skipped_turns_then_plans(self):
        for turn in (1, 2):
            self.assertIn("pass", self._line("A. F. Kay", turn).lower(),
                          f"turn {turn} must be a pass")
            self.assertIn(f"turn {turn}",
                          self._line("A. F. Kay", turn).lower())
        # Turn 3 is hers to act on — the guard must not swallow it.
        self.assertNotIn("pass", self._line("A. F. Kay", 3).lower())

    def test_faelin_passes_only_turn_one(self):
        self.assertIn("pass", self._line("Ambassador Faelin", 1).lower())
        self.assertNotIn("pass", self._line("Ambassador Faelin", 2).lower())

    def test_the_pass_line_names_the_hero(self):
        self.assertIn("A. F. Kay", self._line("A. F. Kay", 1))


if __name__ == "__main__":
    unittest.main()
