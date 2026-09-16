"""Trinket meta integrity: log-id addressing + offered-trinket coverage.

The 2026-09-16 Reno game exposed it: BOTH the player's trinkets (Flaming
Portrait BG35_MagicItem_156, Minion Bait BG30_MagicItem_973) were absent
from the DB — the manual paste had hsreplay's old 4-digit id space while
the log speaks 3-digit ids — so the Greater pick was ranked on raw stats
alone and recommended Timeworn Candelabra over the engine-perfect
Flaming Portrait. refresh_trinkets.py rebuilds the DB with log ids;
these tests keep it that way.
"""
import glob
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import meta  # noqa: E402


class TestLogIdAddressing(unittest.TestCase):
    """The DB must be addressed by the ids the LOG actually prints."""

    def test_reno_game_trinkets_present_by_log_id(self):
        """The two trinkets of the 2026-09-16 win, pinned by log id."""
        by_id = {t["id"]: t for t in meta.trinkets()}
        for cid, name in (("BG35_MagicItem_156", "Flaming Portrait"),
                          ("BG30_MagicItem_973", "Minion Bait")):
            self.assertIn(cid, by_id, f"{name} missing from trinkets DB")
            self.assertEqual(by_id[cid]["name"], name)
            self.assertTrue(by_id[cid].get("description"),
                            f"{name} has no description")

    def test_sous_chef_under_log_id(self):
        """The original drift case: log printed BG35_MagicItem_801, the
        paste had ..._8012. The log id is the one that must resolve."""
        ids = {t["id"] for t in meta.trinkets()}
        self.assertIn("BG35_MagicItem_801", ids)
        self.assertNotIn("BG35_MagicItem_8012", ids)

    def test_flaming_portrait_annotated_as_elemental(self):
        """The pick ranker's synergy term must see the Enforcer amp as an
        Elemental trinket — that's what should have won the 09-16 pick."""
        ann = meta.trinket_effects()
        rec = ann.get("BG35_MagicItem_156")
        self.assertIsNotNone(rec, "Flaming Portrait has no curated read")
        self.assertIn("Elemental", rec.get("synergy", {}).get("tribes", []))


class TestOfferedCoverage(unittest.TestCase):
    """Every trinket any local session ever OFFERED must be in the DB by
    its log id — skipped when no session log exists, so the committed
    suite stays deterministic."""

    CHOICE_OPT = re.compile(
        r"DebugPrintEntityChoices.*?cardId=(BG\d+_MagicItem_\w+)")

    def test_all_offered_trinkets_in_db(self):
        import json
        offered = set()
        logs = sorted(glob.glob(os.path.join(
            r"C:\Program Files (x86)\Hearthstone\Logs",
            "Hearthstone_*", "Power.log")), key=os.path.getmtime,
            reverse=True)[:6]
        if not logs:
            self.skipTest("no Hearthstone session log found")
        for path in logs:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = self.CHOICE_OPT.search(line)
                    if m:
                        offered.add(m.group(1))
        if not offered:
            self.skipTest("no trinket offers in recent logs")
        ids = {t["id"] for t in meta.trinkets()}
        missing = sorted(offered - ids)
        self.assertFalse(
            missing, f"trinkets offered in logs but absent from DB: {missing}")


if __name__ == "__main__":
    unittest.main()
