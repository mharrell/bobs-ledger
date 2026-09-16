"""Reachability and body hunger (analysis/engine_coaching.md Plan 2).

Layer A: the curated discover_sources table's integrity, the live-source
detector (board/hand/trinkets/hero, deduped, mechanical-only), the
_hunt_check TIER/POOL reachability paths with the recency guard, and the
Q1 above-veto exception (discover lifts the veto, random never does).
Layer B: fuel_specs integrity and the feed-the-engine line's gates
(engine live on board, tier >= 4, gold idle).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import meta
from value import (live_reach_sources, _hunt_check, _comp_needs_by_tier,
                   _fuel_line, _weak_reach_note, _src_reaches, _src_weak_hit,
                   _load_card_db, _load_spell_db, _load_bg_names)

UNBOUND = {"card": "BG36_352", "name": "Unbound Tempest"}  # tier 6
GLOBE = {"kind": "discover", "tier_cap": 6, "name": "Azeroth Model Globe"}
TEMPEST_SRC = live_reach_sources(board=[{"card": "BGS_123"}])


class TestTables(unittest.TestCase):
    def test_every_source_is_mechanical_with_a_name(self):
        for key, src in meta.discover_sources().items():
            if key.startswith("_"):
                continue
            self.assertEqual(src.get("confidence"), "mechanical", key)
            self.assertTrue(src.get("name"), key)
            self.assertIn(src.get("kind"),
                          ("discover", "token", "random_generate"), key)

    def test_source_ids_exist_in_the_dbs(self):
        minion_ids = {m.get("id") for m in meta.minions()}
        trinket_ids = {t.get("id") for t in meta.trinkets()}
        for key, src in meta.discover_sources().items():
            if key.startswith("_") or key.startswith("hero:"):
                continue
            if key in minion_ids or key in trinket_ids:
                continue
            # The trinket paste is manual and lags the patch (Boom's Monster
            # Portrait is not in trinkets.json yet); accept the MagicItem
            # id pattern so the entry still documents the source.
            self.assertRegex(key, r"^BG\d+_MagicItem_\d+$", key)
        token = meta.discover_sources()["BG32_MagicItem_172"]
        # The token's grant (Dr. Boom's Monster) is a token minion our
        # comp-focused minions paste doesn't carry — accept the id pattern.
        self.assertRegex(token["grants"], r"^BG\d+_\d+$")

    def test_fuel_specs_reference_real_minions_with_known_tribe(self):
        db = _load_card_db()
        for cid, spec in meta.fuel_specs().items():
            if cid.startswith("_"):
                continue
            self.assertIn(cid, db, cid)
            self.assertIn(spec.get("trigger"), ("play", "sell", "summon"))
            self.assertEqual(spec.get("payoff"), "quality_independent")
            self.assertTrue(spec.get("fuel_tribe"))


class TestLiveSources(unittest.TestCase):
    def test_board_hand_trinket_and_hero(self):
        srcs = live_reach_sources(
            board=[{"card": "BGS_123"}],
            hand=[{"card": "BG24_715"}],
            trinkets=[{"id": "BG30_MagicItem_4250", "name": "Globe"}],
            hero_name="Ambassador Faelin")
        names = {s["name"] for s in srcs}
        self.assertEqual(names, {"Tavern Tempest", "Patient Scout",
                                 "Azeroth Model Globe",
                                 "Ambassador Faelin"})

    def test_same_card_on_board_and_in_hand_is_one_source(self):
        srcs = live_reach_sources(board=[{"card": "BGS_123"}],
                                  hand=[{"card": "BGS_123"}])
        self.assertEqual(len(srcs), 1)

    def test_unheld_cards_produce_nothing(self):
        self.assertEqual(live_reach_sources(board=[{"card": "BG36_352"}]),
                         [])


class TestHuntReachability(unittest.TestCase):
    def test_tier_gate_blocks_unreachable_above_piece(self):
        ok, why = _hunt_check(UNBOUND, 5, 10, {}, False, None)
        self.assertFalse(ok)
        self.assertEqual(why, "needs tier 6")

    def test_discover_source_passes_the_tier_gate(self):
        ok, why = _hunt_check(UNBOUND, 5, 10, {}, False, None, reach=[GLOBE])
        self.assertTrue(ok)
        self.assertIn("Azeroth Model Globe", why)

    def test_random_generate_never_passes_any_gate(self):
        ok, why = _hunt_check(UNBOUND, 5, 10, {}, False, None,
                              reach=TEMPEST_SRC)
        self.assertFalse(ok)
        self.assertEqual(why, "needs tier 6")

    def test_token_generator_passes_for_its_grant_only(self):
        token = {"kind": "token", "grants": "BG36_352",
                 "name": "Boom's Monster Portrait"}
        ok, _ = _hunt_check(UNBOUND, 5, 10, {}, False, None, reach=[token])
        self.assertTrue(ok)
        # another tier-6 piece the token does NOT grant stays blocked
        surge = {"card": "BG32_846", "name": "Unleashed Mana Surge"}
        ok, why = _hunt_check(surge, 5, 10, {}, False, None, reach=[token])
        self.assertFalse(ok)
        self.assertEqual(why, "needs tier 6")

    def test_discover_bypasses_a_dry_pool(self):
        dry = {"BG36_352": 999}
        ok, why = _hunt_check(UNBOUND, 6, 10, {}, False, dry, reach=[GLOBE])
        self.assertTrue(ok)
        ok, why = _hunt_check(UNBOUND, 6, 10, {}, False, dry)
        self.assertFalse(ok)
        self.assertIn("pool dry", why)

    def test_recency_still_applies_when_reachable(self):
        seen = {"BG36_352": 3}  # 7 turns silent > HUNT_SEEN_WINDOW
        ok, why = _hunt_check(UNBOUND, 6, 10, seen, True, None, reach=[GLOBE])
        self.assertFalse(ok)
        self.assertIn("last shown", why)

    def test_tier_cap_resolutions(self):
        self.assertTrue(_src_reaches({"kind": "discover",
                                      "tier_cap": "tier+1"},
                                     "X", 6, 5))
        self.assertFalse(_src_reaches({"kind": "discover",
                                       "tier_cap": "current"},
                                      "X", 6, 5))
        self.assertIsNone(_src_reaches({"kind": "random_generate"},
                                       "X", 6, 5))

    def test_weak_hit_needs_the_tribe(self):
        self.assertTrue(_src_weak_hit(TEMPEST_SRC[0], "BG36_352", 6))
        self.assertFalse(_src_weak_hit(TEMPEST_SRC[0], "BG31_176", 6))

    def test_weak_mention_footnote(self):
        note = _weak_reach_note(TEMPEST_SRC, [UNBOUND])
        self.assertIn("Tavern Tempest can still drop it", note)
        self.assertEqual(_weak_reach_note([], [UNBOUND]), "")


class TestQ1Exception(unittest.TestCase):
    ANALYSIS = {"tier": 4, "target_cards": {"core": [
        dict(UNBOUND, owned=False, banned=False)], "addons": []}}

    def test_unreachable_above_piece_vetoes_the_stay(self):
        above_core = _comp_needs_by_tier(self.ANALYSIS, _load_card_db())[4]
        self.assertEqual(above_core, 1)

    def test_discover_reachable_above_piece_does_not_veto(self):
        got = _comp_needs_by_tier(self.ANALYSIS, _load_card_db(),
                                  reach=[GLOBE])
        self.assertEqual(got[4], 0)

    def test_random_reachable_above_piece_still_vetoes(self):
        got = _comp_needs_by_tier(self.ANALYSIS, _load_card_db(),
                                  reach=TEMPEST_SRC)
        self.assertEqual(got[4], 1)


class TestFuelLine(unittest.TestCase):
    DB = _load_card_db()
    SPELLS = _load_spell_db()
    NAMES = _load_bg_names()
    COSTS = {"BGS_115": 3, "BG28_518": 3}  # Sellemental, Chef's Choice

    def line(self, analysis, spare):
        return _fuel_line(analysis, self.DB, self.SPELLS, self.NAMES,
                          self.COSTS, spare)

    def test_fires_with_engine_on_board_and_idle_gold(self):
        a = {"tier": 5, "board": [{"card": "BG36_352"}],
             "shop_rank": [("BGS_115", 5.0)]}
        out = self.line(a, 6)
        self.assertIn("feed the engine", out)
        self.assertIn("Sellemental", out)
        self.assertIn("quantity beats quality", out)

    def test_minion_body_outranks_costlier_spell(self):
        a = {"tier": 5, "board": [{"card": "BG36_352"}],
             "shop_rank": [("BG28_518", 9.0), ("BGS_115", 4.0)]}
        out = self.line(a, 6)
        # equal bodies-per-gold -> first in shop order wins the tie
        self.assertIn("Chef's Choice", out)

    def test_gates(self):
        base = {"tier": 5, "board": [{"card": "BG36_352"}],
                "shop_rank": [("BGS_115", 5.0)]}
        self.assertIsNone(self.line(dict(base, tier=3), 6))   # early tempo
        self.assertIsNone(self.line(base, 2))                 # gold not idle
        self.assertIsNone(self.line(base, None))              # no budget
        no_engine = dict(base, board=[{"card": "BGS_123"}])
        self.assertIsNone(self.line(no_engine, 6))            # no engine
        no_fuel_shop = dict(base, shop_rank=[("BG31_176", 5.0)])
        self.assertIsNone(self.line(no_fuel_shop, 6))         # no conversion


if __name__ == "__main__":
    unittest.main()
