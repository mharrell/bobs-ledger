"""The saved-replay store: a review outlives the process, the tab can list
and reload past games, and one corrupt file never takes the dropdown down."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import replay_store  # noqa: E402


def _rep(hero="Chenvaala", placement=2, created="2026-10-06T18:55:02",
         turns=3):
    return {
        "schema": 1, "created": created, "session": "Hearthstone_x",
        "log": "Power.log", "game": 1,
        "hero": hero, "placement": placement,
        "phases": [{"turn": i} for i in range(1, 3)],
        "totals": {"phases": 2, "taken": 1, "ignored": 1},
        "timeline": {"turns": [{"turn": i} for i in range(1, turns + 1)]},
        "timeline_error": None, "caveat": "x",
    }


class TestSave(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)

    def test_save_makes_a_readable_id_and_round_trips(self):
        out = replay_store.save(_rep(), root=self.root.name)
        self.assertEqual(out["id"], "2026-10-06_185502-Chenvaala-2")
        loaded = replay_store.load(out["id"], root=self.root.name)
        self.assertEqual(loaded["rep"]["hero"], "Chenvaala")
        self.assertEqual(loaded["placement"], 2)

    def test_list_rows_are_summaries_without_the_rep(self):
        replay_store.save(_rep(turns=3), root=self.root.name)
        rows = replay_store.list(root=self.root.name)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("rep", rows[0])
        self.assertEqual(rows[0]["turns"], 3)   # timeline turns, not phases
        self.assertEqual(rows[0]["hero"], "Chenvaala")

    def test_same_second_games_get_suffixes_not_overwrites(self):
        a = replay_store.save(_rep(), root=self.root.name)
        b = replay_store.save(_rep(), root=self.root.name)
        self.assertNotEqual(a["id"], b["id"])
        self.assertTrue(os.path.exists(b["path"]))
        self.assertEqual(len(replay_store.list(root=self.root.name)), 2)

    def test_odd_names_are_slugged(self):
        out = replay_store.save(
            _rep(hero="Fae/Whing*er?", placement=None), root=self.root.name)
        self.assertNotIn("/", out["id"])
        self.assertIn("Fae-Whing-er", out["id"])
        self.assertIn("na", out["id"])

    def test_undated_rep_still_saves(self):
        out = replay_store.save(_rep(created=None), root=self.root.name)
        self.assertTrue(out["id"].startswith("undated"))
        self.assertIsNotNone(replay_store.load(out["id"], root=self.root.name))


class TestList(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)

    def test_empty_store_is_an_empty_list_not_an_error(self):
        self.assertEqual(replay_store.list(root=self.root.name), [])
        self.assertIsNone(replay_store.load("x", root=self.root.name))

    def test_newest_first(self):
        replay_store.save(_rep(created="2026-10-05T10:00:00"),
                          root=self.root.name)
        replay_store.save(_rep(created="2026-10-06T10:00:00"),
                          root=self.root.name)
        rows = replay_store.list(root=self.root.name)
        self.assertEqual(rows[0]["created"], "2026-10-06T10:00:00")

    def test_a_corrupt_file_is_skipped(self):
        replay_store.save(_rep(), root=self.root.name)
        with open(os.path.join(self.root.name, "zz-broken.json"), "w") as fh:
            fh.write("{not json")
        rows = replay_store.list(root=self.root.name)
        self.assertEqual([r["id"] for r in rows],
                         ["2026-10-06_185502-Chenvaala-2"])


class TestLoadPathSafety(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)

    def test_separators_and_dots_never_reach_the_filesystem(self):
        for bad in ("../escape", "a/b", "a\\b", "..", "", None, "x y!"):
            self.assertIsNone(replay_store.load(bad, root=self.root.name),
                              f"load({bad!r}) must refuse")

    def test_load_survives_a_deleted_store(self):
        self.assertIsNone(replay_store.load("whatever", root=self.root.name))


if __name__ == "__main__":
    unittest.main()
