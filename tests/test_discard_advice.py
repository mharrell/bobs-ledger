"""Discard advice: name the card, or don't advise the outlet at all.

The player's report (2026-09-23): "I'm getting coaching to activate a minion to
discard a card when I don't have any cards to discard. Much like selling to make
room, we should specify which card(s) are safe (or improved!) to discard."

Two defects, one arbiter:

1. `_affordable_activation` checked the GOLD BUDGET and nothing else, so an
   "Activate (0): Discard a card to ..." outlet was advised with an empty hand
   (and with a hand holding nothing expendable).
2. Even when the outlet WAS right, the plan never said which card to spend.

And the opportunity the same work exposed: a discard outlet plus a card whose own
text says discarding beats casting it (Energizing Chamber and Sludge Corrosion
both cast twice, Corrupted Coin raises max Gold) is a STRICT gain — the outlet's
payoff AND the upgraded card — so it belongs in the plan even on a rich turn. The
2026-09-23 Drest'agath win held four Energizing Chambers with a Mindbending
Recruiter on board for five straight phases and the plan never connected them.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import value  # noqa: E402

OUTLET = "BG36_312"      # Mindbending Recruiter: Activate (0): Discard a card ->
#                          get a random Aberration
PLAIN_ACT = "BG36_345"   # Suspicious Prisonguard: Activate (1): Give another
#                          minion +3/+3 — discards nothing
CHAMBER = "BG36_371"     # Energizing Chamber: +7/+7 to your Deity; discarded, casts twice
GHURSHA = "BG36_097"     # a build body, worth keeping
COIN = "BG28_810"        # Tavern Coin: Gain 1 Gold (cheap fodder)


def analysis(hand, activations=(OUTLET,), gold=10, **over):
    a = {
        "board": [{"card": OUTLET}], "playable_comps": {}, "sell_rank": [],
        "shop_rank": [], "gold": gold, "tier": 5, "level_cost": None,
        "hand_plan": hand, "activations": [{"cid": c} for c in activations],
    }
    a.update(over)
    return a


def hand(*entries):
    return list(entries)


class TestFodderSelection(unittest.TestCase):
    def test_the_improved_card_wins_even_over_a_cheaper_one(self):
        a = analysis(hand(
            {"card": GHURSHA, "name": "Mindbender Ghur'sha", "verb": "play", "score": 40},
            {"card": COIN, "name": "Tavern Coin", "verb": "cast", "score": 2},
            {"card": CHAMBER, "name": "Energizing Chamber", "verb": "cast", "score": 14},
        ))
        fodder = value.discard_fodder(a)
        self.assertEqual(fodder["card"], CHAMBER)
        self.assertTrue(fodder["improved"])
        self.assertIn("cast it twice", fodder["why"])

    def test_otherwise_the_cheapest_expendable_card(self):
        a = analysis(hand(
            {"card": GHURSHA, "name": "Mindbender Ghur'sha", "verb": "play", "score": 40},
            {"card": COIN, "name": "Tavern Coin", "verb": "cast", "score": 2},
        ))
        fodder = value.discard_fodder(a)
        self.assertEqual(fodder["card"], COIN)
        self.assertFalse(fodder["improved"])

    def test_an_empty_hand_has_nothing_to_discard(self):
        self.assertIsNone(value.discard_fodder(analysis(hand())))

    def test_a_hand_of_real_cards_is_not_fodder(self):
        """The reported complaint, second half: don't spend a body worth keeping."""
        a = analysis(hand({"card": GHURSHA, "name": "Mindbender Ghur'sha",
                           "verb": "play", "score": 40}))
        self.assertIsNone(value.discard_fodder(a))

    def test_the_card_held_for_a_triple_is_never_the_fodder(self):
        a = analysis(hand({"card": GHURSHA, "name": "Mindbender Ghur'sha",
                           "verb": "hold", "score": 3,
                           "why": "hold — 1 regular on board; a 3rd copy turns "
                                  "it golden"}))
        self.assertIsNone(value.discard_fodder(a))

    def test_an_improved_card_is_fodder_even_as_a_comp_core(self):
        """The guards protect CARDS, and discarding an improved card does not
        lose it — "if you discard this, cast it twice" means the effect happens
        twice, which is what the build wants anyway."""
        comp = {"name": "Aberrations - Deity Feed", "tribe": "Aberration",
                "core": [CHAMBER], "addons": []}
        a = analysis(
            hand({"card": CHAMBER, "name": "Energizing Chamber", "verb": "cast",
                  "score": 4}),
            playable_comps={"a": comp}, target_comp=comp["name"])
        fodder = value.discard_fodder(a)
        self.assertIsNotNone(fodder)
        self.assertTrue(fodder["improved"])

    def test_a_plain_comp_core_is_never_the_fodder(self):
        comp = {"name": "Aberrations - Deity Feed", "tribe": "Aberration",
                "core": [COIN], "addons": []}
        a = analysis(
            hand({"card": COIN, "name": "Tavern Coin", "verb": "cast",
                  "score": 2}),
            playable_comps={"a": comp}, target_comp=comp["name"])
        self.assertIsNone(value.discard_fodder(a))

    def test_an_unscored_hand_card_is_not_fodder(self):
        a = analysis(hand({"card": COIN, "name": "Tavern Coin", "verb": "cast",
                           "score": None}))
        self.assertIsNone(value.discard_fodder(a))


class TestTheOutletIsNotAdvisedWithoutFodder(unittest.TestCase):
    def test_an_empty_hand_removes_the_outlet_from_the_plan(self):
        a = analysis(hand(), gold=1)
        self.assertIsNone(value._affordable_activation(a, 1))
        line = value.top_move(a)
        self.assertNotIn("Activate", line)

    def test_a_non_discard_activation_still_fires(self):
        """The guard is about the discard, not about activations at all."""
        a = analysis(hand(), activations=(PLAIN_ACT,), gold=1)
        act = value._affordable_activation(a, 1)
        self.assertIsNotNone(act)
        self.assertIsNone(act[4], "it discards nothing, so it needs no fodder")
        self.assertIn("Activate Suspicious Prisonguard", value.top_move(a))

    def test_the_outlet_is_skipped_but_a_later_activation_is_tried(self):
        a = analysis(hand(), activations=(OUTLET, PLAIN_ACT), gold=1)
        act = value._affordable_activation(a, 1)
        self.assertEqual(act[0], PLAIN_ACT)

    def test_with_fodder_the_outlet_is_advised_and_named(self):
        """The outlet's own path: nothing else to spend the turn on, a cheap
        card in hand, so "activate, discarding X" beats a reroll."""
        coin = {"card": COIN, "name": "Tavern Coin", "verb": "cast", "score": 2}
        a = analysis(hand(coin), gold=1)
        # `hand` is the raw list the overlay carries; hand_plan is None here so
        # the plan has no hand steps to render and reaches the fallback.
        a["hand"] = [dict(coin)]
        a["hand_plan"] = None
        line = value.top_move(a)
        self.assertIn("Activate Mindbending Recruiter", line)
        self.assertIn("discard Tavern Coin (least useful card in hand)", line)
        self.assertIn("beats a reroll", line, "the fallback wording is kept")


class TestTheDiscardLoop(unittest.TestCase):
    """An improved card + an outlet is a strict gain, so it leads the plan."""

    def test_the_plan_leads_with_the_loop_and_names_both_halves(self):
        a = analysis(hand(
            {"card": CHAMBER, "name": "Energizing Chamber", "verb": "cast", "score": 14},
            {"card": CHAMBER, "name": "Energizing Chamber", "verb": "cast", "score": 14},
            {"card": GHURSHA, "name": "Mindbender Ghur'sha", "verb": "play", "score": 40},
        ))
        line = value.top_move(a)
        self.assertTrue(line.startswith("1. Discard Energizing Chamber"),
                        line)
        self.assertIn("via Mindbending Recruiter", line)
        self.assertIn("cast it twice", line)
        verbs = [s["verb"] for s in a["hand_plan"]]
        self.assertEqual(verbs.count("discard"), 1,
                         "one outlet, one discarded card")
        self.assertEqual(verbs.count("cast"), 1,
                         "the other copy is still cast")
        self.assertEqual(a["discard_target"]["card"], CHAMBER)

    def test_a_cheap_card_is_claimed_by_the_outlet_rather_than_cast(self):
        """One card, one use — and the outlet's payoff (a random Aberration)
        beats the single gold a Tavern Coin casts for. The discard decision now
        runs FIRST (step 3b of the planner), so the card it spends is no longer
        also cast in the same plan; it becomes a `discard` hand verb naming the
        outlet."""
        a = analysis(hand({"card": COIN, "name": "Tavern Coin", "verb": "cast",
                           "score": 2}))
        line = value.top_move(a)
        self.assertEqual([s["verb"] for s in a["hand_plan"]], ["discard"])
        self.assertIn("Discard Tavern Coin (via Mindbending Recruiter", line)
        self.assertNotIn("Cast Tavern Coin", line)
        self.assertEqual(a["discard_target"]["card"], COIN)

    def test_no_outlet_means_no_loop(self):
        a = analysis(hand({"card": CHAMBER, "name": "Energizing Chamber",
                           "verb": "cast", "score": 14}), activations=())
        line = value.top_move(a)
        self.assertIn("Cast Energizing Chamber", line)
        self.assertNotIn("Discard", line)

    def test_the_loop_step_classifies_as_discard(self):
        a = analysis(hand({"card": CHAMBER, "name": "Energizing Chamber",
                           "verb": "cast", "score": 14}))
        value.top_move(a)
        kinds = {s["kind"] for s in a["top_move_steps"]}
        self.assertIn("discard", kinds)


class TestThePlanDoesNotContradictItself(unittest.TestCase):
    """The 2026-09-23 conflict report, verbatim from the overlay:

        Do this now
        Aberrations build — hunting pieces (provisional) · strong (101 vs ~64) …
        FRAGILE — 15 effective HP …
        1 Play Brann Bronzebeard        (board is full)
        2 Swap: play Brann Bronzebeard, sell Mindbending Recruiter  (7.6 vs 3.0)
        3 Activate Mindbending Recruiter — discard Brann Bronzebeard

    Step 2 sold the outlet step 3 needed, and step 3 spent the card step 1 was
    playing. Three rules now keep one plan to one use per card.
    """

    BRANN = "BG25_354"      # a real body: 7.6 in the report
    BOARD = ["BG36_112", "BG36_318", "BG36_103", "BG36_115", "BG36_109",
             OUTLET, "BG36_320"]

    def _analysis(self, hand, sells=None, **over):
        a = analysis(hand, activations=(OUTLET,), **over)
        a["board"] = [{"card": c, "atk": 5, "health": 5, "tribe": "Aberration"}
                      for c in self.BOARD]
        a["sell_rank"] = sells if sells is not None else [(OUTLET, 3.0),
                                                          ("BG36_112", 5.6),
                                                          ("BG36_115", 9.0)]
        return a

    def test_a_real_body_is_not_discarded_just_after_being_played(self):
        a = self._analysis([{"card": self.BRANN, "name": "Brann Bronzebeard",
                             "verb": "play", "score": 7.6}])
        line = value.top_move(a)
        self.assertNotIn("Activate", line)
        self.assertNotIn("discard Brann", line)
        self.assertIsNone(a.get("discard_target"))
        self.assertIn("Swap: play Brann Bronzebeard", line,
                      "the play-and-sell advice stands on its own")

    def test_but_a_cheap_card_is_still_fodder(self):
        a = self._analysis([
            {"card": self.BRANN, "name": "Brann Bronzebeard", "verb": "play",
             "score": 7.6},
            {"card": COIN, "name": "Tavern Coin", "verb": "cast", "score": 2}])
        a["hand_plan"] = a["hand_plan"]      # same list, the plan mutates it
        line = value.top_move(a)
        self.assertIn("Discard Tavern Coin", line)
        self.assertIn("Play Brann Bronzebeard", line)
        self.assertIn("Swap: play Brann Bronzebeard", line)

    def test_the_outlet_is_not_sold_while_the_plan_uses_it(self):
        a = self._analysis([
            {"card": self.BRANN, "name": "Brann Bronzebeard", "verb": "play",
             "score": 7.6},
            {"card": COIN, "name": "Tavern Coin", "verb": "cast", "score": 2}])
        value.top_move(a)
        rows = value.slot_swaps(a, reserved_outlet=OUTLET)
        self.assertTrue(rows)
        self.assertNotEqual(rows[0]["outgoing"], OUTLET,
                            "the cheapest body to sell is the outlet the plan "
                            "is activating")
        self.assertEqual(rows[0]["outgoing"], "BG36_112")

    def test_the_fodder_is_not_the_swaps_incoming_card(self):
        """One card, one use: whichever decision runs first claims the card.
        The discard runs first (3b) precisely so the swap cannot offer to play
        the card the plan is spending."""
        a = self._analysis([
            {"card": COIN, "name": "Tavern Coin", "verb": "play", "score": 2}])
        line = value.top_move(a)
        self.assertIn("Discard Tavern Coin", line)
        self.assertNotIn("Swap: play Tavern Coin", line)
        self.assertNotIn("1. Play Tavern Coin", line)

    def test_a_seven_point_card_is_not_filler(self):
        self.assertLess(value.DISCARD_FODDER_MAX, 7.6,
                        "the report's Brann card scored 7.6 and must not read "
                        "as 'least useful card in hand'")

    def test_the_improved_loop_still_leads_and_still_discards(self):
        a = self._analysis([
            {"card": CHAMBER, "name": "Energizing Chamber", "verb": "cast",
             "score": 14},
            {"card": COIN, "name": "Tavern Coin", "verb": "cast", "score": 2}])
        line = value.top_move(a)
        self.assertTrue(line.startswith("1. Discard Energizing Chamber"), line)
        self.assertEqual(a["discard_target"]["card"], CHAMBER)


if __name__ == "__main__":
    unittest.main()
