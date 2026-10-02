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
import meta  # noqa: E402
import patch_day  # noqa: E402
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

    def test_golden_and_triple_golden_variants_are_not_unknowns(self):
        """BG36_330_Gt/_Gt2 were two phantom gaps in a 2026-09-23 game. The log
        calls those token entities CARDTYPE=SPELL, so the MINION token rule
        never saw them, and only a bare `_G` suffix was being stripped — the
        base BG36_330 (Sly Infiltrator) was in the DB all along."""
        known = {"BG36_330"}
        self.assertFalse(logquery._plausible_card("BG36_330_Gt", "SPELL", known))
        self.assertFalse(logquery._plausible_card("BG36_330_Gt2", "SPELL", known))
        self.assertFalse(logquery._plausible_card("BG36_330_G", "MINION", known))
        self.assertTrue(logquery._plausible_card("BG36_331_Gt", "SPELL", known),
                        "an unknown base is a real gap and must survive")

    def test_an_answered_gap_is_not_reported_again(self):
        """meta/patch_gaps.json is the registry of questions already answered
        (Gem Day has no tier anywhere and never leaves SETASIDE). A pre-flight
        that re-reports answered ids is one nobody reads."""
        self.assertFalse(logquery._plausible_card("BG31_893", "SPELL", set()))
        self.assertTrue(logquery._plausible_card("BG36_777", "SPELL", set()))

    def test_every_registered_gap_carries_a_reason_and_evidence(self):
        """The file's own contract, enforced here: 'an entry with no evidence
        is a gap someone talked themselves out of.'"""
        doc = meta._raw("patch_gaps.json") or {}
        for section in ("expected_missing", "seen_not_carried"):
            for row in (doc.get(section) or []):
                with self.subTest(section=section, name=row.get("name")):
                    self.assertTrue(row.get("reason"))
                    self.assertTrue(row.get("evidence"))
                    if section == "seen_not_carried":
                        self.assertTrue(row.get("id"), "an id is what the "
                                        "pre-flight matches on")

    def test_the_registry_is_what_the_preflight_reads(self):
        self.assertIn("BG31_893", logquery._ANSWERED_GAPS)

    def test_a_golden_variant_of_a_known_card_is_also_known(self):
        """The log prints the golden copy with a `_G` suffix (BGFYM_002t_G for
        the Aberrant Tentacle token). The token was a registry gap until
        2026-09-24, when it was CARRIED in minions.json (the player sold one
        from board and the Sell row printed the raw id) — so the golden now
        resolves through _meta_ids instead of the registry. Either way the
        question must stay closed, and an unregistered variant must not."""
        known = logquery._meta_ids()
        self.assertIn("BGFYM_002t", known,
                      "the token is carried — it must never be a gap again")
        self.assertFalse(
            logquery._plausible_card("BGFYM_002t_G", "MINION", known))
        self.assertTrue(
            logquery._plausible_card("BGFYM_999_G", "MINION", known),
            "an unknown variant is still a gap")


class TestReviewKit(unittest.TestCase):
    def test_verdict_classification(self):
        self.assertEqual(review_kit._classify("TAKEN (Fire Baller)"), "taken")
        self.assertEqual(review_kit._classify("passed (coach pick: X)"), "passed")
        self.assertEqual(review_kit._classify(
            "passed on-comp (bought Mysterious K'Thir; coach pick: Y)"),
            "passed_on_comp")
        self.assertEqual(review_kit._classify("plan said level only — player bought"), "not_applicable")
        self.assertEqual(review_kit._classify("spells only (X)"), "other")

    def test_on_comp_passes_are_counted_and_not_mismatches(self):
        """A comp-piece buy under a different #1 is agreement: counted
        separately and NOT flagged as a phase worth opening (the 09-26
        reviews misread coherent builds as rejections)."""
        facts = {"game": 1, "hero": "H", "place": 2, "phases": [1, 2],
                 "verdicts": ["TAKEN (X)",
                              "passed on-comp (bought A; coach pick: B)"]}
        split = review_kit._adherence(facts["verdicts"])
        self.assertEqual(split["passed_on_comp"], 1)
        self.assertEqual(split["passed"], 0)
        self.assertEqual(review_kit._moments(facts), [2])
        line = review_kit._compact_line(facts, split)
        self.assertIn("passed=0 (on-comp=1)", line)

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


class TestPatchDay(unittest.TestCase):
    """The canaries' helpers. Each pins a failure this project actually had."""

    def test_bg_overview_link_is_absolutised(self):
        html = ('<a href="/en-us/news/24302091">full Battlegrounds overview</a>')
        url, label = patch_day._bg_overview_url(html, "x")
        self.assertEqual(url, "https://hearthstone.blizzard.com/en-us/news/24302091")
        self.assertIn("overview", label.lower())

    def test_absolute_overview_link_is_left_alone(self):
        html = '<a href="https://example.com/a">Battlegrounds overview</a>'
        url, _ = patch_day._bg_overview_url(html, "x")
        self.assertEqual(url, "https://example.com/a")

    def test_no_link_returns_none(self):
        self.assertEqual(patch_day._bg_overview_url("<p>nothing</p>", "x"),
                         (None, None))

    def test_card_names_from_the_numbered_table(self):
        text = ("| # | Name | Tier |\n|---|---|---|\n"
                "| 1 | **Joyous** | 1 |\n| 2 | **Zoatroid** | 1 |\n")
        names, method = patch_day._card_names(text)
        self.assertEqual(names, ["Joyous", "Zoatroid"])
        self.assertEqual(method, "numbered table")

    def test_card_names_fall_back_to_bullets(self):
        text = "- **Drest'agath**\n- **Kith'ix**\n"
        names, method = patch_day._card_names(text)
        self.assertEqual(names, ["Drest'agath", "Kith'ix"])
        self.assertEqual(method, "bolded bullets")

    def test_card_names_fall_back_to_tier_lines_then_report_nothing(self):
        """The real overview is neither a table nor bolded bullets."""
        names, method = patch_day._card_names("- [Tier 3] 1/1. Deity.\n")
        self.assertEqual(len(names), 1)
        self.assertIn("[Tier N] stat lines", method)
        names, method = patch_day._card_names("<p>prose only</p>")
        self.assertEqual(names, [])
        self.assertEqual(method, "nothing matched")

    def test_the_truncation_threshold_is_far_above_the_known_bug(self):
        """The 2026-09-22 bug extracted 92 chars of a thousands-char section."""
        self.assertGreater(patch_day.MIN_BG_CHARS, 92 * 2)

    def test_report_can_be_written_and_names_its_next_steps(self):
        result = {"date": "2026-09-22", "db_patch": "36.6.1",
                  "patch": "36.6.1 Test", "url": "u", "overview": "o",
                  "bg_chars": 1169, "card_names": 38,
                  "canaries": [patch_day._canary("C1 bg section", "ok", "1169 chars")],
                  "art": {"got": 1, "total": 1}}
        path = patch_day._write_report(result)
        try:
            body = open(path, encoding="utf-8").read()
            self.assertIn("**ok** C1 bg section", body)
            self.assertIn("check_patch_db.py", body)
        finally:
            os.remove(path)


def _newest_session_log():
    import glob
    from config import HS_LOG_GLOB
    logs = sorted(glob.glob(HS_LOG_GLOB), key=os.path.getmtime, reverse=True)
    return logs[0] if logs else None


REAL_LOG = _newest_session_log()


@unittest.skipUnless(
    REAL_LOG and os.environ.get("HEARTH_REAL_SESSION_TESTS") == "1",
    "pinned to exact row counts from a 2026-09-23 session that is no longer "
    "on disk, so these cannot pass against whatever log happens to exist — "
    "re-pointing them fails on fixture coupling, not product bugs "
    "(2026-10-02). Set HEARTH_REAL_SESSION_TESTS=1 to drive them anyway; "
    "checking in a frozen session fixture would restore the protection.")
class TestAgainstARealSession(unittest.TestCase):
    """The bugs a test drive found in minutes, pinned so they stay fixed.

    Every one of these failed the first time a tool met real input: `stats`
    reported `hp: None` for every turn, and `board` returned zero rows because
    `GameState.board` is a METHOD taking the friendly player and returning a
    (friendly, opponents) tuple. Synthetic fixtures would not have caught any of
    them, which is the argument for driving the tools on a real session.
    """

    @classmethod
    def setUpClass(cls):
        cls.sess = logquery.Session(REAL_LOG)

    def _args(self, **kw):
        return type("A", (), {"game": kw.get("game"), "turn": kw.get("turn"),
                              "tag": None, "top": 50})()

    def test_games_reports_placements_and_heroes(self):
        rows = logquery.q_games(self.sess, self._args())
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["hero"] for r in rows))
        self.assertTrue(all(r["place"] for r in rows))

    def test_stats_reports_real_hp_not_none(self):
        rows = logquery.q_stats(self.sess, self._args(game=1))
        self.assertTrue(rows, "hero stat series must not be empty")
        self.assertTrue(any(r["hp"] is not None for r in rows),
                        "base health comes from the FULL_ENTITY block; a regex "
                        "over cardId-tagged writes misses it entirely")
        self.assertTrue(any(r["armor"] is not None for r in rows))

    def test_board_returns_minion_dicts(self):
        rows = logquery.q_board(self.sess, self._args(game=2, turn=13))
        self.assertTrue(rows, "the board query must not return an empty list")
        for r in rows:
            self.assertIsInstance(r, dict)
            self.assertIn("card", r)
            self.assertIsNotNone(r.get("atk"))

    def test_board_without_a_turn_uses_the_final_board(self):
        self.assertTrue(logquery.q_board(self.sess, self._args(game=2)))

    def test_show_moments_slices_only_the_requested_phases(self):
        text = ("header\nt5  tier 2  gold 6  board 2\n     coach: A\n"
                "t6  tier 2  gold 6  board 2\n     coach: B\n"
                "t7  (no shop phase — transition/death turn)\n")
        got = review_kit.show_moments(text, [6])
        self.assertIn("coach: B", got)
        self.assertNotIn("coach: A", got)
        self.assertIn("no such phase", review_kit.show_moments(text, [99]))


class TestPoolIdFamilies(unittest.TestCase):
    """extend_pool's id filter: BG reprints are pool minions, tokens are not.

    The 2026-09-23 Drest'agath game rendered `BG_EX1_170` (Emperor Cobra, a BG
    reprint that keeps its Blackrock Mountain id) as a raw id in the coach's own
    advice, because the tool's `BG<nn>_<num>` shape filter could not see it. The
    fix has to stay narrow: the card cache calls tokens, buddies and warp
    variants MINIONs with a techLevel too, so widening to "cache says MINION"
    pulled in 15 rows of junk on the first try.
    """

    def test_a_bg_reprint_is_a_pool_id(self):
        import extend_pool
        self.assertTrue(extend_pool._REPRINT_ID.match("BG_EX1_170"))
        self.assertTrue(extend_pool.MINION_ID.match("BG26_350"))

    def test_tokens_buddies_and_machinery_are_not_reprints(self):
        import extend_pool
        for cid in ("BG19_010t", "BG28_603t", "BG30_MagicItem_442t",
                    "BG34_634t", "BG_ICC_026t", "BG34_Giant_015",
                    "TB_BaconUps_079", "TB_BaconShop_HERO_33_Buddy",
                    "EX1_093"):
            with self.subTest(cid=cid):
                self.assertIsNone(extend_pool._REPRINT_ID.match(cid))

    def test_the_reprint_is_in_the_db_now(self):
        import meta
        ids = {m["id"] for m in meta.minions()}
        self.assertIn("BG_EX1_170", ids, "Emperor Cobra was rendered raw in play")
        self.assertIn("BG26_350", ids, "Bassgill was rendered raw in play")


if __name__ == "__main__":
    unittest.main()
