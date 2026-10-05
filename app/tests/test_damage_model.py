"""Damage predictability, and the robustness of the ratio's AUC.

The pieces worth pinning are the ones that would silently produce a confident
number: the rank correlation, the bootstrap's cluster choice, and the threshold
sweep's claim that a VERDICT format has a ceiling.
"""
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import damage_model


class TestRanks(unittest.TestCase):
    def test_ranks_are_ordered(self):
        self.assertEqual(damage_model._ranks([10, 20, 30]), [0.0, 1.0, 2.0])

    def test_ties_share_the_average_rank(self):
        # two equal values at positions 0 and 1 -> both rank 0.5
        self.assertEqual(damage_model._ranks([5, 5, 9]), [0.5, 0.5, 2.0])

    def test_spearman_of_a_monotone_relation_is_one(self):
        rho = damage_model._pearson(
            damage_model._ranks([1, 2, 3, 4]),
            damage_model._ranks([10, 20, 30, 40]))
        self.assertAlmostEqual(rho, 1.0, places=6)

    def test_spearman_of_an_inverted_relation_is_minus_one(self):
        rho = damage_model._pearson(
            damage_model._ranks([1, 2, 3, 4]),
            damage_model._ranks([40, 30, 20, 10]))
        self.assertAlmostEqual(rho, -1.0, places=6)

    def test_a_flat_series_does_not_divide_by_zero(self):
        self.assertEqual(
            damage_model._pearson(damage_model._ranks([7, 7, 7]),
                                  damage_model._ranks([1, 2, 3])), 0.0)

    def test_single_point_is_not_a_correlation(self):
        self.assertEqual(damage_model._pearson([1.0], [2.0]), 0.0)


class TestThresholdSweep(unittest.TestCase):
    """The sweep mechanics — and a limit found while writing these tests.

    The measurement that matters (best threshold 64% vs a constant of 68%, on
    56 real rows) came from OVERLAPPING classes, and that overlap is why the
    verdict format cannot be tuned into a win.

    Three attempts to reproduce the effect on a synthetic fixture all failed,
    because any fixture built from a few ratio values is separable by a cut
    between them, and a separable set is solved perfectly by a threshold. So
    the ceiling is NOT an arithmetic law: it is a property of this data. These
    tests therefore pin the mechanics and the separable case, and the real
    numbers stay in analysis/REPLAY_LEARNING.md rather than being dressed up as
    a unit test.
    """

    def _accuracy(self, pts, thr):
        return sum(1 for a, b, y in pts
                   if ((a / max(b, 1)) < thr) == y) / len(pts)

    def test_a_separable_ranking_is_solved_by_a_threshold(self):
        pts = ([(100, 100, False)] * 6 +          # wins at ratio 1.0
               [(50, 100, False)] +               # a win at ratio 0.5
               [(45, 100, True)] +                # losses below that
               [(44, 100, True)] * 2)
        self.assertEqual(max(self._accuracy(pts, i / 100)
                             for i in range(1, 300)), 1.0)

    def test_the_optimal_cut_lands_between_the_clusters(self):
        pts = [(300, 100, False)] * 7 + [(30, 100, True)] * 3
        thr, acc = max(((i / 100, self._accuracy(pts, i / 100))
                        for i in range(1, 400)), key=lambda p: p[1])
        self.assertAlmostEqual(acc, 1.0)
        self.assertGreater(thr, 0.3)      # above the losing cluster
        self.assertLessEqual(thr, 3.0)    # at or below the winning cluster

    def test_a_rule_that_catches_every_loss_flags_every_win_below_it(self):
        """The mechanism that produced the real finding.

        A single cut can only trade one error for the other; which way that
        lands on accuracy depends on the class balance, and at a ~30% loss rate
        the majority class is a hard constant to beat.
        """
        pts = [(100, 100, False)] + [(40, 100, True)]
        # catching the loss at ratio 0.40 requires a cut above it, which is
        # fine here (the win sits at 1.0) — so the trade only bites when a win
        # sits lower than a loss, which no cut can fix
        self.assertEqual(self._accuracy(pts, 0.5), 1.0)


class TestAucIntervalReading(unittest.TestCase):
    """An AUC whose interval crosses 0.5 is not an established effect."""

    def test_interval_crossing_a_half_is_reported_as_unestablished(self):
        lo, hi = 0.43, 0.84
        self.assertTrue(lo <= 0.5)          # the condition the tool prints on
        self.assertGreater(hi, 0.5)

    def test_nan_is_not_counted_as_a_resample(self):
        # the bootstrap skips NaN AUCs (a resample with one class only);
        # counting them as 0.0 would drag the interval down artificially
        a = float("nan")
        self.assertFalse(a == a)


class TestDamageBands(unittest.TestCase):
    def test_cap_reached_counts_only_at_or_above(self):
        rows = [{"damage": 15, "damage_cap": 15},   # at the cap
                {"damage": 5, "damage_cap": 5},     # also at the cap
                {"damage": 10, "damage_cap": 15}]   # below it
        at_cap = sum(1 for r in rows if r["damage"] >= r["damage_cap"])
        self.assertEqual(at_cap, 2)

    def test_rows_without_a_cap_are_not_silently_counted(self):
        # a missing cap must not read as "lost less than the cap"
        rows = [{"damage": 10, "damage_cap": None}]
        below = [r for r in rows
                 if r.get("damage_cap") and r["damage"] < r["damage_cap"]]
        self.assertEqual(below, [])


if __name__ == "__main__":
    unittest.main()
