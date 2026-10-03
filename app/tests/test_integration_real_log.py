"""Integration smoke: parse the most recent real session Power.log if it
exists (Hearthstone installed locally). Skipped when absent — the committed
suite stays deterministic. Catches regressions the hand-built fixtures can
miss (log format drift, new card-id shapes)."""
import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import live_coach  # noqa: E402

from config import HS_LOG_GLOB as LOG_GLOB


def _newest_log():
    logs = sorted(glob.glob(LOG_GLOB), key=os.path.getmtime, reverse=True)
    return logs[0] if logs else None


class TestRealLog(unittest.TestCase):
    def setUp(self):
        self.log = _newest_log()
        if not self.log:
            self.skipTest("no Hearthstone session log found")

    def test_turn_one_advises_when_monitor_started_before_game(self):
        """Regression: a game that starts while live.py is already running
        deadlocked at turn 1. The monitor only calls analyze() (which parses
        the hero) when the fingerprint CHANGES, but a fresh game's fingerprint
        is None and the previous state was also None — so the parse never ran
        and no turn ever advised (only the hero pick showed, which ranks
        without the hero). ensure_meta() must flip None -> parseable.
        """
        with open(self.log, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        starts = [i for i, l in enumerate(lines)
                  if "CREATE_GAME" in l and "GameState" in l]
        if not starts:
            self.skipTest(f"{self.log} contains no Battlegrounds game")
        coach = live_coach.LiveCoach()
        for line in lines[starts[0]:]:
            coach.feed(line)
            # Stop at the first shop offers of turn 1 — the exact moment the
            # monitor's fingerprint gate first sees a buy phase.
            if (coach.actions.in_buying and coach.shop_cards
                    and coach.state_fingerprint() is None):
                break
        else:
            self.skipTest(f"{self.log} never reaches a turn-1 shop "
                          f"(short/mid-loading session)")
        # Deadlock precondition: feeding alone never parses the hero, so the
        # fingerprint is still None here (monitor-side: state == last_state).
        self.assertIsNone(coach.state_fingerprint())
        coach.ensure_meta()  # the fix: the monitor retries this each tick
        self.assertIsNotNone(coach.state_fingerprint(),
                             "ensure_meta did not parse the hero from "
                             "lines already fed")
        self.assertIsNotNone(coach.analyze())

    def test_turns_and_board_are_plausible(self):
        with open(self.log, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        starts = [i for i, l in enumerate(lines)
                  if "CREATE_GAME" in l and "GameState" in l]
        if not starts:
            self.skipTest(f"{self.log} contains no Battlegrounds game "
                          f"(different mode session)")
        # Only the last game (the log may still be mid-game).
        seg = lines[starts[-1]:]
        coach = live_coach.LiveCoach()
        for line in seg:
            coach.feed(line)
        # Buy phases are bounded; the old PTL double-count inflated them ~60%.
        self.assertLessEqual(coach.actions.turn, 30)
        a = coach.analyze()
        if a is None:
            # A just-opened client writes a session with a game started but no
            # parseable hero yet — nothing to assert on until a real game runs.
            self.skipTest(f"{self.log} has no parseable game yet "
                          f"(client just opened / mid-loading)")
        # A finished (or in-progress) friendly board parses.
        self.assertIsInstance(a["board"], list)


if __name__ == "__main__":
    unittest.main()