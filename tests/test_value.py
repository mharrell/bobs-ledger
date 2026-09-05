"""Regression tests for the value function's tribe handling.

The historical bug: comps.json ("Elementals"), minions.json ("ELEMENTAL") and
bans.canon() ("Elemental") never intersected, so W_TRIBE never fired, the
banned-tribe penalty hit every minion, and _best_comp returned the first comp
in the file. These tests pin the corrected behavior.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import value
from value import _best_comp, minion_value, sell_recommendation

EL = "BG33_886"   # Tusked Camper (Beast, t1) — present in the real BG pool
MECH = "BG29_503"  # a real mech in minions.json if present; tests skip if not


def _card(cid, atk=3, health=4):
    return value._load_card_db().get(cid) or {
        "name": cid, "race": "Beast", "attack": atk, "health": health,
        "mechanics": [], "text": "",
    }


class TestBestComp(unittest.TestCase):
    COMPS = {
        "mech-ladder": {"name": "Mech", "tribe": "Mech", "core": [], "addons": []},
        "beast-pack": {"name": "Beast", "tribe": "Beast", "core": [], "addons": []},
    }

    def test_matches_board_tribes_not_dict_order(self):
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}]
        self.assertIs(_best_comp(board, self.COMPS), self.COMPS["beast-pack"])

    def test_no_fit_returns_none(self):
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": None}]
        self.assertIsNone(_best_comp(board, self.COMPS))

    def test_legacy_plural_comps_still_match(self):
        comps = {"beast-pack": {"name": "Beast", "tribe": "Beasts",
                                "core": [], "addons": []}}
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}]
        self.assertIs(_best_comp(board, comps), comps["beast-pack"])


class TestWTribe(unittest.TestCase):
    def test_w_tribe_fires_for_matching_comp(self):
        m = {"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}
        card = _card(EL)
        base = minion_value(m, card, None)
        # Card NOT in the comp's core/addons: the only difference is W_TRIBE.
        same = minion_value(m, card, {"tribe": "Beast", "core": [], "addons": []})
        other = minion_value(m, card, {"tribe": "Mech", "core": [], "addons": []})
        self.assertEqual(same - base, value.W_TRIBE)
        self.assertEqual(other - base, 0.0)

    def test_traditionally_failing_legacy_comp_tribe(self):
        """A comp still carrying the legacy plural must still get the bonus
        (normalize handles it) — and the raw-log board minion matches it."""
        m = {"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}
        card = _card(EL)
        base = minion_value(m, card, None)
        legacy = minion_value(m, card, {"tribe": "Beasts", "core": [], "addons": []})
        self.assertEqual(legacy - base, value.W_TRIBE)


class TestBannedPenalty(unittest.TestCase):
    def test_penalty_only_for_actually_banned_tribes(self):
        """Same minion, two games: Beast allowed vs Beast banned. Delta is
        exactly the penalty."""
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}]
        allowed = dict(sell_recommendation(board, [], allowed_tribes=["Beast"]))
        banned = dict(sell_recommendation(board, [], allowed_tribes=["Mech"]))
        self.assertEqual(banned[EL] - allowed[EL], -2.0)

    def test_no_penalty_without_ban_info(self):
        """allowed_tribes=None (= no ban data) must not penalize anyone — the
        old fail-closed behavior penalized every minion in every game."""
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": "BEAST"}]
        ranked = sell_recommendation(board, [], allowed_tribes=None)
        ranked_empty = sell_recommendation(board, [], allowed_tribes=[])
        self.assertEqual(ranked, ranked_empty)

    def test_compound_tribe_playable_if_either_half_allowed(self):
        board = [{"card": EL, "atk": 3, "health": 4, "tribe": "DEMON/BEAST"}]
        penalized = dict(sell_recommendation(board, [], allowed_tribes=["Mech"]))
        clean = dict(sell_recommendation(board, [], allowed_tribes=["Beast"]))
        self.assertEqual(penalized[EL] - clean[EL], -2.0)


if __name__ == "__main__":
    unittest.main()

class TestNoEvidenceNoComp(unittest.TestCase):
    """A target comp requires EVIDENCE (2026-09-04 live note: "already has
    a recommended comp listed from the beginning of the game, which is
    unrealistic"). No board commit and no recent core buys -> None — the
    coach says nothing instead of inventing a checklist comp."""

    def test_no_evidence_no_comp(self):
        comps = {"a": {"name": "A", "meta_tier": "A", "core": [], "addons": []},
                 "b": {"name": "B", "meta_tier": "B", "core": [], "addons": []}}
        self.assertIsNone(value.comp_target([], comps))

    def test_one_board_core_is_not_a_commit(self):
        comps = {"nagas": {"name": "Nagas", "core": ["BG33_140"], "addons": []}}
        self.assertIsNone(value.comp_target([{"card": "BG33_140"}], comps))

    def test_board_copies_commit(self):
        """2x one core is a commit (copies count, same as a pivot)."""
        comps = {"nagas": {"name": "Nagas", "core": ["BG33_140"], "addons": []}}
        board = [{"card": "BG33_140"}, {"card": "BG33_140"}]
        self.assertIs(value.comp_target(board, comps), comps["nagas"])


class TestHandPlan(unittest.TestCase):
    """Hand plays the coach never made (2026-09-04: five spells sat in hand
    that would 10x the board's stats while the coach said nothing). Casting
    from hand is free, a stuck minion plays free — each is pure profit."""

    BANANA = "BG28_897"   # Tavern Dish Banana: give a minion +2/+2 (t1 spell)
    MINION = "BG33_140"   # River Skipper, a tier-1 body

    def test_casts_and_plays_carry_verbs(self):
        hand = [{"card": self.BANANA, "type": "spell"},
                {"card": self.MINION, "type": "minion",
                 "atk": 2, "health": 2}]
        steps = value.hand_plan(hand, board_minions=[])
        self.assertTrue(steps)
        self.assertEqual(steps[0]["verb"], "cast")
        self.assertEqual(steps[0]["card"], self.BANANA)
        self.assertIn("play", [s["verb"] for s in steps])

    def test_engine_fuel_boosts_a_cast(self):
        """A running cast-spell engine turns every cast into compounding
        growth — the spell scores higher and says so."""
        spell = [{"card": self.BANANA, "type": "spell"}]
        plain = value.hand_plan(spell, board_minions=[],
                                scenario={"cast_spell": 0})
        glambot_board = [{"card": "BG36_853", "name": "Glambot",
                          "atk": 4, "health": 4}]
        fueled = value.hand_plan(spell, board_minions=glambot_board,
                                 scenario={"cast_spell": 10})
        self.assertGreater(fueled[0]["score"], plain[0]["score"])
        self.assertTrue(fueled[0]["why"])

    def test_unknown_spell_skipped(self):
        """Generated spell entities without a real id can't be advised."""
        self.assertEqual(value.hand_plan(
            [{"card": "UNKNOWN_SPELL_X", "type": "spell"}]), [])


class TestTopMoveHand(unittest.TestCase):
    """The hand leads the numbered plan (free actions, execution order)."""

    def _analysis(self, hand_entries=None):
        return {"tier": 2, "gold": 6, "level_cost": 5, "health": 30,
                "armor": 0, "turn": 7, "damage_last": None, "loss_streak": 0,
                "board": [], "shop_rank": [], "buy_this": None,
                "playable_comps": {}, "choice": None, "sell_rank": [],
                "target_comp": None, "target_cards": None,
                "hand_plan": hand_entries or []}

    def test_hand_casts_lead_the_plan(self):
        tm = value.top_move(self._analysis([
            {"card": "BG28_897", "verb": "cast", "name": "Tavern Dish Banana",
             "score": 4, "why": None}]))
        self.assertTrue(tm.startswith("1. Cast Tavern Dish Banana"), tm)
        self.assertIn("2. LEVEL to tier 3 (standard curve)", tm)

    def test_copies_group_and_rest_summarize(self):
        entries = ([{"card": "BG28_897", "verb": "cast",
                     "name": "Tavern Dish Banana", "score": 4, "why": None}]
                   * 2
                   + [{"card": "BG28_810", "verb": "cast",
                       "name": "Tavern Coin", "score": 1, "why": None}])
        tm = value.top_move(self._analysis(entries))
        self.assertIn("1. Cast Tavern Dish Banana x2", tm)
        self.assertIn("2. Cast Tavern Coin", tm)
        self.assertIn("3. LEVEL", tm)

    def test_more_than_three_kinds_summarize(self):
        entries = [{"card": f"BG28_80{i}", "verb": "cast", "name": f"Spell {i}",
                    "score": 5 - i, "why": None} for i in range(4)]
        tm = value.top_move(self._analysis(entries))
        self.assertIn("then the rest of your hand (1 more)", tm)

    def test_hand_minion_on_full_board_says_make_room(self):
        entries = [{"card": "BG33_140", "verb": "play", "name": "River Skipper",
                    "score": 10, "why": "board is full — sell to make room"}]
        tm = value.top_move(self._analysis(entries))
        self.assertIn("Play River Skipper (board is full — sell to make room)",
                      tm)

    def test_wait_for_end_of_turn_casts_first(self):
        """End-of-turn compounding counts casts made THIS turn — the hand
        goes before the pass."""
        a = self._analysis([
            {"card": "BG28_897", "verb": "cast",
             "name": "Tavern Dish Banana", "score": 4, "why": None}])
        a["tier"] = 6  # nothing left to level — the pass is the only spend move
        a["board"] = [{"card": "BG32_235"}] * 7  # end-of-turn scaler, full board
        tm = value.top_move(a)
        self.assertTrue(tm.startswith("1. Cast Tavern Dish Banana"), tm)
        self.assertIn("wait for end of turn", tm)

    def test_committed_endgame_says_scale(self):
        """Once committed the endgame is enriching what we have (2026-09-04:
        "we committed, we have it, now we scale it to kingdom come") — the
        stale fallback says scale, not hold."""
        a = self._analysis()
        a["gold"] = 0
        a["target_comp"] = "Nagas - Groundbreaker"
        a["target_state"] = "committing"
        tm = value.top_move(a)
        self.assertIn("scale Nagas - Groundbreaker", tm)
        self.assertIn("sell nothing that grows", tm)
