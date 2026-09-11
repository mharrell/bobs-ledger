"""Golden tests for tribes.py — the canonical tribe vocabulary."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tribes import (ALL_MARKER, ALL_TRIBES, DISPLAY_TRIBES, canon, is_banned,
                    matches, normalize, overlaps, parts, tribes_from_races)


def _pool_block(entity_id, cid, race=None):
    """A FULL_ENTITY pool-minion reveal, as bans_from_log walks it."""
    lines = [
        "D 12:00:00 GameState.DebugPrintPower() -     FULL_ENTITY"
        f" - Creating ID={entity_id} CardID={cid}\n",
    ]
    if race:
        lines.append(
            "D 12:00:00 GameState.DebugPrintPower() -"
            f"         tag=CARDRACE value={race}\n")
    lines.append(
        "D 12:00:00 GameState.DebugPrintPower() -"
        "         tag=IS_BACON_POOL_MINION value=1\n")
    return lines


class TestNormalize(unittest.TestCase):
    def test_raw_log_values(self):
        self.assertEqual(normalize("ELEMENTAL"), "Elemental")
        self.assertEqual(normalize("MECHANICAL"), "Mech")
        self.assertEqual(normalize("QUILBOAR"), "Quilboar")

    def test_already_canonical_is_idempotent(self):
        for t in DISPLAY_TRIBES:
            self.assertEqual(normalize(t), t)

    def test_legacy_plural_forms(self):
        # The pre-canonicalization comps.json vocabulary must still normalize.
        self.assertEqual(normalize("Elementals"), "Elemental")
        self.assertEqual(normalize("Mechs"), "Mech")
        self.assertEqual(normalize("Murlocs"), "Murloc")

    def test_compound(self):
        self.assertEqual(normalize("DEMON/QUILBOAR"), "Demon/Quilboar")
        self.assertEqual(normalize("Demon/Dragon"), "Demon/Dragon")
        self.assertEqual(normalize("Mech/Murloc"), "Mech/Murloc")

    def test_never_banned_markers_and_none(self):
        self.assertIsNone(normalize("All"))
        self.assertIsNone(normalize("ALL"))
        self.assertIsNone(normalize("Neutral"))
        self.assertIsNone(normalize("NEUTRAL"))
        self.assertIsNone(normalize(None))
        self.assertIsNone(normalize(""))


class TestCanon(unittest.TestCase):
    def test_mech_special_case(self):
        self.assertEqual(canon("MECHANICAL"), "Mech")

    def test_round_trip_over_all_tribes(self):
        for t in ALL_TRIBES:
            self.assertEqual(canon(t), t.title() if t != "MECHANICAL" else "Mech")

    def test_all_tribes_map_to_display(self):
        self.assertEqual(sorted(DISPLAY_TRIBES),
                         sorted(canon(t) for t in ALL_TRIBES))


class TestIsBanned(unittest.TestCase):
    def test_allowed_tribe_not_banned(self):
        self.assertFalse(is_banned("ELEMENTAL", ["Elemental", "Beast"]))
        self.assertFalse(is_banned("Elemental", ["Beast", "Elemental"]))

    def test_banned_tribe(self):
        self.assertTrue(is_banned("ELEMENTAL", ["Beast", "Mech"]))

    def test_compound_either_half_allowed(self):
        self.assertFalse(is_banned("Demon/Quilboar", ["Quilboar"]))
        self.assertTrue(is_banned("Demon/Quilboar", ["Beast"]))

    def test_fail_open_on_unknown_and_no_info(self):
        self.assertFalse(is_banned(None, ["Beast"]))
        self.assertFalse(is_banned("Elemental", None))   # no ban info
        self.assertFalse(is_banned("WEIRDRACE", ["Beast"]))


class TestTribeBanKillsComps(unittest.TestCase):
    """A comp whose own tribe is banned drops regardless of core composition
    (2026-09-07 live: the coach pivoted to Nagas with Naga banned —
    nagas-end-of-turn has only ONE naga-tribe core card, so the
    core-majority degraded-keep rule alone passed it). The core rule then
    only governs HYBRID comps whose tribe is allowed (the 2026-09-05
    Sky-hatch case: Naga allowed, the Dragon piece banned -> degraded
    keep with _blocked_core)."""

    COMPS = {
        "nagas-eot": {"name": "Nagas - End Of Turn/Spell Buff",
                      "tribe": "Naga",
                      "core": ["BG32_821", "BG26_ICC_901", "BG36_640",
                               "BG32_837", "BG35_883"], "addons": []},
        "groundbreaker": {"name": "Nagas - Groundbreaker", "tribe": "Naga",
                          "core": ["BG31_035", "BG36_243", "BG35_883",
                                   "BG34_925"], "addons": []},
        "beasts": {"name": "Beasts - Test", "tribe": "Beast",
                   "core": ["BG36_202"], "addons": []},
    }

    def _filter(self, allowed):
        from bans import filter_comps_by_available_tribes
        races = {"BG32_821": ["Demon"], "BG26_ICC_901": None,
                 "BG36_640": None, "BG32_837": ["Naga"], "BG35_883": None,
                 "BG31_035": ["Naga"], "BG36_243": ["Dragon"],
                 "BG34_925": ["Naga"], "BG36_202": ["Beast"]}
        return filter_comps_by_available_tribes(self.COMPS, races,
                                                allowed)

    def test_banned_tribe_drops_all_its_comps(self):
        # Naga banned: BOTH naga comps die — even the one with only 1 of 5
        # naga-tribe core cards.
        allowed = ["Beast", "Demon", "Dragon", "Quilboar", "Undead"]
        filtered = self._filter(allowed)
        self.assertEqual(set(filtered), {"beasts"})

    def test_hybrid_comp_survives_with_blocked_pieces(self):
        # Naga ALLOWED, Dragon banned: groundbreaker degraded-keeps with
        # the Dragon core piece marked.
        allowed = ["Beast", "Naga", "Quilboar", "Undead", "Elemental"]
        got = self._filter(allowed)
        self.assertIn("groundbreaker", got)
        self.assertEqual(got["groundbreaker"].get("_blocked_core"),
                         ["BG36_243"])
        self.assertIn("nagas-eot", got)


class TestBansFromLogCardRace(unittest.TestCase):
    """bans_from_log must read each pool minion's own `tag=CARDRACE` from its
    FULL_ENTITY block — the log is the only patch-proof source. Upstream
    hearthstonejson lags the patch by weeks (2026-09-09: the new set's ids
    were absent, detection never saw 5 tribes, allowed stayed None and the
    comp filter failed OPEN all game — every comp listed, banned tribes
    included). The card_races cache stays as the fallback for blocks that
    print no race tag, and the observed map is returned so callers can
    merge it over the cache for the comp-ban marks. Each tribe contributes
    MIN_PURE_POOL_CARDS distinct cards here — a tribe only counts as
    allowed once it clears that bar (see TestBansFromLogGenerationLeaks)."""

    LINES = (
        ["D 12:00:00 GameState.DebugPrintPower() - GAME_SEED value=42\n"]
        + _pool_block(1, "NEWSET_001", "BEAST")
        + _pool_block(2, "NEWSET_001B", "BEAST")
        + _pool_block(3, "NEWSET_001C", "BEAST")
        + _pool_block(4, "NEWSET_002", "QUILBOAR")
        + _pool_block(5, "NEWSET_002B", "QUILBOAR")
        + _pool_block(6, "NEWSET_002C", "QUILBOAR")
        + _pool_block(7, "NEWSET_003")
    )

    def test_log_native_races_reveal_tribes_without_cache(self):
        from bans import bans_from_log
        games = bans_from_log(None, {}, lines=self.LINES)
        self.assertEqual(len(games), 1)
        g = games[0]
        self.assertEqual(g["allowed"], ["Beast", "Quilboar"])
        # The neutral pool minion (no CARDRACE tag, unknown to the cache)
        # is correctly not counted as a tribe.
        self.assertNotIn("NEUTRAL", g["allowed"])
        # Observed races are returned for callers to merge (the comp-ban
        # marks need per-card races, not just the 5-tribe set).
        self.assertEqual(g["races"],
                         {"NEWSET_001": ["BEAST"], "NEWSET_001B": ["BEAST"],
                          "NEWSET_001C": ["BEAST"], "NEWSET_002": ["QUILBOAR"],
                          "NEWSET_002B": ["QUILBOAR"],
                          "NEWSET_002C": ["QUILBOAR"]})
        self.assertNotIn("NEWSET_003", g["races"])

    def test_cache_fallback_for_blocks_without_race_tag(self):
        from bans import bans_from_log
        lines = list(self.LINES) + (
            _pool_block(8, "OLDMON")
            + _pool_block(9, "OLDMON2")
            + _pool_block(10, "OLDMON3"))
        # (ids all-caps: the walk's CardID regex only reads [A-Z0-9_]+)
        games = bans_from_log(None, {o: ["MECHANICAL"] for o in
                                     ("OLDMON", "OLDMON2", "OLDMON3")},
                              lines=lines)
        g = games[0]
        self.assertEqual(g["allowed"], ["Beast", "Mech", "Quilboar"])
        self.assertEqual(g["races"]["OLDMON"], ["MECHANICAL"])


class TestBansFromLogGenerationLeaks(unittest.TestCase):
    """Card effects summon banned-tribe pool minions mid-game (2026-09-10:
    BG34_500 Flaming Enforcer, Demon, entered an opponent's board from a
    spell, carrying IS_BACON_POOL_MINION + CARDRACE=DEMON). Counting SEEN
    tribes pushed the set to 6-8, the live coach's 5/5 gate failed OPEN and
    the comps panel listed banned comps all game. A tribe therefore only
    counts as allowed with MIN_PURE_POOL_CARDS distinct pure pool minions —
    real allowed tribes show 10+ within minutes; observed leaks are 1-2."""

    def _lines(self, leaks):
        """5 real tribes x 3 cards each, plus `leaks` — (race, count) pairs
        of effect-summoned singletons of other tribes."""
        lines = ["D 12:00:00 GameState.DebugPrintPower() - GAME_SEED value=42\n"]
        eid = 1
        for race in ("BEAST", "DRAGON", "ELEMENTAL", "MURLOC", "PIRATE"):
            for copy in "ABC":  # card ids are uppercase (the log parser's
                lines += _pool_block(eid, f"REAL_{race}_{copy}", race)  # CardID regex is [A-Z0-9_]+)
                eid += 1
        for race, count in leaks:
            for copy in range(count):
                lines += _pool_block(eid, f"LEAK_{race}_{copy}", race)
                eid += 1
        return lines

    def _assert_real_five(self, games):
        self.assertEqual(games[0]["allowed"],
                         ["Beast", "Dragon", "Elemental", "Murloc", "Pirate"])

    def test_singleton_leak_does_not_become_allowed(self):
        from bans import bans_from_log
        # The 2026-09-10 game: one Demon summoned mid-game; Naga never seen.
        games = bans_from_log(None, {}, lines=self._lines([("DEMON", 1)]))
        self._assert_real_five(games)

    def test_two_card_leak_also_ignored(self):
        from bans import bans_from_log
        games = bans_from_log(None, {}, lines=self._lines(
            [("UNDEAD", 1), ("QUILBOAR", 1)]))
        self._assert_real_five(games)
        # The leak's races still ride the observed map (comp-ban marks).
        self.assertEqual(games[0]["races"]["LEAK_UNDEAD_0"], ["UNDEAD"])

    def test_three_distinct_cards_make_a_tribe(self):
        from bans import bans_from_log
        # A 6th tribe with exactly MIN_PURE_POOL_CARDS distinct cards IS
        # plausible (5/5 mode then reads 6 -> the live gate's fail-open);
        # the detector must report it, not swallow it.
        games = bans_from_log(None, {}, lines=self._lines([("NAGA", 3)]))
        self.assertEqual(len(games[0]["allowed"]), 6)

    def test_repeat_copies_do_not_pad_the_count(self):
        from bans import bans_from_log
        # Four reveals of the SAME leak card — one distinct id — stay a leak
        # (the shop/board re-reveals copies of a card all game long).
        lines = self._lines([]) + _pool_block(90, "LEAK_D", "DEMON") * 4
        games = bans_from_log(None, {}, lines=lines)
        self._assert_real_five(games)
        self.assertEqual(games[0]["races"]["LEAK_D"], ["DEMON"])


class TestTribesFromRaces(unittest.TestCase):
    """Raw race lists (log CARDRACE / hearthstonejson) -> the meta tribe field."""

    def test_single_race(self):
        self.assertEqual(tribes_from_races(["ELEMENTAL"]), "Elemental")
        self.assertEqual(tribes_from_races(["MECHANICAL"]), "Mech")

    def test_compound_preserved(self):
        # parse_minions/extend_pool used to write races[0] — Felboar became
        # pure Demon and its Quilboar half was lost to every consumer.
        self.assertEqual(tribes_from_races(["DEMON", "QUILBOAR"]),
                         "Demon/Quilboar")

    def test_all_marker_not_collapsed(self):
        # Amalgams used to become None (= untribed) via normalize("ALL").
        self.assertEqual(tribes_from_races(["ALL"]), ALL_MARKER)
        self.assertEqual(tribes_from_races(["ALL", "BEAST"]), ALL_MARKER)

    def test_empty_and_neutral(self):
        self.assertIsNone(tribes_from_races([]))
        self.assertIsNone(tribes_from_races(None))
        self.assertIsNone(tribes_from_races(["NEUTRAL"]))


class TestParts(unittest.TestCase):
    def test_all_expands_to_every_tribe(self):
        self.assertEqual(parts(ALL_MARKER), DISPLAY_TRIBES)

    def test_compound_splits(self):
        self.assertEqual(parts("Demon/Quilboar"), ["Demon", "Quilboar"])

    def test_raw_and_canonical(self):
        self.assertEqual(parts("ELEMENTAL"), ["Elemental"])
        self.assertEqual(parts("Elemental"), ["Elemental"])

    def test_untribed_matches_nothing(self):
        self.assertEqual(parts(None), [])
        self.assertEqual(parts("Neutral"), [])


class TestMatches(unittest.TestCase):
    def test_compound_membership(self):
        self.assertTrue(matches("Demon/Quilboar", "Demon"))
        self.assertTrue(matches("Demon/Quilboar", "QUILBOAR"))
        self.assertFalse(matches("Demon/Quilboar", "Mech"))

    def test_amalgam_matches_everything(self):
        for t in DISPLAY_TRIBES:
            self.assertTrue(matches(ALL_MARKER, t))

    def test_untribed_matches_nothing(self):
        self.assertFalse(matches(None, "Beast"))
        self.assertFalse(matches("Neutral", "Beast"))

    def test_raw_forms_accepted_on_both_sides(self):
        self.assertTrue(matches("MECHANICAL", "Mech"))
        self.assertTrue(matches("Mech", "MECHANICAL"))


class TestOverlaps(unittest.TestCase):
    def test_compound_vs_compound_shared_part(self):
        self.assertTrue(overlaps("Demon/Quilboar", "Naga/Quilboar"))
        self.assertFalse(overlaps("Demon/Quilboar", "Naga/Dragon"))

    def test_amalgam_overlaps_any_tribed_field(self):
        self.assertTrue(overlaps(ALL_MARKER, "Beast"))
        self.assertTrue(overlaps("Beast", ALL_MARKER))
        self.assertTrue(overlaps(ALL_MARKER, ALL_MARKER))

    def test_untribed_overlaps_nothing(self):
        self.assertFalse(overlaps(None, "Beast"))
        self.assertFalse(overlaps("Beast", None))
        self.assertFalse(overlaps(None, ALL_MARKER))

    def test_is_the_w_tribe_fit_test(self):
        # The consumer contract: comp "Demon" vs minion "Demon/Quilboar"
        # must fit (the old equality test silently denied the W_TRIBE bonus).
        self.assertTrue(overlaps("Demon/Quilboar", "Demon"))