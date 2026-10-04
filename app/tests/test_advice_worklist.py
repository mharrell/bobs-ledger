"""The ranked worklist: the coach's own numbers, disagreeing with themselves.

The primary signal needs no claim about optimal play. `shop_rank` is the
coach's scoring of the shop; the plan's buy step names the card it
recommended. When the card the player actually bought scores HIGHER on that
same list, the coach has contradicted itself, and both halves of the
contradiction are its own arithmetic.

These tests are the pure ones. They run always; the replay that produces real
rows lives in test_coach_invariants.py behind HEARTH_REAL_SESSION_TESTS=1,
because one real game takes minutes.
"""
import contextlib
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import outcome_audit as oa  # noqa: E402

SAID = "BGS_034"      # what the coach recommended
CHOSEN = "BG25_016"   # what the player actually bought, and scored higher


def _row(rank, said=SAID, bought=(CHOSEN,), lead="buy", turn=6, gold=10,
         followed=True):
    return {"session": "s", "game": 1, "turn": turn, "gold": gold,
            "card": said, "shop_rank": list(rank), "player_buys": list(bought),
            "lead": lead, "followed_buy": followed, "followed_level": followed,
            "followed_roll": followed, "steps": [], "level_cost": None,
            "shop_costs": {}}


class TestDisagreement(unittest.TestCase):
    def test_the_coachs_own_numbers_prefer_what_the_player_bought(self):
        rows = [_row([(SAID, 5.0), (CHOSEN, 9.0)])]
        found = oa.disagreement_rows(rows)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["coach"], SAID)
        self.assertEqual(found[0]["player"], CHOSEN)
        self.assertAlmostEqual(found[0]["delta"], 4.0)

    def test_agreement_is_not_reported(self):
        """The coach recommended its own top card: nothing to see."""
        self.assertEqual(oa.disagreement_rows([_row([(SAID, 9.0),
                                                      (CHOSEN, 4.0)])]), [])

    def test_a_buy_from_off_the_ranked_shop_is_skipped(self):
        """The player may have rolled first; a card the coach never priced is
        not evidence of a contradiction."""
        self.assertEqual(oa.disagreement_rows(
            [_row([(SAID, 5.0)], bought=("NOT_IN_SHOP",))]), [])

    def test_a_recommendation_that_is_not_a_shop_card_is_skipped(self):
        """`card` can be a trinket or hero pick, which is never in the shop."""
        self.assertEqual(oa.disagreement_rows(
            [_row([(CHOSEN, 9.0)], said="BG_TRINKET_PICK")]), [])

    def test_the_player_buying_two_cards_is_judged_on_the_better_one(self):
        rows = [_row([(SAID, 5.0), (CHOSEN, 9.0), ("BG_OTHER", 2.0)],
                     bought=(CHOSEN, "BG_OTHER"))]
        self.assertEqual(oa.disagreement_rows(rows)[0]["player"], CHOSEN)

    def test_the_biggest_contradiction_ranks_first(self):
        rows = [_row([(SAID, 5.0), (CHOSEN, 6.0)], turn=2),
                _row([(SAID, 5.0), (CHOSEN, 20.0)], turn=9)]
        found = oa.disagreement_rows(rows)
        self.assertEqual([f["turn"] for f in found], [9, 2])

    def test_no_rows_is_not_an_error(self):
        self.assertEqual(oa.disagreement_rows([]), [])


class TestIgnoredAdvice(unittest.TestCase):
    def test_ignored_counts_rank_above_followed_ones(self):
        rows = [_row([("a", 1.0)], lead="level", followed=False, turn=t)
                for t in (1, 2, 3)]
        rows += [_row([("a", 1.0)], lead="buy", followed=True, turn=4)]
        summary = oa.ignored_summary(rows)
        self.assertEqual(summary[0], ("level", 3, 3))
        self.assertEqual(summary[1], ("buy", 1, 0))

    def test_only_actionable_leads_are_counted(self):
        """A hold cannot be ignored, and counting it would drown the signal."""
        rows = [_row([("a", 1.0)], lead="hold", followed=False),
                _row([("a", 1.0)], lead="note", followed=False)]
        self.assertEqual(oa.ignored_summary(rows), [])

    def test_the_totals_are_printed_beside_the_ignored_counts(self):
        """A count of 4 means nothing without the 20 it came from."""
        rows = [_row([("a", 1.0)], lead="roll", followed=False, turn=t)
                for t in range(4)]
        self.assertEqual(oa.ignored_summary(rows), [("roll", 4, 4)])


class TestThePrintedWorklist(unittest.TestCase):
    def _output(self, rows):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            oa._print_worklist(rows)
        return buf.getvalue()

    def test_it_names_all_three_signals_in_order(self):
        text = self._output([_row([(SAID, 5.0), (CHOSEN, 9.0)])])
        self.assertLess(text.index("disagreeing with itself"),
                        text.index("impossible advice"))
        self.assertLess(text.index("impossible advice"),
                        text.index("not taken"))

    def test_it_says_how_many_sessions_the_counts_came_from(self):
        text = self._output([_row([(SAID, 5.0), (CHOSEN, 9.0)])])
        self.assertIn("1 session(s)", text)

    def test_it_reports_the_coachs_numbers_not_a_verdict(self):
        text = self._output([_row([(SAID, 5.0), (CHOSEN, 9.0)])])
        self.assertIn("counts, not verdicts", text)

    def test_empty_input_prints_without_crashing(self):
        text = self._output([])
        self.assertIn("0 advisories", text)

    def test_an_impossible_step_is_shown_with_its_purse(self):
        row = _row([(SAID, 1.0)], bought=(), lead="level")
        row["steps"] = [{"kind": "level"}]
        row["level_cost"] = 7
        row["gold"] = 0
        text = self._output([row])
        self.assertIn("LEVEL costs 7 with 0 gold", text)


if __name__ == "__main__":
    unittest.main()
