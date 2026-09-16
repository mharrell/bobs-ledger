"""Engine recipes (analysis/engine_coaching.md Plan 1).

Covers the curated tables' integrity (recipe schema + the hero_powers text
quotes that catch semantic drift on a patch), activation matching (hero +
trinkets, mechanical-confidence only), the fuel check (literal card text),
the loud play-time terms (shop boost delta, buy-intention naming), the
quiet capped pick-time terms (hero-power recipe term, SYN_CAP), the
reverse trinket->comp nudge, and the held-trinket id-drift resolution the
whole path depends on (Sous Chef Sticker: BG35_MagicItem_801 in the log,
BG35_MagicItem_8012 in the DB).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import meta
from board_state import GameState
from choices import _rank_trinkets, SYN_CAP
from live_coach import _resolve_trinkets
from value import (active_recipes, recipe_fuel_hit, shop_ranking,
                   _buy_intention, comp_target, comp_progress, W_RECIPE_FUEL)

RECIPE_ID = "shudderwock-sous-chef-battlecries"
SOUS_CHEF_DB_ID = "BG35_MagicItem_8012"
SOUS_CHEF_LOG_ID = "BG35_MagicItem_801"  # the id the live log actually used


def _sous_chef_rec():
    return {"cid": SOUS_CHEF_LOG_ID, "name": "Sous Chef Sticker"}


class TestRecipeTables(unittest.TestCase):
    def test_recipe_exists_and_mechanical(self):
        recs = meta.engine_recipes()
        self.assertIn(RECIPE_ID, recs)
        rec = recs[RECIPE_ID]
        self.assertEqual(rec["confidence"], "mechanical")
        self.assertEqual(rec["hero"], "Shudderwock")
        self.assertIn(SOUS_CHEF_DB_ID, rec["trinkets"])
        self.assertEqual(rec["fuel"]["keyword"], "battlecry")
        self.assertIn("id", rec)  # consumers key on the embedded id

    def test_hero_power_text_quotes_match_heroes_db(self):
        """A patch that rewords a hero power must flag the stale semantics
        here, not silently misfire at runtime."""
        heroes = {h["name"]: h for h in meta.heroes() if h.get("name")}
        for name, sem in meta.hero_powers().items():
            if name.startswith("_"):  # the _comment prose row
                continue
            self.assertIn(name, heroes,
                          f"hero_powers entry {name!r} not in heroes.json")
            self.assertEqual(sem.get("text"), (heroes[name].get("hero_power")
                                               or "").strip(),
                             f"stale text quote for {name!r} — re-encode "
                             f"the semantics from the new power text")


class TestActivation(unittest.TestCase):
    def test_hero_plus_trinket_activates(self):
        got = active_recipes("Shudderwock", [_sous_chef_rec()])
        self.assertEqual([r["id"] for r in got], [RECIPE_ID])

    def test_trinket_matched_by_db_id_or_name(self):
        by_id = active_recipes("Shudderwock",
                               [{"cid": SOUS_CHEF_DB_ID, "name": None}])
        by_name = active_recipes("Shudderwock",
                                 [{"cid": "XX_99", "name": "Sous Chef Sticker"}])
        self.assertEqual([r["id"] for r in by_id], [RECIPE_ID])
        self.assertEqual([r["id"] for r in by_name], [RECIPE_ID])

    def test_wrong_hero_no_activation(self):
        self.assertEqual(active_recipes("Ragnaros", [_sous_chef_rec()]), [])

    def test_missing_trinket_no_activation(self):
        self.assertEqual(active_recipes("Shudderwock", []), [])
        self.assertEqual(active_recipes("Shudderwock",
                                        [{"cid": "BG30_MagicItem_7000",
                                          "name": "Deathly Phylactery"}]), [])

    def test_plain_string_trinkets_accepted(self):
        for s in (SOUS_CHEF_DB_ID, "Sous Chef Sticker"):
            got = active_recipes("Shudderwock", [s])
            self.assertEqual([r["id"] for r in got], [RECIPE_ID])

    def test_observed_confidence_never_activates(self):
        """Observed rows sit inert until corpus data justifies them."""
        got = active_recipes("Shudderwock", [_sous_chef_rec()])
        self.assertTrue(all(r["confidence"] == "mechanical" for r in got))


class TestFuelHit(unittest.TestCase):
    def test_battlecry_text_hits(self):
        card = {"text": "Battlecry: Get a random Elemental."}
        rec = meta.engine_recipes()[RECIPE_ID]
        self.assertTrue(recipe_fuel_hit(card, rec))

    def test_non_battlecry_misses(self):
        rec = meta.engine_recipes()[RECIPE_ID]
        self.assertFalse(recipe_fuel_hit({"text": "After you sell an "
                                          "Elemental, gain +4/+4."}, rec))
        self.assertFalse(recipe_fuel_hit(None, rec))
        self.assertFalse(recipe_fuel_hit({"text": "Battlecry: X"}, None))


class TestPlayTime(unittest.TestCase):
    def test_shop_boost_is_exactly_the_recipe_boost(self):
        comps = {}
        recipes = active_recipes("Shudderwock", [_sous_chef_rec()])
        plain = dict(shop_ranking(["BGS_123"], comps, recipes=None))
        boosted = dict(shop_ranking(["BGS_123"], comps, recipes=recipes))
        self.assertAlmostEqual(boosted["BGS_123"],
                               plain["BGS_123"] + W_RECIPE_FUEL)

    def test_shop_boost_applies_to_golden_variant(self):
        recipes = active_recipes("Shudderwock", [_sous_chef_rec()])
        plain = dict(shop_ranking(["BGS_123_G"], comps := {}))
        boosted = dict(shop_ranking(["BGS_123_G"], comps, recipes=recipes))
        self.assertAlmostEqual(boosted["BGS_123_G"],
                               plain["BGS_123_G"] + W_RECIPE_FUEL)

    def test_other_cards_untouched(self):
        from value import _load_card_db
        db = _load_card_db()
        recipes = active_recipes("Shudderwock", [_sous_chef_rec()])
        # real DB ids with no battlecry in the text
        cids = [cid for cid, c in db.items()
                if cid != "BGS_123"
                and "battlecry" not in (c.get("text") or "").lower()][:3]
        plain = dict(shop_ranking(cids, {}))
        boosted = dict(shop_ranking(cids, {}, recipes=recipes))
        for cid in cids:
            self.assertAlmostEqual(boosted[cid], plain[cid])

    def test_buy_intention_names_the_engine(self):
        recs = active_recipes("Shudderwock", [_sous_chef_rec()])
        card_db = {"BGS_123": {"text": "Battlecry: Get a random Elemental."}}
        why = _buy_intention("BGS_123", None, card_db, recipes=recs)
        self.assertEqual(why, "hero-power engine fuel")

    def test_comp_core_outranks_recipe_fuel(self):
        recs = active_recipes("Shudderwock", [_sous_chef_rec()])
        card_db = {"BGS_123": {"text": "Battlecry: X"}}
        comp = {"tribe": "Elemental", "core": ["BGS_123"], "addons": []}
        why = _buy_intention("BGS_123", comp, card_db, recipes=recs)
        self.assertTrue(why.startswith("committing to Elemental"))


class TestPickTime(unittest.TestCase):
    def test_recipe_term_on_required_trinket(self):
        ranked = _rank_trinkets([("Sous Chef Sticker", SOUS_CHEF_LOG_ID)],
                                [], hero="Shudderwock")
        _n, _c, score, why = ranked[0]
        self.assertIn("amps your hero-power engine", why)
        base = _rank_trinkets([("Sous Chef Sticker", SOUS_CHEF_LOG_ID)],
                              [])[0][2]
        self.assertAlmostEqual(score - base, SYN_CAP)

    def test_no_term_for_other_hero(self):
        ranked = _rank_trinkets([("Sous Chef Sticker", SOUS_CHEF_LOG_ID)],
                                [], hero="Ragnaros")
        self.assertNotIn("hero-power", ranked[0][3])

    def test_synergy_capped_at_syn_cap(self):
        """Board fit + recipe term together still add at most SYN_CAP."""
        board = [{"tribe": "ELEMENTAL", "keywords": ["Economy"]}]
        ranked = _rank_trinkets([("Sous Chef Sticker", SOUS_CHEF_LOG_ID)],
                                board, hero="Shudderwock")
        _n, _c, score, why = ranked[0]
        self.assertIn("fits your board", why)
        self.assertIn("amps your hero-power engine", why)
        base = _rank_trinkets([("Sous Chef Sticker", SOUS_CHEF_LOG_ID)],
                              [])[0][2]
        self.assertAlmostEqual(score - base, SYN_CAP)

    def test_rank_choices_passes_hero_through(self):
        from choices import rank_choices
        ranked = rank_choices("trinket",
                              [("Sous Chef Sticker", SOUS_CHEF_LOG_ID)],
                              hero="Shudderwock")
        self.assertIn("amps your hero-power engine", ranked[0][3])


class TestCompNudge(unittest.TestCase):
    COMPS = {
        "beasts": {"name": "Beasts", "tribe": "Beast",
                   "core": ["b1", "b2"], "addons": []},
        "elementals": {"name": "Elementals", "tribe": "Elemental",
                       "core": ["e1", "e2"], "addons": []},
    }
    # 2 core hits each — a committed-evidence tie the nudge may tip
    BOARD = [{"card": "b1"}, {"card": "b2"}, {"card": "e1"}, {"card": "e2"}]

    def test_trinket_tips_equal_evidence(self):
        trinkets = [{"synergy": {"tribes": ["Elemental"]}}]
        got = comp_target(self.BOARD, self.COMPS, trinkets=trinkets)
        self.assertEqual((got or {}).get("name"), "Elementals")

    def test_no_trinket_no_flip(self):
        got = comp_target(self.BOARD, self.COMPS)
        self.assertNotEqual((got or {}).get("name"), "Elementals")

    def test_nudge_never_manufactures_direction(self):
        """No core hits anywhere -> still no direction (modulates, never
        originates)."""
        trinkets = [{"synergy": {"tribes": ["Elemental"]}}]
        got = comp_target([{"card": "x9"}], self.COMPS, trinkets=trinkets)
        self.assertIsNone(got)

    def test_progress_rows_carry_fit_but_ready_needs_two_hits(self):
        trinkets = [{"synergy": {"tribes": ["Elemental"]}}]
        rows = comp_progress(self.BOARD, self.COMPS, trinkets=trinkets)
        by_name = {r["name"]: r for r in rows}
        self.assertTrue(by_name["Elementals"]["trinket_fit"])
        # The nudge orders the 2-hit tie but `ready` was already earned by
        # real evidence on both sides.
        self.assertLess(rows.index(by_name["Elementals"]),
                        rows.index(by_name["Beasts"]))
        # One real hit + a nudge is still not ready: the nudge orders, it
        # never promotes (modulates, never originates).
        one_hit = comp_progress([{"card": "e1"}], self.COMPS,
                                trinkets=trinkets)
        el = next(r for r in one_hit if r["name"] == "Elementals")
        self.assertFalse(el["ready"])
        self.assertTrue(el["trinket_fit"])


class TestHeldTrinketResolution(unittest.TestCase):
    def test_drifted_log_id_resolves_by_bracket_name(self):
        gs = GameState()
        # The exact line shape the 2026-09-15 log used for the trinket pick
        # (drifted 3-digit log id), in the standard bracket TAG_CHANGE form.
        gs.feed("D 11:00:00.0000000 GameState.DebugPrintPower() - "
                "    TAG_CHANGE Entity=[entityName=Sous Chef Sticker "
                "id=3104 zone=SETASIDE zonePos=0 cardId=BG35_MagicItem_801 "
                "player=1] tag=ZONE value=PLAY")
        recs = gs.held_trinket_records(1)
        self.assertEqual([r["cid"] for r in recs], [SOUS_CHEF_LOG_ID])
        self.assertEqual([r["name"] for r in recs], ["Sous Chef Sticker"])
        by_id = {t["id"]: t for t in meta.trinkets()}
        by_name = {t["name"]: t for t in meta.trinkets() if t.get("name")}
        resolved = _resolve_trinkets(recs, by_id, by_name)
        self.assertEqual([t["id"] for t in resolved], [SOUS_CHEF_DB_ID])

    def test_exact_id_still_resolves(self):
        by_id = {t["id"]: t for t in meta.trinkets()}
        by_name = {t["name"]: t for t in meta.trinkets() if t.get("name")}
        recs = [{"cid": SOUS_CHEF_DB_ID, "name": None}]
        self.assertEqual([t["id"] for t in _resolve_trinkets(recs, by_id,
                                                             by_name)],
                         [SOUS_CHEF_DB_ID])

    def test_unknown_trinket_dropped_not_crashed(self):
        by_id, by_name = {}, {}
        self.assertEqual(_resolve_trinkets([{"cid": "BG99_MagicItem_1",
                                             "name": "Mystery"}],
                                            by_id, by_name), [])


if __name__ == "__main__":
    unittest.main()
