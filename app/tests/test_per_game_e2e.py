"""End to end, per game: one report per game, and a second pass sends nothing.

Drives the real path — decisions_for -> share_session(game=N) ->
session_report.build -> check -> the report file on disk — against a session on
this machine that actually has decision logs. Only the POST is stubbed, so
nothing leaves the machine, and every directory that writes is redirected to a
scratch folder.

Opt in with HEARTH_REAL_SESSION_TESTS=1: it reads a real session's decision log
(megabytes) and distils it, which is slower than the rest of the suite and
depends on this machine having played a game. The install-level version of this
check — watching the files appear under a released install while the player is
mid-session — cannot be done from here and needs the build published and a game
played.
"""
import glob
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tests"))

import real_logs  # noqa: E402
import session_report  # noqa: E402
import share  # noqa: E402

OPT_IN = os.environ.get("HEARTH_REAL_SESSION_TESTS") == "1"


@unittest.skipUnless(OPT_IN, "set HEARTH_REAL_SESSION_TESTS=1 to replay a "
                             "real session's decision log")
class TestOneReportPerGame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with mock.patch.object(real_logs, "MAX_BYTES", 1 << 40):
            log = real_logs.newest_settled()
        if not log:
            raise unittest.SkipTest(real_logs.why_none())
        records = session_report.decisions_for(log)
        games = sorted({r.get("game") for r in records
                        if r.get("game") is not None})
        if not games:
            raise unittest.SkipTest("no decision log for a settled session")
        cls.log = log
        cls.games = games

    def _run(self, tmp, posted):
        def fake_post(*a, **kw):
            posted.append(kw.get("report_id") or len(posted))
            return (True, "sent")

        with mock.patch.object(session_report, "ID_MAP_DIR", tmp), \
                mock.patch.object(share, "REPORTS_DIR", tmp), \
                mock.patch.object(share, "SENT_PATH",
                                  os.path.join(tmp, ".sent.json")), \
                mock.patch.object(share, "CONSENT_PATH",
                                  os.path.join(tmp, "consent.json")), \
                mock.patch.object(share, "post_report", fake_post):
            with open(share.CONSENT_PATH, "w", encoding="utf-8") as f:
                f.write('{"schema": 1, "share": true}')
            for game in self.games:
                share.share_session(self.log, game=game)

    def _reports(self, tmp):
        return sorted(glob.glob(os.path.join(tmp, "report_*")))

    def test_one_report_per_game_with_a_plausible_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, [])
            files = self._reports(tmp)
            self.assertEqual(len(files), len(self.games),
                             f"{len(files)} reports for {len(self.games)} games")
            for path in files:
                size = os.path.getsize(path)
                self.assertGreater(size, 500, f"{os.path.basename(path)} is "
                                              f"{size} bytes - a stub, not a "
                                              f"report")

    def test_a_second_pass_posts_nothing(self):
        """The trigger, the backstop and this all share one code path, so a
        repeat has to be a no-op. A rebuilt report carries a new `created`, and
        the collector answers 409 to an id whose bytes changed."""
        with tempfile.TemporaryDirectory() as tmp:
            first = []
            self._run(tmp, first)
            self.assertEqual(len(first), len(self.games))
            second = []
            self._run(tmp, second)
            self.assertEqual(second, [], "re-running posted again")

    def test_each_report_holds_exactly_one_game(self):
        """The point of the change: not one lump per session."""
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, [])
            for path in self._reports(tmp):
                with mock.patch.object(session_report, "ID_MAP_DIR", tmp):
                    report = session_report.inspect(path)
                self.assertEqual(report["manifest"]["games"], 1,
                                 os.path.basename(path))


if __name__ == "__main__":
    unittest.main()
