"""Consent, and the one path that sends data off the machine.

The coach's welcome card used to promise "Nothing leaves your machine unless
you share a session" with no way to share one. These tests hold the other half
of that sentence: nothing is sent before the player says yes, a no is
remembered, a refused report is never sent even with consent on, and a failure
to send never reaches the player as a problem with the coach.
"""
import gzip
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # app/
sys.path.insert(0, HERE)          # the code dir, wherever this runs from

import session_report  # noqa: E402
import share  # noqa: E402

HANDLE = "HiddenSquid"
#: Assembled at runtime, split before the "#": the publish gate refuses to
#: ship a file containing a BattleTag-shaped string (even a synthetic one) and
#: this test needs one the scanner really flags. The value is invented.
FAKE_TAG = "Imaginary" + "#" + "0000"


def records(count=3):
    out = []
    for turn in range(6, 6 + count):
        out.append({
            "schema": 1, "ts": f"2026-10-03T10:{turn:02d}:00",
            "coach_version": "abc1234", "log": "Power.log", "offset": turn,
            "game": 1, "turn": turn, "gold": 8, "tier": 2, "health": 30,
            "analysis": {"top_move": "Buy something", "board_stats": 17,
                         "tribes_seen": 3}},
        )
    return out


class ShareFixture(unittest.TestCase):
    """Redirects consent, the report dir and the sent-list into a temp dir:
    these tests must not touch the real install's state."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self._saved = (share.CONSENT_PATH, share.REPORTS_DIR, share.SENT_PATH)
        share.CONSENT_PATH = os.path.join(self.dir, ".share_consent.json")
        share.REPORTS_DIR = os.path.join(self.dir, "session_reports")
        share.SENT_PATH = os.path.join(share.REPORTS_DIR, ".sent.json")
        self.posted = []

    def tearDown(self):
        (share.CONSENT_PATH, share.REPORTS_DIR, share.SENT_PATH) = self._saved
        self._tmp.cleanup()

    def fake_post(self, ok=True, detail="stored", code=200):
        def _post(blob, url=None, timeout=30):
            self.posted.append(blob)
            return ok, detail
        return _post

    def share(self, recs=None, **kw):
        with mock.patch.object(session_report, "decisions_for",
                               lambda path: records() if recs is None else recs):
            with mock.patch.object(share, "post_report", self.fake_post(**kw)):
                return share.share_session("Power.log", url="http://test")


class TestConsent(ShareFixture):
    def test_nothing_is_decided_at_first(self):
        self.assertEqual(share.status(), "undecided")
        self.assertFalse(share.enabled())

    def test_a_yes_is_remembered(self):
        self.assertEqual(share.set_choice(True), "on")
        self.assertTrue(share.enabled())

    def test_a_no_is_remembered(self):
        self.assertEqual(share.set_choice(False), "off")
        self.assertFalse(share.enabled())

    def test_an_unreadable_consent_file_counts_as_undecided(self):
        with open(share.CONSENT_PATH, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(share.status(), "undecided")


class TestNothingIsSentWithoutConsent(ShareFixture):
    def test_undecided_sends_nothing(self):
        self.assertEqual(self.share(), "undecided")
        self.assertEqual(self.posted, [])

    def test_off_sends_nothing(self):
        share.set_choice(False)
        self.assertEqual(self.share(), "off")
        self.assertEqual(self.posted, [])

    def test_on_sends(self):
        share.set_choice(True)
        self.assertEqual(self.share(), "sent")
        self.assertEqual(len(self.posted), 1)

    def test_what_was_sent_is_kept_locally_for_the_player_to_read(self):
        share.set_choice(True)
        self.share()
        kept = [f for f in os.listdir(share.REPORTS_DIR)
                if f.endswith(".json.gz")]
        self.assertEqual(len(kept), 1)
        with gzip.open(os.path.join(share.REPORTS_DIR, kept[0]), "rt",
                       encoding="utf-8") as f:
            self.assertIn("advisories", json.load(f))


class TestTheVerifierIsNotDecoration(ShareFixture):
    def test_a_report_that_fails_the_spec_is_never_sent(self):
        """Consent is not permission to send something unverified."""
        share.set_choice(True)
        bad = session_report.build(records())
        bad["advisories"][0]["analysis"]["opp_comp"] = {"name": HANDLE}
        with mock.patch.object(session_report, "build", lambda recs: bad):
            with mock.patch.object(session_report, "decisions_for",
                                   lambda path: records()):
                with mock.patch.object(share, "post_report",
                                       self.fake_post()) as _p:
                    with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                        outcome = share.share_session("Power.log")
        self.assertEqual(outcome, "refused")
        self.assertEqual(self.posted, [])
        self.assertIn("NOT SENT", out.getvalue())

    def test_a_report_with_a_handle_in_the_text_is_not_sent(self):
        share.set_choice(True)
        bad = session_report.build(records())
        bad["advisories"][1]["analysis"]["situation"] = "vs " + FAKE_TAG
        with mock.patch.object(session_report, "build", lambda recs: bad):
            with mock.patch.object(session_report, "decisions_for",
                                   lambda path: records()):
                with mock.patch.object(share, "post_report", self.fake_post()):
                    with mock.patch("sys.stdout", new_callable=io.StringIO):
                        outcome = share.share_session("Power.log")
        self.assertEqual(outcome, "refused")
        self.assertEqual(self.posted, [])


class TestItNeverBreaksPlay(ShareFixture):
    def test_a_network_failure_is_a_word_not_an_exception(self):
        share.set_choice(True)
        self.assertEqual(self.share(ok=False, detail="URLError: offline"),
                         "failed")

    def test_an_unexpected_post_failure_is_a_word_not_an_exception(self):
        """share_session's docstring promises it never raises. The first
        version of this test asserted the opposite - that an unforeseen
        exception inside post_report came straight out - which is the bug the
        promise exists to rule out, so the code was fixed rather than the
        test."""
        share.set_choice(True)

        def boom(blob, url=None, timeout=30):
            raise RuntimeError("something nobody predicted")

        with mock.patch.object(session_report, "decisions_for",
                               lambda path: records()):
            with mock.patch.object(share, "post_report", boom):
                with mock.patch("sys.stdout", new_callable=io.StringIO):
                    outcome = share.share_session("Power.log")
        self.assertEqual(outcome, "failed")
        # and the local copy is still there for the player to inspect
        self.assertTrue(any(f.endswith(".json.gz")
                            for f in os.listdir(share.REPORTS_DIR)))

    def test_post_report_turns_a_connection_failure_into_a_detail(self):
        ok, detail = share.post_report(b"x", url="http://127.0.0.1:1/")
        self.assertFalse(ok)
        self.assertIn("Error", detail)

    def test_a_session_with_no_advisories_is_not_a_failure(self):
        share.set_choice(True)
        self.assertEqual(self.share(recs=[]), "nothing")
        self.assertEqual(self.posted, [])

    def test_the_same_session_is_not_sent_twice(self):
        share.set_choice(True)
        self.assertEqual(self.share(), "sent")
        self.assertEqual(self.share(), "already")
        self.assertEqual(len(self.posted), 1)


class TestSharingHook(unittest.TestCase):
    """live.py calls this at the two moments a game is certainly over: a new
    session appearing, and the player stopping the coach."""

    def test_the_no_share_flag_skips_this_session(self):
        import live
        self.assertEqual(live._share_finished("x.log", ["--no-share"]),
                         "skipped")

    def test_it_passes_the_finished_log_through(self):
        import live
        with mock.patch.object(share, "share_session",
                               return_value="sent") as m:
            self.assertEqual(live._share_finished("that.log"), "sent")
        m.assert_called_once_with("that.log")

    def test_an_error_in_sharing_never_reaches_the_player_as_a_crash(self):
        import live
        with mock.patch.object(share, "share_session",
                               side_effect=RuntimeError("boom")):
            with mock.patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(live._share_finished("x.log"), "error")


if __name__ == "__main__":
    unittest.main()
