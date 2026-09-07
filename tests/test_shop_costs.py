"""Regression tests for live shop pricing.

The historical bug (2026-09-05, "the coach recommends buying minions when I
only have 2 gold"): since patch 36.4.x a minion's BUY COST is per-card and
decoupled from its TECH_LEVEL — the logs show 86 of 117 shop creations where
COST != TECH_LEVEL (Lullabot TECH_LEVEL 1 but COST 2; Soul Rewinder tier 2
but COST 4). The coach priced every minion at its DB tier, blessed buys the
purse couldn't cover, and the decision log holds 24 low-gold Buy
recommendations that day.

The fix: board_state captures the entity COST tag (printed numerically as
tag=479), live_coach maps the shop offers to those live prices, and
value._top_move_text overlays them on the DB price map — DB tier stays only
as the fallback for cards the log hasn't priced.
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