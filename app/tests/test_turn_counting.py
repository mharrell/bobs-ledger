"""Golden tests for turn counting: PowerTaskList STEP duplicates must not spawn
spurious turns, and the first MAIN_ACTION is a real Battlegrounds buy phase."""
import os
import sys
import unittest

# app/ is where the code lives; deriving it from this file
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed

from live_coach import LiveCoach, _LiveActions
from player_actions import parse_actions
from tests.test_shop_parsing import opt_block

GS = "D 21:17:13.7844972 GameState.DebugPrintPower() - "
PTL = "D 21:18:00.0000000 PowerTaskList.DebugPrintPower() - "

STEP = ("TAG_CHANGE Entity=GameEntity tag=STEP value={} ")

BUY = (
    "BLOCK_START BlockType=PLAY Entity=[entityName=Drag To Buy id=290 zone=PLAY "
    "zonePos=0 cardId=TB_BaconShop_DragBuy player=1] Target=[entityName=Tusked "
    "Camper id=289 zone=PLAY zonePos=3 cardId=BG33_886 player=9]"
)


class TestParseActions(unittest.TestCase):
    def test_ptl_step_duplicates_do_not_spawn_turns(self):
        """GameState and PowerTaskList both log tag=STEP; the PTL MAIN_ACTION
        copy arrives after GS MAIN_END. Real symptom: 16 reported turns for ~10
        buy phases."""
        lines = [
            GS + STEP.format("MAIN_ACTION"),
            GS + BUY,
            GS + STEP.format("MAIN_END"),
            PTL + STEP.format("MAIN_ACTION"),   # the spurious one
            PTL + STEP.format("MAIN_END"),
            GS + STEP.format("MAIN_ACTION"),    # turn 2
            GS + BUY,
            GS + STEP.format("MAIN_END"),
            PTL + STEP.format("MAIN_ACTION"),
            PTL + STEP.format("MAIN_END"),
        ]
        turns = parse_actions(lines, friendly=1)
        self.assertEqual(len(turns), 2, [t["turn"] for t in turns])
        self.assertEqual([t["turn"] for t in turns], [1, 2])

    def test_first_main_action_is_a_real_buy_phase(self):
        """In Battlegrounds the first MAIN_ACTION has a full shop; a turn-1 buy
        must be recorded (the old parser dropped it as 'setup')."""
        lines = [GS + STEP.format("MAIN_ACTION"), GS + BUY]
        turns = parse_actions(lines, friendly=1)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["buys"], ["BG33_886"])

    def test_turn_1_pass_is_kept_numbering_stable(self):
        lines = [GS + STEP.format("MAIN_ACTION"), GS + STEP.format("MAIN_END"),
                 GS + STEP.format("MAIN_ACTION"), GS + BUY]
        turns = parse_actions(lines, friendly=1)
        # Only the acted-in phase is kept (has_action filter), renumbered 1.
        self.assertEqual([t["turn"] for t in turns], [1])
        self.assertEqual(turns[0]["buys"], ["BG33_886"])


class TestLiveActions(unittest.TestCase):
    def test_ptl_steps_ignored_and_first_turn_counted(self):
        a = _LiveActions()
        for line in [GS + STEP.format("MAIN_ACTION"),
                     PTL + STEP.format("MAIN_ACTION"),
                     GS + STEP.format("MAIN_END"),
                     PTL + STEP.format("MAIN_ACTION"),
                     PTL + STEP.format("MAIN_END"),
                     GS + STEP.format("MAIN_ACTION")]:
            a.feed(line)
        # Neither pair opened a turn on the bare MAIN_ACTION: the first
        # closed unpromoted (a combat's step pair), the second is still
        # waiting for its shop offers.
        self.assertEqual(a.turn, 0)
        a.open_buy_phase()   # the shop table filled during the second phase
        self.assertEqual(a.turn, 1)

    def test_full_game_shape(self):
        """Three buy phases, each followed by a combat's own step pair ->
        3 turns, not 6: the fight's MAIN_ACTION..MAIN_END pair opens none."""
        a = _LiveActions()
        for t in range(3):
            a.feed(GS + STEP.format("MAIN_ACTION"))
            a.feed(PTL + STEP.format("MAIN_ACTION"))
            a.open_buy_phase()                  # the shop offers arrived
            a.feed(GS + STEP.format("MAIN_END"))
            a.feed(PTL + STEP.format("MAIN_END"))
            a.feed(PTL + STEP.format("MAIN_ACTION"))
            # The fight: its own MAIN_ACTION..MAIN_END pair, no shop offers.
            a.feed(GS + STEP.format("MAIN_ACTION"))
            a.feed(GS + STEP.format("MAIN_END"))
        self.assertEqual(a.turn, 3)

    def test_main_end_without_shop_cancels_the_pending_turn(self):
        """A MAIN_ACTION..MAIN_END pair that never saw an offer (the measured
        2026-10-07 combat pairs: 56 ms apart, ATTACK blocks inside) must not
        consume a turn number — the replay viewer rendered those pairs as
        shop turns with no gold and no board."""
        a = _LiveActions()
        a.feed(GS + STEP.format("MAIN_ACTION"))
        a.open_buy_phase()
        a.feed(GS + STEP.format("MAIN_END"))
        a.feed(GS + STEP.format("MAIN_ACTION"))   # the fight's pair opens
        self.assertEqual(a.turn, 1)
        self.assertTrue(a.pending_buy)            # waiting for proof of a shop
        a.feed(GS + STEP.format("MAIN_END"))      # ...and closes, still no shop
        self.assertEqual(a.turn, 1)
        self.assertFalse(a.pending_buy)
        # The next real shop is turn 2, not 3.
        a.feed(GS + STEP.format("MAIN_ACTION"))
        a.open_buy_phase()
        self.assertEqual(a.turn, 2)


class TestCombatStepPair(unittest.TestCase):
    """Battlegrounds runs some fights inside their own MAIN_ACTION..MAIN_END
    step pair — measured 2026-10-07: a pair 56 ms apart holding 6947 lines of
    ATTACK/DEATHS blocks and never a shop offer. Through the old counter
    every such pair stole a turn number and its fight's drain snapshots were
    stamped "buy" into a phantom bucket, which the replay viewer rendered as
    a shop turn: gold "—", "played 0 cards", ENDED WITH "—" over a board the
    player did have. Four phantoms sat in that one game; every game's
    round-1 fight was one."""

    def _coach(self):
        c = LiveCoach()
        c.friendly = 3
        c.hero_card = "BG30_HERO_100"
        c.account = "TestAccount"
        c.playable = {}
        return c

    def _shop(self, c, n):
        c.feed(f"{GS}Entity=GameEntity tag=STEP value=MAIN_ACTION")
        for line in opt_block(n, [("River Skipper", "BG33_140", 15)]):
            c.feed(line)
        c.tavern_offers()   # the poll that proves the shop and opens the turn

    MINE = ("Entity=[entityName=M id=77 zone=PLAY zonePos=3 "
            "cardId=BG25_008 player=3]")

    def test_pair_opens_no_turn_and_stamps_nothing_buy(self):
        c = self._coach()
        self._shop(c, 1)
        self.assertEqual(c.actions.turn, 1)
        c.gs.cardtype[77] = "MINION"
        # The shop: a minion played from hand snapshots the board (buy).
        c.feed(f"{GS}TAG_CHANGE {self.MINE} tag=ZONE value=HAND")
        c.feed(f"{GS}TAG_CHANGE {self.MINE} tag=ZONE value=PLAY")
        c.feed(f"{GS}Entity=GameEntity tag=STEP value=MAIN_END")
        # The fight: its own step pair, ATTACK blocks inside, no offers —
        # and a death, which is a snapshot the fight's drain produces.
        c.feed(f"{GS}Entity=GameEntity tag=STEP value=MAIN_ACTION")
        c.feed(f"{GS}TAG_CHANGE {self.MINE} tag=ZONE value=REMOVEDFROMGAME")
        c.feed(f"{GS}Entity=GameEntity tag=STEP value=MAIN_END")
        self.assertEqual(c.actions.turn, 1, "the fight's pair steals no turn")
        self.assertEqual(sorted(c._snap_by_turn), [1], "no phantom bucket")
        self.assertEqual([s["phase"] for s in c._snap_by_turn[1]],
                         ["buy", "combat"],
                         "the drain stamps combat into the fight's own turn")

    def test_pair_does_not_steal_the_next_shop_number(self):
        c = self._coach()
        self._shop(c, 1)
        c.feed(f"{GS}Entity=GameEntity tag=STEP value=MAIN_END")
        c.feed(f"{GS}Entity=GameEntity tag=STEP value=MAIN_ACTION")  # the fight
        c.feed(f"{GS}Entity=GameEntity tag=STEP value=MAIN_END")
        self._shop(c, 2)
        self.assertEqual(c.actions.turn, 2)
        self.assertEqual(c._phase, "buy")

    def test_pair_main_end_writes_no_pairing(self):
        """The buy-phase MAIN_END writes the fight pairing; the combat pair's
        MAIN_END must not (it would re-key the announced opponent against a
        turn that never shopped)."""
        c = self._coach()
        c.feed(f"{GS}TAG_CHANGE Entity=[entityName=H id=9 zone=PLAY "
               f"zonePos=1 cardId=BG30_HERO_100 player=3] "
               f"tag=NEXT_OPPONENT_PLAYER_ID value=4")
        self._shop(c, 1)
        c.feed(f"{GS}Entity=GameEntity tag=STEP value=MAIN_END")
        self.assertEqual(c._pairing, {1: 4})
        c.feed(f"{GS}Entity=GameEntity tag=STEP value=MAIN_ACTION")  # the fight
        c.feed(f"{GS}Entity=GameEntity tag=STEP value=MAIN_END")
        self.assertEqual(c._pairing, {1: 4}, "the pair's MAIN_END writes none")


if __name__ == "__main__":
    unittest.main()