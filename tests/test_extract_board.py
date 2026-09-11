"""Final-board extraction: last-known zone must survive the log's traps.

The old read (2026-09-10 game review) listed SOLD minions on the final board
and missed one of two same-card minions: a TAG_CHANGE whose bracket carries
zone=PLAY while writing tag=ZONE value=REMOVEDFROMGAME poisoned the zone with
the stale bracket value, and mid-game entities created with only bare block
tags had no zone at all. Golden minions are real board minions; duplicates
must both report.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extract_board import extract_rows, is_noise

GS = "D 23:27:30.3874527 GameState.DebugPrintPower() - "
OPT = "D 23:27:30.3874527 GameState.DebugPrintOptions() - "

# A mid-game summon whose zone exists ONLY as bare block tags (no Entity=
# prefix lines) — the second Fauna Whisperer shape.
SUMMON_BLOCK = [
    GS + "FULL_ENTITY - Creating ID=300 CardID=BG32_837",
    GS + "        tag=ZONE value=PLAY",
    GS + "        tag=CONTROLLER value=1",
    GS + "        tag=ATK value=275",
    GS + "        tag=HEALTH value=304",
    GS + "        tag=EXHAUSTED value=1",
]

# A sold minion: removed via a TAG_CHANGE whose BRACKET still says zone=PLAY.
SOLD_MINION = [
    GS + "FULL_ENTITY - Creating ID=301 CardID=BG31_924",
    GS + "        tag=ZONE value=PLAY",
    GS + "        tag=CONTROLLER value=1",
    GS + "TAG_CHANGE Entity=[entityName=Thaumaturgist id=301 zone=PLAY "
         "zonePos=3 cardId=BG31_924 player=1] tag=ZONE "
         "value=REMOVEDFROMGAME",
]

# An opponent-board minion that DIED (zone left PLAY) — must not report.
DEAD_OPP_MINION = [
    GS + "FULL_ENTITY - Creating ID=302 CardID=BG23_007",
    GS + "        tag=ZONE value=PLAY",
    GS + "        tag=CONTROLLER value=2",
    GS + "TAG_CHANGE Entity=[entityName=Waveshaper id=302 zone=PLAY "
         "zonePos=1 cardId=BG23_007 player=2] tag=ZONE value=GRAVEYARD",
]


def _log(lines):
    fd, path = tempfile.mkstemp(suffix=".log", dir=os.path.dirname(
        os.path.abspath(__file__)))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


class TestExtractBoard(unittest.TestCase):
    def setUp(self):
        self.lines = []
        self.lines += SUMMON_BLOCK          # Fauna #1 (bare-tag zone)
        self.lines += SOLD_MINION           # sold: must NOT report
        self.lines += DEAD_OPP_MINION       # dead opponent minion: must NOT
        # Fauna #2: created earlier via a plain bracket line, still in PLAY —
        # the duplicate-card case the old cid-set collapsed.
        self.lines += [GS + "FULL_ENTITY - Creating ID=303 CardID=BG32_837",
                       GS + "Entity=[entityName=Fauna Whisperer id=303 "
                            "zone=PLAY zonePos=4 cardId=BG32_837 player=1] "
                            "tag=CARDTYPE value=MINION"]
        # Golden Groundbreaker + a golden TRINKET lookalike (noise tail G on
        # a real golden must stay; prefab shop cards must go).
        self.lines += [GS + "FULL_ENTITY - Creating ID=304 CardID=BG31_035_G",
                       GS + "        tag=ZONE value=PLAY",
                       GS + "        tag=CONTROLLER value=1",
                       GS + "FULL_ENTITY - Creating ID=305 "
                            "CardID=BG_ShopBuff",
                       GS + "        tag=ZONE value=PLAY",
                       GS + "        tag=CONTROLLER value=1",
                       # a later options re-print with a stale bracket must
                       # not resurrect the sold minion's zone
                       OPT + "  option 3 type=POWER mainEntity=["
                            "entityName=Thaumaturgist id=301 zone=PLAY "
                            "zonePos=0 cardId=BG31_924 player=1] "
                            "error=NONE errorParam="]
        self.path = _log(self.lines)

    def tearDown(self):
        os.unlink(self.path)

    def test_duplicates_preserved_and_noise_excluded(self):
        board = extract_rows(self.path, 1, len(self.lines) + 1)
        rows = sorted(board[1], key=lambda r: (r[0], r[1] or 0, r[2] or 0))
        self.assertEqual([cid for cid, _a, _h in rows],
                         ["BG31_035_G", "BG32_837", "BG32_837"])
        fauna = [(a, h) for cid, a, h in rows if cid == "BG32_837"]
        self.assertIn((275, 304), fauna)  # bare-tag stats attached

    def test_removed_minion_not_reported(self):
        board = extract_rows(self.path, 1, len(self.lines) + 1)
        all_cids = [cid for rows in board.values() for cid, _a, _h in rows]
        self.assertNotIn("BG31_924", all_cids)      # sold
        self.assertNotIn("BG23_007", all_cids)      # dead, opponent
        self.assertNotIn("BG_ShopBuff", all_cids)   # prefab

    def test_noise_tail_digits_normalized(self):
        # e2/te3 enchantment variants are noise like e/te; _G goldens are not.
        self.assertTrue(is_noise("BG23_007e2"))
        self.assertTrue(is_noise("BG31_881te3"))
        self.assertFalse(is_noise("BG31_035_G"))


if __name__ == "__main__":
    unittest.main()
