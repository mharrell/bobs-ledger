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
        """Turn 1 (gold 3, button 5): no impossible LEVEL step at all — an
        upgrade the player can't make this turn isn't advice (2026-09-04)."""
        from value import top_move
        a = {"tier": 1, "gold": 3, "level_cost": 5, "board": [],
             "shop_rank": [], "buy_this": None, "playable_comps": {},
             "choice": None, "target_comp": None, "sell_rank": []}
        tm = top_move(a)
        self.assertNotIn("LEVEL", tm)
        self.assertIn("roll", tm)


class TestLevelVsBoard(unittest.TestCase):
    """Leveling that costs the board must not lead: when dying, or when the
    leftover couldn't buy the shop's top card and it's a target-comp core,
    the buy comes first (2026-09-03: "we can't upgrade the board if we're
    going to die / miss important minions as a result")."""

    def _analysis(self, gold=6, level_cost=5, health=None, core_pick=False):
        from value import top_move, _load_card_db
        db = _load_card_db()
        hi = next(cid for cid, v in db.items()
                  if v.get("tier") == 4)   # costs 4 > spare 1
        a = {"tier": 2, "gold": gold, "level_cost": level_cost,
             "health": health, "armor": 0, "board": [],
             "shop_rank": [(hi, 9.0)], "buy_this": hi,
             "playable_comps": {}, "choice": None, "target_comp": None,
             "sell_rank": [],
             "target_cards": {"core": [{"card": hi}] if core_pick else []}}
        return a, top_move

    def test_dying_hero_buys_instead_of_levels(self):
        a, top_move = self._analysis(health=8)
        tm = top_move(a)
        self.assertTrue(tm.startswith("1. Buy "), tm)
        self.assertIn("LEVEL next turn", tm)

    def test_core_card_beats_level(self):
        a, top_move = self._analysis(health=40, core_pick=True)
        tm = top_move(a)
        self.assertTrue(tm.startswith("1. Buy "), tm)
        self.assertIn("LEVEL next turn", tm)

    def test_level_still_leads_when_both_fit(self):
        """Healthy, no core pick, and the leftover covers the top card:
        level-first is unchanged."""
        a, top_move = self._analysis(gold=10)  # spare 5 >= cost 4
        tm = top_move(a)
        self.assertTrue(tm.startswith("1. LEVEL "), tm)
        self.assertIn("Buy", tm)

    def test_level_leads_when_healthy_and_no_core(self):
        a, top_move = self._analysis()  # spare 1 < 4, but nothing important
        tm = top_move(a)
        self.assertTrue(tm.startswith("1. LEVEL "), tm)


class TestLevelGates(unittest.TestCase):
    """The leveling gates of analysis/LEVELING_MODEL.md, each with a stated
    reason: armor flow (Q0), the shopping-list tier filter (Q1), and the
    curve prior as the default."""

    def _analysis(self, gold=6, level_cost=5, health=40, armor=0,
                  damage_last=None, loss_streak=0, next_pieces=(),
                  here_pieces=(), tier=2):
        from value import top_move, _load_card_db
        db = _load_card_db()

        def cid_of(t, exclude=()):
            return next(c for c, v in db.items()
                        if v.get("tier") == t and c not in exclude)

        t1 = cid_of(1)   # shop headline the budget can cover after a level
        t2 = cid_of(2, exclude=(t1,))
        t3 = cid_of(3, exclude=(t1, t2))
        t4 = cid_of(4, exclude=(t1, t2, t3))

        def row(cid):
            return {"card": cid, "name": cid, "owned": False}

        a = {"tier": tier, "gold": gold, "level_cost": level_cost,
             "health": health, "armor": armor, "turn": 7,
             "damage_last": damage_last, "loss_streak": loss_streak,
             "board": [], "shop_rank": [(t4, 9.0), (t1, 4.0)],
             "buy_this": t4, "playable_comps": {}, "choice": None,
             "target_comp": "Test", "sell_rank": [],
             "target_cards": {"name": "Test",
                              "core": [row(c) for c in next_pieces],
                              "addons": [row(c) for c in here_pieces]}}
        return a, top_move

    def test_payoff_next_tier_reason(self):
        """A comp piece the player needs sits at tier+1: the level states
        the payoff as its reason."""
        a, top_move = self._analysis(next_pieces=("TIER3X",))
        # point the comp piece at a real tier-3 card
        from value import _load_card_db
        t3 = next(c for c, v in _load_card_db().items() if v.get("tier") == 3)
        a["target_cards"]["core"] = [{"card": t3, "name": t3, "owned": False}]
        tm = top_move(a)
        self.assertTrue(tm.startswith(
            "1. LEVEL to tier 3 (the comp's next pieces live there)"), tm)

    def test_needs_here_stays_and_buys(self):
        """The comp's missing pieces are ON the current tier: leveling would
        LOWER the odds of finding them — stay is stated, buy leads."""
        from value import _load_card_db
        db = _load_card_db()
        t2 = next(c for c, v in db.items() if v.get("tier") == 2)
        a, top_move = self._analysis(here_pieces=(t2,))
        tm = top_move(a)
        self.assertNotIn("LEVEL", tm)
        self.assertIn("stay on tier 2", tm)
        self.assertIn("lower the odds", tm)

    def test_loss_streak_defers_level_with_reason(self):
        """Two straight real losses and the level + top card can't both fit:
        buy tempo, level trails with the reason stated."""
        a, top_move = self._analysis(damage_last=8, loss_streak=2, tier=3)
        tm = top_move(a)
        self.assertTrue(tm.startswith("1. Buy "), tm)
        self.assertIn("lost 2 straight fights", tm)
        self.assertIn("LEVEL next turn", tm)

    def test_single_real_loss_defers_with_reason(self):
        a, top_move = self._analysis(damage_last=12, loss_streak=1, tier=3)
        tm = top_move(a)
        self.assertTrue(tm.startswith("1. Buy "), tm)
        self.assertIn("took 12 last fight", tm)

    def test_early_game_losses_do_not_flip(self):
        """Tiers 1-2 are shop-driven (Jeef): early losses don't gate levels."""
        a, top_move = self._analysis(damage_last=4, loss_streak=3, tier=2)
        tm = top_move(a)
        self.assertTrue(tm.startswith("1. LEVEL "), tm)

    def test_token_loss_does_not_flip(self):
        """A 2-damage combat is a won fight, not a tempo alarm."""
        a, top_move = self._analysis(damage_last=2, loss_streak=0)
        tm = top_move(a)
        self.assertTrue(tm.startswith("1. LEVEL "), tm)

    def test_curve_prior_names_itself(self):
        a, top_move = self._analysis()
        tm = top_move(a)
        self.assertIn("LEVEL to tier 3 (standard curve)", tm)


class TestArmorFlow(unittest.TestCase):
    """Armor/HP drops between buy phases are the loss-streak signal (Q0,
    analysis/LEVELING_MODEL.md): 'took N last fight' / 'lost N straight'."""

    HERO = ("Entity=[entityName=H id=9 zone=PLAY zonePos=1 "
            "cardId=BG30_HERO_100 player=7]")

    def test_damage_last_and_streak(self):
        c = LiveCoach()
        c.friendly = 7
        c.hero_card = "BG30_HERO_100"
        c.account = "TestAccount"
        c.playable = {}
        c.feed(f"{GS}TAG_CHANGE {self.HERO} tag=HEALTH value=30")
        c.feed(f"{GS}TAG_CHANGE {self.HERO} tag=ARMOR value=20")
        c.actions.turn = 1
        a = c.analyze()
        self.assertIsNone(a["damage_last"])  # no prior phase to compare
        c.feed(f"{GS}TAG_CHANGE {self.HERO} tag=ARMOR value=12")
        c.actions.turn = 2
        a = c.analyze()
        self.assertEqual(a["damage_last"], 8)
        self.assertEqual(a["loss_streak"], 1)
        c.feed(f"{GS}TAG_CHANGE {self.HERO} tag=ARMOR value=4")
        c.actions.turn = 3
        a = c.analyze()
        self.assertEqual(a["damage_last"], 8)
        self.assertEqual(a["loss_streak"], 2)  # two consecutive real losses

    def test_armor_gain_is_not_a_loss(self):
        c = LiveCoach()
        c.friendly = 7
        c.hero_card = "BG30_HERO_100"
        c.account = "TestAccount"
        c.playable = {}
        c.feed(f"{GS}TAG_CHANGE {self.HERO} tag=HEALTH value=30")
        c.feed(f"{GS}TAG_CHANGE {self.HERO} tag=ARMOR value=4")
        c.actions.turn = 1
        c.analyze()
        c.feed(f"{GS}TAG_CHANGE {self.HERO} tag=ARMOR value=8")
        c.actions.turn = 2
        a = c.analyze()
        self.assertIsNone(a["damage_last"])  # armor went UP: not a loss
        self.assertEqual(a["loss_streak"], 0)


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


class TestBuyStep(unittest.TestCase):
    def _analysis(self, gold, budget_card_first=True):
        from value import top_move, _load_card_db
        db = _load_card_db()
        priced = [(cid, v["tier"]) for cid, v in db.items() if v.get("tier")]
        hi = next(cid for cid, t in priced if t >= 3)
        lo = next(cid for cid, t in priced if t == 1)
        a = {"tier": 2, "gold": gold, "level_cost": 5, "board": [],
             "shop_rank": [(hi, 9.0), (lo, 4.0)], "buy_this": hi,
             "playable_comps": {}, "choice": None, "target_comp": None,
             "sell_rank": []}
        return a, hi, lo, top_move

    def test_unaffordable_headline_walks_down(self):
        """Gold 6, level 5, headline costs 3: the plan buys the affordable
        card, and buy_step_card says so (the UI's Buy box must agree)."""
        a, hi, lo, top_move = self._analysis(6)
        tm = top_move(a)
        self.assertEqual(a["buy_step_card"], lo)
        self.assertIn("Buy", tm)
        self.assertNotIn("roll —", tm)

    def test_nothing_affordable_after_level_is_silence(self):
        """Gold 5, level 5 (budget 0): the level spent everything — no
        phantom "roll" with 0 gold (a roll costs 1 too)."""
        a, hi, lo, top_move = self._analysis(5)
        tm = top_move(a)
        self.assertIsNone(a["buy_step_card"])
        self.assertIsNone(a["buy_step_roll"])
        self.assertNotIn("roll", tm)
        self.assertTrue(tm.startswith("1. LEVEL"), tm)

    def test_impossible_level_not_recommended(self):
        """Gold 6 with the level costing 7: the upgrade is out of reach this
        turn, so it is not in the plan at all (2026-09-04: the plan led with
        the upgrade and buried the buy as step 2)."""
        a, hi, lo, top_move = self._analysis(6)
        a["level_cost"] = 7
        tm = top_move(a)
        self.assertTrue(tm.startswith(f"1. Buy "), tm)
        self.assertNotIn("LEVEL", tm)

    def test_zero_gold_passes(self):
        """Gold 0, nothing affordable, level out of reach: pass, not a
        phantom roll or an impossible upgrade."""
        a, hi, lo, top_move = self._analysis(0)
        tm = top_move(a)
        self.assertIn("pass — out of gold", tm)
        self.assertNotIn("roll", tm)
        self.assertNotIn("LEVEL", tm)
        self.assertIsNone(a["buy_step_card"])


class TestBanGate(unittest.TestCase):
    def test_partial_pool_reveal_fails_open(self):
        """One tribe's pool minions seen (allowed=[Beast]) is NOT ban info —
        the old code froze 9 banned tribes in the UI for a whole game."""
        from unittest import mock
        from live_coach import LiveCoach
        c = LiveCoach()
        c._comps = {}
        c._card_races = {}
        c._seed = "1"
        c.cur_lines = ["x"]
        fake = [{"seed": "1", "allowed": ["Beast"], "banned": [
            "Demon", "Dragon", "Elemental", "Mech", "Murloc", "Naga",
            "Pirate", "Quilboar", "Undead"]}]
        with mock.patch("live_coach.bans_from_log", return_value=fake):
            c._refresh_bans()
        self.assertIsNone(c.allowed)
        self.assertFalse(c._bans_ready)  # keeps retrying on later analyzes

    def test_complete_ban_set_locks(self):
        from unittest import mock
        from live_coach import LiveCoach
        c = LiveCoach()
        c._comps = {}
        c._card_races = {}
        c._seed = "1"
        c.cur_lines = ["x"]
        allowed = ["Beast", "Mech", "Murloc", "Naga", "Quilboar"]
        fake = [{"seed": "1", "allowed": allowed, "banned": ["x"] * 5}]
        with mock.patch("live_coach.bans_from_log", return_value=fake):
            c._refresh_bans()
        self.assertEqual(c.allowed, allowed)
        self.assertTrue(c._bans_ready)


class TestRenderJsonComps(unittest.TestCase):
    def test_playable_comps_dict_becomes_name_list(self):
        """The analysis carries a slug->comp dict; the UI reads a["comps"] as
        a name list — the box sat on "—" forever without this mapping."""
        from coach_ui import render_json
        analysis = {"board": [], "sell_rank": [], "shop_rank": [],
                    "playable_comps": {
                        "beasts-x": {"name": "Beasts - X", "meta_tier": "A"},
                        "mechs-y": {"name": "Mechs - Y", "meta_tier": "S"}}}
        a = render_json(analysis)
        self.assertEqual(a["comps"], ["Mechs - Y", "Beasts - X"])
        self.assertEqual(a["buy_step_card"], None)

    def test_sell_rank_groups_duplicates(self):
        """Two board copies of one card showed as two confusing rows; they
        group with a ×N badge and the sell-first instance's score."""
        from coach_ui import render_json
        analysis = {"board": [], "shop_rank": [], "playable_comps": {},
                    "sell_rank": [("BG33_140", 5.0), ("BG33_886", 9.0),
                                  ("BG33_140", 2.0)]}
        a = render_json(analysis)
        rows = a["sell_rank"]
        self.assertEqual([r["card"] for r in rows], ["BG33_140", "BG33_886"])
        self.assertEqual(rows[0]["n"], 2)
        self.assertEqual(rows[0]["score"], 2)

    def test_shop_rows_carry_tavern_prices(self):
        """Prices are invisible in the UI, so a wrong one ("thinks minions
        cost 1 gold") was undiagnosable. Minion = tier, spell = cost."""
        from coach_ui import render_json
        analysis = {"board": [], "sell_rank": [], "playable_comps": {},
                    "shop_rank": [("BG30_123", 5.0), ("BG28_504", 3.0)]}
        a = render_json(analysis)
        by_card = {r["card"]: r for r in a["shop_rank"]}
        # BG30_123 Fearless Foodie = tier-3 minion (healed from the log's
        # TECH_LEVEL after a patch moved it); BG28_504 Recruit a Trainee =
        # 2g spell (spell DB, not the minion pool)
        self.assertEqual(by_card["BG30_123"]["price"], 3)
        self.assertEqual(by_card["BG28_504"]["price"], 2)

    def test_unpriced_cards_carry_no_price(self):
        from coach_ui import render_json
        analysis = {"board": [], "sell_rank": [], "playable_comps": {},
                    "shop_rank": [("NOT_IN_ANY_DB", 1.0)]}
        a = render_json(analysis)
        self.assertIsNone(a["shop_rank"][0]["price"])


if __name__ == "__main__":
    unittest.main()