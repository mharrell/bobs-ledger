"""Tests for the tribe lookup backfill (parse_minions.py, 2026-09-11).

The DB must KNOW each minion's tribe from lookup sources (curated override >
Power.log CARDRACE ∪ hearthstonejson > kept paste value) — never infer it
from card text. These pin the scanner's run semantics and the resolution
precedence, including the union rule: a partial shop reveal must not erase a
race the upstream DB knows (Ominous Seer revealed only NAGA in six logs while
hearthstonejson knows Demon/Naga).
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parse_minions import _scan_file, parse, refresh_tribes


def _log(lines):
    f = tempfile.NamedTemporaryFile("w", suffix=".log", delete=False,
                                    encoding="utf-8")
    f.write("".join(lines))
    f.close()
    return f.name


def _reveal(component, entity_id, cid, races, extra_tags=()):
    """A FULL_ENTITY/SHOW_ENTITY block as the game prints it."""
    out = [f"D 12:00:00 {component} - FULL_ENTITY"
           f" - Creating ID={entity_id} CardID={cid}\n"]
    for r in races:
        out.append(f"D 12:00:00 {component} -     tag=CARDRACE value={r}\n")
    for t in extra_tags:
        out.append(f"D 12:00:00 {component} -     tag={t} value=1\n")
    return out


class TestScanFile(unittest.TestCase):
    def test_captures_reveals(self):
        path = _log(_reveal("GameState.DebugPrintPower()", 4, "BG28_300",
                            ["UNDEAD"]))
        try:
            self.assertEqual(_scan_file(path), {"BG28_300": ["UNDEAD"]})
        finally:
            os.unlink(path)

    def test_interleaved_components_both_captured(self):
        # GameState and PowerTaskList print the same blocks interleaved; a
        # strict per-block tracker lost nearly everything to the interleave.
        lines = (_reveal("GameState.DebugPrintPower()", 4, "BG28_300",
                         ["UNDEAD"])
                 + _reveal("PowerTaskList.DebugPrintPower()", 4, "BG28_300",
                           ["UNDEAD"]))
        path = _log(lines)
        try:
            self.assertEqual(_scan_file(path), {"BG28_300": ["UNDEAD"]})
        finally:
            os.unlink(path)

    def test_compound_multiple_race_tags(self):
        lines = _reveal("GameState.DebugPrintPower()", 7, "BG28_633",
                        ["DEMON", "QUILBOAR"])
        path = _log(lines)
        try:
            self.assertEqual(_scan_file(path),
                             {"BG28_633": ["DEMON", "QUILBOAR"]})
        finally:
            os.unlink(path)

    def test_run_ends_at_non_tag_line(self):
        # A line with neither header nor tag= ends the run: a later TAG_CHANGE
        # on some other entity must not attribute to the last revealed card.
        lines = (_reveal("GameState.DebugPrintPower()", 4, "BG28_300",
                         ["UNDEAD"])
                 + ["D 12:00:01 GameState.DebugPrintPower() - BLOCK_START"
                    " BlockType=TRIGGER\n",
                    "D 12:00:01 GameState.DebugPrintPower() - TAG_CHANGE"
                    " Entity=Ooze tag=CARDRACE value=BEAST\n"])
        path = _log(lines)
        try:
            self.assertEqual(_scan_file(path), {"BG28_300": ["UNDEAD"]})
        finally:
            os.unlink(path)

    def test_hidden_entities_skipped(self):
        lines = ["D 12:00:00 GameState.DebugPrintPower() - FULL_ENTITY"
                 " - Creating ID=9 CardID=\n",
                 "D 12:00:00 GameState.DebugPrintPower() -"
                 "     tag=CARDRACE value=BEAST\n"]
        path = _log(lines)
        try:
            self.assertEqual(_scan_file(path), {})
        finally:
            os.unlink(path)


class TestRefreshTribes(unittest.TestCase):
    def _entry(self, cid, name="X", tribe=None):
        return {"id": cid, "name": name, "tribe": tribe}

    def test_union_not_log_wins(self):
        # The motivating case: a partial reveal (NAGA only) must not erase
        # the race hearthstonejson knows (DEMON too).
        minions = [self._entry("BG31_330", "Ominous Seer", "Demon")]
        changed, unknown = refresh_tribes(minions, {"BG31_330": ["NAGA"]},
                                          {"BG31_330": ["DEMON", "NAGA"]}, {})
        self.assertEqual(minions[0]["tribe"], "Demon/Naga")
        self.assertEqual(minions[0]["tribe_src"], "log")
        self.assertEqual(len(changed), 1)

    def test_override_beats_everything(self):
        minions = [self._entry("BGS_012", "Kangor's Apprentice")]
        changed, _ = refresh_tribes(minions, {"BGS_012": ["UNDEAD"]},
                                    {"BGS_012": ["BEAST"]},
                                    {"BGS_012": "Mech"})
        self.assertEqual(minions[0]["tribe"], "Mech")
        self.assertEqual(minions[0]["tribe_src"], "override")

    def test_amalgam_from_log(self):
        # Titus Rivendare: unknown upstream, revealed ALL in a local log.
        minions = [self._entry("BG25_354", "Titus Rivendare")]
        refresh_tribes(minions, {"BG25_354": ["ALL"]}, {}, {})
        self.assertEqual(minions[0]["tribe"], "All")

    def test_conflicting_sources_keep_log_and_report(self):
        minions = [self._entry("C_1", "Weird Card")]
        changed, _ = refresh_tribes(minions, {"C_1": ["UNDEAD"]},
                                    {"C_1": ["BEAST"]}, {})
        self.assertEqual(minions[0]["tribe"], "Undead")
        self.assertEqual(changed[0][4], "log")

    def test_paste_value_kept_when_no_source_knows(self):
        minions = [self._entry("C_2", "Curated Beast", tribe="Beast")]
        changed, unknown = refresh_tribes(minions, {}, {}, {})
        self.assertEqual(minions[0]["tribe"], "Beast")
        self.assertEqual(minions[0]["tribe_src"], "paste")
        self.assertEqual(changed, [])
        self.assertNotIn(("C_2", "Curated Beast"), unknown)

    def test_unknown_listed_for_curation(self):
        minions = [self._entry("C_3", "Mystery")]
        _, unknown = refresh_tribes(minions, {}, {}, {})
        self.assertEqual(unknown, [("C_3", "Mystery")])
        self.assertIsNone(minions[0]["tribe"])
        # The audit stamp: this entry WAS looked up — no source knows.
        self.assertIn("tribe_src", minions[0])


class TestParseCompoundAware(unittest.TestCase):
    """The rebuild path must carry compounds and Amalgams too."""

    CARD_MAP = {
        "Felboar": {"id": "BG28_633", "name": "Felboar", "cost": 3,
                    "races": ["DEMON", "QUILBOAR"], "attack": 2, "health": 4,
                    "mechanics": [], "text": ""},
        "Gatekeeper Amalgam": {"id": "BG36_640", "name": "Gatekeeper Amalgam",
                               "cost": 4, "races": ["ALL"], "attack": 4,
                               "health": 4, "mechanics": [], "text": ""},
        "Brann Bronzebeard": {"id": "BG_LOE_077", "name": "Brann Bronzebeard",
                              "cost": 3, "races": [], "attack": 2,
                              "health": 4, "mechanics": [],
                              "text": "Your Battlecries trigger twice."},
    }

    def _parse(self, name):
        return parse(f"Tavern Tier 1\n{name}\n", self.CARD_MAP)[0]

    def test_compound(self):
        row = self._parse("Felboar")
        self.assertEqual(row["tribe"], "Demon/Quilboar")
        self.assertEqual(row["tribe_src"], "hearthstonejson")

    def test_amalgam(self):
        self.assertEqual(self._parse("Gatekeeper Amalgam")["tribe"], "All")

    def test_untribed(self):
        row = self._parse("Brann Bronzebeard")
        self.assertIsNone(row["tribe"])
        self.assertIsNone(row["tribe_src"])


if __name__ == "__main__":
    unittest.main()
