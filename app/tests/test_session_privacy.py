"""What may leave the machine.

Two paths carry coach data off a player's disk, and both had the same hole:
the logged analysis stores the opponent's DISPLAY HANDLE in
`analysis.opp_comp.name`, and `privacy_scan` cannot see it — the scanner
looks for the shapes the log writes (`PlayerName=`, `Entity=`, account ids),
and a name inside a JSON key called "name" matches none of them. One real
session's decision log carried 50 advisories with that field.

So these tests are less about features than about the boundary: what the
report can contain, what it must never contain however the payload changes,
and that the verifier notices an intruder field instead of trusting the
builder that emitted it.
"""
import gzip
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # app/
sys.path.insert(0, HERE)          # the code dir, wherever this runs from

import package_corpus  # noqa: E402
import privacy_scan  # noqa: E402
import session_report  # noqa: E402

HANDLE = "HiddenSquid"          # the documented shape: no discriminator


def advisory(turn=6, handle=None, **extra):
    """One decision-log record, shaped like the real thing."""
    analysis = {
        "gold": 8, "tier": 2, "health": 30, "armor": 1, "current_place": 6,
        "damage_cap": 10, "damage_last": 8, "damage_recent3": 11,
        "loss_streak": 2, "close_losses": False, "forecast": "✕ behind",
        "situation": "behind — 17 vs 41", "hero": "Guff Runetotem",
        "hero_power": "Hero Power text", "board_stats": 17, "tribes_seen": 4,
        "top_move": "Buy Might of Stormwind (tempo)",
        "top_move_steps": [{"text": "Buy Might of Stormwind", "kind": "2",
                            "card": "BG_Test", "action": "buy", "tag": "buy",
                            "reason": None, "details": []}],
        "fragility": {"band": "steady", "eff_health": 31, "health": 30,
                      "armor": 1, "last_hit": 8, "recent3": 11, "cap": 10,
                      "note": None},
        "scenario": {"cast_spell": 2, "cast_spell_total": 4},
        "board": [{"card": "A"}, {"card": "B"}],
        # the bulk that makes the raw log 48 KB per record
        "game_comps": {"beasts-tasty-lobstah": {"name": "Beasts", "x": 1}},
        "playable_comps": {"mechs-magnetics": {"name": "Mechs"}},
        "hand": [{"name": "Some Card"}],
    }
    if handle:
        # shaped like the real thing: cards is {card_id: count}, goldens a
        # list of ids, hero a hero card id, name the person.
        analysis["opp_comp"] = {"hero_name": "The Great Akazamzarak",
                                "hero": "TB_BaconShop_HERO_21",
                                "name": handle, "turn": 7,
                                "cards": {"BG36_101": 1}, "goldens": []}
    analysis.update(extra)
    return {
        "schema": 1, "ts": f"2026-10-02T22:{turn:02d}:00", "coach_version": "abc1234",
        "log": "Hearthstone_2026_10_02_22_09_59", "offset": 100 * turn,
        "game": 1, "turn": turn, "gold": analysis["gold"],
        "tier": analysis["tier"], "health": analysis["health"],
        "fingerprint": "deadbeef", "analysis": analysis,
    }


class TestReportCannotCarryAPerson(unittest.TestCase):
    def setUp(self):
        self.records = [advisory(6, handle=HANDLE), advisory(7),
                        advisory(8, handle=HANDLE)]
        self.report = session_report.build(self.records)

    def test_the_handle_is_not_anywhere_in_the_report(self):
        body = json.dumps(self.report, ensure_ascii=False)
        self.assertNotIn(HANDLE, body)
        self.assertNotIn("opp_comp", body)

    def test_the_opponent_hero_survives_because_it_is_a_game_character(self):
        rows = [r for r in self.report["advisories"]
                if r["analysis"].get("opponent")]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["analysis"]["opponent"]["hero_name"],
                         "The Great Akazamzarak")

    def test_the_session_directory_name_is_not_in_the_report(self):
        body = json.dumps(self.report, ensure_ascii=False)
        self.assertNotIn("Hearthstone_2026", body)

    def test_the_dropped_handle_count_is_reported(self):
        self.assertEqual(self.report["manifest"]["opponent_names_dropped"], 2)

    def test_the_verifier_accepts_a_real_report(self):
        self.assertEqual(session_report.verify(self.report,
                                               session_report.REPORT_SPEC), [])

    def test_an_independent_scan_of_the_report_is_clean(self):
        body = json.dumps(self.report, ensure_ascii=False)
        self.assertEqual(privacy_scan.find(body), {})

    def test_the_bulk_is_gone(self):
        """game_comps/playable_comps/hand are what make a record 48 KB."""
        body = json.dumps(self.report, ensure_ascii=False)
        for dropped in ("game_comps", "playable_comps", "hand", "board\""):
            self.assertNotIn(dropped, body)

    def test_it_is_small(self):
        """The whole point of the tier: one session must be tens of KB, not
        the 7.5 MB decision log it came from."""
        tiny = gzip.compress(json.dumps(self.report).encode())
        self.assertLess(len(tiny), 8_000)


class TestVerifierCatchesIntruders(unittest.TestCase):
    """The whitelist is the privacy control, so it gets its own check: a
    builder that emits a field cannot be trusted to police itself."""

    def setUp(self):
        self.report = session_report.build([advisory(6, handle=HANDLE)])

    def test_a_person_field_added_back_is_reported(self):
        self.report["advisories"][0]["analysis"]["opp_comp"] = {"name": HANDLE}
        self.assertEqual(session_report.verify(self.report,
                                              session_report.REPORT_SPEC),
                         ["advisories[0].analysis.opp_comp"])

    def test_a_new_analysis_field_is_reported(self):
        """The failure mode this exists for: a future analysis key that
        carries something personal would otherwise ride out silently."""
        self.report["advisories"][0]["analysis"]["new_thing"] = "Someone#1234"
        self.assertEqual(session_report.verify(self.report,
                                              session_report.REPORT_SPEC),
                         ["advisories[0].analysis.new_thing"])

    def test_a_nested_field_inside_an_unknown_places_is_reported(self):
        self.report["advisories"][0]["analysis"]["fragility"]["who"] = "x"
        self.assertIn("advisories[0].analysis.fragility.who",
                      session_report.verify(self.report,
                                            session_report.REPORT_SPEC))

    def test_an_absent_list_field_is_omitted_not_nulled(self):
        """A null where the spec declares a list is a shape violation; "we do
        not have it" is better said by absence."""
        row = session_report.build([advisory(6)])["advisories"][0]
        self.assertNotIn("opponent", json.dumps(row))   # no opp_comp at all
        self.assertNotIn("choice", json.dumps(row))
        self.assertEqual(session_report.verify(self.report,
                                              session_report.REPORT_SPEC), [])


class TestReportIdLinksNothing(unittest.TestCase):
    def test_the_same_session_gets_the_same_id(self):
        a = session_report.build([advisory(6, handle=HANDLE)])
        b = session_report.build([advisory(6, handle=HANDLE)])
        self.assertEqual(a["manifest"]["report_id"], b["manifest"]["report_id"])

    def test_a_different_session_gets_a_different_id(self):
        a = session_report.build([advisory(6)])
        b = session_report.build([advisory(7)])
        self.assertNotEqual(a["manifest"]["report_id"], b["manifest"]["report_id"])

    def test_the_id_is_not_derived_from_the_session_directory(self):
        """A session directory (or an account id) links a player's sessions
        together — privacy_scan's own finding category."""
        one = advisory(6)
        two = dict(one, log="Hearthstone_2026_01_01_00_00_00")
        self.assertEqual(session_report.report_id_for([one]),
                         session_report.report_id_for([two]))


class TestInspectRefusesABadReport(unittest.TestCase):
    def _write(self, report):
        path = os.path.join(tempfile.mkdtemp(), "report.json.gz")
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(report, f)
        return path

    def test_a_clean_report_passes(self):
        path = self._write(session_report.build([advisory(6, handle=HANDLE)]))
        self.assertEqual(session_report.inspect(path), 0)

    def test_a_report_with_a_battletag_in_it_fails(self):
        report = session_report.build([advisory(6)])
        report["advisories"][0]["analysis"]["situation"] = "vs Someone#1234"
        self.assertEqual(session_report.inspect(self._write(report)), 1)

    def test_a_report_with_an_undeclared_field_fails(self):
        report = session_report.build([advisory(6)])
        report["advisories"][0]["analysis"]["opp_comp"] = {"name": HANDLE}
        self.assertEqual(session_report.inspect(self._write(report)), 1)


class TestCorpusDecisionsAreSanitized(unittest.TestCase):
    """package_corpus.py shipped the SAME hole: it put the raw decision log in
    the bundle and verified it with privacy_scan, which cannot see
    opp_comp.name. `inspect` printed "verified clean ... in the log or the
    decisions" over a bundle carrying an opponent's handle."""

    def test_the_handle_is_removed_from_bundled_decisions(self):
        clean, dropped = package_corpus.sanitize_decisions(
            [advisory(6, handle=HANDLE), advisory(7)])
        body = json.dumps(clean, ensure_ascii=False)
        self.assertNotIn(HANDLE, body)
        self.assertEqual(dropped, 1)
        # the hero, the comp names and the card names are game data: kept
        self.assertIn("The Great Akazamzarak", body)
        self.assertIn("Beasts", body)

    def test_the_session_directory_name_is_removed(self):
        clean, _ = package_corpus.sanitize_decisions([advisory(6)])
        self.assertNotIn("Hearthstone_2026", json.dumps(clean))

    def test_a_sanitized_bundle_passes_the_independent_scan(self):
        clean, _ = package_corpus.sanitize_decisions(
            [advisory(6, handle=HANDLE)])
        self.assertEqual(privacy_scan.find(json.dumps(clean)), {})

    def test_the_scan_cannot_see_a_handle_in_a_json_name_field(self):
        """The honest measure of the old hole, stated exactly.

        The scanner DOES flag the session directory in this fixture — that is
        its session_dir category working. What it does not flag is the handle
        sitting in `analysis.opp_comp.name`, which is why the strip has to
        exist rather than the scan being trusted to catch it.
        """
        raw = json.dumps([advisory(6, handle=HANDLE)])
        self.assertIn(HANDLE, raw)
        found = json.dumps(privacy_scan.find(raw))
        self.assertNotIn(HANDLE, found)
        self.assertIn("Hearthstone_2026", found)     # session_dir: caught


if __name__ == "__main__":
    unittest.main()
