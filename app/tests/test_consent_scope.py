"""What a yes covers.

The answer gates the only outbound player data, and it was scoped to nothing:
`share_session` sent every record in the decision log, so saying yes uploaded the
games the player had already played while the answer was no — or before they had
been asked at all. Reproduced 2026-10-04: nine advisories across three games
recorded with sharing off, then `_share_finished` → three POSTs the moment the
answer became yes. Nothing on screen said so; the overlay's own sentence was
"Nothing has been sent, and nothing will be until you answer."

The scope now starts at the answer. `set_choice` already stamped `decided` for
this, so the rule is one comparison: a record written before that moment is not
sent, ever.
"""
import datetime
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
#: session name fixtures may use (a real-looking session directory is a
#: personal-data finding in the publish gate, correctly).
_SESSION_DIR = "Hearthstone_2026_01_01"

ANSWERED_AT = "2026-10-04T12:00:00"
BEFORE = "2026-10-04T11:00:00"
AFTER = "2026-10-04T13:00:00"


def _analysis():
    return {"situation": "probe", "top_move": "Buy a thing",
            "top_move_steps": [], "board": [], "hand": [], "shop_rank": []}


def _shift(iso, seconds):
    """`iso` moved by `seconds` — both stamps come from the stored answer, so
    the test does not depend on the clock."""
    moment = datetime.datetime.fromisoformat(iso)
    return (moment + datetime.timedelta(seconds=seconds)).isoformat(
        timespec="seconds")


class ConsentScopeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, name, value in (
                (decision_log, "LOG_DIR", os.path.join(self.tmp.name, "logs")),
                (session_report, "ID_MAP_DIR", os.path.join(self.tmp.name, "r")),
                (share, "REPORTS_DIR", os.path.join(self.tmp.name, "r")),
                (share, "SENT_PATH",
                 os.path.join(self.tmp.name, "r", ".sent.json")),
                (share, "CONSENT_PATH",
                 os.path.join(self.tmp.name, "consent.json"))):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.posted = []
        p = mock.patch.object(share, "post_report", self._capture)
        p.start()
        self.addCleanup(p.stop)

    def _capture(self, blob, url=None, timeout=30):
        self.posted.append(blob)
        return True, "stored"

    def _session(self, recorded_at):
        """A session whose advisories were all written at `recorded_at`."""
        path = os.path.join(self.tmp.name, _SESSION_DIR)
        os.makedirs(path, exist_ok=True)
        log = os.path.join(path, "Power.log")
        open(log, "w").close()
        decision_log.record(_analysis(), log_path=log, log_offset=42, game_no=1)
        # `record` stamps ts=now, so rewrite it to the moment under test.
        dpath = os.path.join(decision_log.LOG_DIR,
                            f"decision_{_SESSION_DIR}.jsonl")
        with open(dpath, encoding="utf-8") as f:
            entry = json.loads(f.readline())
        entry["ts"] = recorded_at
        with open(dpath, "w", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return log

    def _answer_yes_at(self, when):
        """A stored yes, stamped `when` — what set_choice writes."""
        with open(share.CONSENT_PATH, "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "share": True, "decided": when}, f)

    def _records_sent(self):
        import gzip
        out = []
        for blob in self.posted:
            report = json.loads(gzip.decompress(blob))
            out.extend(a.get("ts") for a in report["advisories"])
        return out

    # ---------------------------------------------------------------- tests

    def test_a_game_played_before_the_answer_is_never_sent(self):
        log = self._session(BEFORE)
        self._answer_yes_at(ANSWERED_AT)
        self.assertEqual(share.share_session(log, game=1, quiet=True), "nothing")
        self.assertEqual(self.posted, [], "a pre-answer game was uploaded")

    def test_a_game_played_after_the_answer_is_sent(self):
        log = self._session(AFTER)
        self._answer_yes_at(ANSWERED_AT)
        self.assertEqual(share.share_session(log, game=1, quiet=True), "sent")
        self.assertEqual(len(self.posted), 1)

    def test_only_the_records_after_the_answer_go(self):
        """A session can straddle the answer: the log spans an update restart."""
        log = self._session(BEFORE)
        decision_log.record(_analysis(), log_path=log, log_offset=99, game_no=2)
        dpath = os.path.join(decision_log.LOG_DIR,
                            f"decision_{_SESSION_DIR}.jsonl")
        with open(dpath, encoding="utf-8") as f:
            lines = [json.loads(ln) for ln in f if ln.strip()]
        lines[1]["ts"] = AFTER
        with open(dpath, "w", encoding="utf-8") as f:
            for entry in lines:
                f.write(json.dumps(entry) + "\n")
        self._answer_yes_at(ANSWERED_AT)

        share.share_session(log, game=2, quiet=True)
        self.assertEqual(self._records_sent(), [AFTER])
        # and the pre-answer game is not reachable either
        self.assertEqual(share.share_session(log, game=1, quiet=True), "nothing")

    def test_the_answer_moment_is_the_one_stored_by_set_choice(self):
        """Not a copy of it: the same file `set_choice` writes.

        Both record timestamps are derived from the STORED answer, so this does
        not depend on what time of day the suite happens to run at — the first
        version of it did, and asserted the comparison backwards.
        """
        share.set_choice(True)
        decided = share.load()["decided"]
        earlier = _shift(decided, -60)
        later = _shift(decided, +60)

        log = self._session(earlier)
        self.assertEqual(share.share_session(log, game=1, quiet=True), "nothing",
                         "a game written before the stored answer was sent")
        with open(share.CONSENT_PATH, "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "share": True, "decided": decided}, f)
        os.remove(os.path.join(decision_log.LOG_DIR,
                               f"decision_{_SESSION_DIR}.jsonl"))
        log = self._session(later)
        self.assertEqual(share.share_session(log, game=1, quiet=True), "sent")

    def test_a_consent_file_without_a_stamp_blocks_nothing(self):
        """Documented fallback: a file set_choice did not write has no moment,
        so no record can be shown to predate it."""
        log = self._session(BEFORE)
        with open(share.CONSENT_PATH, "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "share": True}, f)
        self.assertEqual(share.share_session(log, game=1, quiet=True), "sent")

    def test_the_overlay_says_the_scope_out_loud(self):
        """A control nobody can read is not consent."""
        import coach_ui
        privacy = json.loads(coach_ui.welcome_payload())["privacy"]
        self.assertIn("from that point on", privacy)


if __name__ == "__main__":
    unittest.main()
