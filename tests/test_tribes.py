"""Golden tests for tribes.py — the canonical tribe vocabulary."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tribes import ALL_TRIBES, DISPLAY_TRIBES, canon, is_banned, normalize


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
    merge it over the cache for the comp-ban marks."""

    LINES = [
        "D 12:00:00 GameState.DebugPrintPower() - GAME_SEED value=42\n",
        "D 12:00:00 GameState.DebugPrintPower() -     FULL_ENTITY - Creating ID=1 CardID=NEWSET_001\n",
        "D 12:00:00 GameState.DebugPrintPower() -         tag=CARDRACE value=BEAST\n",
        "D 12:00:00 GameState.DebugPrintPower() -         tag=IS_BACON_POOL_MINION value=1\n",
        "D 12:00:00 GameState.DebugPrintPower() -     FULL_ENTITY - Creating ID=2 CardID=NEWSET_002\n",
        "D 12:00:00 GameState.DebugPrintPower() -         tag=CARDRACE value=QUILBOAR\n",
        "D 12:00:00 GameState.DebugPrintPower() -         tag=IS_BACON_POOL_MINION value=1\n",
        "D 12:00:00 GameState.DebugPrintPower() -     FULL_ENTITY - Creating ID=3 CardID=NEWSET_003\n",
        "D 12:00:00 GameState.DebugPrintPower() -         tag=IS_BACON_POOL_MINION value=1\n",
    ]

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
                         {"NEWSET_001": ["BEAST"], "NEWSET_002": ["QUILBOAR"]})
        self.assertNotIn("NEWSET_003", g["races"])

    def test_cache_fallback_for_blocks_without_race_tag(self):
        from bans import bans_from_log
        lines = self.LINES + [
            "D 12:00:00 GameState.DebugPrintPower() -     FULL_ENTITY - Creating ID=4 CardID=OLDMON\n",
            "D 12:00:00 GameState.DebugPrintPower() -         tag=IS_BACON_POOL_MINION value=1\n",
        ]
        games = bans_from_log(None, {"OLDMON": ["MECHANICAL"]}, lines=lines)
        g = games[0]
        self.assertEqual(g["allowed"], ["Beast", "Mech", "Quilboar"])
        self.assertEqual(g["races"]["OLDMON"], ["MECHANICAL"])