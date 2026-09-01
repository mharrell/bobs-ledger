"""Golden tests for turn counting: PowerTaskList STEP duplicates must not spawn
spurious turns, and the first MAIN_ACTION is a real Battlegrounds buy phase."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live_coach import _LiveActions
from player_actions import parse_actions

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
        self.assertEqual(a.turn, 2)

    def test_full_game_shape(self):
        """Three buy phases + interleaved PTL copies -> 3 turns, not 5-6."""
        a = _LiveActions()
        for t in range(3):
            a.feed(GS + STEP.format("MAIN_ACTION"))
            a.feed(PTL + STEP.format("MAIN_ACTION"))
            a.feed(GS + STEP.format("MAIN_END"))
            a.feed(PTL + STEP.format("MAIN_END"))
            a.feed(PTL + STEP.format("MAIN_ACTION"))
        self.assertEqual(a.turn, 3)


if __name__ == "__main__":
    unittest.main()