"""The save-every-replay checkbox: the answer, the endpoint, the card, the write.

The feature has four halves, and missing any one is the old failure mode of
a control that does nothing (2026-10-07):

1. the answer persists on disk (`replay_store.AUTO_PATH`), defaulting to no;
2. POST /review/auto-save persists exactly what it is handed and refuses
   anything else;
3. the end-of-game card's payload carries the answer, so the checkbox
   renders checked while it stands;
4. the finished game's replay is written as the review builds when — and
   only when — the answer is yes (`coach_ui.auto_save_current_review`),
   with no click.

The path patching mirrors test_share.py (the consent answer is the same
shape of thing), and the store override mirrors test_replay_store.py.
"""
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import coach_ui  # noqa: E402
import replay_store  # noqa: E402


def _rep(hero="Chenvaala", placement=2):
    """A minimal rep, the same shape test_replay_store saves."""
    return {"hero": hero, "placement": placement,
            "created": "2026-10-07T19:00:00", "turns": 12,
            "log": "session_dir", "game": 3, "timeline": {"turns": []}}


class _Patched(unittest.TestCase):
    """AUTO_PATH in a tmp dir; the store inside the same tmp dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_path = replay_store.AUTO_PATH
        self._saved_dir = replay_store.store_dir
        replay_store.AUTO_PATH = os.path.join(self._tmp.name,
                                              ".save_all_replays.json")
        store = os.path.join(self._tmp.name, "saved_replays")
        replay_store.store_dir = (lambda root=None: store)
        self._store = store

    def tearDown(self):
        replay_store.AUTO_PATH = self._saved_path
        replay_store.store_dir = self._saved_dir
        self._tmp.cleanup()

    def _saved_review(self):
        coach_ui.set_review("<html>review</html>", rep=_rep())
        self.addCleanup(coach_ui.set_review, "", None)
        return coach_ui.current_review_rep()

    def _store_files(self):
        """The store is created by the first save; an absent directory is
        an empty store."""
        return os.listdir(self._store) if os.path.isdir(self._store) else []


class TestTheAnswer(_Patched):
    """The answer lives on disk and defaults to no."""

    def test_unanswered_is_off(self):
        self.assertFalse(replay_store.auto_save_enabled())

    def test_set_true_round_trips(self):
        replay_store.set_auto_save(True)
        self.assertTrue(replay_store.auto_save_enabled())
        with open(replay_store.AUTO_PATH, encoding="utf-8") as f:
            body = json.load(f)
        self.assertTrue(body["save_all"])
        self.assertEqual(body["schema"], 1)
        self.assertIn("answered", body)

    def test_set_false_round_trips(self):
        replay_store.set_auto_save(True)
        replay_store.set_auto_save(False)
        self.assertFalse(replay_store.auto_save_enabled())

    def test_a_corrupt_file_is_off_not_an_error(self):
        with open(replay_store.AUTO_PATH, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertFalse(replay_store.auto_save_enabled())


class TestTheEndpoint(_Patched):
    """POST /review/auto-save persists the answer and refuses the rest."""

    def _post(self, body, raw=False):
        srv = coach_ui.start_server(0)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        url = (f"http://127.0.0.1:{srv.server_address[1]}"
               f"/review/auto-save")
        data = body if raw else json.dumps(body).encode()
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_true_is_persisted_and_answered(self):
        code, body = self._post({"enabled": True})
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertTrue(body["enabled"])
        self.assertTrue(replay_store.auto_save_enabled())

    def test_false_is_persisted_too(self):
        replay_store.set_auto_save(True)
        code, _body = self._post({"enabled": False})
        self.assertEqual(code, 200)
        self.assertFalse(replay_store.auto_save_enabled())

    def test_a_non_bool_is_refused(self):
        code, body = self._post({"enabled": "yes"})
        self.assertEqual(code, 400)
        self.assertIn("enabled", body["error"])
        self.assertFalse(replay_store.auto_save_enabled())

    def test_bad_json_is_refused(self):
        code, _body = self._post(b"{nope", raw=True)
        self.assertEqual(code, 400)


class TestTheCard(_Patched):
    """The game-over card's payload carries the answer for the checkbox."""

    def _payload(self, game_over=None):
        return json.loads(coach_ui.welcome_payload(game_over=game_over))

    def test_the_card_carries_the_answer_and_its_label(self):
        p = self._payload(game_over={"placement": 2})
        self.assertIn("auto_save", p)
        self.assertFalse(p["auto_save"]["enabled"])
        self.assertEqual(p["auto_save"]["label"],
                         "Save every replay automatically")

    def test_the_card_reflects_a_yes(self):
        replay_store.set_auto_save(True)
        self.assertTrue(self._payload(game_over={"placement": 2})
                        ["auto_save"]["enabled"])

    def test_a_page_payload_is_not_an_analysis_field(self):
        """The same wall share_state sits behind: `render_json` — the one
        place the analysis becomes the page's view — never carries the
        answer. It is added in welcome_payload only, so it cannot reach
        `decision_log` and therefore cannot reach `session_report.SPEC`."""
        import test_live_view
        out = coach_ui.render_json(test_live_view._analysis())
        self.assertNotIn("auto_save", out)


class TestTheWrite(_Patched):
    """The checkbox's promise: the replay is written without a click."""

    def test_off_saves_nothing(self):
        self._saved_review()
        self.assertIsNone(coach_ui.auto_save_current_review())
        self.assertEqual(self._store_files(), [])

    def test_on_saves_the_finished_game(self):
        self._saved_review()
        replay_store.set_auto_save(True)
        rid = coach_ui.auto_save_current_review()
        self.assertTrue(rid)
        self.assertEqual(os.listdir(self._store), [rid + ".json"])

    def test_no_finished_game_saves_nothing_even_when_on(self):
        replay_store.set_auto_save(True)
        self.assertIsNone(coach_ui.auto_save_current_review())
        self.assertEqual(self._store_files(), [])

    def test_an_empty_review_clears_the_target(self):
        """set_review("", ...) resets the rep to None (the "build failed"
        path) — the write must not resurrect it."""
        coach_ui.set_review("", rep=_rep())
        self.assertIsNone(coach_ui.current_review_rep())


if __name__ == "__main__":
    unittest.main()
