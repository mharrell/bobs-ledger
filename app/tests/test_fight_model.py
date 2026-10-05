"""The fight model: feature extraction, fitting, and the AUC that grades it.

What matters here is not that a logistic regression converges but that the
EVALUATION cannot quietly lie. Two ways it could:

  * a row-wise split instead of leave-one-GAME-out. Rows inside a game share an
    opponent pool, a hero and a run of luck, so a row split leaks and reports a
    fantasy. This project has been bitten by the row/game distinction before.
  * scoring accuracy alone at a ~23% base rate, where "never lost" scores ~77%
    by knowing nothing. Accuracy is reported, but AUC is what answers "does
    this know anything at all".
"""
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import fight_model


def m(card, atk, hp, kw=()):
    return {"card": card, "atk": atk, "health": hp, "golden": False,
            "keywords": list(kw)}


def row(ours, theirs):
    return {"our_board": ours, "their_board": theirs, "lost": False,
            "session": "s", "game": 1, "turn": 5}


class TestFeatures(unittest.TestCase):
    def test_ratio_is_symmetric_under_swapping(self):
        """Swapping the boards must flip the sign, not change the magnitude."""
        a = [m("A", 10, 10)]
        b = [m("B", 5, 5)]
        x = fight_model.features_of(row(a, b))
        y = fight_model.features_of(row(b, a))
        self.assertAlmostEqual(x[0], -y[0], places=6)
        self.assertGreater(x[0], 0)        # we are bigger -> positive

    def test_keyword_differences_are_signed(self):
        ours = [m("A", 1, 1, ("DIVINE_SHIELD",)), m("B", 1, 1)]
        theirs = [m("C", 1, 1)]
        x = fight_model.features_of(row(ours, theirs))
        self.assertGreater(x[1], 0)        # more shields than them
        self.assertAlmostEqual(x[1], 1 / 3)

    def test_missing_board_is_not_a_feature_vector(self):
        """An unseen opponent is 'no opinion', never a zero-valued row."""
        self.assertIsNone(fight_model.features_of(row([m("A", 1, 1)], [])))
        self.assertIsNone(fight_model.features_of(row([], [m("A", 1, 1)])))

    def test_empty_boards_do_not_divide_by_zero(self):
        """Both sides empty still yields a finite vector (the +20 smoothing)."""
        x = fight_model.features_of(row([m("A", 0, 0)], [m("B", 0, 0)]))
        self.assertTrue(all(math.isfinite(v) for v in x))


class TestFit(unittest.TestCase):
    def _rows(self, sign):
        """A separable toy set with one informative feature."""
        return [([sign * 2.0], 1.0), ([sign * 1.5], 1.0), ([sign * -2.0], 0.0),
                ([sign * -1.5], 0.0)]

    def test_learns_the_sign_of_the_feature(self):
        w = fight_model.fit(self._rows(1.0), epochs=800, lr=0.5, l2=0.0)
        self.assertGreater(w[0], 0)
        self.assertGreater(fight_model.predict(w, [2.0]), 0.5)
        self.assertLess(fight_model.predict(w, [-2.0]), 0.5)

    def test_regularisation_shrinks_the_weights(self):
        plain = fight_model.fit(self._rows(1.0), epochs=800, lr=0.5, l2=0.0)
        reg = fight_model.fit(self._rows(1.0), epochs=800, lr=0.5, l2=0.5)
        self.assertLess(abs(reg[0]), abs(plain[0]))

    def test_predictions_are_probabilities(self):
        w = fight_model.fit(self._rows(1.0), epochs=200)
        for x in ([10.0], [0.0], [-10.0], [999.0]):
            p = fight_model.predict(w, x)
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)


class TestAuc(unittest.TestCase):
    def test_perfect_separation(self):
        self.assertEqual(fight_model._auc([(0.9, True), (0.1, False)]), 1.0)

    def test_inverted_separation(self):
        self.assertEqual(fight_model._auc([(0.1, True), (0.9, False)]), 0.0)

    def test_no_information_is_a_half(self):
        pairs = [(0.5, True), (0.5, False), (0.5, True), (0.5, False)]
        self.assertEqual(fight_model._auc(pairs), 0.5)

    def test_ties_count_a_half(self):
        self.assertEqual(fight_model._auc([(0.7, True), (0.7, False)]), 0.5)

    def test_one_class_is_undefined_not_a_number(self):
        self.assertTrue(math.isnan(fight_model._auc([(0.9, True)])))


class TestFeatureList(unittest.TestCase):
    def test_venomous_is_deliberately_absent(self):
        """It shows up twice in the whole corpus — a weight for it would be
        fitted to two rows, which is why the plan's proposed keyword budget was
        cut down by the data rather than by preference."""
        for name in fight_model.FEATURES:
            self.assertNotIn("venom", name.lower())

    def test_the_feature_budget_stays_small(self):
        # the parameter-budget rule: a handful of free weights at this sample
        # size, not a model per keyword
        self.assertLessEqual(len(fight_model.FEATURES), 5)


if __name__ == "__main__":
    unittest.main()
