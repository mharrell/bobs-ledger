"""Mid-turn advice updates: the monitor re-advises whenever the decision state
changes during a buy phase (buy, roll, play, sell), not once per buy phase.

The old loop advised once per MAIN_ACTION transition and went stale for the
rest of the turn — the overlay kept showing the pre-buy shop and affordability
even after the player spent gold.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live_coach import LiveCoach
from tests.test_shop_parsing import opt_block

GS = "D 21:17:13.7844972 GameState.DebugPrintPower() - "
OPT = "D 21:17:14.0000000 GameState.DebugPrintOptions() - "


def _coach_with_offers(*offers):
    c = LiveCoach()
    c.friendly = 7  # hero parsed (as it is by the first seeded advise)
    for line in ["x tag=STEP value=MAIN_ACTION"] + opt_block(1, offers):
        c.feed(line)
    return c


class TestStateFingerprint(unittest.TestCase):
    def test_none_before_hero_parsed(self):
        self.assertIsNone(LiveCoach().state_fingerprint())

    def test_gold_change_changes_fingerprint(self):
        """A buy spends gold — the fingerprint must notice (affordability)."""
        c = LiveCoach()
        c.friendly = 7
        c.account = "TestAccount"
        c.feed(f"{GS}Entity=TestAccount tag=RESOURCES value=5")
        before = c.state_fingerprint()
        c.feed(f"{GS}Entity=TestAccount tag=RESOURCES value=3")
        self.assertNotEqual(before, c.state_fingerprint())

    def test_shop_change_changes_fingerprint(self):
        """After a buy/refresh the shop loses an offer — the advice must re-run."""
        c = self._offers_coach()
        before = c.state_fingerprint()
        # A refresh wipes the captured offers until the next options block.
        c.feed("x BlockType=PLAY Entity=[entityName=Refresh "
               "cardId=TB_BaconShop_8p_Reroll_Button player=7] Target=")
        self.assertNotEqual(before, c.state_fingerprint())

    def _offers_coach(self):
        from live_coach import LiveCoach
        c = LiveCoach()
        c.friendly = 7
        for line in ["x tag=STEP value=MAIN_ACTION"] + opt_block(1, [
                ("River Skipper", "BG33_140", 15),
                ("Tusked Camper", "BG33_886", 15)]):
            c.feed(line)
        return c


class TestGoldSpending(unittest.TestCase):
    def test_spent_gold_is_subtracted(self):
        """Gold = RESOURCES - RESOURCES_USED. The purse alone made mid-turn
        advice judge affordability against gold the player already spent."""
        c = LiveCoach()
        c.feed(f"{GS}Entity=TestAccount tag=RESOURCES value=5")
        self.assertEqual(c.gs.gold.get("TestAccount"), 5)
        c.feed(f"{GS}Entity=TestAccount tag=RESOURCES_USED value=3")
        self.assertEqual(c.gs.gold.get("TestAccount"), 2)

    def test_fingerprint_notices_spending(self):
        c = LiveCoach()
        c.friendly = 7
        c.account = "TestAccount"
        c.feed(f"{GS}Entity=TestAccount tag=RESOURCES value=5")
        before = c.state_fingerprint()
        c.feed(f"{GS}Entity=TestAccount tag=RESOURCES_USED value=3")
        self.assertNotEqual(before, c.state_fingerprint())


class TestLevelCost(unittest.TestCase):
    def _coach(self, tier):
        from live_coach import LiveCoach
        c = LiveCoach()
        c.friendly = 7
        c.hero_card = "HERO_X"
        c.gs.hero_meta["HERO_X"]["tier"] = tier
        return c

    def test_live_button_cost_wins(self):
        """The TechUp button's COST tag is the authoritative upgrade price."""
        c = self._coach(2)
        c.feed(f"{GS}TAG_CHANGE Entity=[entityName=Tavern Tier 3 id=1013 "
               f"cardId=TB_BaconShopTechUp03_Button player=7] tag=COST value=6")
        self.assertEqual(c.level_cost(), 6)

    def test_death_writes_and_zero_costs_ignored(self):
        """Teardown writes (COST 0, or after the button left PLAY) must not
        pollute the live price."""
        c = self._coach(2)
        c.feed(f"{GS}TAG_CHANGE Entity=[entityName=Tavern Tier 3 id=1013 "
               f"cardId=TB_BaconShopTechUp03_Button player=7] tag=COST value=6")
        c.feed(f"{GS}TAG_CHANGE Entity=[entityName=Tavern Tier 3 id=1013 "
               f"cardId=TB_BaconShopTechUp03_Button player=7] tag=ZONE "
               f"value=REMOVEDFROMGAME")
        c.feed(f"{GS}TAG_CHANGE Entity=[entityName=Tavern Tier 3 id=1013 "
               f"cardId=TB_BaconShopTechUp03_Button player=7] tag=COST value=7")
        self.assertEqual(c.level_cost(), 6)

    def test_turn1_button_costs_5(self):
        """Turn 1: the tier-2 button costs 5 (3 gold cannot level — the old
        tier+1 model said 2 and advised an impossible level-then-buy)."""
        c = self._coach(1)
        c._tier_seen_turn = 0
        c.actions.turn = 1
        self.assertEqual(c.level_cost(), 5)

    def test_price_drops_per_turn_at_tier(self):
        """Wiki rule: tier+5 minus turns at the tier (2nd turn: 4)."""
        c = self._coach(1)
        c._tier_seen_turn = 0
        c.actions.turn = 2
        self.assertEqual(c.level_cost(), 4)

    def test_top_move_uses_real_cost(self):
        """Turn 1 (gold 3, button 5): 'next turn — 2 short', never the
        impossible level-then-buy."""
        from value import top_move
        a = {"tier": 1, "gold": 3, "level_cost": 5, "board": [],
             "shop_rank": [], "buy_this": None, "playable_comps": {},
             "choice": None, "target_comp": None, "sell_rank": []}
        tm = top_move(a)
        self.assertIn("LEVEL next turn — 2 short", tm)
        self.assertNotIn("LEVEL to tier 2", tm)


class TestBoardFallback(unittest.TestCase):
    def test_empty_board_falls_back_to_snapshot(self):
        """A full-board turn's combat teardown leaves the log's PLAY board
        empty until after the shop prints (2026-09-03: one phase per game
        advised on board 0). analyze must estimate from the last snapshot."""
        c = LiveCoach()
        c.friendly = 7
        c.hero_card = "HERO_X"
        c.gs.hero_meta["HERO_X"]["tier"] = 3
        c.account = "TestAccount"
        c.playable = {}
        c.gs.snapshots.append([
            {"card": "BG33_140", "player": 7, "atk": 2, "health": 2},
            {"card": "BG33_886", "player": 15, "atk": 3, "health": 3},
        ])
        a = c.analyze()
        self.assertEqual([m["card"] for m in a["board"]], ["BG33_140"])

    def test_real_board_beats_snapshot(self):
        """When the live PLAY board exists it is used (no snapshot ghosting)."""
        c = LiveCoach()
        c.friendly = 7
        c.hero_card = "HERO_X"
        c.gs.hero_meta["HERO_X"]["tier"] = 3
        c.account = "TestAccount"
        c.playable = {}
        c.gs.snapshots.append([{"card": "BG33_140", "player": 7,
                                "atk": 2, "health": 2}])
        c.feed(f"{GS}TAG_CHANGE Entity=[entityName=X id=99 zone=PLAY "
               f"zonePos=1 cardId=BG33_886 player=7] tag=ZONE value=PLAY")
        c.gs.cardtype[99] = "MINION"
        a = c.analyze()
        self.assertEqual([m["card"] for m in a["board"]], ["BG33_886"])


if __name__ == "__main__":
    unittest.main()