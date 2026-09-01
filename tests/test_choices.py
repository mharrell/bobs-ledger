"""Selection ranker: the coach ranks the picks it could only count before.

Covers choice-block parsing (kind detection, PTL dedup, option dedup) and
the three ranking paths (heroes by pick_rate, trinkets by meta + synergy,
minion discovers by comp fit) plus the live wiring (pending choice tracked
incrementally, resolved on SendChoices, and SendChoices still counted for
the discover trigger totals).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from choices import choice_kind, parse_choice_blocks, rank_choices
from live_coach import LiveCoach

GS = "D 11:10:55.4853849 GameState.DebugPrintEntityChoices() - "
PTL = "D 11:10:55.4853849 PowerTaskList.DebugPrintEntityChoices() - "
SEND = ("D 11:10:56.0000000 GameState.SendChoices() -   m_chosenEntities[0]="
        "[entityName=Baller Portrait id=3226 zone=SETASIDE zonePos=0 "
        "cardId=BG36_MagicItem_390 player=3]")

_TRINKETS = [("Baller Portrait", "BG36_MagicItem_390"),
             ("Deathly Phylactery", "BG30_MagicItem_700"),
             ("Reflective Pendant", "BG30_MagicItem_706"),
             ("Stuffed Coin Purse", "BG35_MagicItem_814")]


def _trinket_block(ptl=False, dup=False):
    """A Lesser Trinket choice block (with optional duplicated option lines,
    as the hero-selection screen re-prints)."""
    tag = "PowerTaskList." if ptl else "GameState."
    lines = [f"{tag}DebugPrintEntityChoices() - id=8 Player=X TaskList=1253 "
             f"ChoiceType=GENERAL CountMin=1 CountMax=1",
             f"{tag}DebugPrintEntityChoices() -   Source=[entityName=Lesser "
             f"Trinket id=388 zone=PLAY zonePos=0 cardId=BG30_Trinket_1st "
             f"player=3]"]
    for i, (n, c) in enumerate(_TRINKETS):
        line = (f"{tag}DebugPrintEntityChoices() -   Entities[{i}]="
                f"[entityName={n} id=32{i} zone=SETASIDE zonePos=0 "
                f"cardId={c} player=3]")
        lines.append(line)
        if dup:
            lines.append(line)
    return lines


class TestChoiceParsing(unittest.TestCase):
    def test_trinket_block_kind_source_options(self):
        (kind, src, opts), = parse_choice_blocks(_trinket_block())
        self.assertEqual(kind, "trinket")
        self.assertEqual(src, "Lesser Trinket")
        self.assertEqual(len(opts), 4)

    def test_ptl_copies_skipped(self):
        """PowerTaskList re-prints choices — counting them doubles options."""
        lines = _trinket_block(ptl=True) + _trinket_block()
        (kind, _src, opts), = parse_choice_blocks(lines)
        self.assertEqual(kind, "trinket")
        self.assertEqual(len(opts), 4)

    def test_reprinted_options_deduped(self):
        """The hero-selection screen re-prints the same option lines."""
        lines = _trinket_block(dup=True)
        (kind, _src, opts), = parse_choice_blocks(lines)
        self.assertEqual(len(opts), 4)

    def test_kind_detection_fallbacks(self):
        self.assertEqual(choice_kind("GENERAL", "Shift your Hero Power",
                                     [("Reborn Rites", "BG31_XYZ")]), "unknown")
        self.assertEqual(choice_kind("GENERAL", None,
                                     [("A", "BG31_880")]), "discover")
        self.assertEqual(choice_kind("MULLIGAN", None, []), "hero")


class TestRanking(unittest.TestCase):
    def test_heroes_ranked_by_pick_rate_with_power_text(self):
        ranked = rank_choices("hero", [
            ("King Mukla", "TB_BaconShop_HERO_38"),
            ("Reno Jackson", "TB_BaconShop_HERO_41")])
        self.assertEqual(ranked[0][0], "Reno Jackson")   # ~60% pick rate
        self.assertTrue(ranked[0][3])                    # power text surfaced
        self.assertLess(ranked[-1][2], ranked[0][2])     # both scored, ordered

    def test_unknown_hero_still_listed(self):
        ranked = rank_choices("hero", [("Brand New Hero", "TB_BaconShop_HERO_99")])
        self.assertIsNone(ranked[0][2])
        self.assertEqual(ranked[0][0], "Brand New Hero")

    def test_trinkets_ranked_by_meta(self):
        ranked = rank_choices("trinket", [
            ("Stuffed Coin Purse", "BG35_MagicItem_814"),
            ("Baller Portrait", "BG36_MagicItem_390")])
        self.assertEqual(ranked[0][0], "Baller Portrait")  # better meta pick
        self.assertIn("pick", ranked[0][3])

    def test_unknown_trinket_still_listed(self):
        ranked = rank_choices("trinket", [("Totally New Trinket", "XX_1")])
        self.assertEqual(ranked[0][2], 0.0)
        self.assertEqual(ranked[0][0], "Totally New Trinket")

    def test_discover_prefers_comp_core(self):
        comps = {"beasts": {"name": "Beasts", "tribe": "Beast",
                            "core": ["BG33_886"], "addons": []}}
        board = [{"card": "BG33_886", "atk": 3, "health": 4, "tribe": "BEAST"},
                 {"card": "BG33_886", "atk": 3, "health": 4, "tribe": "BEAST"}]
        ranked = rank_choices("discover",
                              [("Metallic Hunter", "BG33_449"),
                               ("Tusked Camper", "BG33_886")],
                              board, comps)
        self.assertEqual(ranked[0][0], "Tusked Camper")


class TestLiveWiring(unittest.TestCase):
    def _coach(self):
        c = LiveCoach()
        c.friendly = 7  # hero parsed (as it is by the first seeded advise)
        return c

    def test_pending_choice_tracked_and_resolved(self):
        c = self._coach()
        for line in _trinket_block():
            c.feed(line)
        self.assertIsNotNone(c.choice)
        self.assertEqual(c.choice["source"], "Lesser Trinket")
        self.assertEqual(len(c.choice["options"]), 4)
        c.feed(SEND)
        self.assertEqual(c.choice["picked"], "Baller Portrait")

    def test_ptl_choice_lines_ignored(self):
        c = self._coach()
        for line in _trinket_block(ptl=True):
            c.feed(line)
        self.assertIsNone(c.choice)

    def test_sendchoices_still_counts_as_discover(self):
        """The choice tracking must not swallow SendChoices from the action
        tracker — the discover trigger totals depend on it."""
        c = self._coach()
        for line in _trinket_block():
            c.feed(line)
        c.actions.friendly = 7
        c.in_buying = True
        c.feed(SEND)
        self.assertEqual(c.actions.discovers, 1)


if __name__ == "__main__":
    unittest.main()