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


class TestGrowthCalibration(unittest.TestCase):
    """One-shot effects are tempo, not growth — a big one-shot battlecry must
    not outrank real repeating scaling (the 2026-09-01 consistency complaint:
    off-comp growth cards kept winning the shop ranking)."""

    def test_one_shot_battlecry_discounted(self):
        # En-Djinn Blazer: battlecry, +10/+10 to a random Tavern minion once.
        one_shot = value.growth_potential({"text": "battlecry: give a random "
                                                  "minion +10/+10."})
        self.assertEqual(one_shot, 1.0 + 10.0 / 4.0)  # trigger + discounted mag

    def test_repeating_trigger_keeps_full_magnitude(self):
        scaling = value.growth_potential({"text": "at the end of your turn, "
                                                  "give a minion +4/+4."})
        self.assertEqual(scaling, 2.0 + 4.0)  # end-of-turn trigger + full mag

    def test_committed_comp_damps_off_tribe_shop_cards(self):
        """Same off-tribe card, committed vs not committed: delta is exactly
        the damping."""
        comps = {"beasts": {"name": "Beasts", "tribe": "Beast",
                            "core": ["BG33_886"], "addons": []}}
        committed = [{"card": "BG33_886", "atk": 3, "health": 4, "tribe": "BEAST"},
                     {"card": "BG33_886", "atk": 3, "health": 4, "tribe": "BEAST"}]
        not_yet = [{"card": "BG29_503", "atk": 4, "health": 4, "tribe": "MECHANICAL"}]
        committed_rank = dict(shop_ranking(["BG29_503"], comps, board_minions=committed))
        not_yet_rank = dict(shop_ranking(["BG29_503"], comps, board_minions=not_yet))
        self.assertEqual(committed_rank["BG29_503"] - not_yet_rank["BG29_503"],
                         value.W_OFF_COMP)

    def test_neutral_cards_not_damped(self):
        comps = {"beasts": {"name": "Beasts", "tribe": "Beast",
                            "core": ["BG33_886"], "addons": []}}
        board = [{"card": "BG33_886", "atk": 3, "health": 4, "tribe": "BEAST"},
                 {"card": "BG33_886", "atk": 3, "health": 4, "tribe": "BEAST"}]
        scored = dict(shop_ranking(["BG33_886", "BG26_ICC_901"], comps,
                                   board_minions=board))
        # BG26_ICC_901 (Drakkari, no tribe) is exempt from damping; the comp
        # core card gets +10, so it outranks the neutral by more than that.
        self.assertGreater(scored["BG33_886"], scored["BG26_ICC_901"])


class TestTopMovePriority(unittest.TestCase):
    """Buy prices are tavern prices (minion = TIER, not mana cost) and are
    budgeted from the leftover after leveling; steps are numbered and the
    level leads."""

    def _analysis(self, tier, gold, buy_this, shop_rank):
        return {"board": [], "playable_comps": {}, "tier": tier,
                "gold": gold, "buy_this": buy_this, "shop_rank": shop_rank,
                "sell_rank": []}

    def test_steps_are_numbered_and_level_leads(self):
        line = top_move(self._analysis(2, 5, None, []))
        self.assertTrue(line.startswith("1. LEVEL"))

    def test_minion_priced_by_tier_not_mana_cost(self):
        """A minion whose TIER exceeds gold must not be suggested even if its
        (irrelevant) mana cost fits — the 2026-09-01 evening complaint."""
        # Shadow Rager: mana cost 3, tavern tier 4.
        cid = next(c for c, v in value._load_card_db().items()
                   if v.get("name") == "Shadow Rager")
        line = top_move(self._analysis(5, 3, cid, [(cid, 9.0)]))
        self.assertNotIn("Buy Shadow Rager", line)
        self.assertIn("roll", line)

    def test_buy_budgeted_from_leftover_after_leveling(self):
        """When leveling leads, buys must fit the LEFTOVER gold, not the purse:
        tier 5 (level costs 6) with 7 gold leaves 1 — a tier-2 minion doesn't
        fit; a tier-1 one does."""
        card_db = value._load_card_db()
        t1 = next(c for c, v in card_db.items() if v.get("tier") == 1)
        t2 = next(c for c, v in card_db.items() if v.get("tier") == 2)
        line = top_move(self._analysis(5, 7, t2, [(t2, 9.0), (t1, 5.0)]))
        self.assertIn(f"1. LEVEL to tier 6 — 1 left", line)
        self.assertNotIn(f"Buy {value._load_bg_names().get(t2, t2)} (", line)
        self.assertIn(f"Buy {value._load_bg_names().get(t1, t1)}", line)


class TestCompCards(unittest.TestCase):
    """The target-comp shopping list (UI/console box): names + owned flags."""

    def test_owned_flags_and_names(self):
        target = {"name": "Test Comp", "tribe": "Beast",
                  "core": ["BG33_886", "NOT_IN_ANY_DB"], "addons": ["BG33_140"]}
        board = [{"card": "BG33_886", "atk": 3, "health": 4, "tribe": "BEAST"}]
        tc = value.comp_cards(target, board)
        self.assertEqual(tc["name"], "Test Comp")
        core = {c["card"]: c for c in tc["core"]}
        self.assertTrue(core["BG33_886"]["owned"])
        self.assertEqual(core["BG33_886"]["name"], "Tusked Camper")  # BG-pool name
        self.assertFalse(core["NOT_IN_ANY_DB"]["owned"])
        self.assertEqual(core["NOT_IN_ANY_DB"]["name"], "NOT_IN_ANY_DB")  # id fallback

    def test_no_target_returns_none(self):
        self.assertIsNone(value.comp_cards(None, []))


if __name__ == "__main__":
    unittest.main()