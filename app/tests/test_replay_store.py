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
         turns=3, gid=None, game=1):
    return {
        "schema": 1, "created": created, "session": "Hearthstone_x",
        "log": "Power.log", "game": game,
        "hero": hero, "placement": placement,
        "gid": gid,
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

    def test_explicit_rid_updates_in_place(self):
        """The rebuild path re-saves under the KNOWN id — an update, not a
        -2 suffixed copy stacking up beside the game it refreshed."""
        first = replay_store.save(_rep(), root=self.root.name)
        out = replay_store.save(_rep(hero="Rebuilt", turns=5),
                                root=self.root.name, rid=first["id"])
        self.assertEqual(out["id"], first["id"])
        self.assertEqual(sorted(os.listdir(self.root.name)),
                         [first["id"] + ".json"],
                         "no suffix copy beside the game it refreshed")
        loaded = replay_store.load(first["id"], root=self.root.name)
        self.assertEqual(loaded["rep"]["hero"], "Rebuilt")
        self.assertEqual(len(loaded["rep"]["timeline"]["turns"]), 5)


class TestOneGameOneFile(unittest.TestCase):
    """The 2026-10-09 restart bug. The first id was minted from `created` —
    the wall clock AT BUILD — so every restart that caught up on a leftover
    log re-detected the finished game and saved it again under a fresh name.
    The gid, not the clock, decides: the same game saves over itself."""

    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)

    @staticmethod
    def _gid(**over):
        return replay_store.game_gid(over.get("session", "Hearthstone_x"),
                                     over.get("log", "Power.log"),
                                     over.get("game", 1))

    def test_the_same_game_saves_over_itself(self):
        a = replay_store.save(_rep(gid=self._gid()), root=self.root.name)
        b = replay_store.save(_rep(gid=self._gid(), hero="Rebuilt"),
                              root=self.root.name)
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(len(replay_store.list(root=self.root.name)), 1)
        self.assertEqual(
            replay_store.load(a["id"], root=self.root.name)["rep"]["hero"],
            "Rebuilt", "the reprocessing lands in the SAME file")

    def test_two_different_games_keep_both(self):
        a = replay_store.save(_rep(gid=self._gid(game=1), game=1),
                              root=self.root.name)
        b = replay_store.save(_rep(gid=self._gid(game=2), game=2),
                              root=self.root.name)
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(len(replay_store.list(root=self.root.name)), 2)

    def test_a_rep_without_a_gid_keeps_the_suffix_behaviour(self):
        """Every save written before gids existed, and any caller that has
        nothing to key on: the old never-overwrite rule still holds."""
        a = replay_store.save(_rep(), root=self.root.name)
        b = replay_store.save(_rep(), root=self.root.name)
        self.assertNotEqual(a["id"], b["id"])

    def test_rid_for_game_answers_what_the_store_holds(self):
        saved = replay_store.save(_rep(gid=self._gid()),
                                  root=self.root.name)
        self.assertEqual(replay_store.rid_for_game(
            "Hearthstone_x", "Power.log", 1, root=self.root.name),
            saved["id"])
        self.assertIsNone(replay_store.rid_for_game(
            "Hearthstone_x", "Power.log", 2, root=self.root.name))

    def test_the_gid_never_carries_the_session_name(self):
        """The session directory can carry the player's handle; the id is
        what shows up in listings, so it is a one-way hash."""
        gid = self._gid(session="Hearthstone_Someones_Handle")
        self.assertNotIn("Someones_Handle", gid)
        self.assertRegex(gid, r"^[0-9a-f]{16}$")

    def test_a_gidless_pointer_answers_none(self):
        self.assertIsNone(replay_store.game_gid("Hearthstone_x", "Power.log",
                                                None))
        self.assertIsNone(replay_store.rid_for_game("Hearthstone_x",
                                                    "Power.log", None))


class TestBackfill(unittest.TestCase):
    """The one-time migration: give stored games their gid and keep one file
    per game. Runs from the pointer each summary already carries, so it needs
    no log — Hearthstone rotates session logs away, and a migration that
    needed one would quietly never run."""

    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)

    def _write_legacy(self, rid, session, game, created, hero="H"):
        """A file in the pre-gid shape, written the way the old save() did."""
        body = {"id": rid, "hero": hero, "placement": 1, "turns": 1,
                "created": created, "session": session, "log": "Power.log",
                "game": game}
        with open(os.path.join(self.root.name, rid + ".json"), "w",
                  encoding="utf-8") as fh:
            json.dump(body, fh)

    def test_gids_are_added_and_duplicates_collapse(self):
        self._write_legacy("a-older", "Hearthstone_x", 1,
                           "2026-10-01T10:00:00")
        self._write_legacy("a-newer", "Hearthstone_x", 1,
                           "2026-10-02T10:00:00")
        self._write_legacy("b-only", "Hearthstone_x", 2,
                           "2026-10-03T10:00:00")
        out = replay_store.backfill(root=self.root.name)
        self.assertEqual(out["removed"], ["a-older"],
                         "the older build of the same game goes")
        rows = replay_store.list(root=self.root.name)
        self.assertEqual(sorted(r["id"] for r in rows),
                         ["a-newer", "b-only"])
        self.assertTrue(all(r["gid"] for r in rows),
                        "every surviving row carries its gid")

    def test_a_second_run_writes_nothing(self):
        self._write_legacy("only", "Hearthstone_x", 1, "2026-10-01T10:00:00")
        first = replay_store.backfill(root=self.root.name)
        self.assertEqual(first["backfilled"], 1)
        second = replay_store.backfill(root=self.root.name)
        self.assertEqual(second, {"backfilled": 0, "removed": []})

    def test_a_file_with_no_pointer_is_left_alone(self):
        body = {"id": "pointless", "hero": "H", "created": "x"}
        with open(os.path.join(self.root.name, "pointless.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(body, fh)
        out = replay_store.backfill(root=self.root.name)
        self.assertEqual(out, {"backfilled": 0, "removed": []})
        with open(os.path.join(self.root.name, "pointless.json"),
                  encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), body)

    def test_an_absent_store_is_nothing_to_do(self):
        self.assertEqual(replay_store.backfill(root=self.root.name),
                         {"backfilled": 0, "removed": []})


if __name__ == "__main__":
    unittest.main()
