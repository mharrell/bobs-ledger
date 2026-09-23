"""Tests for the agent-facing automation tools (logquery / review_kit / doctor).

These tools exist to save OUTPUT tokens, so most of what is worth pinning is
their *contract*: bounded output, honest classification, and the parsing
edge cases that made earlier hand-rolled versions quietly wrong — above all the
entity-name regex, which must survive names containing brackets.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import doctor  # noqa: E402
import logquery  # noqa: E402
import review_kit  # noqa: E402

GS = "D 12:00:00 GameState.DebugPrintPower() -"


class TestBracketRegex(unittest.TestCase):
    """The bug that hid the Deity: names contain brackets."""

    def test_name_with_brackets_is_matched(self):
        line = (f"{GS} TAG_CHANGE Entity=[entityName=Secret Deity [DNT] id=564 "
                f"zone=SETASIDE zonePos=0 cardId=BG_OldGod player=4] "
                f"tag=BACON_DEITY_SIGIL value=1")
        m = logquery.BRACKET.search(line)
        self.assertIsNotNone(m, "a bracketed name must not break the match")
        self.assertEqual(m.group(1), "Secret Deity [DNT]")
        self.assertEqual(m.group(2), "564")
        self.assertEqual(m.group(5), "BG_OldGod")

    def test_plain_name_still_matches(self):
        m = logquery.BRACKET.search(
            f"{GS} TAG_CHANGE Entity=[entityName=Wrath Weaver id=330 "
            f"zone=PLAY zonePos=1 cardId=BGS_004 player=7] tag=ATK value=5")
        self.assertEqual(m.group(1), "Wrath Weaver")

    def test_missing_cardid_is_tolerated(self):
        m = logquery.BRACKET.search(
            f"{GS} TAG_CHANGE Entity=[entityName=Some Token id=9 zone=PLAY "
            f"zonePos=1 player=7] tag=ATK value=1")
        self.assertIsNotNone(m)
        self.assertIsNone(m.group(5))


class TestUnresolvedPreflight(unittest.TestCase):
    """The review pre-flight: which real cards would render as raw ids."""

    def test_excludes_machinery_tokens_and_known_variants(self):
        known = {"BG31_880", "BG32_236"}
        self.assertFalse(logquery._plausible_card("TB_Baconups_079", "MINION", known))
        self.assertFalse(logquery._plausible_card("TB_BaconShop_DragBuy", "SPELL", known))
        self.assertFalse(logquery._plausible_card("BGS_115t", "MINION", known))
        self.assertFalse(logquery._plausible_card("BG31_880t", "SPELL", known))
        self.assertFalse(logquery._plausible_card("BG36_MidGameEffect_010", "SPELL", known))
        self.assertFalse(logquery._plausible_card("BG_OldGod", "MINION", known))

    def test_keeps_a_real_unknown_card_and_a_real_known_suffix_id(self):
        known = {"BG31_880"}
        # BG36_301t is a real tavern spell whose id legitimately ends in `t`.
        self.assertTrue(logquery._plausible_card("BG36_301t", "BATTLEGROUND_SPELL", known))
        self.assertTrue(logquery._plausible_card("BG36_999", "MINION", known))

    def test_scan_finds_only_the_real_gap(self):
        chunk = [
            f'{GS} FULL_ENTITY - Creating ID=1 CardID=BG36_999\n',
            f"{GS}     tag=CARDTYPE value=MINION\n",
            f'{GS} FULL_ENTITY - Creating ID=2 CardID=TB_BaconShop_CheckTriples\n',
            f"{GS}     tag=CARDTYPE value=MINION\n",
            f'{GS} FULL_ENTITY - Creating ID=3 CardID=BG36_998\n',
            f"{GS}     tag=CARDTYPE value=ENCHANTMENT\n",
        ]
        got = [c for c, _ in logquery._unresolved_ids(chunk)]
        self.assertEqual(got, ["BG36_999"])


class TestReviewKit(unittest.TestCase):
    def test_verdict_classification(self):
        self.assertEqual(review_kit._classify("TAKEN (Fire Baller)"), "taken")
        self.assertEqual(review_kit._classify("passed (coach pick: X)"), "passed")
        self.assertEqual(review_kit._classify("plan said level only — player bought"), "not_applicable")
        self.assertEqual(review_kit._classify("spells only (X)"), "other")

    def test_header_and_phase_regexes(self):
        text = ("replay review — Hearthstone_x game 2/3, hero=Marin the Manager, "
                "placement 6\n12 buy phases\n\nt7  tier 3  gold 8  board 1\n"
                "     coach: 1. LEVEL\n     actual: buy X\n"
                "     buy match: passed (coach pick: Y)\n")
        self.assertEqual(review_kit.HEADER.search(text).group(3), "Marin the Manager")
        self.assertEqual([int(m.group(1)) for m in review_kit.PHASE.finditer(text)], [7])
        self.assertEqual(review_kit.PHASES.search(text).group(1), "12")
        self.assertEqual(len(review_kit.VERDICT.findall(text)), 1)


class TestDoctor(unittest.TestCase):
    def test_db_patch_prefers_the_roster_over_the_latch(self):
        """The latch stays on the last patch check_patch_notes reported."""
        got, source = doctor._db_patch()
        self.assertEqual(source, "roster")
        self.assertEqual(got, "36.6.1")

    def test_every_check_returns_a_level_and_one_line(self):
        checks = {
            "patch": doctor.check_patch(online=False),
            "art": doctor.check_art(),
            "roster": doctor.check_roster(),
            "engines": doctor._engine_check(),
        }
        for name, (level, detail) in checks.items():
            self.assertIn(level, (doctor.OK, doctor.WARN, doctor.FAIL), name)
            self.assertIsInstance(detail, str, name)
            self.assertLess(len(detail), 200, f"{name}: detail must stay one line")

    def test_art_check_counts_the_patchs_own_cards(self):
        level, detail = doctor.check_art()
        self.assertIn("aberration", detail)
        self.assertIn(level, (doctor.OK, doctor.WARN))


if __name__ == "__main__":
    unittest.main()
