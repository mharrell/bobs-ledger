"""Atomic updates: a killed commit must not leave a broken install.

The update used to rewrite the install file by file. Killed part way through
that left a tree of two versions at once — with no way back but downloading
the zip again. The sequence is now stage -> verify -> commit (one atomic move
per file, everything replaced set aside first) -> verify -> tidy, with the
phase written to disk so a later start can finish whichever direction was
interrupted.

Two directions are tested with equal care. Undoing a half-applied update is
the obvious one; the subtler one is that recovery must NOT undo a commit that
verified, because that would throw away a good update — and the marker that
separates the two is a rename, which is why it cannot be half-written.
"""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import update  # noqa: E402

V1 = {"VERSION": "v1", "README.md": "old readme\n",
      "app/live.py": "OLD LIVE\n", "app/value.py": "OLD VALUE\n"}
V2 = {"VERSION": "v2", "README.md": "new readme\n",
      "app/live.py": "NEW LIVE\n", "app/value.py": "NEW VALUE\n",
      "app/brand_new.py": "NEW MODULE\n"}
#: What the player creates. None of it is in a release, so none of it may move.
PLAYER_DATA = {"app/decision_logs/decision_x.jsonl": '{"a": 1}\n',
               "app/.share_consent.json": '{"choice": "on"}\n',
               "app/session_reports/report_ab.json.gz": "not really gzip",
               "app/img_cache/art.png": "PNG"}


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for rel, body in files.items():
            z.writestr(rel, body)
    return buf.getvalue()


def _write(root, files):
    for rel, body in files.items():
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)


def _read(root, rel):
    with open(os.path.join(root, *rel.split("/")), encoding="utf-8") as f:
        return f.read()


def _install(root, files):
    _write(root, files)
    return root


class TestAMidCommitFailure(unittest.TestCase):
    def test_the_install_is_left_exactly_as_it_was(self):
        """A locked file — a second coach window is the real case — must not
        leave a half-updated install behind."""
        with tempfile.TemporaryDirectory() as td:
            _install(td, V1)
            real = os.replace
            calls = {"n": 0}

            def flaky(src, dst):
                calls["n"] += 1
                if calls["n"] == 3:
                    raise PermissionError(13, "Permission denied", dst)
                return real(src, dst)

            with mock.patch.object(os, "replace", flaky):
                written = update.apply_zip(_zip(V2), root=td)
            self.assertEqual(written, 0)
            self.assertIsNotNone(update.LAST_ERROR)
            for rel, body in V1.items():
                self.assertEqual(_read(td, rel), body, rel)
            self.assertFalse(os.path.exists(
                os.path.join(td, "app", "brand_new.py")))
            self.assertFalse(os.path.isdir(os.path.join(td, ".staging")),
                             "a failed commit must not leave its stage behind")

    def test_a_killed_commit_is_undone_at_the_next_start(self):
        """The kill case the markers exist for: no rollback ran, so the
        install is part old and part new until recovery finishes it."""
        with tempfile.TemporaryDirectory() as td:
            _install(td, V1)
            real = os.replace
            calls = {"n": 0}

            def killed(src, dst):
                calls["n"] += 1
                if calls["n"] == 5:
                    raise KeyboardInterrupt("killed")
                return real(src, dst)

            with mock.patch.object(os, "replace", killed):
                with self.assertRaises(KeyboardInterrupt):
                    update.apply_zip(_zip(V2), root=td)
            # Part old, part new — the state that used to be terminal.
            self.assertEqual(_read(td, "VERSION"), "v2")
            self.assertTrue(os.path.exists(
                os.path.join(td, ".staging", update.APPLYING)))

            message = update.recover(td)
            self.assertIn("interrupted", message)
            for rel, body in V1.items():
                self.assertEqual(_read(td, rel), body, rel)
            self.assertFalse(os.path.exists(
                os.path.join(td, "app", "brand_new.py")),
                "a file the interrupted release added must not survive it")
            self.assertFalse(os.path.isdir(os.path.join(td, ".staging")))

    def test_recovery_does_not_undo_a_commit_that_verified(self):
        """The dangerous direction: APPLIED means the update is good, and
        rolling it back would throw it away."""
        with tempfile.TemporaryDirectory() as td:
            _install(td, V1)
            entries, refused = update.stage_release(_zip(V2), root=td)
            self.assertEqual(refused, [])
            ok, problems = update.verify_tree(
                entries, update._stage_dir(td, "new"))
            self.assertTrue(ok, problems)
            written, errors = update.commit_staged(entries, root=td)
            self.assertEqual(errors, [])
            self.assertEqual(written, len(entries))
            # apply_zip's cleanup is skipped on purpose: this is the state a
            # kill between "verified" and "tidied up" leaves behind.
            self.assertTrue(os.path.exists(
                os.path.join(td, ".staging", update.APPLIED)))

            update.recover(td)
            self.assertEqual(_read(td, "VERSION"), "v2")
            self.assertEqual(_read(td, "app/brand_new.py"), "NEW MODULE\n")
            self.assertFalse(os.path.isdir(os.path.join(td, ".staging")))


class TestAPlainUpdate(unittest.TestCase):
    def test_every_file_lands_and_the_stage_is_cleaned(self):
        with tempfile.TemporaryDirectory() as td:
            _install(td, V1)
            written = update.apply_zip(_zip(V2), root=td)
            self.assertEqual(written, len(V2))
            for rel, body in V2.items():
                self.assertEqual(_read(td, rel), body, rel)
            self.assertFalse(os.path.isdir(os.path.join(td, ".staging")))

    def test_player_data_is_never_touched(self):
        """The install promise: an update replaces shipped files and nothing
        else — and the slowed-down sequence must not change that."""
        with tempfile.TemporaryDirectory() as td:
            _install(td, {**V1, **PLAYER_DATA})
            update.apply_zip(_zip(V2), root=td)
            for rel, body in PLAYER_DATA.items():
                self.assertEqual(_read(td, rel), body, rel)
            self.assertEqual(_read(td, "app/live.py"), "NEW LIVE\n")

    def test_nothing_to_recover_when_nothing_was_interrupted(self):
        with tempfile.TemporaryDirectory() as td:
            _install(td, V1)
            update.apply_zip(_zip(V2), root=td)
            self.assertIsNone(update.recover(td))


class TestRefusalsAndDamage(unittest.TestCase):
    def test_a_corrupt_archive_changes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            _install(td, V1)
            self.assertEqual(update.apply_zip(b"this is not a zip", root=td), 0)
            self.assertIn("could not unpack", update.LAST_ERROR or "")
            for rel, body in V1.items():
                self.assertEqual(_read(td, rel), body, rel)
            self.assertFalse(os.path.isdir(os.path.join(td, ".staging")))

    def test_zip_slip_is_refused_and_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            _install(td, V1)
            written = update.apply_zip(
                _zip({"../escape.py": "evil\n", "app/live.py": "NEW\n"}),
                root=td)
            self.assertEqual(written, 1, "the honest entry still applies")
            self.assertTrue(update.LAST_REFUSED)
            self.assertFalse(os.path.exists(
                os.path.join(os.path.dirname(td), "escape.py")))

    def test_a_truncated_stage_is_caught_before_anything_moves(self):
        with tempfile.TemporaryDirectory() as td:
            _install(td, V1)
            entries, _ = update.stage_release(_zip(V2), root=td)
            staged = os.path.join(update._stage_dir(td, "new"), "app",
                                  "live.py")
            with open(staged, "w", encoding="utf-8") as f:
                f.write("TRUNC")          # a short write, as a kill leaves
            ok, problems = update.verify_tree(
                entries, update._stage_dir(td, "new"))
            self.assertFalse(ok)
            self.assertTrue(any("truncated" in p for p in problems), problems)
            for rel, body in V1.items():
                self.assertEqual(_read(td, rel), body, rel)


if __name__ == "__main__":
    unittest.main()
