"""The board slot: name the card you sell, and prove the trade.

The player's report this exists for, verbatim:

> The coach will frequently say that a card should be played, and something else
> must be sold to make room for it. But it doesn't say *which* card, or state
> if/how the value of the new card will be greater than the one you'll need to
> sell to play it.

Measured before the fix (analysis/board_swap.md): 37 of 154 cached phases had a
full board, 34 of those advised a play or a buy, and 16 of those 34 said "sell to
make room" without naming a card. Scoring the advised swap over the two newest
sessions: 2 of 12 were value-NEGATIVE — the same decision twice, a 16.0 body
advised over a 20.2 one, in the FRAGILE band.

Both sides of the comparison are already scored in the same currency
(`minion_value`), so the arbiter is a subtraction plus the guards — not a new
model. Stage 1 of three; the keyword ("now") and simulator ("future") terms are
stages 2 and 3.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import meta  # noqa: E402
import value  # noqa: E402

#: A cheap Aberration body (the cut) and two real Aberration minions.
CUT = "BG36_112"
FILLER_SCORE = 5.6
CORE_A, CORE_B = "BG36_318", "BG36_103"     # Faceless Converter, N'raqi Sapper


def board(ids=CORE_A and (CUT, CORE_A, CORE_B, "BG36_115", "BG36_109",
                          "BG36_114", "BG36_320")):
    return [{"card": c, "atk": 5, "health": 5,
             "tribe": "Aberration"} for c in ids]


def analysis(**over):
    comps = meta.comps()
    b = board()
    target = value.comp_target(b, comps)
    a = {
        "board": b, "playable_comps": comps,
        "sell_rank": [(CUT, FILLER_SCORE), ("BG36_311", 14.9)],
        "shop_rank": [], "buy_step_card": None,
        "tier": 4, "gold": 10, "level_cost": 9, "turn": 8,
        "target_comp": target["name"] if target else None,
        "hand_plan": [],
    }
    a.update(over)
    return a


class TestTheArbiterNamesTheTrade(unittest.TestCase):
    def test_a_winning_swap_is_named_with_its_numbers(self):
        a = analysis(hand_plan=[{"card": "BG36_114", "name": "Parasitic Fleshling",
                                 "verb": "play", "score": 34.5, "why": None}])
        rows = value.slot_swaps(a)
        self.assertTrue(rows)
        best = rows[0]
        self.assertEqual(best["verdict"], "take")
        self.assertEqual(best["outgoing"], CUT)
        self.assertAlmostEqual(best["delta"], 34.5 - FILLER_SCORE, places=3)
        line = value.top_move(a)
        self.assertIn("Swap: play Parasitic Fleshling, sell", line)
        self.assertIn("clearly better", line)

    def test_a_marginal_swap_says_it_is_marginal(self):
        a = analysis(hand_plan=[{"card": "BG36_114", "name": "Parasitic Fleshling",
                                 "verb": "play", "score": FILLER_SCORE + 1.0,
                                 "why": None}])
        self.assertEqual(value.slot_swaps(a)[0]["verdict"], "close")
        self.assertIn("marginal", value.top_move(a))

    def test_a_losing_swap_is_vetoed_not_advised(self):
        """The measured failure: a body worth less than the slot it costs."""
        a = analysis(hand_plan=[{"card": "BG36_114", "name": "Parasitic Fleshling",
                                 "verb": "play", "score": 3.4, "why": None}])
        rows = value.slot_swaps(a)
        self.assertEqual(rows[0]["verdict"], "veto")
        line = value.top_move(a)
        self.assertNotIn("Swap:", line)
        self.assertIn("Hold Parasitic Fleshling", line)
        entry = a["hand_plan"][0]
        self.assertEqual(entry["verb"], "hold")
        self.assertIn("it would cost", entry["why"])

    def test_one_slot_one_queue(self):
        """Two plays and one slot: one is chosen, the other becomes a hold."""
        a = analysis(hand_plan=[
            {"card": "BG36_114", "name": "Parasitic Fleshling", "verb": "play",
             "score": FILLER_SCORE + 6.0, "why": None},
            {"card": "BG36_115", "name": "Nightmare Corroder", "verb": "play",
             "score": FILLER_SCORE + 0.5, "why": None},
        ])
        line = value.top_move(a)
        self.assertIn("Swap: play Parasitic Fleshling", line)
        self.assertEqual(a["hand_plan"][0]["verb"], "play")
        self.assertEqual(a["hand_plan"][1]["verb"], "hold")
        self.assertIn("it would cost", a["hand_plan"][1]["why"])


class TestGuards(unittest.TestCase):
    def test_the_comps_own_core_is_never_the_cut(self):
        a = analysis(sell_rank=[(CORE_A, -5.0), (CUT, FILLER_SCORE)],
                     hand_plan=[{"card": "BG36_114", "name": "X", "verb": "play",
                                 "score": 40.0, "why": None}])
        rows = value.slot_swaps(a)
        self.assertEqual(rows[0]["outgoing"], CUT,
                         "the cheapest sell was the comp's core and must be skipped")

    def test_a_held_golden_hunt_is_never_the_cut(self):
        a = analysis(sell_rank=[("BG36_311", 7.7), (CUT, FILLER_SCORE)],
                     hand_plan=[{"card": "BG36_311", "name": "Held", "verb": "hold",
                                 "score": -1.3, "why": "hold — 1 regular on board; "
                                 "a 3rd copy turns it golden"},
                                {"card": "BG36_114", "name": "X", "verb": "play",
                                 "score": 40.0, "why": None}])
        self.assertEqual(value.slot_swaps(a)[0]["outgoing"], CUT)

    def test_a_multiplier_is_never_the_cut(self):
        """Titus-class bodies are worth what they amplify, not their stats."""
        mult = next((m["id"] for m in meta.minions()
                     if value._is_multiplier(m)), None)
        if not mult:
            self.skipTest("no multiplier in the minion DB")
        b = board()
        b[0] = {"card": mult, "atk": 1, "health": 2, "tribe": "All"}
        a = analysis(board=b, sell_rank=[(mult, -9.0), (CUT, FILLER_SCORE)],
                     hand_plan=[{"card": "BG36_114", "name": "X", "verb": "play",
                                 "score": 40.0, "why": None}])
        self.assertEqual(value.slot_swaps(a)[0]["outgoing"], CUT,
                         "the ranker's cheapest sell was a multiplier")


class TestTheDecisionBoundaries(unittest.TestCase):
    def test_no_swap_question_on_a_board_with_space(self):
        a = analysis(board=board()[:6],
                     hand_plan=[{"card": "BG36_114", "name": "X", "verb": "play",
                                 "score": 40.0, "why": None}])
        self.assertEqual(value.slot_swaps(a), [])

    def test_spells_do_not_compete_for_a_slot(self):
        """A cast needs no room, so it must not be offered as an incoming card."""
        a = analysis(hand_plan=[{"card": "BG28_810", "name": "Tavern Coin",
                                 "verb": "cast", "score": 99.0, "why": None}])
        self.assertEqual(value.slot_swaps(a), [])

    def test_a_marginal_swap_is_vetoed_while_dying(self):
        """Contract item 4, stage-1 slice: at <=12 effective HP a small upgrade
        is not worth a body — the swap must be clearly better to be advised."""
        a = analysis(fragility={"band": "dying", "eff_health": 8},
                     hand_plan=[{"card": "BG36_114", "name": "X", "verb": "play",
                                 "score": FILLER_SCORE + 1.0, "why": None}])
        self.assertEqual(value.slot_swaps(a)[0]["verdict"], "veto")
        b = analysis(fragility={"band": "fragile", "eff_health": 14},
                     hand_plan=[{"card": "BG36_114", "name": "Y", "verb": "play",
                                 "score": FILLER_SCORE + 1.0, "why": None}])
        self.assertEqual(value.slot_swaps(b)[0]["verdict"], "close",
                         "the FRAGILE band is stage 2's, not this rule's")

    def test_a_shop_buy_that_loses_the_slot_becomes_roll_advice(self):
        a = analysis(gold=20, level_cost=9, shop_rank=[("BG36_116", 3.4)],
                     buy_this="BG36_116", buy_step_card="BG36_116")
        line = value.top_move(a)
        # The buy step renders and is then REWRITTEN by the arbiter: leaving
        # "Buy X" up would be a go-ahead the numbers contradict, and a bare
        # refusal leaves the player nothing to do with the gold.
        self.assertIn("roll instead", line)
        self.assertNotIn("Buy Underrot Spawn", line)
        self.assertNotIn("Swap:", line)
        self.assertEqual(a.get("buy_step_swap_veto"), "Underrot Spawn",
                         "the overlay's Buy box must know, or it keeps glowing")

    def test_no_sell_candidates_means_no_swap_advice(self):
        """Nothing to compare is not a licence to say 'sell something'."""
        a = analysis(sell_rank=[],
                     hand_plan=[{"card": "BG36_114", "name": "X", "verb": "play",
                                 "score": 40.0, "why": "board is full — sell to "
                                 "make room"}])
        self.assertEqual(value.slot_swaps(a), [])
        self.assertIn("sell to make room", value.top_move(a),
                      "with no ranking the old wording stands — unchanged")


class TestTheRenderedStep(unittest.TestCase):
    def test_the_swap_is_a_first_class_step_kind(self):
        a = analysis(hand_plan=[{"card": "BG36_114", "name": "Parasitic Fleshling",
                                 "verb": "play", "score": 34.5, "why": None}])
        value.top_move(a)
        swaps = [s for s in a["top_move_steps"] if s["kind"] == "swap"]
        self.assertEqual(len(swaps), 1, "exactly one slot decision per turn")
        step = swaps[0]
        self.assertTrue(step["action"].startswith("Swap: play"))
        self.assertIn("sell", step["action"])

    def test_the_swap_leads_the_plan_body(self):
        """It belongs with the play it serves: after the hand, before LEVEL."""
        a = analysis(hand_plan=[{"card": "BG36_114", "name": "Parasitic Fleshling",
                                 "verb": "play", "score": 34.5, "why": None}])
        line = value.top_move(a)
        self.assertLess(line.index("Swap:"), line.index("LEVEL"),
                        "the slot decision must not trail the level advice")


if __name__ == "__main__":
    unittest.main()
