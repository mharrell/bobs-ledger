"""The Settle Up tab's endpoints: list, game, save — and the one contract
that matters most, that a review rep sitting in coach_ui state never leaks
into the live /analysis payload (PIVOT.md; test_live_view pins the same
wall from the payload side)."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import coach_ui  # noqa: E402
import replay_store  # noqa: E402


def _board(card="BG_X_001"):
    return [{"card": card, "atk": 3, "health": 3, "golden": False,
             "keywords": []}]


def _rep(hero="Chenvaala", placement=2, created="2026-10-06T18:55:02"):
    return {
        "schema": 1, "created": created, "session": "Hearthstone_x",
        "log": "Power.log", "game": 1, "hero": hero, "placement": placement,
        "phases": [{"turn": 1, "plan": "1. Buy X", "kind": "taken",
                    "verdict": "taken", "acted": "bought X", "outcome": -3}],
        "totals": {"phases": 1, "taken": 1, "ignored": 0},
        "timeline": {"turns": [{"turn": 1, "gold": 3, "stats": {"buy_end": 9,
                    "growth": 9}, "spend": {"total": 3},
                    "commitment": {"target": "Murlocs"},
                    "buy_end": _board(), "battle_end": _board(),
                    "combat_start": {"ours": _board(), "theirs": _board()},
                    "combat_ours_text": "X 3/3", "combat_theirs_text": "Y 2/2",
                    "buy_end_text": "X 3/3", "battle_end_text": "X 3/3",
                    "sell_questions": [], "notes": []}]},
        "timeline_error": None, "caveat": "c",
    }


class _StoreRoot(unittest.TestCase):
    """Point replay_store at a fresh temp dir for the whole test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(replay_store, "store_dir",
                              lambda root=None: self.tmp.name)
        p.start()
        self.addCleanup(p.stop)


class TestReviewList(_StoreRoot):
    def test_empty_store_lists_nothing(self):
        code, _h, body = coach_ui._review_list_response()
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {"ok": True, "games": []})

    def test_saved_games_appear_newest_first(self):
        replay_store.save(_rep(created="2026-10-05T10:00:00"))
        replay_store.save(_rep(created="2026-10-06T10:00:00"))
        code, _h, body = coach_ui._review_list_response()
        games = json.loads(body)["games"]
        self.assertEqual([g["created"] for g in games],
                         ["2026-10-06T10:00:00", "2026-10-05T10:00:00"])


class TestReviewGame(_StoreRoot):
    def test_saved_game_serves_the_whole_rep(self):
        out = replay_store.save(_rep())
        code, _h, body = coach_ui._review_game_response(out["id"])
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["rep"]["timeline"]["turns"][0]["turn"], 1)

    def test_unknown_id_is_a_json_404_not_an_empty_200(self):
        code, _h, body = coach_ui._review_game_response("no-such-id")
        self.assertEqual(code, 404)
        self.assertIn("no saved replay", json.loads(body)["error"])

    def test_traversal_shaped_id_is_refused_not_read(self):
        code, _h, _b = coach_ui._review_game_response("../../etc")
        self.assertEqual(code, 404)


class TestReviewSave(_StoreRoot):
    def setUp(self):
        super().setUp()
        coach_ui._state.review_rep = None
        self.addCleanup(setattr, coach_ui._state, "review_rep", None)

    def test_no_review_yet_is_a_409_with_the_reason(self):
        code, _h, body = coach_ui._review_save_response()
        self.assertEqual(code, 409)
        self.assertIn("no finished game", json.loads(body)["error"])

    def test_saving_persists_and_names_the_game(self):
        coach_ui.set_review("<html>review</html>", "Settle up — X", rep=_rep())
        code, _h, body = coach_ui._review_save_response()
        self.assertEqual(code, 200)
        rid = json.loads(body)["id"]
        self.assertIn("Chenvaala", rid)
        self.assertEqual(replay_store.load(rid)["rep"]["hero"], "Chenvaala")

    def test_saving_twice_keeps_both(self):
        coach_ui.set_review("<html>r</html>", rep=_rep())
        first = json.loads(coach_ui._review_save_response()[2])["id"]
        second = json.loads(coach_ui._review_save_response()[2])["id"]
        self.assertNotEqual(first, second)


class TestOpenFolder(_StoreRoot):
    """Open folder: the browser cannot open a local directory, so the
    button asks the machine to. The handler must not open Explorer during
    a test — open_dir is the seam."""

    def test_ok_when_the_os_opens(self):
        with mock.patch.object(replay_store, "open_dir",
                               return_value=None) as opener:
            code, _h, body = coach_ui._review_open_folder_response()
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["ok"])
        opener.assert_called_once()

    def test_failure_is_a_500_with_the_reason(self):
        with mock.patch.object(replay_store, "open_dir",
                               return_value="OSError: no file browser"):
            code, _h, body = coach_ui._review_open_folder_response()
        self.assertEqual(code, 500)
        self.assertIn("no file browser", json.loads(body)["error"])


class TestNamedBoards(_StoreRoot):
    """The tab draws card tiles, which want display names; the stored rep
    keeps ids on purpose. The join happens at serve time."""

    def test_served_boards_carry_names(self):
        out = replay_store.save(_rep())
        with mock.patch.object(coach_ui, "_load_bg_names",
                               return_value={"BG_X_001": "Fire Baller"}):
            code, _h, body = coach_ui._review_game_response(out["id"])
        row = json.loads(body)["rep"]["timeline"]["turns"][0]
        for board in (row["buy_end"], row["battle_end"],
                      row["combat_start"]["ours"],
                      row["combat_start"]["theirs"]):
            self.assertEqual([m["name"] for m in board],
                             ["Fire Baller"] * len(board))

    def test_the_stored_file_stays_canonical(self):
        out = replay_store.save(_rep())
        with mock.patch.object(coach_ui, "_load_bg_names",
                               return_value={"BG_X_001": "Fire Baller"}):
            coach_ui._review_game_response(out["id"])
        on_disk = replay_store.load(out["id"])
        for m in on_disk["rep"]["timeline"]["turns"][0]["buy_end"]:
            self.assertNotIn("name", m)

    def test_a_golden_is_named_through_its_base_and_keeps_its_flag(self):
        """The join NAMES cards; goldens are the snapshot's own business.

        `board_state._minion` strips the `_G` suffix and keeps the flag beside
        the base id, so a timeline board carries `{"card": "BG_X_001",
        "golden": true}` — measured on a real 15-turn rep: 0 board ids end in
        `_G`, 91 minions carry golden. The join must therefore add a name and
        touch nothing else, and `value.display_name` is the one place the
        golden spelling lives (lowercase, the string the plan text parses).
        """
        rep = _rep()
        rep["timeline"]["turns"][0]["buy_end"] = [
            {"card": "BG_X_001_G", "atk": 6, "health": 9, "golden": True,
             "keywords": []}]
        out = replay_store.save(rep)
        with mock.patch.object(coach_ui, "_load_bg_names",
                               return_value={"BG_X_001": "Fire Baller"}):
            _code, _h, body = coach_ui._review_game_response(out["id"])
        m = json.loads(body)["rep"]["timeline"]["turns"][0]["buy_end"][0]
        self.assertEqual(m["name"], "Fire Baller (golden)")
        self.assertTrue(m["golden"], "the join must not be what says golden")
        self.assertEqual(m["atk"], 6)


class TestTheWall(_StoreRoot):
    """The review rep lives in coach_ui state. It must behave like the HTML
    already does: invisible to the live payload, present only to /review/*."""

    def test_rep_never_leaks_into_the_live_payload(self):
        coach_ui.set_review("<html>r</html>", rep=_rep())
        code, _h, body = coach_ui._analysis_response(None)
        self.assertEqual(code, 200)
        text = body.decode("utf-8")
        for banned in ("review_rep", "timeline", '"phases"', "top_move",
                       "sell_questions"):
            self.assertNotIn(banned, text)

    def test_rep_survives_a_new_games_clear_like_the_html_does(self):
        # clear_analysis() keeps the finished review on purpose (a new game
        # must not make it look like a dead coach, 2026-10-04). The rep is
        # part of that review, so a late save still works.
        coach_ui.set_review("<html>r</html>", rep=_rep())
        coach_ui.clear_analysis()
        code, _h, body = coach_ui._review_save_response()
        self.assertEqual(code, 200)
        self.assertTrue(replay_store.load(json.loads(body)["id"]))


if __name__ == "__main__":
    unittest.main()
