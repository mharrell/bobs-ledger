"""Reshaping a pre-app/ install into the app/ layout.

Updating a flat install only ADDS app/. Without the reshape, everyone who
already had the coach keeps all 62 loose files at the root that the
reorganisation existed to remove — the folder would look tidy only for people
who happened to download fresh.

The delete list is the dangerous half, so these tests pin what SURVIVES as
carefully as what goes: the player's own files, their logs, the stamps the
update mechanism depends on, and the documents the launcher points at.
"""
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # app/
sys.path.insert(0, HERE)          # the code dir, wherever this runs from

import update  # noqa: E402

#: Root files of an install that was NOT touched by the reshape.
SURVIVORS = ("README.md", "LICENSE", "Start Bob's Ledger.cmd", "VERSION",
             ".update_state.json", "screenshot.png", "my_notes.txt",
             "my_script.py")


def new_layout_zip():
    """A release in the app/ shape — 'app/live.py' in the zip is the signal."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("VERSION", "deadbee\n")
        z.writestr(".update_state.json", json.dumps({"version": "deadbee"}))
        for rel in ("app/live.py", "app/meta/pool_roster.json",
                    "app/tests/test_x.py", "app/python-hslog/hslog.py",
                    "Start Bob's Ledger.cmd", "README.md"):
            z.writestr(rel, "x\n")
    return buf.getvalue()


class LayoutFixture(unittest.TestCase):
    """A flat install, as the release before app/ unpacked it."""

    MODULES = ("live.py", "update.py", "value.py")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self._saved = update.ROOT
        update.ROOT = self.root
        self.data = new_layout_zip()
        # the old flat tree, exactly as it shipped
        for name in self.MODULES:
            self.write(name, "# old module\n")
        for d in ("meta", "tests", "python-hslog"):
            self.write(os.path.join(d, "thing.json"), "old\n")
        for name in ("bobs-ledger.ico", "requirements.txt",
                     "requirements-dev.txt", "DESIGN.md", "ROADMAP.md",
                     ".gitattributes", ".gitignore", ".card_races.json"):
            self.write(name, "old\n")
        # local data the player would notice losing
        self.write(os.path.join("decision_logs", "decision_mine.jsonl"),
                   '{"advice": "keep me"}\n')
        self.write(os.path.join("img_cache", "ABC.png"), "PNG")
        self.write(".art_miss.json", "{}\n")
        # documents and stamps that must survive. The PNG stands in for a file a
        # player left at the root, which the reshape must not touch — it used to
        # be `docs/decide.png`, a directory the repo no longer has (2026-10-06).
        self.write("README.md", "# Bob's Ledger\n")
        self.write("LICENSE", "MIT\n")
        self.write("screenshot.png", "PNG")
        self.write("Start Bob's Ledger.cmd", "@echo off\r\n")
        self.write("VERSION", "b42b652\n")
        self.write(".update_state.json", '{"version": "b42b652"}\n')
        # the player's own files, including a module with no shipped twin
        self.write("my_notes.txt", "mine\n")
        self.write("my_script.py", "# mine\n")
        # the release has already landed: apply_zip runs first, on purpose
        for name in self.MODULES:
            self.write(os.path.join("app", name), "# new module\n")
        for d in ("meta", "tests", "python-hslog"):
            self.write(os.path.join("app", d, "thing.json"), "new\n")
        self.write(os.path.join("app", ".card_races.json"), "new snapshot\n")

    def tearDown(self):
        update.ROOT = self._saved
        self._tmp.cleanup()

    def write(self, rel, body):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(body)

    def exists(self, rel):
        return os.path.exists(os.path.join(self.root, rel))

    def read(self, rel):
        with open(os.path.join(self.root, rel), encoding="utf-8") as f:
            return f.read()


class TestDetection(LayoutFixture):
    def test_a_flat_install_is_recognised(self):
        self.assertTrue(update.looks_pre_app(self.data))

    def test_a_nested_install_is_left_completely_alone(self):
        os.remove(os.path.join(self.root, "live.py"))
        self.assertFalse(update.looks_pre_app(self.data))
        self.assertEqual(update.migrate_flat_layout(self.data), [])
        self.assertTrue(self.exists("meta/thing.json"))
        self.assertTrue(self.exists("decision_logs/decision_mine.jsonl"))

    def test_an_old_shaped_zip_never_triggers_it(self):
        """A release in the OLD shape has no app/live.py: updating one flat
        install with another must not start moving data around."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("live.py", "x")
        self.assertFalse(update.looks_pre_app(buf.getvalue()))

    def test_a_corrupt_zip_never_triggers_it(self):
        self.assertFalse(update.looks_pre_app(b"not a zip at all"))


class TestReshape(LayoutFixture):
    def setUp(self):
        super().setUp()
        self.done = update.migrate_flat_layout(self.data)

    def test_local_data_follows_the_code(self):
        self.assertTrue(self.exists("app/decision_logs/decision_mine.jsonl"))
        self.assertIn("keep me",
                      self.read("app/decision_logs/decision_mine.jsonl"))
        self.assertFalse(self.exists("decision_logs"))
        self.assertTrue(self.exists("app/img_cache/ABC.png"))
        self.assertFalse(self.exists("img_cache"))
        self.assertTrue(self.exists("app/.art_miss.json"))

    def test_the_old_flat_tree_is_gone(self):
        for name in self.MODULES + ("meta", "tests", "python-hslog",
                                    "bobs-ledger.ico", "requirements.txt",
                                    "requirements-dev.txt", "DESIGN.md",
                                    "ROADMAP.md", ".gitattributes",
                                    ".gitignore"):
            self.assertFalse(self.exists(name), f"{name} survived the reshape")

    def test_stale_bytecode_from_the_flat_modules_goes_too(self):
        self.assertFalse(self.exists("__pycache__"))

    def test_the_new_tree_is_not_damaged(self):
        for rel in ("app/live.py", "app/meta/thing.json",
                    "app/tests/thing.json", "app/python-hslog/thing.json"):
            self.assertTrue(self.exists(rel), f"{rel} was damaged")

    def test_player_documents_and_stamps_survive(self):
        for name in SURVIVORS:
            self.assertTrue(self.exists(name), f"{name} was deleted")

    def test_the_shipped_snapshot_beats_the_stale_local_cache(self):
        self.assertEqual(self.read("app/.card_races.json"), "new snapshot\n")
        self.assertFalse(self.exists(".card_races.json"))

    def test_it_says_what_it_did(self):
        self.assertTrue(any("decision_logs" in line for line in self.done))
        self.assertIn("removed the old live.py", self.done)


class TestMergeNeverOverwrites(LayoutFixture):
    def test_a_colliding_log_keeps_both(self):
        self.write(os.path.join("app", "decision_logs", "decision_new.jsonl"),
                   "new\n")
        update.migrate_flat_layout(self.data)
        self.assertEqual(
            self.read("app/decision_logs/decision_new.jsonl"), "new\n")
        self.assertEqual(
            self.read("app/decision_logs/decision_mine.jsonl"),
            '{"advice": "keep me"}\n')

    def test_a_colliding_file_leaves_the_root_copy_in_place(self):
        """Never silently drop a file: if a name collides, the root copy stays
        (and so does its directory) rather than being deleted as 'moved'."""
        self.write(os.path.join("app", "img_cache", "ABC.png"), "NEW")
        update.migrate_flat_layout(self.data)
        self.assertEqual(self.read("app/img_cache/ABC.png"), "NEW")
        self.assertTrue(self.exists("img_cache/ABC.png"))

    def test_a_locked_path_is_reported_and_does_not_abort_the_rest(self):
        """A cache held open by a running coach must not stop the tidy-up."""
        target = os.path.join(self.root, "img_cache")
        real_move = update.shutil.move

        def refuse(src, dst, *a, **kw):
            if os.path.abspath(str(src)) == os.path.abspath(target):
                raise OSError("in use by another process")
            return real_move(src, dst, *a, **kw)

        update.shutil.move = refuse
        try:
            done = update.migrate_flat_layout(self.data)
        finally:
            update.shutil.move = real_move
        self.assertTrue(any("could not move img_cache" in line
                            for line in done))
        # everything else still happened
        self.assertTrue(self.exists("app/decision_logs/decision_mine.jsonl"))
        self.assertFalse(self.exists("live.py"))


@unittest.skipUnless(sys.platform == "win32",
                     "the read-only ATTRIBUTE is a Windows concept")
class TestWindowsReadOnlyAttribute(LayoutFixture):
    """Windows' read-only ATTRIBUTE is not a lock, and both halves of the
    update used to treat it as one.

    Found by rehearsing the reshape against a real install the user had copied
    out of OneDrive: those directories carry FILE_ATTRIBUTE_READONLY, so
    rmtree refused them with WinError 5 and three stale directories survived
    an update in which nothing was locked at all (2026-10-02).

    Read the attribute through os.stat, NOT os.access: the CRT reports a
    read-only DIRECTORY as writable, which is exactly the trap that made an
    earlier version of this test pass a broken fixture.
    """

    def assertReadOnly(self, path):
        self.assertFalse(os.stat(path).st_mode & stat.S_IWRITE,
                         f"{path} is not read-only")

    def test_plain_rmtree_is_defeated_by_the_attribute(self):
        """The witness for the workaround: without it, this is the failure the
        rehearsal hit. If this ever stops raising, the read-only handling can
        be deleted — that is what this test is here to tell you."""
        target = os.path.join(self.root, "meta")
        os.chmod(target, stat.S_IREAD)
        self.assertReadOnly(target)
        try:
            with self.assertRaises(OSError):
                shutil.rmtree(target)
        finally:
            os.chmod(target, stat.S_IWRITE)   # let the fixture clean up

    def test_a_read_only_old_directory_is_still_removed(self):
        target = os.path.join(self.root, "meta")
        os.chmod(target, stat.S_IREAD)
        self.assertReadOnly(target)
        done = update.migrate_flat_layout(self.data)
        self.assertFalse(self.exists("meta"))
        self.assertNotIn("could not remove the old meta/", done)

    def test_a_read_only_file_is_overwritten_by_an_update(self):
        """Otherwise one read-only file makes every future update fail, with
        an error that reads like a permissions problem the player cannot fix."""
        target = os.path.join(self.root, "app", "live.py")
        with open(target, "w", encoding="utf-8", newline="") as f:
            f.write("# old\n")
        os.chmod(target, stat.S_IREAD)
        self.assertReadOnly(target)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("app/live.py", "# new\n")
        written = update.apply_zip(buf.getvalue(), root=self.root)
        self.assertEqual(written, 1)
        with open(target, encoding="utf-8") as f:
            self.assertEqual(f.read(), "# new\n")


if __name__ == "__main__":
    unittest.main()
