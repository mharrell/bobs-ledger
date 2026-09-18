"""Regression tests for the 2026-09-16 evening + 2026-09-17 review gates:

- DYING hard gate: an affordable LEVEL is still not advice at <=12 eff HP
  (t16 last night: "LEVEL to tier 6 — 1 left after" at 8 HP; the player
  followed it and died 3rd).
- Cast gold gate: hand-spell casts spend the spell price and demote to a
  hold when the purse can't cover them after the plan's buy ("Cast Tavern
  Coin" led plans at gold 0 three games running).
- Comp-flip persistence: no cross-tribe flip while DYING, and no
  evidence-free flip onto a board with a single tribe unit (t16: Mechs ->
  Nagas on one Fauna Whisperer).
- Forecast honesty: estimates carry "~" + anchor age; "favored" caps to
  "ahead on paper" at <=10 effective HP.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from value import (combat_forecast, sticky_comp_target, top_move,
                   _load_spell_db)

BEASTS = {"name": "Beasts - Tasty Lobstah", "tribe": "Beast",
          "core": ["BG25_354", "BG36_202"]}
NAGAS = {"name": "Nagas - End Of Turn/Spell Buff", "tribe": "Naga",
         "core": ["BG36_204", "BG31_803"]}


def _analysis(**over):
    a = {"tier": 4, "gold": 10, "level_cost": 7, "health": 8, "armor": 0,
         "turn": 16, "damage_last": None, "loss_streak": 0,
         "board": [], "shop_rank": [], "buy_this": None,
         "playable_comps": {}, "choice": None, "sell_rank": [],
         "target_comp": None, "target_cards": None,
         "hand_plan": []}
    a.update(over)
    return a


class TestDyingHardGate(unittest.TestCase):
    def test_affordable_level_after_buy_stays_deferred(self):
        """t16 regression: dying at 8 HP, the level IS affordable after the
        buy — the plan must still render the deferred form, never the
        actionable 'LEVEL to tier N — X left after'."""
        a = _analysis(buy_this="BG25_016", shop_rank=[("BG25_016", 20.0)])
        tm = top_move(a)
        self.assertNotIn("LEVEL to tier", tm)
        self.assertIn("LEVEL next turn (too fragile to level first)", tm)

    def test_short_level_form_unchanged(self):
        """A dying plan whose buy leaves the level short keeps the short
        form (gold 8 arms the ladder, the 3g buy leaves it 2 short)."""
        a = _analysis(gold=8, buy_this="BG25_016",
                      shop_rank=[("BG25_016", 20.0)])
        tm = top_move(a)
        self.assertIn("LEVEL next turn (too fragile to level first)", tm)
        self.assertIn("short after the buy", tm)

    def test_healthy_board_still_gets_actionable_level(self):
        """Same shape at healthy HP: the affordable level is still advised."""
        a = _analysis(health=20, armor=0, buy_this="BG25_016",
                      shop_rank=[("BG25_016", 20.0)])
        # 20 HP + a behind-board flip? No loss streak, no damage — the
        # level-lead path: assert the actionable form leads.
        tm = top_move(a)
        self.assertIn("LEVEL to tier 5", tm)


class TestCastGoldGate(unittest.TestCase):
    def _spell_id(self):
        for cid, v in _load_spell_db().items():
            if isinstance(v.get("cost"), int) and v["cost"] >= 1:
                return cid
        self.fail("no priced spell in the DB")

    def test_gold_zero_demotes_cast(self):
        """The evening bug: gold 0, the plan's only step was 'Cast X'."""
        cid = self._spell_id()
        a = _analysis(gold=0, hand_plan=[
            {"card": cid, "name": "Test Spell", "verb": "cast",
             "score": 5.0, "why": None}])
        tm = top_move(a)
        self.assertNotIn("1. Cast", tm)
        self.assertIn("no gold", tm)

    def test_cast_may_not_eat_the_committed_buy(self):
        """A cast that would outspend the plan's buy demotes with its price."""
        cid = self._spell_id()
        cost = _load_spell_db()[cid]["cost"]
        # gold covers the 3g buy + cost-1: the cast is 1 short of the
        # post-buy purse, so it must demote while the buy stays.
        a = _analysis(gold=2 + cost, buy_this="BG25_016",
                      shop_rank=[("BG25_016", 20.0)],
                      hand_plan=[
                          {"card": cid, "name": "Test Spell", "verb": "cast",
                           "score": 5.0, "why": None}])
        tm = top_move(a)
        self.assertIn("Buy ", tm)
        self.assertIn("needs", tm)

    def test_funded_cast_survives(self):
        """'Castable NOW', not a ban: a funded cast keeps its step."""
        cid = self._spell_id()
        cost = _load_spell_db()[cid]["cost"]
        a = _analysis(gold=10 + cost, shop_rank=[("BG25_016", 20.0)],
                      hand_plan=[
                          {"card": cid, "name": "Test Spell", "verb": "cast",
                           "score": 5.0, "why": None}])
        tm = top_move(a)
        self.assertIn("1. Cast Test Spell", tm)


class TestStickyFlipRules(unittest.TestCase):
    def test_dying_blocks_cross_tribe_flip_even_with_evidence(self):
        """Equal hits, empty board — nothing stronger to take over with."""
        self.assertIs(
            sticky_comp_target(BEASTS, NAGAS, 2, 2, board=[], dying=True),
            BEASTS)

    def test_dying_takes_over_on_dominant_board(self):
        """2026-09-18 regression: a triple-golden Mech core at 4 HP stayed
        labeled "Nagas" all game — the dying flip freeze outlived its
        evidence. Equal hits + the new comp's tribe is a board majority
        while the prev's isn't = a commit correction, not churn."""
        mechs = {"name": "Mechs - Magnetics/Spells", "tribe": "Mech",
                 "core": ["BG26_152", "BG35_883", "BG36_853"]}
        board = [{"card": "BG26_152", "tribe": "Mech"},
                 {"card": "BG36_853", "tribe": "Mech"},
                 {"card": "BG35_883", "tribe": "Mech"},
                 {"card": "BG36_506", "tribe": "Mech"},
                 {"card": "BG32_837", "tribe": "Naga"},
                 {"card": "BG32_837", "tribe": "Naga"}]
        self.assertIs(
            sticky_comp_target(NAGAS, mechs, 2, 2, board=board, dying=True),
            mechs)

    def test_dying_still_holds_on_minority_evidence(self):
        """Equal hits, the new comp a minority of the board (the t16
        one-Naga-on-a-Beast-board shape): the freeze holds."""
        board = [{"card": "X", "tribe": "Naga"},
                 {"card": "Y", "tribe": "Beast"},
                 {"card": "Y2", "tribe": "Beast"},
                 {"card": "Y3", "tribe": "Beast"},
                 {"card": "Y4", "tribe": "Beast"}]
        self.assertIs(
            sticky_comp_target(BEASTS, NAGAS, 2, 2, board=board, dying=True),
            BEASTS)

    def test_dying_flips_on_strictly_more_evidence(self):
        self.assertIs(
            sticky_comp_target(BEASTS, NAGAS, 0, 2,
                               board=[{"card": "Y", "tribe": "Beast"}],
                               dying=True),
            NAGAS)

    def test_single_unit_board_blocks_evidence_free_flip(self):
        board = [{"tribe": "Naga"}, {"tribe": "Beast"},
                 {"tribe": "Beast"}, {"tribe": "Beast"}]
        self.assertIs(
            sticky_comp_target(BEASTS, NAGAS, 0, 0, board=board,
                               dying=False),
            BEASTS)

    def test_two_units_flip(self):
        board = [{"tribe": "Naga"}, {"tribe": "Naga"},
                 {"tribe": "Beast"}]
        self.assertIs(
            sticky_comp_target(BEASTS, NAGAS, 0, 0, board=board,
                               dying=False),
            NAGAS)

    def test_stronger_evidence_flips_without_units(self):
        board = [{"tribe": "Beast"}]
        self.assertIs(
            sticky_comp_target(BEASTS, NAGAS, 0, 2, board=board,
                               dying=False),
            NAGAS)


class TestForecastHonesty(unittest.TestCase):
    def test_favored_fresh_anchor_unchanged(self):
        fc = combat_forecast({"board_stats": 895, "opp_stats": 165,
                              "health": 30, "armor": 0, "board": []})
        self.assertEqual(fc, "favored — 895 vs 165")

    def test_low_hp_caps_favored(self):
        """'favored' at <=10 eff HP read as a guarantee (t12/t16 deaths)."""
        fc = combat_forecast({"board_stats": 895, "opp_stats": 165,
                              "health": 4, "armor": 0, "board": []})
        self.assertTrue(fc.startswith("ahead on paper"), fc)

    def test_estimate_carries_tilde_and_age(self):
        fc = combat_forecast({"board_stats": 679, "lobby_opp": 54,
                              "opp_age": 2, "health": 30, "armor": 0,
                              "board": []})
        self.assertEqual(fc, "favored — 679 vs ~54, seen 2 rounds ago")

    def test_close_and_behind_carry_marks_too(self):
        fc = combat_forecast({"board_stats": 40, "baseline_opp": 90,
                              "opp_age": 1, "health": 30, "armor": 0,
                              "board": []})
        self.assertIn("behind — 40 vs ~90, seen 1 round ago", fc)


if __name__ == "__main__":
    unittest.main()
