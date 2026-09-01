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

LOG_GLOB = r"C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_*\Power.log"


def _newest_log():
    logs = sorted(glob.glob(LOG_GLOB), key=os.path.getmtime, reverse=True)
    return logs[0] if logs else None


class TestRealLog(unittest.TestCase):
    def setUp(self):
        self.log = _newest_log()
        if not self.log:
            self.skipTest("no Hearthstone session log found")

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
        self.assertTrue(a, "analyze() returned nothing for the last game")
        # A finished (or in-progress) friendly board parses.
        self.assertIsInstance(a["board"], list)


if __name__ == "__main__":
    unittest.main()