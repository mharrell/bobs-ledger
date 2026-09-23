"""Regression tests for live shop pricing.

Two superseded pricing models are on record (don't re-derive them):
1. 2026-09-05: "buy price = DB tier" died — 86 of 117 shop creations had
   COST != TECH_LEVEL, so the coach blessed buys the purse couldn't cover.
   board_state now captures the entity COST tag (tag=479).
2. 2026-09-06: "price from the captured COST tag" died too — those tags are
   stale legacy tier costs (RESOURCES_USED=3 charged for tags saying 1).
   Player-confirmed: minions cost a FLAT 3 gold at every tier, goldens
   included. The captured costs feed TAVERN SPELLS ONLY
   (value._buy_prices); TestTopMoveAffordability below pins that split.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from board_state import GameState
import value

GS = "D 12:22:28.3956768 GameState.DebugPrintPower() - "

LULLABOT = "BG26_146"   # DB tier 1 — log COST 2 (the report's exact case)


def creating(gs, eid, cid):
    gs.feed(f"{GS}    FULL_ENTITY - Creating ID={eid} CardID={cid}")


def tag(gs, eid, tag_name, val, cid=""):
    gs.feed(f"{GS}        tag={tag_name} value={val}")


def change(gs, eid, tag_name, val, cid=""):
    gs.feed(f"{GS}    TAG_CHANGE Entity=[entityName=M id={eid} zone=SETASIDE "
            f"zonePos=0 cardId={cid} player=7] tag={tag_name} value={val}")


class TestCostCapture(unittest.TestCase):
    def test_creation_block_carries_cost(self):
        gs = GameState()
        creating(gs, 971, LULLABOT)
        for t, v in (("CONTROLLER", 7), ("CARDTYPE", "MINION"),
                     ("TECH_LEVEL", 1), ("479", 2)):
            tag(gs, 971, t, v)
        self.assertEqual(gs.cost[971], 2)
        self.assertEqual(gs.tier[971], 1)  # TECH_LEVEL is separate, still tracked

    def test_minion_dict_carries_cost(self):
        gs = GameState()
        creating(gs, 971, LULLABOT)
        tag(gs, 971, "479", 2)
        m = gs._minion(971, LULLABOT)
        self.assertEqual(m["cost"], 2)

    def test_tag_change_updates_cost(self):
        # Cost modifiers (trinkets/spells that re-price the shop) write the
        # same tag on TAG_CHANGE lines — the live price must follow.
        gs = GameState()
        creating(gs, 971, LULLABOT)
        tag(gs, 971, "479", 2)
        change(gs, 971, "479", 1, LULLABOT)
        self.assertEqual(gs.cost[971], 1)

    def test_named_cost_tag_also_captured(self):
        gs = GameState()
        creating(gs, 971, LULLABOT)
        tag(gs, 971, "COST", 2)
        self.assertEqual(gs.cost[971], 2)


class TestShopCostMap(unittest.TestCase):
    """Capture plumbing only: shop_cost_map returns the raw captured COST
    values (minions included — kept for spell pricing and debugging).
    Downstream, value._buy_prices applies shop_costs to SPELLS only; a
    minion's captured tag is never its buy price."""

    def _gs_with(self, *specs):
        """specs: (eid, cid, cost) in feed order."""
        gs = GameState()
        for eid, cid, cost in specs:
            creating(gs, eid, cid)
            tag(gs, eid, "479", cost)
        return gs

    def test_offer_priced_from_log(self):
        gs = self._gs_with((971, LULLABOT, 2))
        self.assertEqual(
            __import__("live_coach").shop_cost_map(gs, [LULLABOT]),
            {LULLABOT: 2})

    def test_unpriced_card_absent(self):
        gs = GameState()
        self.assertEqual(
            __import__("live_coach").shop_cost_map(gs, [LULLABOT]), {})

    def test_later_entity_wins(self):
        # The most recent creation is the current shop's copy (an earlier
        # entity with the same card id may be a bought board minion).
        gs = self._gs_with((100, LULLABOT, 3), (971, LULLABOT, 2))
        self.assertEqual(
            __import__("live_coach").shop_cost_map(gs, [LULLABOT]),
            {LULLABOT: 2})

    def test_golden_maps_both_ids(self):
        gs = self._gs_with((971, LULLABOT + "_G", 4))
        got = __import__("live_coach").shop_cost_map(gs, [LULLABOT])
        self.assertEqual(got, {LULLABOT: 4})


class TestTopMoveAffordability(unittest.TestCase):
    """top_move must never bless a Buy the purse can't cover. Minions cost a
    FLAT 3 (the patch's default for ALL tiers — the log's tag=479 minion
    values are stale legacy costs: 2026-09-06 charged 3 for tags saying 1,
    player-confirmed); tavern spells keep their own prices."""

    def _analysis(self, gold, cid, cost):
        return {"gold": gold, "buy_this": cid, "shop_costs": {cid: cost},
                "shop_rank": [[cid, 5.0]], "board": [], "turn": 9}

    def test_minion_costs_flat_three(self):
        # The stale log tag says 1 and the DB tier says 1 — the minion still
        # costs 3, so 2 gold must NOT bless the buy.
        a = self._analysis(2, LULLABOT, 1)
        text = value.top_move(a)
        self.assertNotIn("buy", [s["kind"] for s in a["top_move_steps"]])
        self.assertIsNone(a["buy_step_card"])
        self.assertIn("roll", text)

    def test_minion_affordable_at_three(self):
        a = self._analysis(3, LULLABOT, 1)
        text = value.top_move(a)
        self.assertIn("buy", [s["kind"] for s in a["top_move_steps"]])
        self.assertEqual(a["buy_step_card"], LULLABOT)

    def test_spell_log_cost_decides(self):
        # A tavern spell's own log COST tag is real: a tier-5 spell priced
        # at 2 is buyable at 2 gold even though the spell DB says more.
        spell_db = value._load_spell_db()
        cid = next(c for c, v in spell_db.items()
                   if (v or {}).get("cost", 0) and (v or {}).get("cost") > 2)
        a = self._analysis(2, cid, 2)
        value.top_move(a)
        self.assertEqual(a["buy_step_card"], cid)

    def test_spell_fallback_walk_uses_log_costs(self):
        # Headline (a minion at 3) unaffordable, a cheaper spell affordable —
        # the ranking walk must price both correctly.
        spell_db = value._load_spell_db()
        spell = next(c for c, v in spell_db.items()
                     if (v or {}).get("cost", 0) > 2)
        alt = next(c for c in spell_db if c != spell)
        a = self._analysis(2, LULLABOT, 99)
        a["shop_costs"][spell] = 2
        a["shop_rank"] = [[LULLABOT, 5.0], [spell, 3.0]]
        value.top_move(a)
        self.assertEqual(a["buy_step_card"], spell)


class TestPriceModifiers(unittest.TestCase):
    """Held-trinket price overrides (2026-09-20 ruling: the coach models
    the text-stated exceptions to flat-3). Electrode Attractor: 'Magnetic
    Mechs cost (2)'. Bazaar Sticker: '1 Tavern spell/turn costs Health
    instead of Gold' — one spell per turn can't live in a flat price map,
    so the plan walk discounts the one spell it would buy and says so."""

    def test_electrode_attractor_magnetics_cost_two(self):
        from player_actions import _load_bg_magnetic_ids
        mag = sorted(_load_bg_magnetic_ids())[0]
        plain = next(c for c in value._load_card_db()
                     if c not in _load_bg_magnetic_ids())
        self.assertEqual(value._buy_prices({})[mag], 3)
        held = value._buy_prices(
            {"scenario": {"trinkets": ["Electrode Attractor"]}})
        self.assertEqual(held[mag], 2)
        self.assertEqual(held[mag + "_G"], 2)
        self.assertEqual(held[plain], 3)  # non-magnetic stays flat 3

    def _spell_analysis(self, health=20):
        spell_db = value._load_spell_db()
        cid = next(c for c, v in spell_db.items()
                   if (v or {}).get("cost", 0) >= 1)
        return cid, {"gold": 0, "buy_this": cid, "shop_costs": {cid: 3},
                     "shop_rank": [[cid, 5.0]], "board": [], "turn": 9,
                     "health": health, "armor": 0,
                     "scenario": {"trinkets": ["Bazaar Sticker"]}}

    def test_bazaar_sticker_first_spell_costs_health_not_gold(self):
        """Gold 0 and the spell priced 3: the plan still buys it — the
        Sticker pays its price in health — and says so."""
        cid, a = self._spell_analysis()
        text = value.top_move(a)
        self.assertEqual(a["buy_step_card"], cid)
        self.assertIn("Health instead of gold", text)

    def test_bazaar_sticker_not_while_dying(self):
        """At <=12 effective HP a health spend is how runs end — the
        discount is refused and the spell stays unaffordable at 0 gold."""
        cid, a = self._spell_analysis(health=8)
        text = value.top_move(a)
        self.assertIsNone(a["buy_step_card"])
        self.assertNotIn("Health instead of gold", text)

    def test_spell_needs_gold_without_the_sticker(self):
        cid, a = self._spell_analysis()
        a["scenario"] = {}
        value.top_move(a)
        self.assertIsNone(a["buy_step_card"])


class TestShopCostMapEntityExact(unittest.TestCase):
    """shop_cost_map must price the shop's OWN entities: the 2026-09-05 Holmes
    game priced a shop Waverider 31g off a discovery-pool copy's COST write
    (SETASIDE, combat scaling) — card-id "later write wins" picked the junk
    value. The offer entity's own COST wins; the cid scan is fallback only."""

    def _gs(self, lines):
        gs = GameState()
        for line in lines:
            gs.feed(line)
        return gs

    def test_offer_entity_beats_later_same_card_write(self):
        shop_eid, junk_eid = 12023, 15222
        lines = [
            f"{GS}TAG_CHANGE Entity=[entityName=Shop Waverider id={shop_eid} "
            f"zone=PLAY cardId=BG23_007 player=15] tag=479 value=3",
            # a later, different entity of the same card with junk cost
            f"{GS}TAG_CHANGE Entity=[entityName=Pool Waverider id={junk_eid} "
            f"zone=SETASIDE cardId=BG23_007 player=5] tag=479 value=31",
        ]
        gs = self._gs(lines)
        from live_coach import shop_cost_map
        costs = shop_cost_map(gs, ["BG23_007"], {"BG23_007": shop_eid})
        self.assertEqual(costs["BG23_007"], 3)

    def test_cid_scan_fallback_without_eids(self):
        lines = [
            f"{GS}TAG_CHANGE Entity=[entityName=Waverider id=1 "
            f"zone=PLAY cardId=BG23_007 player=15] tag=479 value=3",
        ]
        gs = self._gs(lines)
        from live_coach import shop_cost_map
        self.assertEqual(shop_cost_map(gs, ["BG23_007"])["BG23_007"], 3)


if __name__ == "__main__":
    unittest.main()