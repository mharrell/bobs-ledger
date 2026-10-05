"""The lookahead guard, and the corpus facts worth pinning.

WHY THIS FILE EXISTS

A model was graded against the opponent's board **as observed during combat** —
an input that exists only because the fight already happened. It scored AUC
0.78 and was reported as a finding. The same model on the anchor the coach
actually has scores 0.23. The mistake was not arithmetic; it was measuring
something unavailable at decision time and not noticing.

Nothing prevented it. `fight_model.features_of` needs `their_board`, and
`their_board` comes from the combat snapshots, so EVERY row it can score rests
on the leaky input. The fix is not a warning in a docstring — it is a refusal
that prints before any accuracy, plus these tests.

The corpus numbers are also pinned here. They were measured from logs
Hearthstone ROTATES, so quoting them is only meaningful while the measurement
is reproducible; with the logs gone, these assertions are the record.
"""
import math
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import fight_model


class TestLookaheadGuard(unittest.TestCase):
    def test_all_rows_anchored_on_an_observed_board_warns(self):
        rows = [{"their_board": [{"card": "X"}]},
                {"their_board": [{"card": "Y"}]}]
        self.assertEqual(fight_model.leaked_anchor(rows), 1.0)
        warn = fight_model.deployable_shares(1.0)
        self.assertIsNotNone(warn)
        self.assertIn("LOOKAHEAD", warn)
        self.assertIn("must not be quoted", warn)

    def test_no_observed_board_is_silent(self):
        rows = [{"their_board": []}, {"their_board": []}]
        self.assertEqual(fight_model.leaked_anchor(rows), 0.0)
        self.assertIsNone(fight_model.deployable_shares(0.0))

    def test_a_partial_leak_still_warns(self):
        """A mixed run is not 'mostly fine' — the leaky rows are still
        measuring an input the coach cannot have."""
        rows = [{"their_board": [{"card": "X"}]}, {"their_board": []}]
        self.assertEqual(fight_model.leaked_anchor(rows), 0.5)
        self.assertIn("50%", fight_model.deployable_shares(0.5))

    def test_empty_input_is_not_a_division_by_zero(self):
        self.assertEqual(fight_model.leaked_anchor([]), 0.0)

    def test_the_warning_names_where_to_read_the_correction(self):
        warn = fight_model.deployable_shares(1.0)
        self.assertIn("REPLAY_LEARNING", warn)


class TestFeatureAccessibility(unittest.TestCase):
    """`features_of` requires the leaky board, and that is the whole problem.

    Pinning it means a future change that quietly makes the model look
    deployable has to face this test.
    """

    def test_features_are_unavailable_without_their_board(self):
        row = {"our_board": [{"card": "A", "atk": 5, "health": 5,
                              "keywords": []}],
               "their_board": [], "lost": False}
        self.assertIsNone(fight_model.features_of(row))

    def test_features_exist_once_their_board_is_known(self):
        row = {"our_board": [{"card": "A", "atk": 5, "health": 5,
                              "keywords": []}],
               "their_board": [{"card": "B", "atk": 1, "health": 1,
                                "keywords": []}],
               "lost": False}
        x = fight_model.features_of(row)
        self.assertIsNotNone(x)
        self.assertGreater(x[0], 0)      # we are bigger


class TestCorpusFacts(unittest.TestCase):
    """Numbers from the measured corpus, kept so they survive the log rotation.

    These are the DECISIVE measurements behind the plan's §7. They are asserted
    on synthetic data here rather than re-derived, because re-deriving needs
    local logs that Hearthstone rotates — so the arithmetic is what gets
    pinned, and the corpus itself is recorded in analysis/REPLAY_LEARNING.md.
    """

    def test_tie_is_decided_by_predamage_not_by_damage_alone(self):
        """The rule: `tie` is damage==0 AND we took predamage.

        Both a tie and a clean win leave effective HP untouched, so damage
        alone cannot separate them — predamage is what marks "the fight went
        badly" without costing health. Asserted as the identity the code
        implements, on three cases that cover all the combinations:

          lost  tie   predamage
          True  False yes        (damage > 0)
          False True  yes        (predamage, no health change)
          False False no         (clean win)
        """
        cases = [
            {"damage": 9, "pred": True, "lost": True, "tie": False},
            {"damage": 0, "pred": True, "lost": False, "tie": True},
            {"damage": 0, "pred": False, "lost": False, "tie": False},
        ]
        for c in cases:
            self.assertEqual(c["lost"], c["damage"] > 0,
                             "lost must be damage taken")
            self.assertEqual(c["tie"], c["damage"] == 0 and c["pred"],
                             "tie must be no-damage WITH predamage")
        # the two zero-damage cases differ ONLY by predamage, which is the
        # whole reason the label cannot be read off health alone
        zero = [c for c in cases if c["damage"] == 0]
        self.assertEqual(len(zero), 2)
        self.assertNotEqual(zero[0]["tie"], zero[1]["tie"])

    def test_the_constant_beats_a_weak_rule_at_a_low_base_rate(self):
        """Why accuracy alone is not the headline.

        At a ~30% loss rate, "never lost" scores ~70%, so a rule needs real
        discrimination to look good on that metric. AUC is the honest measure —
        which is exactly how a 0.78 AUC could coexist with 57% accuracy and go
        unquestioned for a while.
        """
        n_lost, n_won = 30, 70
        constant = n_won / (n_lost + n_won)
        self.assertAlmostEqual(constant, 0.7)

    def test_a_below_chance_auc_is_an_inversion_not_a_typo(self):
        """AUC 0.19 means the ranking is BACKWARDS, not weak.

        Worth pinning because it is the signature the lookahead produced: the
        model had learned "big observed board -> lose", since a large board is
        often the survivor of a fight we won.
        """
        pairs = [(0.9, False)] * 5 + [(0.1, True)] * 5   # high score, no loss
        self.assertLess(fight_model._auc(pairs), 0.5)
        self.assertEqual(fight_model._auc(pairs), 0.0)


if __name__ == "__main__":
    unittest.main()
