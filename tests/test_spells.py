"""Spell buy advice: tavern spells are ranked in the shop, priced per gold,
and credited as fuel for cast-spell engines (Glambot/Nomi/Felboar).

Historical gap: spells were the player's most common buys, but shop advice
covered minions only — replay review could only label spell-only turns as
"not covered".
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import value
from value import _spell_effect, _spell_fuel_bonus, _spell_score, shop_ranking, top_move

NAMES = value._load_bg_names()
SPELLS = value._load_spell_db()

FLAG_ID = next((sid for sid, s in SPELLS.items() if s["name"] == "Alliance Flag"), None)
GLAMBOT_ID = next((cid for cid, n in NAMES.items()
                   if "glambot" in (n or "").lower()), None)


def _spell(text, cost=1, name="Test Spell"):
    return {"id": "TEST_1", "name": name, "tier": 1, "cost": cost, "text": text}


class TestSpellEffect(unittest.TestCase):
    def test_choose_one_takes_best_branch_not_sum(self):
        """'+3/+1; or +1/+3' resolves ONE branch — 4 stat points, not 8."""
        self.assertEqual(_spell_effect(_spell("Choose One - Give a minion "
                                              "+3/+1; or\n+1/+3.")), 4.0)

    def test_plain_buff_counts_both_stats(self):
        self.assertEqual(_spell_effect(_spell("Give a minion +2/+2.")), 4.0)

    def test_board_wide_scope_scales_with_board_size(self):
        solo = _spell_effect(_spell("Give your minions +1/+1."), board_size=1)
        full = _spell_effect(_spell("Give your minions +1/+1."), board_size=7)
        self.assertEqual(solo, 2.0)
        self.assertEqual(full, 14.0)

    def test_scaling_text_is_worth_more(self):
        once = _spell_effect(_spell("Give a minion +2/+2."))
        repeat = _spell_effect(_spell("At the end of your turn, "
                                      "give a minion +2/+2."))
        self.assertEqual(repeat, once * 2.0)

    def test_cost_efficiency(self):
        """The same effect at cost 1 outscores cost 5."""
        cheap = _spell_score(_spell("Give a minion +3/+1.", cost=1), [], NAMES)
        pricey = _spell_score(_spell("Give a minion +3/+1.", cost=5), [], NAMES)
        self.assertAlmostEqual(cheap, pricey * 5.0)


@unittest.skipUnless(GLAMBOT_ID, "Glambot missing from the BG pool")
class TestSpellFuel(unittest.TestCase):
    def _glambot_board(self):
        return [{"card": GLAMBOT_ID, "atk": 4, "health": 4,
                 "tribe": "MECHANICAL"}]

    def test_fuel_fires_on_a_cast_spell_engine(self):
        fuel = _spell_fuel_bonus(self._glambot_board(), NAMES,
                                 {"cast_spell": 3})
        # Glambot magnetizes a 4/4 per spell: one more cast = +8 stats.
        self.assertEqual(fuel, 8.0)

    def test_no_fuel_without_the_engine(self):
        board = [{"card": "BG33_886", "atk": 3, "health": 4, "tribe": "BEAST"}]
        self.assertEqual(_spell_fuel_bonus(board, NAMES, {"cast_spell": 3}), 0.0)

    def test_no_fuel_with_no_board(self):
        self.assertEqual(_spell_fuel_bonus([], NAMES, {"cast_spell": 3}), 0.0)

    def test_fuel_boosts_a_spell_score(self):
        board = self._glambot_board()
        off = _spell_score(_spell("Give a minion +3/+1."), [], NAMES,
                           {"cast_spell": 3})
        on = _spell_score(_spell("Give a minion +3/+1."), board, NAMES,
                          {"cast_spell": 3})
        self.assertAlmostEqual(on - off,
                               value.W_SPELL_FUEL * 8.0)


@unittest.skipUnless(FLAG_ID, "Alliance Flag missing from tavern_spells.json")
class TestShopRankingSpells(unittest.TestCase):
    def test_spell_ranked_alongside_minions(self):
        ranked = shop_ranking([FLAG_ID, "BG33_886"], {},
                              board_minions=[], scenario={"cast_spell": 4})
        self.assertEqual({cid for cid, _ in ranked}, {FLAG_ID, "BG33_886"})

    def test_unknown_ids_still_skipped_silently(self):
        ranked = shop_ranking([FLAG_ID, "NOT_IN_ANY_DB"], {},
                              board_minions=[], scenario={"cast_spell": 4})
        self.assertEqual([cid for cid, _ in ranked], [FLAG_ID])

    def test_engine_board_ranks_spell_above_plain_body(self):
        """A running Glambot makes ANY spell worth more than a filler body —
        the spell converts gold into engine growth."""
        assert GLAMBOT_ID
        board = [{"card": GLAMBOT_ID, "atk": 4, "health": 4,
                  "tribe": "MECHANICAL"}]
        ranked = shop_ranking([FLAG_ID, "BG33_886"], {},
                              board_minions=board, scenario={"cast_spell": 4})
        self.assertEqual(ranked[0][0], FLAG_ID)


@unittest.skipUnless(FLAG_ID, "Alliance Flag missing from tavern_spells.json")
class TestTopMoveSpells(unittest.TestCase):
    def _analysis(self, gold):
        return {
            "board": [],
            "playable_comps": {},
            "tier": 2,
            "gold": gold,
            "buy_this": FLAG_ID,
            "shop_rank": [(FLAG_ID, 4.0)],
            "sell_rank": [],
        }

    def test_buy_spell_line_and_intention(self):
        line = top_move(self._analysis(gold=5))
        self.assertIn("Buy Alliance Flag", line)
        self.assertIn("tempo", line)  # plain stat buff intention

    def test_cannot_afford_spell_falls_back(self):
        line = top_move(self._analysis(gold=0))
        self.assertNotIn("Buy Alliance Flag", line)
        self.assertIn("roll", line)


if __name__ == "__main__":
    unittest.main()