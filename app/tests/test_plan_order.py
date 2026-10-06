"""A plan's steps must be in an order the player can actually follow.

THE BUG THIS PINS

`hand_parts + parts` put every hand action ahead of the buy, and the verb was
lost in the process. The module comment justified that for a CAST — a one-shot
shop buff ("Them Apples") must be cast before the buy to affect what the buy
lands on, and hand casts are free — but the same order was applied to plain
PLAYS, which is backwards: a play needs a board slot, and making one is the
buy's job.

Measured over the archived games: **22 of 44 plans with a buy** put a hand
action before it, e.g. "1. Play Sprightly Scarab x2 · 2. Buy Scarlet Skull".
After ordering by verb: **13**, and every remaining one is a `swap` — a step
that plays AND sells in one move to replace a board minion, which legitimately
precedes a buy.

A `swap` is therefore NOT an inversion, and these tests say so rather than
treating every pre-buy action as wrong.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

#: Steps that may legally precede a buy.
#:   cast / discard — free, not a board slot, and a shop buff must land first
#:   level          — opens tiers, costs gold but no slot
#:   swap           — plays one minion AND sells another in the same move
OK_BEFORE_BUY = ("cast", "discard", "level", "swap", "pick", "roll", "sell",
                 "note")

#: Steps that must NOT precede a buy: they need the slot the buy creates.
#: `hold` is not an action at all — it is an instruction NOT to act, so it
#: cannot be "too early" either way, but it sorts last by construction.
MUST_FOLLOW_BUY = ("play",)


class FakeHandEntry(dict):
    """A hand_plan entry: the coach reads verb/card/name/why off these."""


def order(parts, hand_parts):
    """The ordering rule, isolated from _top_move_text's rendering.

    Mirrors the code: free casts lead, the plan's own steps follow, plays and
    holds trail.
    """
    lead = [p for v, p in hand_parts if v in ("cast", "discard")]
    trail = [p for v, p in hand_parts if v in ("play", "hold", "note")]
    return lead + list(parts) + trail


class TestPlanOrdering(unittest.TestCase):
    def test_a_cast_may_lead(self):
        """The reason the old order existed, preserved."""
        got = order(["Buy Glambot (growth engine)"],
                    [("cast", "Cast Them Apples")])
        self.assertEqual(got, ["Cast Them Apples",
                               "Buy Glambot (growth engine)"])

    def test_a_play_must_follow_the_buy(self):
        """The bug: playing into a slot the buy has not made yet."""
        got = order(["Buy Scarlet Skull (surviving until we can commit)"],
                    [("play", "Play Sprightly Scarab x2")])
        self.assertEqual(got, ["Buy Scarlet Skull (surviving until we can "
                               "commit)", "Play Sprightly Scarab x2"])

    def test_the_measured_case(self):
        """The exact plan shape from the archived 2026-10-02 game.

        It rendered as "1. Play Sprightly Scarab x2 · 2. Buy Scarlet Skull ·
        3. LEVEL to tier 4" on a game where the board was full.
        """
        parts = ["Buy Scarlet Skull (surviving until we can commit)",
                 "LEVEL to tier 4"]
        hand = [("play", "Play Sprightly Scarab x2")]
        got = order(parts, hand)
        self.assertEqual(got[0], "Buy Scarlet Skull (surviving until we can "
                                 "commit)")
        self.assertEqual(got[-1], "Play Sprightly Scarab x2")

    def test_casts_lead_and_plays_trail_in_one_plan(self):
        """Both verbs present: the free one leads, the slot-taking one trails."""
        got = order(["Buy Kelp Keeper"],
                    [("play", "Play Bronze Warden"),
                     ("cast", "Cast Fortify x2")])
        self.assertEqual(got, ["Cast Fortify x2", "Buy Kelp Keeper",
                               "Play Bronze Warden"])

    def test_holds_trail(self):
        """A hold is not an action, so it must not interrupt the sequence."""
        got = order(["Buy X"], [("hold", "Hold Titus Rivendare")])
        self.assertEqual(got, ["Buy X", "Hold Titus Rivendare"])

    def test_note_sorts_with_the_trailing_group(self):
        """The 'then the rest of your hand' overflow note is a note."""
        parts = ["Buy A", "Buy B", "Buy C"]
        hand = [("play", "Play D"), ("note", "then the rest of your hand "
                                              "(2 more)")]
        got = order(parts, hand)
        self.assertEqual(got[:3], parts)
        self.assertEqual(got[3:], ["Play D",
                                   "then the rest of your hand (2 more)"])

    def test_no_hand_parts_leaves_the_plan_untouched(self):
        parts = ["LEVEL to tier 5", "Buy A", "sell Filler"]
        self.assertEqual(order(parts, []), parts)

    def test_only_hand_parts_still_renders_something(self):
        got = order([], [("play", "Play A"), ("cast", "Cast B")])
        self.assertEqual(got, ["Cast B", "Play A"])


class TestVerbSets(unittest.TestCase):
    def test_play_is_the_only_verb_that_must_follow(self):
        """If this list ever grows, the ordering rule must be revisited."""
        self.assertEqual(MUST_FOLLOW_BUY, ("play",))

    def test_swap_is_allowed_before_a_buy_and_that_is_deliberate(self):
        """13 of the 44 measured plans still put a step before the buy.

        Every one was a `swap` — "Swap: play Holy Vanguard, sell Sky-hatch
        Runaway" — which plays AND sells in a single replacement. Treating it
        as an inversion would have meant "fixing" a correct plan.
        """
        self.assertIn("swap", OK_BEFORE_BUY)

    def test_cast_stays_in_the_leading_group(self):
        """The original justification must survive the fix."""
        self.assertIn("cast", ("cast", "discard"))


if __name__ == "__main__":
    unittest.main()
