"""One game per report, sent when that game ends (2026-10-04).

Sharing used to distil a whole SESSION and only fire when the session ended.
Measured: the player finished a game, closed Hearthstone, and nothing left the
machine until they closed the coach window — and if that window is closed with
the X button the process is terminated instead of running live.py's cleanup, so
an abandoned session shared nothing at all. Every report that did go also mixed
several games together.

This file covers the two seams that make per-game reports possible: the game
filter in session_report.build, and share_session keying one report id per
game. The live.py trigger and the unsent-games backstop come next; nothing here
changes what a summary CONTAINS, which SPEC and verify() still decide.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import session_report  # noqa: E402
import share  # noqa: E402


def _advisory(game, turn=5, cid="BGS_034"):
    """One decision record, shaped like the real ones."""
    return {"schema": 1, "ts": "2026-10-04T10:30:00", "coach_version": "test",
            "log": "Power.log", "offset": turn * 100, "game": game,
            "turn": turn, "gold": 3, "tier": 2, "health": 30,
            "analysis": {"situation": "probe", "top_move": "Buy a thing",
                         "top_move_steps": [{"text": "Buy a thing",
                                             "kind": "buy",
                                             "card": cid}],
                         "board": [], "hand": [], "shop_rank": [[cid, 5.0]]}}


class TestTheGameFilter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # EVERYTHING that writes goes to the temp dir: the id map beside the
        # logs, and share.py's report, sent-ledger and consent files. Patching
        # only the id map left these tests writing empty reports into the real
        # session_reports/ folder and recording them as sent - found by running
        # the end-to-end check and finding a 67-byte report whose id was the
        # literal "x" one of the stubs returns (2026-10-04).
        self._patches = [
            mock.patch.object(session_report, "ID_MAP_DIR", self.tmp.name),
            mock.patch.object(share, "REPORTS_DIR", self.tmp.name),
            mock.patch.object(share, "SENT_PATH",
                              os.path.join(self.tmp.name, ".sent.json")),
            mock.patch.object(share, "CONSENT_PATH",
                              os.path.join(self.tmp.name, "consent.json")),
        ]
        for patch in self._patches:
            patch.start()
        # Consent is the player's, not the developer's: these tests must not
        # pass or fail according to what this machine happens to have answered.
        with open(share.CONSENT_PATH, "w", encoding="utf-8") as f:
            f.write('{"schema": 1, "share": true}')

    def tearDown(self):
        for patch in self._patches:
            patch.stop()
        self.tmp.cleanup()

    def test_only_the_named_game_is_included(self):
        records = [_advisory(1), _advisory(2), _advisory(2), _advisory(3)]
        report = session_report.build(records, session_key="s#2", game=2)
        self.assertEqual(report["manifest"]["advisories"], 2)
        self.assertEqual(report["manifest"]["games"], 1)

    def test_no_filter_still_reports_every_game(self):
        """The old behaviour, for callers that want a whole session."""
        records = [_advisory(1), _advisory(2), _advisory(3)]
        report = session_report.build(records, session_key="s")
        self.assertEqual(report["manifest"]["games"], 3)

    def test_a_game_with_no_advisories_is_an_empty_report_not_an_error(self):
        report = session_report.build([_advisory(1)], session_key="s#9", game=9)
        self.assertEqual(report["manifest"]["advisories"], 0)
        self.assertEqual(report["advisories"], [])

    def test_each_game_keeps_its_own_report_id(self):
        """A re-send of the same game must be byte-identical, so the id has to
        be stable per game - and different between games."""
        one = session_report.build([_advisory(1)], session_key="s#1",
                                   game=1)["manifest"]["report_id"]
        again = session_report.build([_advisory(1)], session_key="s#1",
                                     game=1)["manifest"]["report_id"]
        two = session_report.build([_advisory(2)], session_key="s#2",
                                   game=2)["manifest"]["report_id"]
        self.assertEqual(one, again)
        self.assertNotEqual(one, two)

    def test_the_privacy_whitelist_still_verifies_a_per_game_report(self):
        """verify() walks the WHOLE report here, against the envelope spec.

        The first version of this test unpacked `ok, problems = verify(...)`,
        but verify() returns a LIST of problems — so `ok` was the string
        "manifest" and the assertion passed for any report at all. It also
        checked the report against the one-advisory SPEC instead of REPORT_SPEC,
        which reports the report's own "manifest"/"advisories" keys as intruders.
        """
        problems = session_report.verify(
            session_report.build([_advisory(2)], session_key="s#2", game=2),
            session_report.REPORT_SPEC)
        self.assertEqual(problems, [])


class TestShareSessionWiring(unittest.TestCase):
    """share_session is pointed at one game: the filter is passed through and
    the id key carries the game, which is what keeps the re-send identical."""

    def setUp(self):
        # THIS is the class that calls the real share_session, so this is the
        # class that needs every directory redirected. The first attempt at
        # fixing the leak patched TestTheGameFilter instead - a class that never
        # writes anything - and a stub still landed in the real
        # session_reports/ folder on the next run (2026-10-04).
        self.tmp = tempfile.TemporaryDirectory()
        self._patches = [
            mock.patch.object(session_report, "ID_MAP_DIR", self.tmp.name),
            mock.patch.object(share, "REPORTS_DIR", self.tmp.name),
            mock.patch.object(share, "SENT_PATH",
                              os.path.join(self.tmp.name, ".sent.json")),
            mock.patch.object(share, "CONSENT_PATH",
                              os.path.join(self.tmp.name, "consent.json")),
        ]
        for patch in self._patches:
            patch.start()
        with open(share.CONSENT_PATH, "w", encoding="utf-8") as f:
            f.write('{"schema": 1, "share": true}')

    def tearDown(self):
        for patch in self._patches:
            patch.stop()
        self.tmp.cleanup()

    def _capture(self, **kwargs):
        captured = {}

        def fake_build(records, **kw):
            captured.update(kw)
            captured["records"] = records
            return {"manifest": {"report_id": "x"}, "advisories": []}

        with mock.patch.object(session_report, "decisions_for",
                               return_value=[_advisory(1), _advisory(2)]), \
                mock.patch.object(session_report, "build", fake_build), \
                mock.patch.object(share, "post_report",
                                  return_value=(True, "sent")):
            share.share_session("Power.log", url="http://test", quiet=True,
                                **kwargs)
        return captured

    def test_the_session_key_carries_the_game(self):
        captured = self._capture(game=2)
        self.assertTrue(captured["session_key"].endswith("#2"),
                        captured["session_key"])
        self.assertEqual(captured["game"], 2)

    def test_no_game_means_the_session_key_is_unchanged(self):
        captured = self._capture()
        self.assertFalse(captured["session_key"].endswith("#"),
                         captured["session_key"])
        self.assertIsNone(captured["game"])

    def test_the_old_two_argument_call_still_works(self):
        """live.py calls share_session(log_path, url, quiet) today; a new
        keyword must not break that path. Run through the REAL build, so this
        covers the whole call rather than a mock's idea of it."""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(session_report, "ID_MAP_DIR", td), \
                    mock.patch.object(session_report, "decisions_for",
                                      return_value=[_advisory(1)]), \
                    mock.patch.object(share, "post_report",
                                      return_value=(True, "sent")):
                share.share_session("Power.log", "http://test", True)


class TestTheSessionEndBackstop(unittest.TestCase):
    """The backstop shares only what this run has not already sent.

    A re-built report carries a new `created`, so a duplicate would be a POST
    the collector refuses (409: same id, different bytes). The rule is cheap to
    hold and noisy to lose.
    """

    def setUp(self):
        import live
        self.live = live
        live._shared_games.clear()

    def tearDown(self):
        self.live._shared_games.clear()

    def _run(self, records, opts=()):
        sent = []

        def fake_share(log_path, game=None, **kw):
            sent.append(game)
            return "sent"

        with mock.patch.object(session_report, "decisions_for",
                               return_value=records), \
                mock.patch.object(share, "share_session", fake_share):
            outcome = self.live._share_finished("Power.log", opts)
        return sent, outcome

    def test_every_game_of_a_session_is_shared_once(self):
        records = [_advisory(1), _advisory(2), _advisory(2), _advisory(3)]
        sent, outcome = self._run(records)
        self.assertEqual(sent, [1, 2, 3], "one share per game, no repeats")
        self.assertEqual(outcome, "sent")

    def test_a_second_pass_sends_nothing(self):
        """The backstop runs on every session switch and at exit."""
        records = [_advisory(1), _advisory(2)]
        self._run(records)
        sent, outcome = self._run(records)
        self.assertEqual(sent, [])
        self.assertEqual(outcome, "skipped")

    def test_no_share_sends_nothing_at_all(self):
        sent, outcome = self._run([_advisory(1)], opts=("--no-share",))
        self.assertEqual(sent, [])
        self.assertEqual(outcome, "skipped")

    def test_records_without_a_game_number_fall_back_to_the_session(self):
        """A legacy record from before the field existed must not become a
        report for game None, and it must not be dropped either: with no game
        numbers to work from, the backstop shares the session as a whole, which
        is what this path did before per-game reports existed."""
        odd = _advisory(1)
        odd.pop("game")
        calls = []

        def fake_share(log_path, game=None, **kw):
            calls.append(game)
            return "sent"

        with mock.patch.object(session_report, "decisions_for",
                               return_value=[odd]), \
                mock.patch.object(share, "share_session", fake_share):
            self.live._share_finished("Power.log")
        self.assertEqual(calls, [None], "one whole-session share, no game")

    def test_a_failure_in_one_game_does_not_stop_the_others(self):
        sent = []

        def flaky(log_path, game=None, **kw):
            sent.append(game)
            if game == 1:
                raise RuntimeError("network")
            return "sent"

        with mock.patch.object(session_report, "decisions_for",
                               return_value=[_advisory(1), _advisory(2)]), \
                mock.patch.object(share, "share_session", flaky):
            self.live._share_finished("Power.log")
        self.assertEqual(sent, [1, 2])


class TestOnlyFinishedGamesAreShared(unittest.TestCase):
    """A game that is still being played must never be uploaded.

    The exit backstop runs from main()'s finally, which is exactly where a player
    who quits mid-game arrives — and it used to share whatever the decision log
    held, finished or not. Measured 2026-10-04: a turn-5 game went up with 14 of
    its eventual 128 advisories, and because a report id is minted for good while
    the collector refuses one id carrying two different bodies, the cloud kept the
    first sixth of that game permanently (the complete rebuild was refused 409).
    """

    def setUp(self):
        import live
        self.live = live
        live._shared_games.clear()
        self.addCleanup(live._shared_games.clear)

    def _run(self, records, last_game=None, opts=()):
        sent = []

        def fake_share(log_path, game=None, **kw):
            sent.append(game)
            return "sent"

        with mock.patch.object(session_report, "decisions_for",
                               return_value=records), \
                mock.patch.object(share, "share_session", fake_share):
            outcome = self.live._share_finished("Power.log", opts, last_game)
        return sent, outcome

    def test_the_game_being_played_is_not_shared(self):
        sent, outcome = self._run([_advisory(1)], last_game=(1, False))
        self.assertEqual(sent, [], "a game that had not ended was uploaded")
        self.assertEqual(outcome, "skipped")

    def test_an_ended_game_is_shared(self):
        sent, _ = self._run([_advisory(1)], last_game=(1, True))
        self.assertEqual(sent, [1])

    def test_the_games_before_the_live_one_are_all_finished(self):
        """Game 3 starting is proof that games 1 and 2 ended."""
        sent, _ = self._run([_advisory(1), _advisory(2), _advisory(3)],
                            last_game=(3, False))
        self.assertEqual(sent, [1, 2])

    def test_the_exit_path_reads_the_monitors_last_view(self):
        """main()'s finally has no coach object, so monitor() publishes one.

        Without that bridge the exit path sees None, assumes every game finished,
        and re-offers the very game the player is in the middle of.
        """
        with mock.patch.object(self.live, "_LAST_GAME", (1, False)):
            sent, outcome = self._run([_advisory(1)])
        self.assertEqual(sent, [])
        self.assertEqual(outcome, "skipped")

    def test_a_transport_failure_is_retried_but_a_refusal_is_not(self):
        """The two failures are not the same, and the memo must agree.

        A transport failure is worth another attempt — it is the game's only
        chance to be counted. A verifier refusal would be refused again, and
        re-reading a multi-megabyte decision log every 30 s to be told so helps
        nobody.
        """
        attempts = []

        def fake_share(log_path, game=None, **kw):
            attempts.append(game)
            return "failed" if len(attempts) == 1 else "refused"

        with mock.patch.object(share, "share_session", fake_share):
            self.live._share_game("Power.log", 1)
            self.live._share_game("Power.log", 1)   # retried after the failure
            self.live._share_game("Power.log", 1)   # "refused" is final
        self.assertEqual(attempts, [1, 1])


class TestTheVersionStamp(unittest.TestCase):
    """Which build produced a game's advice, stated honestly.

    `manifest.coach_version` was the FIRST record's version, which is a lie for a
    game coached across an update — and the corpus exists to compare builds. The
    measured instance (2026-10-04): the report rebuilt at 11:57:39 claims
    5b7e83c while 114 of its 128 advisories were recorded by 6bcfbcc, because the
    player updated mid-game and the coach restarted onto the new code.
    """

    def _records(self, *versions):
        out = []
        for i, version in enumerate(versions):
            r = _advisory(1, turn=4 + i)
            r["coach_version"] = version
            out.append(r)
        return out

    def test_one_build_is_named(self):
        report = session_report.build(self._records("abc1234"),
                                      session_key="s#1", game=1)
        self.assertEqual(report["manifest"]["coach_version"], "abc1234")
        self.assertEqual(report["manifest"]["coach_versions"], ["abc1234"])

    def test_a_game_spanning_an_update_claims_no_single_version(self):
        report = session_report.build(self._records("old1111", "old1111",
                                                    "new9999"),
                                      session_key="s#1", game=1)
        self.assertIsNone(report["manifest"]["coach_version"],
                          "a mixed report must not be attributed to one build")
        self.assertEqual(report["manifest"]["coach_versions"],
                         ["old1111", "new9999"])

    def test_the_new_field_still_passes_the_spec_walk(self):
        """Adding a manifest field means adding it to MANIFEST_SPEC on purpose."""
        report = session_report.build(self._records("old1111", "new9999"),
                                      session_key="s#1", game=1)
        self.assertEqual(
            session_report.verify(report, session_report.REPORT_SPEC), [])


class TestTheOutcomeIsInTheReport(unittest.TestCase):
    """The corpus has to be able to say whether advice went WELL, not only what
    it said (2026-10-07). Two outcome fields, and the shape of each matters more
    than the value:

      * `manifest.placement` is the game's OWN final placement, handed in by the
        coach that watched it end. It is deliberately NOT read back off the last
        advisory: that advisory is taken before the final fight resolves, and
        measured over three real games its standing was wrong once (4 where the
        game says 3). An unknown placement stays None — a guess here is a wrong
        number in every conclusion drawn from the corpus afterwards.
      * `hp_change` is the effective HP the NEXT advisory of the SAME game
        reports, minus this one's: what the fight between them cost. The last row
        of a game has none, and so does a row whose successor belongs to another
        game — never 0, which would read as "the fight cost nothing".
    """

    def test_the_manifest_carries_the_placement_it_was_given(self):
        report = session_report.build([_advisory(1)], session_key="s#1",
                                      game=1, placement=3)
        self.assertEqual(report["manifest"]["placement"], 3)

    def test_an_unknown_placement_is_none_not_a_guess(self):
        report = session_report.build([_advisory(1)], session_key="s#1", game=1)
        self.assertIsNone(report["manifest"]["placement"])

    def test_hp_change_is_the_next_advisory_minus_this_one(self):
        rows = [dict(_advisory(1), turn=1, health=30, analysis={"armor": 0}),
                dict(_advisory(1), turn=2, health=24, analysis={"armor": 2})]
        report = session_report.build(rows, session_key="s#1", game=1)
        self.assertEqual(report["advisories"][0]["hp_change"], -4)
        self.assertIsNone(report["advisories"][1]["hp_change"],
                          "the last row of a game has no following fight")

    def test_hp_change_is_not_invented_across_games(self):
        rows = [dict(_advisory(1), turn=9, health=30, analysis={"armor": 0}),
                dict(_advisory(2), turn=1, health=40, analysis={"armor": 0})]
        report = session_report.build(rows, session_key="s")
        self.assertIsNone(report["advisories"][0]["hp_change"],
                          "a session report spans games; the gap between two of "
                          "them is not a fight")

    def test_missing_health_is_not_a_zero_cost(self):
        rows = [dict(_advisory(1), turn=1, health=None, analysis={}),
                dict(_advisory(1), turn=2, health=20, analysis={"armor": 0})]
        report = session_report.build(rows, session_key="s#1", game=1)
        self.assertIsNone(report["advisories"][0]["hp_change"])

    def test_the_new_fields_pass_the_reports_own_verifier(self):
        """SPEC and MANIFEST_SPEC are the whitelists: a field neither names is
        dropped on the way out, and the two are checked separately."""
        rows = [dict(_advisory(1), turn=1, health=30, analysis={"armor": 1}),
                dict(_advisory(1), turn=2, health=20, analysis={"armor": 0})]
        report = session_report.build(rows, session_key="s#1", game=1,
                                      placement=1)
        problems, findings = session_report.check(report)
        self.assertEqual((problems, findings), ([], {}))
        self.assertEqual(report["advisories"][0]["hp_change"], -11)


if __name__ == "__main__":
    unittest.main()
