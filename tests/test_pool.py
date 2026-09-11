"""Own-side pool accounting (phase 1, analysis/pool_availability.md).

The pool is shared lobby-wide; phase 1 subtracts exactly what WE hold
(board + hand, golden = 3) and gates the golden-hunt advice on it: a
triple whose missing copies we already hold the pool dry for can never
complete. Pins the math, the honest-label wording, and the three value
gates (hand hold-flip, triple note, hunt check).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import meta
import pool
import value

# A real tier-1 minion (pool of 18) from minions.json.
T1 = next(m["id"] for m in meta.minions() if m.get("tier") == 1)
SIZES = pool.sizes()


class TestOwnHoldings(unittest.TestCase):
    def test_regular_is_one_copy(self):
        held = pool.own_holdings([{"card": T1, "golden": False}])
        self.assertEqual(held[T1], 1)

    def test_golden_flag_counts_three(self):
        held = pool.own_holdings([{"card": T1, "golden": True}])
        self.assertEqual(held[T1], 3)

    def test_golden_id_suffix_counts_three(self):
        held = pool.own_holdings([{"card": T1 + "_G"}])
        self.assertEqual(held[T1], 3)

    def test_hand_holds_too(self):
        held = pool.own_holdings([{"card": T1}],
                                 [{"card": T1}, {"card": T1}])
        self.assertEqual(held[T1], 3)

    def test_duplicates_accumulate(self):
        held = pool.own_holdings([{"card": T1}] * 2)
        self.assertEqual(held[T1], 2)


class TestLeft(unittest.TestCase):
    def test_pool_minus_holdings(self):
        held = pool.own_holdings([{"card": T1, "golden": True}])
        self.assertEqual(pool.left(T1, held), SIZES[1] - 3)

    def test_clamps_at_zero(self):
        held = {T1: 99}
        self.assertEqual(pool.left(T1, held), 0)

    def test_unknown_tier_is_no_opinion(self):
        self.assertIsNone(pool.left("NOT_A_REAL_CARD", {}))

    def test_sizes_override(self):
        self.assertEqual(pool.left(T1, {T1: 17}, {1: 18}), 1)

    def test_meta_pool_sizes_accessor(self):
        got = meta.pool_sizes()
        self.assertEqual(got.get(1), 18)
        self.assertEqual(got.get(7), 5)


class TestChip(unittest.TestCase):
    def test_dry(self):
        self.assertEqual(pool.chip(T1, {T1: 99}), "pool dry")

    def test_last_copy(self):
        self.assertEqual(pool.chip(T1, {T1: SIZES[1] - 1}), "last pool copy")

    def test_count_left(self):
        self.assertEqual(pool.chip(T1, {T1: SIZES[1] - 4}),
                         "4 pool left")

    def test_unknown_tier_no_chip(self):
        self.assertIsNone(pool.chip("NOT_A_REAL_CARD", {}))


class TestHandPlanPoolGate(unittest.TestCase):
    def test_hold_when_pool_can_produce(self):
        hand = [{"card": T1, "golden": False}]
        board = [{"card": T1, "golden": False}]
        steps = value.hand_plan(hand, board_minions=board,
                                pool_held={T1: 2})
        step = next(s for s in steps if s["card"] == T1)
        self.assertEqual(step["verb"], "hold")
        self.assertIn("3rd copy", step["why"])

    def test_play_when_pool_dry(self):
        # Holding all 18 copies of a tier-1: the 3rd can never roll.
        hand = [{"card": T1, "golden": False}]
        board = [{"card": T1, "golden": False}]
        held = pool.own_holdings(board + hand)
        held[T1] = SIZES[1]  # board + hand + every other copy gone
        steps = value.hand_plan(hand, board_minions=board,
                                pool_held=held)
        step = next(s for s in steps if s["card"] == T1)
        self.assertEqual(step["verb"], "play")
        self.assertIn("no 3rd copy left", step["why"])

    def test_no_pool_arg_keeps_hold(self):
        hand = [{"card": T1, "golden": False}]
        board = [{"card": T1, "golden": False}]
        steps = value.hand_plan(hand, board_minions=board)
        step = next(s for s in steps if s["card"] == T1)
        self.assertEqual(step["verb"], "hold")


class TestTripleNotePool(unittest.TestCase):
    def test_golden_needs_more_pool_short(self):
        board = [{"card": T1, "golden": True}, {"card": T1, "golden": False}]
        # Pool can only offer 1 more regular; 2 are needed.
        held = {T1: SIZES[1] - 1}
        note = value._triple_note(T1, board, pool_held=held)
        self.assertIn("pool can't produce them", note)
        self.assertIn("1 left beyond your holdings", note)

    def test_golden_pool_can_produce_untouched(self):
        board = [{"card": T1, "golden": True}]
        note = value._triple_note(T1, board, pool_held={T1: 0})
        self.assertIn("still needed for a triple", note)
        self.assertNotIn("pool can't", note)

    def test_completing_buy_unaffected(self):
        # The 3rd copy is IN the shop — buying it is always feasible.
        board = [{"card": T1, "golden": False}, {"card": T1, "golden": False}]
        note = value._triple_note(T1, board, pool_held={T1: SIZES[1] - 2})
        self.assertEqual(note, "this buy completes a golden triple")


class TestHuntPoolGate(unittest.TestCase):
    def test_pool_dry_blocks_hunt(self):
        row = {"card": T1, "name": "x"}
        ok, why = value._hunt_check(row, 6, 9, {}, False,
                                    pool_held={T1: 99})
        self.assertFalse(ok)
        self.assertIn("pool dry", why)

    def test_pool_available_hunts_on(self):
        row = {"card": T1, "name": "x"}
        ok, why = value._hunt_check(row, 6, 9, {}, False, pool_held={})
        self.assertTrue(ok)
        self.assertIsNone(why)

    def test_no_pool_arg_unchanged(self):
        ok, _ = value._hunt_check({"card": T1, "name": "x"}, 6, 9, {}, False)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
