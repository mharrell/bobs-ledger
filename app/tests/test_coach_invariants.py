"""The two invariants that 2026-10-03 proved the suite could not see.

1119 tests passed while the coach told a player to LEVEL as step 5 of a turn
with 0 gold left, and while it issued nothing at all through turn 1 of a game
it was already watching. Neither is visible to a test that hands the coach a
hand-built analysis dict: both are about what the coach knows and says at a
moment in a real game. So the pure checks are tested here directly, and the
real-session replay behind them is opt-in (HEARTH_REAL_SESSION_TESTS=1) the
same way the other session-dependent tests are, because one replay of a real
game takes minutes.
"""
import glob
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))

import outcome_audit  # noqa: E402
import real_logs  # noqa: E402

OPT_IN = os.environ.get("HEARTH_REAL_SESSION_TESTS") == "1"
NO_SESSION = unittest.skipUnless(
    OPT_IN, "set HEARTH_REAL_SESSION_TESTS=1 to replay a real session")


def _row(gold, steps, level_cost=None, shop_costs=None, turn=5):
    return {"session": "probe", "game": 1, "turn": turn, "gold": gold,
            "steps": steps, "level_cost": level_cost,
            "shop_costs": shop_costs or {}}


class TestPlanCostViolations(unittest.TestCase):
    """Narrow on purpose: an empty purse needs no price to judge, and with gold
    in hand the two cost fields have not been confirmed against their writers
    (three false "impossible buy" findings, 2026-10-04)."""

    def test_a_level_with_no_gold_left_is_reported(self):
        """The 2026-10-03 shape: LEVEL planned on a purse of 0."""
        bad = outcome_audit.plan_cost_violations(
            [_row(0, [{"kind": "level"}], level_cost=7)])
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["step"], "LEVEL")
        self.assertEqual(bad[0]["gold"], 0)

    def test_a_buy_with_no_gold_left_is_reported(self):
        bad = outcome_audit.plan_cost_violations(
            [_row(0, [{"kind": "buy", "card": "BGS_034"}])])
        self.assertEqual([b["step"] for b in bad], ["Buy BGS_034"])

    def test_a_funded_purse_is_not_judged_at_all(self):
        """2 gold cannot buy a 3-gold minion by the game's rules, but the
        analysis's cost fields are not a price list this check can trust, so it
        says nothing rather than guessing."""
        self.assertEqual(outcome_audit.plan_cost_violations(
            [_row(2, [{"kind": "buy", "card": "BGS_034"}],
                  shop_costs={"BGS_034": 3})]), [])
        self.assertEqual(outcome_audit.plan_cost_violations(
            [_row(1, [{"kind": "level"}], level_cost=5)]), [])

    def test_steps_that_are_not_purchases_are_never_flagged(self):
        """A roll or a hold with 0 gold is not the bug: the bug was telling a
        player to BUY or LEVEL something."""
        self.assertEqual(outcome_audit.plan_cost_violations(
            [_row(0, [{"kind": "roll"}, {"kind": "note"},
                      {"kind": "hold"}, {"kind": "sell"}])]), [])

    def test_an_unknown_purse_is_skipped_not_passed(self):
        """gold=None was the account-map bug (fixed 2026-10-03). It has its own
        check; this one must not count it as an empty purse either."""
        self.assertEqual(outcome_audit.plan_cost_violations(
            [_row(None, [{"kind": "level"}], level_cost=7)]), [])

    def test_the_report_carries_enough_to_find_the_phase(self):
        bad = outcome_audit.plan_cost_violations(
            [_row(0, [{"kind": "level"}], turn=9)])
        self.assertEqual((bad[0]["turn"], bad[0]["gold"]), (9, 0))


@NO_SESSION
class TestAgainstARealSession(unittest.TestCase):
    """Opt in: these replay a real game, which takes minutes, not milliseconds.

    They assert the two things that were wrong on 2026-10-03 and could not be
    seen by any unit test. A failure here is a coaching bug, not a test bug.
    """

    @classmethod
    def setUpClass(cls):
        # The size preference in real_logs exists to keep the DEFAULT suite
        # fast; here the slow, rich session is the point, so it is lifted for
        # this opt-in test rather than the rule being loosened for everyone.
        with mock.patch.object(real_logs, "MAX_BYTES", 1 << 40):
            cls.log = real_logs.newest_settled()
        if not cls.log:
            raise unittest.SkipTest(real_logs.why_none())
        with open(cls.log, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        # The first game only: one replay is already minutes, and the checks
        # are per-game.
        starts = [i for i, l in enumerate(lines)
                  if "CREATE_GAME" in l and "GameState" in l]
        if not starts:
            raise unittest.SkipTest(f"{cls.log} contains no Battlegrounds game")
        cls.chunk = lines[starts[0]:starts[1] if len(starts) > 1 else len(lines)]

    def test_no_advisory_asked_for_what_the_purse_could_not_buy(self):
        rows = outcome_audit.audit_game(self.chunk, 1,
                                        os.path.basename(self.log))
        self.assertTrue(rows, "the replay produced no advisories to check")
        bad = outcome_audit.plan_cost_violations(rows)
        self.assertEqual(
            bad, [], f"{len(bad)} of {len(rows)} advisories asked for a step "
                     f"the purse could not buy, e.g. {bad[:3]}")

    def test_the_coach_knows_who_is_playing_at_the_first_shop(self):
        identified, detail = outcome_audit.player_identified_before_first_shop(
            self.chunk)
        if identified is None:
            self.skipTest(detail)
        self.assertTrue(identified, detail)


if __name__ == "__main__":
    unittest.main()
