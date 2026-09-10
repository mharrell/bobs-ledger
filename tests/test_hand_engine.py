"""Hand-charge kits, sell reasons, and the end-of-phase sell regression.

From the 2026-09-10 Cariel replay (placement 5): two Bream Counters charged
to 78/78 in hand while the Diremuck Forager deploy engine was gone — one
Forager died in combat, the second was SOLD at the very end of a buy phase,
and that sell never parsed (it prints as one TAG_CHANGE whose entity bracket
still carries the OLD zone; no later line re-prints it before MAIN_END). The
coach then said "Play Bream Counter x2" with no hold/deploy awareness.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CHARGER = "BG26_137"     # Bream Counter (+6/+6 per Murloc played, in hand)
DEPLOYER = "BG27_556"    # Diremuck Forager (start-of-combat hand summon)
FILLER = "BG33_140"


def _board(n, deployer=True):
    """n board slots, optionally containing the deployer."""
    minions = []
    if deployer:
        minions.append({"card": DEPLOYER, "atk": 10, "health": 10})
    while len(minions) < n:
        minions.append({"card": FILLER, "atk": 1, "health": 1})
    return minions


class TestSellParsesAtPhaseEnd(unittest.TestCase):
    """The sell that killed the engine showed as "(pass / no actions)" in
    the replay review. The real log shape (entity 9978, 11:41:52): a
    Drag To Sell BLOCK is the only action marker — the zone prints as
    TAG_CHANGE lines whose brackets stay stale, and a summoned minion
    (SETASIDE->PLAY, never in hand) isn't in the `played` set the old
    zone-transition inference required anyway."""

    # Verbatim shape from the 2026-09-10 11:23 log (ids preserved).
    SELL_BLOCK = ("D 11:41:52.1298694 GameState.DebugPrintPower() - "
                  "BLOCK_START BlockType=PLAY Entity=[entityName=Drag To Sell"
                  " id=11015 zone=PLAY zonePos=0 cardId=TB_BaconShop_DragSell"
                  " player=1] EffectCardId=System.Collections.Generic.List`1"
                  "[System.String] EffectIndex=0 Target=[entityName=Diremuck"
                  " Forager id=9978 zone=PLAY zonePos=3 cardId=BG27_556"
                  " player=1]\n")
    LINES = [
        "D 11:41:01 GameState.DebugPrintPower() - Entity=GameEntity tag=STEP value=MAIN_ACTION\n",
        "D 11:41:47 GameState.DebugPrintPower() -     TAG_CHANGE Entity=[entityName=Diremuck Forager id=9978 zone=PLAY zonePos=1 cardId=BG27_556 player=1] tag=ZONE_POSITION value=2\n",
        SELL_BLOCK,
        "D 11:41:52 GameState.DebugPrintPower() -     TAG_CHANGE Entity=[entityName=Diremuck Forager id=9978 zone=PLAY zonePos=3 cardId=BG27_556 player=1] tag=ZONE value=SETASIDE\n",
        "D 11:41:52 GameState.DebugPrintPower() - Entity=GameEntity tag=STEP value=MAIN_END\n",
    ]

    def test_end_of_phase_drag_sell_counts_once(self):
        from player_actions import parse_actions
        turns = parse_actions(self.LINES, friendly=1)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["sells"], [DEPLOYER])
        self.assertEqual(turns[0]["plays"], [])

    def test_mid_phase_sell_not_double_counted(self):
        # A sold entity's later zone prints must not count it a second time.
        lines = self.LINES[:-1] + [
            "D 11:41:53 GameState.DebugPrintPower() -     TAG_CHANGE Entity=[entityName=Diremuck Forager id=9978 zone=SETASIDE zonePos=0 cardId=BG27_556 player=1] tag=ZONE value=GRAVEYARD\n",
            "D 11:41:54 GameState.DebugPrintPower() - Entity=GameEntity tag=STEP value=MAIN_END\n",
        ]
        from player_actions import parse_actions
        turns = parse_actions(lines, friendly=1)
        self.assertEqual([t["sells"] for t in turns], [[DEPLOYER]])


class TestHandChargeKit(unittest.TestCase):
    def _hand(self):
        return [{"card": CHARGER, "atk": 78, "health": 78}]

    def test_hold_while_deployer_lives(self):
        from value import hand_plan
        steps = hand_plan(self._hand(), _board(6))
        s = steps[0]
        self.assertEqual(s["verb"], "hold")
        self.assertIn("summons", s["why"])
        self.assertIn("keep a board slot free", s["why"])

    def test_hold_with_full_board_names_the_blocker(self):
        from value import hand_plan
        steps = hand_plan(self._hand(), _board(7))
        self.assertEqual(steps[0]["verb"], "hold")
        self.assertIn("SELL a body", steps[0]["why"])

    def test_play_once_the_deployer_is_gone(self):
        from value import hand_plan
        steps = hand_plan(self._hand(), _board(6, deployer=False))
        self.assertEqual(steps[0]["verb"], "play")
        self.assertIn("no Diremuck Forager on board", steps[0]["why"])

    def test_golden_pairing_still_wins(self):
        from value import hand_plan
        board = _board(6) + [{"card": CHARGER, "atk": 1, "health": 1},
                             {"card": CHARGER, "atk": 1, "health": 1}]
        steps = hand_plan(self._hand(), board)
        self.assertIn("triples golden", steps[0]["why"] or "")

    def test_hand_engine_status(self):
        from value import hand_engine
        e = hand_engine(self._hand(), _board(6))
        self.assertTrue(e["on_board"] and e["space"] and e["charging"] == 1)
        e = hand_engine(self._hand(), _board(7))
        self.assertFalse(e["space"])
        e = hand_engine(self._hand(), _board(6, deployer=False))
        self.assertFalse(e["on_board"])
        self.assertIsNone(hand_engine([], _board(6)))


class TestSellReason(unittest.TestCase):
    def test_categories(self):
        from value import sell_reason
        comp = {"tribe": "Murloc"}
        core = {DEPLOYER}
        addons = {"BG35_141"}
        stats = {"card": FILLER, "atk": 30, "health": 30, "tribe": "Beast"}
        self.assertEqual(sell_reason({"card": DEPLOYER}, {}, core=core),
                         "comp core")
        self.assertEqual(sell_reason({"card": "BG35_141"}, {}, core=core,
                                     addons=addons), "comp addon")
        self.assertEqual(sell_reason({"card": FILLER, "tribe": "Demon"}, {},
                                     banned_tribes={"Demon"}),
                         "banned tribe — can't grow")
        # A big body in the WRONG build reads as off-comp, not just stats;
        # the same stats with no tribe signal read as stats-only.
        self.assertEqual(sell_reason(stats, {}, comp=comp), "off-comp body")
        self.assertEqual(sell_reason(dict(stats, tribe=None), {}, comp=comp),
                         "stats only — no comp role")
        self.assertEqual(sell_reason({"card": FILLER, "atk": 1, "health": 1},
                                     {}, comp=comp),
                         "filler")  # BG33_140 is a Murloc: on-tribe vanilla
        self.assertEqual(sell_reason({"card": "BG26_135", "atk": 1,
                                      "health": 1, "tribe": "Beast"},
                                     {}, comp=comp),
                         "off-comp filler")


class TestShopWantsTheDeployer(unittest.TestCase):
    def test_deployer_boosted_when_charger_in_hand(self):
        from value import shop_ranking
        board = _board(6, deployer=False)
        with_hand = dict(shop_ranking([DEPLOYER], {}, board_minions=board,
                                      hand=[{"card": CHARGER}]))
        without = dict(shop_ranking([DEPLOYER], {}, board_minions=board))
        self.assertGreater(with_hand[DEPLOYER], without[DEPLOYER])


class TestRenderCarriesEngineAndReasons(unittest.TestCase):
    def test_render_json(self):
        from coach_ui import render_json
        analysis = {"board": _board(7), "sell_rank": [(FILLER, 5.0)],
                    "shop_rank": [], "hand": [{"card": CHARGER}],
                    "playable_comps": {}, "banned": ["Demon"]}
        a = render_json(analysis)
        self.assertTrue(a["engine"]["on_board"])
        self.assertFalse(a["engine"]["space"])
        self.assertEqual(a["engine"]["charging"], 1)
        self.assertTrue(a["sell_rank"][0]["why"])


if __name__ == "__main__":
    unittest.main()
