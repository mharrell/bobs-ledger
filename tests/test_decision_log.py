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


class TestSessionStem(unittest.TestCase):
    """Every session's log is named Power.log, so basename-keyed files
    collapsed all sessions into one pile (the 2026-10-01 telemetry test
    PUT a 27 MB bundle carrying every session since 09-04)."""

    def test_session_dir_name_wins(self):
        self.assertEqual(
            decision_log.session_stem(
                r"C:\Hearthstone\Logs\Hearthstone_2026_01_01\Power.log"),
            "Hearthstone_2026_01_01")

    def test_bare_log_falls_back_to_basename(self):
        self.assertEqual(decision_log.session_stem(r"C:\x\Power.log"),
                         "Power.log")
        self.assertEqual(decision_log.session_stem(None), "unknown")


class TestDecisionsForSession(unittest.TestCase):
    """The legacy shared pile is filtered to the packaged log's own
    creation->last-write window — one session's bundle carries one
    session's decisions."""

    def test_legacy_pile_filters_to_the_log_window(self):
        import datetime
        import json as _json
        from unittest import mock

        import package_corpus

        recs = [{"ts": "2026-09-30T17:00:00", "turn": 1},
                {"ts": "2026-09-30T21:00:00", "turn": 2},
                {"ts": "2026-10-01T09:00:00", "turn": 3}]
        with tempfile.TemporaryDirectory() as td:
            legacy = os.path.join(td, "decision_Power.log.jsonl")
            with open(legacy, "w", encoding="utf-8") as f:
                for r in recs:
                    f.write(_json.dumps(r) + "\n")
            log = os.path.join(td, "Hearthstone_2026_01_01",
                               "Power.log")
            os.makedirs(os.path.dirname(log))
            open(log, "w").close()
            lo = datetime.datetime(2026, 9, 30, 16, 0).timestamp()
            hi = datetime.datetime(2026, 9, 30, 21, 30).timestamp()
            with mock.patch.object(decision_log, "LOG_DIR", td), \
                 mock.patch.object(os.path, "getctime", return_value=lo), \
                 mock.patch.object(os.path, "getmtime", return_value=hi):
                got = package_corpus.decisions_for_session(log)
        self.assertEqual([r["turn"] for r in got], [1, 2])


if __name__ == "__main__":
    unittest.main()