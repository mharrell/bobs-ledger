"""End to end, per game: one report per game, and a second pass sends nothing.

Drives the real path — decisions_for -> share_session(game=N) ->
session_report.build -> check -> the report file on disk — against a session on
this machine that actually has decision logs. Only the POST is stubbed, so
nothing leaves the machine, and every directory that writes is redirected to a
scratch folder.

Opt in is gone, deliberately. It was gated on HEARTH_REAL_SESSION_TESTS=1 and
that gate was wrong twice over: this test does NOT replay a Power.log (the
expensive thing the other opt-in tests do) - it reads a decision log, which
takes about a second - and an opt-in that nobody can actually set is not a
test. Three attempts to run it failed on shell plumbing rather than on the
code: `set X=1 && python ...` is cmd.exe syntax and does nothing in PowerShell,
where `set` aliases Set-Variable. It runs by default now and skips only for the
honest reason, when no session on the machine has a decision log.
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


class TestOneReportPerGame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """The newest session that has decision logs HERE.

        Not simply the newest session: a game coached by an INSTALLED copy
        writes its decision log inside that install, not in this repo, so the
        newest log on the machine can have no records here at all - the first
        version of this test skipped for exactly that reason, from a build that
        had coached a game minutes earlier (2026-10-04).
        """
        with mock.patch.object(real_logs, "MAX_BYTES", 1 << 40):
            candidates = real_logs.all_logs()
        chosen = None
        for path in candidates:
            games = sorted({r.get("game")
                            for r in session_report.decisions_for(path)
                            if r.get("game") is not None})
            if games:
                chosen = (path, games)
                break
        if not chosen:
            raise unittest.SkipTest(
                "no session on this machine has a decision log in this repo - "
                "an installed copy keeps its own beside itself, not here")
        cls.log, cls.games = chosen

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
        """The point of the change: not one lump per session.

        Reads the report file rather than calling session_report.inspect, which
        takes a report dict and not a path - the first version of this test
        passed it a path and errored (2026-10-04).
        """
        import gzip
        import json
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, [])
            for path in self._reports(tmp):
                with gzip.open(path, "rt", encoding="utf-8") as f:
                    report = json.load(f)
                manifest = report["manifest"]
                self.assertEqual(manifest["games"], 1,
                                 f"{os.path.basename(path)} holds "
                                 f"{manifest['games']} games")
                self.assertGreater(manifest["advisories"], 0,
                                   f"{os.path.basename(path)} holds no advice")


if __name__ == "__main__":
    unittest.main()
