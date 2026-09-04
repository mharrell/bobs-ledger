"""Decision log: every advisory is recorded with join keys back to the
Power.log (basename + byte offset), for the beta advice-vs-outcome corpus."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import decision_log  # noqa: E402
import live  # noqa: E402
from live_coach import LiveCoach  # noqa: E402


class _FakeCoach:
    def analyze(self):
        return {"hero": "Test Hero", "tier": 2, "gold": 5, "board": [],
                "shop_rank": [], "sell_rank": [], "scenario": {"turns": 3},
                "top_move": "1. roll"}

    def state_fingerprint(self):
        return (5, 2)


class TestDecisionLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_dir = decision_log.LOG_DIR
        decision_log.LOG_DIR = self.tmp.name
        live._last_state = None

    def tearDown(self):
        decision_log.LOG_DIR = self._old_dir
        self.tmp.cleanup()

    def _lines(self, name="decision_Power.log.jsonl"):
        path = os.path.join(self.tmp.name, name)
        with open(path, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]

    def test_advise_records_with_join_keys(self):
        live._advise(_FakeCoach(), force=True, log_path="C:\\x\\Power.log",
                     log_offset=123456, game_no=2)
        entries = self._lines()
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["schema"], decision_log.SCHEMA)
        self.assertEqual(e["log"], "Power.log")
        self.assertEqual(e["offset"], 123456)
        self.assertEqual(e["game"], 2)
        self.assertEqual(e["turn"], 3)
        self.assertEqual(e["coach_version"], decision_log.coach_version())
        self.assertIn("analysis", e)

    def test_unchanged_state_not_recorded(self):
        """The fingerprint dedup gates the record — one line, not one per poll."""
        live._advise(_FakeCoach(), force=True, log_path="P.log", log_offset=1)
        live._advise(_FakeCoach(), log_path="P.log", log_offset=2)
        self.assertEqual(len(self._lines("decision_P.log.jsonl")), 1)

    def test_pick_advice_recorded(self):
        c = LiveCoach()
        c.choice = {"ctype": "CHOOSE", "source": None,
                    "options": [("A", "BG33_140"), ("B", "BG33_886")],
                    "picked": None}
        live._advise_pick(c, log_path="P.log", log_offset=99, game_no=1)
        entries = self._lines("decision_P.log.jsonl")
        self.assertEqual(len(entries), 1)
        self.assertIn("choice", entries[0]["analysis"])

    def test_never_raises_on_bad_target(self):
        decision_log.LOG_DIR = os.path.join(self.tmp.name, "no", "such", "dir",
                                            "file")  # unwritable
        decision_log.record({"top_move": "x"}, log_path="P.log")  # must not raise

    def test_game_counter_bumps_per_game(self):
        c = LiveCoach()
        self.assertEqual(c.game_no, 0)
        c.feed("GameState.DebugPrintPower() - CREATE_GAME")
        self.assertEqual(c.game_no, 1)


if __name__ == "__main__":
    unittest.main()