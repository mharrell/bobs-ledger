"""One report id is ONE payload, and the sent-ledger has to be able to answer
"was this sent?".

What went wrong in the field on 2026-10-04: a game that had not finished was
uploaded (its own test lives in test_per_game_share.py), its report id was minted
for good, and when the complete 128-advisory version was built 15 minutes later
the collector refused it — 409, same id, different bytes. The id never reached
`.sent.json` either, so every later run rebuilt the report, was refused again, and
learned nothing. Three separate defects, and each one alone is enough to lose a
game's data for good:

  1. the payload was rebuilt on every attempt, and `manifest.created` is a
     wall-clock stamp, so a retry could never be byte-identical;
  2. the ledger entry was written only after a completed response, and never for
     a 409 — although that means the bytes ARE in the cloud;
  3. `_remember_sent` was unprotected inside a function that promises never to
     raise, so a failed write became an exception on the way out of the coach.
"""
import datetime
import gzip
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed

import decision_log    # noqa: E402
import session_report  # noqa: E402
import share           # noqa: E402


#: The session name our fixtures use: the placeholder privacy_scan names as THE
#: session name fixtures may use. A session directory is a local path, so a
#: real-looking `Hearthstone_<date>` is a personal-data finding in the publish
#: gate — correctly, and a fixture has no business inventing one.
_SESSION_DIR = "Hearthstone_2026_01_01"


def _advisory(game, turn=4):
    """One decision record, minimal but shaped like the real ones."""
    return {"schema": 1, "ts": "2026-10-04T11:40:00", "coach_version": "test",
            "log": "Power.log", "offset": turn * 100, "game": game,
            "turn": turn, "gold": 3, "tier": 2, "health": 30,
            "analysis": {"situation": "probe", "top_move": "Buy a thing",
                         "top_move_steps": [], "board": [], "hand": [],
                         "shop_rank": []}}


class ShareLedgerTest(unittest.TestCase):
    """A session on disk, with every path the share path writes redirected."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._patch(decision_log, "LOG_DIR",
                    os.path.join(self.tmp.name, "decision_logs"))
        self._patch(session_report, "ID_MAP_DIR",
                    os.path.join(self.tmp.name, "reports"))
        self._patch(share, "REPORTS_DIR", os.path.join(self.tmp.name, "reports"))
        self._patch(share, "SENT_PATH",
                    os.path.join(self.tmp.name, "reports", ".sent.json"))
        self._patch(share, "CONSENT_PATH",
                    os.path.join(self.tmp.name, "consent.json"))
        with open(share.CONSENT_PATH, "w", encoding="utf-8") as f:
            f.write('{"schema": 1, "share": true}')
        self.posted = []
        self.reply = [(True, "stored")]
        self._patch(share, "post_report", self._capture)

    def _patch(self, target, name, value):
        p = mock.patch.object(target, name, value)
        p.start()
        self.addCleanup(p.stop)
        return value

    def _capture(self, blob, url=None, timeout=30):
        self.posted.append(blob)
        # One reply per attempt, and the last one repeats.
        return self.reply[min(len(self.posted), len(self.reply)) - 1]

    def _session(self, name=_SESSION_DIR, games=(1,)):
        path = os.path.join(self.tmp.name, name)
        os.makedirs(path, exist_ok=True)
        log = os.path.join(path, "Power.log")
        open(log, "w").close()
        for game in games:
            # record() takes an ANALYSIS, not a whole record: handing it the
            # record nested one inside the other. source_problems() is what
            # noticed, because a decision log whose analysis carries "analysis"
            # is not a shape the coach can produce.
            decision_log.record(_advisory(game)["analysis"], log_path=log,
                                log_offset=42, game_no=game)
        return log

    def _ledger(self):
        with open(share.SENT_PATH, encoding="utf-8") as f:
            return json.load(f)["ids"]

    # ---------------------------------------------------------------- tests

    def test_a_rebuild_of_one_id_is_never_byte_identical(self):
        """Why immutability is not optional: `created` is a clock.

        Same records, same id, two moments in time. The collector refuses one id
        carrying two bodies, so a rebuild can never be accepted — the only
        surviving copy is whichever attempt arrived first.
        """
        records = [_advisory(1)]
        first = session_report.build(
            records, session_key="s#1", game=1,
            now=datetime.datetime(2026, 10, 4, 11, 42, 6))
        later = session_report.build(
            records, session_key="s#1", game=1,
            now=datetime.datetime(2026, 10, 4, 11, 57, 39))
        self.assertEqual(first["manifest"]["report_id"],
                         later["manifest"]["report_id"])
        self.assertNotEqual(json.dumps(first), json.dumps(later))
        self.assertEqual(first["advisories"], later["advisories"])
        differing = {k for k in first["manifest"]
                     if first["manifest"][k] != later["manifest"][k]}
        self.assertEqual(differing, {"created"})

    def test_a_resend_posts_the_identical_bytes(self):
        log = self._session()
        self.assertEqual(share.share_session(log, game=1, quiet=True), "sent")
        first = self.posted[0]

        # The ledger is lost (or was never written): the retry must still send
        # exactly the bytes the collector already has, or it can never be
        # accepted a second time.
        os.remove(share.SENT_PATH)
        self.assertEqual(share.share_session(log, game=1, quiet=True), "sent")
        self.assertEqual(len(self.posted), 2)
        self.assertEqual(self.posted[0], self.posted[1])
        self.assertIn(
            json.loads(gzip.decompress(first))["manifest"]["report_id"],
            self._ledger())

    def test_a_lost_response_can_be_retried(self):
        """The measured failure shape: the POST arrives, the answer does not."""
        log = self._session()
        self.reply = [(False, "URLError: connection reset by peer"),
                      (True, "stored")]

        self.assertEqual(share.share_session(log, game=1, quiet=True), "failed")
        self.assertFalse(os.path.exists(share.SENT_PATH),
                         "a send that failed must not be recorded as delivered")

        self.assertEqual(share.share_session(log, game=1, quiet=True), "sent")
        self.assertEqual(self.posted[0], self.posted[1],
                         "the retry rebuilt the payload, so it can never be "
                         "accepted: same id, different bytes")
        self.assertEqual(len(self._ledger()), 1)

    def test_a_409_counts_as_delivered(self):
        """The collector already holds these bytes, so the id is spent.

        Retrying is pointless and rebuilding is impossible; the only correct
        answers are to record it and stop.
        """
        log = self._session()
        self.reply = [(False, "HTTP 409 already stored with different bytes")]

        self.assertEqual(share.share_session(log, game=1, quiet=True), "already")
        self.assertEqual(len(self._ledger()), 1)
        self.assertEqual(len(self.posted), 1)

        # …and now it is not attempted again at all.
        self.assertEqual(share.share_session(log, game=1, quiet=True), "already")
        self.assertEqual(len(self.posted), 1)

    def test_an_unwritable_sent_ledger_does_not_escape(self):
        """`share_session` promises never to raise; this call sits near the end."""
        log = self._session()
        # A directory where the ledger file should be: open() raises OSError.
        os.makedirs(share.SENT_PATH, exist_ok=True)

        self.assertEqual(share.share_session(log, game=1, quiet=True), "sent")
        self.assertEqual(len(self.posted), 1)

    def test_the_report_file_is_written_before_the_post(self):
        """So an attempt that dies mid-POST still leaves the payload behind."""
        log = self._session()
        self.reply = [(False, "URLError: offline")]
        share.share_session(log, game=1, quiet=True)

        map_path = os.path.join(share.REPORTS_DIR, ".report_ids.json")
        with open(map_path, encoding="utf-8") as f:
            report_id = json.load(f)[_SESSION_DIR + "#1"]
        self.assertTrue(os.path.exists(os.path.join(
            share.REPORTS_DIR, f"report_{report_id}.json.gz")))

    def test_share_latest_sends_one_report_per_game(self):
        """The CLI must use the same id scheme as the live path.

        A session-level report keys a DIFFERENT id (the stem without `#game`), so
        the two schemes do not dedup against each other: one advisory set reached
        the collector twice under two ids, 31 minutes apart (2026-10-04).
        """
        log = self._session(games=(1, 2, 3))
        with mock.patch.object(share, "HS_LOG_GLOB", log):
            self.assertEqual(share.share_latest(quiet=True), "sent")
            self.assertEqual(len(self.posted), 3)
            sent = {json.loads(gzip.decompress(b))["manifest"]["report_id"]
                    for b in self.posted}
            self.assertEqual(len(sent), 3, "one id per game")
            for game in (1, 2, 3):
                games_sent = {
                    a.get("game")
                    for b in self.posted
                    for a in json.loads(gzip.decompress(b))["advisories"]}
            self.assertEqual(games_sent, {1, 2, 3})
            # A second run re-sends nothing: every id is now in the ledger.
            before = len(self.posted)
            self.assertEqual(share.share_latest(quiet=True), "already")
            self.assertEqual(len(self.posted), before)


if __name__ == "__main__":
    unittest.main()
