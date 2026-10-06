"""Archive discovery for the fight table.

Hearthstone ROTATES its logs, and this corpus has already lost one session to
it: the 2026-10-02 game's Power.log is gone, leaving only its decision log. So
the archive is not a convenience — it is the difference between a measurement
that can be re-derived and one that cannot.

Tested with a temporary archive and a stubbed live glob, because the real
`logs_archive/` is machine-local, gitignored, and holds other people's handles.
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import fight_table


class TestArchivedLogs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = fight_table.ARCHIVE_DIR
        fight_table.ARCHIVE_DIR = self.tmp.name

    def tearDown(self):
        fight_table.ARCHIVE_DIR = self.old
        self.tmp.cleanup()

    def _touch(self, name, body="x"):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        return path

    def test_finds_power_logs_and_strips_the_suffix(self):
        self._touch("Hearthstone_2026_10_04_10_27_10__Power.log")
        self._touch("Hearthstone_2026_10_05_07_53_34__Power.log")
        got = fight_table.archived_logs()
        self.assertEqual(sorted(got), ["Hearthstone_2026_10_04_10_27_10",
                                       "Hearthstone_2026_10_05_07_53_34"])

    def test_ignores_files_that_are_not_power_logs(self):
        """A loose .txt or a notes file must not be read as a game."""
        self._touch("Hearthstone_2026_10_04_10_27_10__Power.log")
        self._touch("notes.txt")
        self._touch("README.md")
        self.assertEqual(len(fight_table.archived_logs()), 1)

    def test_missing_archive_is_empty_not_an_error(self):
        fight_table.ARCHIVE_DIR = os.path.join(self.tmp.name, "nope")
        self.assertEqual(fight_table.archived_logs(), {})

    def test_empty_archive_is_empty(self):
        self.assertEqual(fight_table.archived_logs(), {})


class TestAllLogs(unittest.TestCase):
    """The archive wins over a live session of the same name.

    A live Power.log may still be growing, so it is the less trustworthy copy of
    the same game; reading both would double-count every row — the 10x row
    inflation this project has been bitten by before.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_archive = fight_table.ARCHIVE_DIR
        self.old_glob = fight_table.HS_LOG_GLOB
        fight_table.ARCHIVE_DIR = self.tmp.name
        # a fake live tree: <root>/<session>/Power.log
        self.live = os.path.join(self.tmp.name, "live")
        os.makedirs(self.live)
        for sess in ("Hearthstone_2026_10_04_10_27_10",
                     "Hearthstone_2026_10_09_12_00_00"):
            d = os.path.join(self.live, sess)
            os.makedirs(d)
            with open(os.path.join(d, "Power.log"), "w", encoding="utf-8") as f:
                f.write("x")
        fight_table.HS_LOG_GLOB = os.path.join(self.live, "*", "Power.log")

    def tearDown(self):
        fight_table.ARCHIVE_DIR = self.old_archive
        fight_table.HS_LOG_GLOB = self.old_glob
        self.tmp.cleanup()

    def test_duplicate_session_is_listed_once_and_the_archive_wins(self):
        arch = os.path.join(self.tmp.name,
                            "Hearthstone_2026_10_04_10_27_10__Power.log")
        with open(arch, "w", encoding="utf-8") as f:
            f.write("x")
        got = dict(fight_table.all_logs(include_live=True))
        self.assertEqual(len(got), 2)
        self.assertEqual(got["Hearthstone_2026_10_04_10_27_10"], arch)
        # the live-only session is still picked up
        self.assertIn("Hearthstone_2026_10_09_12_00_00", got)

    def test_a_fresh_live_log_is_skipped_unless_asked_for(self):
        """Half-written sessions are excluded by default (the 1800s guard)."""
        skip = fight_table.all_logs(include_live=False)
        names = [n for n, _p in skip]
        # the just-created fake logs are seconds old, so all are skipped
        self.assertEqual(names, [])

    def test_live_logs_are_included_when_asked(self):
        names = [n for n, _p in fight_table.all_logs(include_live=True)]
        self.assertEqual(sorted(names),
                         ["Hearthstone_2026_10_04_10_27_10",
                          "Hearthstone_2026_10_09_12_00_00"])


class TestArchiveLocation(unittest.TestCase):
    def test_archive_sits_at_the_repo_root(self):
        """It must be the ROOT logs_archive/, the gitignored one.

        `app/logs_archive/` would be a new, unignored directory sitting inside
        the shipped tree — and `publish_release` walks the working tree, so an
        unignored log archive is one `git add -A` from carrying real handles.
        """
        app_dir = os.path.dirname(os.path.abspath(fight_table.__file__))
        repo_root = os.path.dirname(app_dir)
        self.assertEqual(fight_table.ARCHIVE_DIR,
                         os.path.join(repo_root, "logs_archive"))
        self.assertTrue(fight_table.ARCHIVE_DIR.startswith(repo_root))


if __name__ == "__main__":
    unittest.main()
