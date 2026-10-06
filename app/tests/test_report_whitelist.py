"""The report whitelist as a control that can actually fail.

verify() walks the finished report — and by the time it runs, an undeclared
field has already been dropped by project(). So the control was safe but BLIND:
`scenario.trinkets` disappeared from 560 of the 641 real advisories measured on
2026-10-04 and nothing said a word, and a new key inside `scenario` would have
shipped unexamined, because MAP_SCALARS accepts any key it is handed and the
verifier is only ever told about the keys it was asked for.

Three checks now stand between an analysis and the wire, and the last two are
made against the SOURCE rather than the output:

* SPEC + verify()          — what may leave, by name (unchanged, still the control)
* source_problems()        — a source field the spec does not account for, so the
                             drop is deliberate instead of invisible
* identity_findings()      — a handle this very session showed us, found in the
                             payload (privacy_scan cannot see a bare display name),
                             and the game's OWN names it must not fire on: on
                             2026-10-05 a card the advice named refused a whole
                             game's report because the handle was a word inside it.
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

#: Assembled, like test_friendly_player.py: this file ships, and a handle-shaped
#: literal in it reads as a real player to the release's privacy gate.
_OPP = "Fixture" + "Opponent"
_TRIBE_NAMED_OPP = "Demon"        # a tribe name: a real one on this machine


def _advisory(**analysis):
    """One decision record, shaped like the real ones."""
    base = {"situation": "probe", "top_move": "Buy a thing",
            "top_move_steps": [{"text": "Buy a thing", "kind": "buy",
                                "card": "BGS_034", "action": "buy",
                                "tag": None, "reason": None}],
            "board": [], "hand": [], "shop_rank": [], "scenario": {}}
    base.update(analysis)
    return {"schema": 1, "ts": "2026-10-04T10:30:00", "coach_version": "test",
            "log": "Power.log", "offset": 100, "game": 1, "turn": 5, "gold": 3,
            "tier": 2, "health": 30, "analysis": base}


def _card_word():
    """(full game name, one word of it) taken from the DB the coach prints from.

    Derived rather than written down, for two reasons. This file ships, and a
    handle-shaped literal in it reads as a real player to the release's privacy
    gate — the same reason `_OPP` above is assembled. And a hard-coded card would
    rot the day the patch rotates it out, while the rule under test ("a word
    inside a name the game defines is not a handle") has to hold for whichever
    cards are current.

    The word is required to be distinctive: not a game name on its own, and
    printed by exactly one name in the catalogue, so "printed inside the card
    that owns it" and "standing alone" are different payloads and not an
    accident of what else the body happens to contain.
    """
    catalogue = session_report._game_names()
    for full in sorted(catalogue):
        if " " not in full:
            continue
        word = full.rsplit(" ", 1)[1]
        if len(word) < 4 or not word.isalpha() or word in catalogue:
            continue
        owners = [n for n in catalogue if word.lower() in n.lower()]
        if len(owners) == 1:
            return full, word
    raise AssertionError("no distinctive multi-word game name in the meta DB")


class TestSourceProblems(unittest.TestCase):
    """A field the spec does not account for must be loud, not silently dropped."""

    def test_a_brand_new_analysis_key_is_reported(self):
        problems = session_report.source_problems(
            [_advisory(brand_new_metric=7)])
        self.assertEqual(len(problems), 1)
        self.assertIn("brand_new_metric", problems[0])

    def test_a_new_key_inside_scenario_is_reported(self):
        """This is the hole an open MAP_SCALARS left: any key, any value."""
        problems = session_report.source_problems(
            [_advisory(scenario={"opponent_seen": _OPP})])
        self.assertEqual(len(problems), 1)
        self.assertIn("scenario.opponent_seen", problems[0])

    def test_a_new_key_inside_a_comp_progress_row_is_reported(self):
        problems = session_report.source_problems(
            [_advisory(comp_progress=[{"name": "Mechs", "tribe": "MECHANICAL",
                                       "hits": 3, "unexpected": "x"}])])
        self.assertEqual(len(problems), 1)
        self.assertIn("unexpected", problems[0])

    def test_a_deliberately_dropped_key_is_not_reported(self):
        """`board` is dropped on purpose; that must not read as a new field."""
        self.assertEqual(
            session_report.source_problems([_advisory(board=[{"a": 1}])]), [])

    def test_a_real_shaped_record_is_clean(self):
        """Every key the coach really emits is accounted for.

        Measured against 641 real advisories: had any been unaccounted for, the
        sending path would refuse every report — which is why this test exists.
        """
        record = _advisory(
            board=[], hand=[], opp_comp={"name": _OPP, "hero_name": "Reno"},
            scenario={"cast_spell": 1, "cast_spell_total": 2, "turns": 5,
                      "trinkets": ["Innkeeper's Stein"]},
            choice={"kind": "hero", "source": "hero", "ranked": [["A", "B", 1.0,
                                                                 "why"]]},
            comp_progress=[{"name": "Mechs", "tribe": "MECHANICAL",
                            "meta_tier": "A", "provisional": False,
                            "evidence": None, "hits": 3, "lean_hits": 1,
                            "leaning": True, "ready": False,
                            "needs": ["a", "b"], "trinket_fit": False,
                            "tribe_hits": 2}])
        self.assertEqual(session_report.source_problems([record]), [])


class TestIdentityFindings(unittest.TestCase):
    """A handle the session itself showed must not ride out in the payload."""

    def _report(self, records):
        return session_report.build(records, session_key="s",
                                    now=datetime.datetime(2026, 10, 4))

    def test_a_handle_echoed_into_advice_text_is_found(self):
        """The demonstrated hole: privacy_scan sees nothing, this sees it."""
        records = [_advisory(
            opp_comp={"name": _OPP, "hero_name": "Reno"},
            top_move_steps=[{"text": f"scout {_OPP}", "kind": "buy",
                             "card": None, "action": None, "tag": None,
                             "reason": f"{_OPP} is on Dragons"}])]
        self.assertEqual(session_report.identity_findings(self._report(records),
                                                          records), [_OPP])

    def test_a_handle_inside_a_declared_list_is_found(self):
        """An unknown scenario key is now DROPPED by the closed spec (and
        source_problems reports it), so the identity check's job is the fields
        that really do ship — including the lists, which is where a handle would
        ride out if one were ever appended to a counter or a trinket list."""
        records = [_advisory(opp_comp={"name": _OPP},
                             scenario={"turns": 5, "trinkets": [_OPP]})]
        self.assertEqual(session_report.identity_findings(self._report(records),
                                                          records), [_OPP])

    def test_a_dropped_handle_is_not_a_leak(self):
        """opp_comp.name never ships, so its presence in the source is fine."""
        records = [_advisory(opp_comp={"name": _OPP, "hero_name": "Reno"})]
        self.assertEqual(session_report.identity_findings(self._report(records),
                                                          records), [])

    def test_an_opponent_named_after_a_tribe_is_not_flagged(self):
        """Measured false positive, and the reason this check has an exemption.

        One of the four handles in the real sessions on this machine is
        literally "Demon", which the payload carries 88 times in its banned-tribe
        and comp-tribe columns. Flagging that would refuse to share for that
        player in every game — a control that ends someone's measurement to guard
        against a word the game itself uses.
        """
        records = [_advisory(opp_comp={"name": _TRIBE_NAMED_OPP},
                             banned=[_TRIBE_NAMED_OPP, "Beast"],
                             comp_progress=[{"name": "Demons",
                                             "tribe": _TRIBE_NAMED_OPP}])]
        self.assertEqual(session_report.identity_findings(self._report(records),
                                                          records), [])

    def test_a_handle_inside_a_longer_word_is_not_flagged(self):
        """"Ann" must not be found inside "Annoy-o-Module"."""
        records = [_advisory(opp_comp={"name": "Ann"},
                             top_move="Play Annoy-o-Module")]
        self.assertEqual(session_report.identity_findings(self._report(records),
                                                          records), [])

    def test_a_handle_that_is_a_word_inside_a_card_name_is_not_flagged(self):
        """Measured 2026-10-05: the CARD puts the word there, not the person.

        An opponent's display handle was a word inside an Undead minion's name.
        The payload named that minion because a discover offered it
        (`choice.ranked[2]`), and the coincidence refused the whole game's report
        with every other control clean — 1 handle, nothing uploaded, that game's
        measurement simply gone. The real game is not worth re-buying to test, so
        the fixture takes its word from the card DB instead: a handle that IS
        that word, and a payload that prints the card it belongs to.
        """
        card, word = _card_word()
        records = [_advisory(
            opp_comp={"name": word},
            choice={"kind": "discover", "source": "Patient Scout",
                    "ranked": [[card, "BG36_515", 3.4, ""]]})]
        self.assertEqual(session_report.identity_findings(self._report(records),
                                                          records), [])

    def test_the_same_word_standing_alone_is_still_flagged(self):
        """The exemption is positional, so the check keeps its teeth: the same
        word in prose the game does not own is exactly the leak this exists for."""
        _, word = _card_word()
        records = [_advisory(opp_comp={"name": word},
                             situation=f"vs {word}: 240 vs 140")]
        self.assertEqual(session_report.identity_findings(self._report(records),
                                                          records), [word])

    def test_a_card_name_does_not_excuse_a_handle_printed_beside_it(self):
        """One explained occurrence must not hide an unexplained one."""
        card, word = _card_word()
        records = [_advisory(
            opp_comp={"name": word},
            choice={"kind": "discover", "source": "Patient Scout",
                    "ranked": [[card, "BG36_515", 3.4, ""]]},
            top_move_steps=[{"text": "x", "kind": "buy", "card": None,
                             "action": None, "tag": None,
                             "reason": f"scout {word}"}])]
        self.assertEqual(session_report.identity_findings(self._report(records),
                                                          records), [word])

    def test_no_opponent_handle_means_nothing_to_look_for(self):
        records = [_advisory(top_move=f"scout {_OPP}")]
        self.assertEqual(session_report.identity_findings(self._report(records),
                                                          records), [])


class TestTheSilentDropIsFixed(unittest.TestCase):
    def test_offered_trinkets_reach_the_report(self):
        """They were dropped for a whole patch: a list under MAP_SCALARS."""
        report = session_report.build(
            [_advisory(scenario={"turns": 5,
                                 "trinkets": ["Innkeeper's Stein", "Scraper"]})],
            session_key="s")
        self.assertEqual(
            report["advisories"][0]["analysis"]["scenario"]["trinkets"],
            ["Innkeeper's Stein", "Scraper"])


class TestTheSendingPathRefuses(unittest.TestCase):
    """A control that only reports is decoration: the wire must stay shut."""

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
        with open(share.CONSENT_PATH, "w", encoding="utf-8") as f:
            f.write('{"schema": 1, "share": true}')
        self.posted = []
        p = mock.patch.object(share, "post_report", self._capture)
        p.start()
        self.addCleanup(p.stop)

    def _capture(self, blob, url=None, timeout=30):
        self.posted.append(blob)
        return True, "stored"

    def _session(self, record):
        path = os.path.join(self.tmp.name, "Hearthstone_2026_01_01")
        os.makedirs(path, exist_ok=True)
        log = os.path.join(path, "Power.log")
        open(log, "w").close()
        decision_log.record(record["analysis"], log_path=log, log_offset=42,
                            game_no=1)
        return log

    def test_an_unaccounted_field_is_refused(self):
        log = self._session(_advisory(brand_new_metric=7))
        self.assertEqual(share.share_session(log, game=1, quiet=True), "refused")
        self.assertEqual(self.posted, [], "the report went out anyway")

    def test_a_handle_in_the_advice_is_refused(self):
        log = self._session(_advisory(
            opp_comp={"name": _OPP},
            top_move_steps=[{"text": "x", "kind": "buy", "card": None,
                             "action": None, "tag": None,
                             "reason": f"scout {_OPP}"}]))
        self.assertEqual(share.share_session(log, game=1, quiet=True), "refused")
        self.assertEqual(self.posted, [])

    def test_a_clean_record_still_sends(self):
        log = self._session(_advisory(opp_comp={"name": _OPP,
                                                "hero_name": "Reno"},
                                      scenario={"turns": 5}))
        self.assertEqual(share.share_session(log, game=1, quiet=True), "sent")
        self.assertEqual(len(self.posted), 1)
        report = json.loads(gzip.decompress(self.posted[0]))
        self.assertEqual(session_report.check(report), ([], {}))

    def test_a_card_name_that_contains_the_handle_still_sends(self):
        """The 2026-10-05 bug report, end to end: the wire must stay open.

        That game was refused at the game end and never re-attempted, so the
        refusal cost the measurement outright — which is why this asserts the
        send itself rather than only identity_findings().
        """
        card, word = _card_word()
        log = self._session(_advisory(
            opp_comp={"name": word},
            choice={"kind": "discover", "source": "Patient Scout",
                    "ranked": [[card, "BG36_515", 3.4, ""]]}))
        self.assertEqual(share.share_session(log, game=1, quiet=True), "sent")
        self.assertEqual(len(self.posted), 1)
        report = json.loads(gzip.decompress(self.posted[0]))
        self.assertEqual(report["advisories"][0]["analysis"]["choice"]["ranked"]
                         [0][0], card)


if __name__ == "__main__":
    unittest.main()
