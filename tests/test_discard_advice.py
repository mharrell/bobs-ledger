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

    def test_without_an_improved_card_the_loop_stays_a_fallback(self):
        a = analysis(hand({"card": COIN, "name": "Tavern Coin", "verb": "cast",
                           "score": 2}))
        line = value.top_move(a)
        self.assertEqual([s["verb"] for s in a["hand_plan"]], ["cast"],
                         "no demotion: a plain card is only spent when nothing "
                         "else needs the gold")
        self.assertNotIn("discard Tavern Coin", line)

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


if __name__ == "__main__":
    unittest.main()
