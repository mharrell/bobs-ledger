"""One game per report, sent when that game ends (2026-10-04).

Sharing used to distil a whole SESSION and only fire when the session ended.
Measured: the player finished a game, closed Hearthstone, and nothing left the
machine until they closed the coach window — and if that window is closed with
the X button the process is terminated instead of running live.py's cleanup, so
an abandoned session shared nothing at all. Every report that did go also mixed
several games together.

This file covers the two seams that make per-game reports possible: the game
filter in session_report.build, and share_session keying one report id per
game. The live.py trigger and the unsent-games backstop come next; nothing here
changes what a summary CONTAINS, which SPEC and verify() still decide.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import session_report  # noqa: E402
import share  # noqa: E402


def _advisory(game, turn=5, cid="BGS_034"):
    """One decision record, shaped like the real ones."""
    return {"schema": 1, "ts": "2026-10-04T10:30:00", "coach_version": "test",
            "log": "Power.log", "offset": turn * 100, "game": game,
            "turn": turn, "gold": 3, "tier": 2, "health": 30,
            "analysis": {"situation": "probe", "top_move": "Buy a thing",
                         "top_move_steps": [{"text": "Buy a thing",
                                             "kind": "buy",
                                             "card": cid}],
                         "board": [], "hand": [], "shop_rank": [[cid, 5.0]]}}


class TestTheGameFilter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # The id map is a file beside the logs; keep the real one out of it.
        self._old = session_report.ID_MAP_DIR
        session_report.ID_MAP_DIR = self.tmp.name

    def tearDown(self):
        session_report.ID_MAP_DIR = self._old
        self.tmp.cleanup()

    def test_only_the_named_game_is_included(self):
        records = [_advisory(1), _advisory(2), _advisory(2), _advisory(3)]
        report = session_report.build(records, session_key="s#2", game=2)
        self.assertEqual(report["manifest"]["advisories"], 2)
        self.assertEqual(report["manifest"]["games"], 1)

    def test_no_filter_still_reports_every_game(self):
        """The old behaviour, for callers that want a whole session."""
        records = [_advisory(1), _advisory(2), _advisory(3)]
        report = session_report.build(records, session_key="s")
        self.assertEqual(report["manifest"]["games"], 3)

    def test_a_game_with_no_advisories_is_an_empty_report_not_an_error(self):
        report = session_report.build([_advisory(1)], session_key="s#9", game=9)
        self.assertEqual(report["manifest"]["advisories"], 0)
        self.assertEqual(report["advisories"], [])

    def test_each_game_keeps_its_own_report_id(self):
        """A re-send of the same game must be byte-identical, so the id has to
        be stable per game - and different between games."""
        one = session_report.build([_advisory(1)], session_key="s#1",
                                   game=1)["manifest"]["report_id"]
        again = session_report.build([_advisory(1)], session_key="s#1",
                                     game=1)["manifest"]["report_id"]
        two = session_report.build([_advisory(2)], session_key="s#2",
                                   game=2)["manifest"]["report_id"]
        self.assertEqual(one, again)
        self.assertNotEqual(one, two)

    def test_the_privacy_whitelist_still_verifies_a_per_game_report(self):
        ok, problems = session_report.verify(
            session_report.build([_advisory(2)], session_key="s#2", game=2))
        self.assertTrue(ok, problems)


class TestShareSessionWiring(unittest.TestCase):
    """share_session is pointed at one game: the filter is passed through and
    the id key carries the game, which is what keeps the re-send identical."""

    def _capture(self, **kwargs):
        captured = {}

        def fake_build(records, **kw):
            captured.update(kw)
            captured["records"] = records
            return {"manifest": {"report_id": "x"}, "advisories": []}

        with mock.patch.object(session_report, "decisions_for",
                               return_value=[_advisory(1), _advisory(2)]), \
                mock.patch.object(session_report, "build", fake_build), \
                mock.patch.object(share, "post_report",
                                  return_value=(True, "sent")):
            share.share_session("Power.log", url="http://test", quiet=True,
                                **kwargs)
        return captured

    def test_the_session_key_carries_the_game(self):
        captured = self._capture(game=2)
        self.assertTrue(captured["session_key"].endswith("#2"),
                        captured["session_key"])
        self.assertEqual(captured["game"], 2)

    def test_no_game_means_the_session_key_is_unchanged(self):
        captured = self._capture()
        self.assertFalse(captured["session_key"].endswith("#"),
                         captured["session_key"])
        self.assertIsNone(captured["game"])

    def test_the_old_two_argument_call_still_works(self):
        """live.py calls share_session(log_path, url, quiet) today; a new
        keyword must not break that path. Run through the REAL build, so this
        covers the whole call rather than a mock's idea of it."""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(session_report, "ID_MAP_DIR", td), \
                    mock.patch.object(session_report, "decisions_for",
                                      return_value=[_advisory(1)]), \
                    mock.patch.object(share, "post_report",
                                      return_value=(True, "sent")):
                share.share_session("Power.log", "http://test", True)


if __name__ == "__main__":
    unittest.main()
