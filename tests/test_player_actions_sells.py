"""Sell-artifact regression: playing a MAGNETIC minion onto a mech merges it
into the host — the played entity leaves PLAY (SETASIDE/GRAVEYARD) with no
Drag To Sell block. The zone-inference backstop used to count that as a sell
(the 2026-09-16 evening t8 phantom: "buy Prosthetic Hand + Annoy-o-Module;
sell both; play both"). Magnetic plays are not sells; real sells still are."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from player_actions import parse_actions

GS = "D 21:17:13.7844972 GameState.DebugPrintPower() - "
STEP = "TAG_CHANGE Entity=GameEntity tag=STEP value=MAIN_ACTION"

HAND = GS + ("TAG_CHANGE Entity=[entityName={n} id={i} zone=HAND zonePos=0 "
             "cardId={c} player=1] tag=ZONE value=HAND")
PLAY = GS + ("TAG_CHANGE Entity=[entityName={n} id={i} zone=PLAY zonePos=1 "
             "cardId={c} player=1] tag=ZONE value=PLAY")
LEAVE = GS + ("TAG_CHANGE Entity=[entityName={n} id={i} zone={to} zonePos=0 "
              "cardId={c} player=1] tag=ZONE value={to}")
BUY = GS + ("BLOCK_START BlockType=PLAY Entity=[entityName=Drag To Buy id=290 "
            "zone=PLAY zonePos=0 cardId=TB_BaconShop_DragBuy player=1] "
            "Target=[entityName={n} id=0 zone=PLAY zonePos=0 cardId={c} player=9]")
DRAG_SELL = GS + ("BLOCK_START BlockType=PLAY Entity=[entityName=Drag To Sell "
                  "id=301 zone=PLAY zonePos=0 cardId=TB_BaconShop_DragSell "
                  "player=1] Target=[entityName={n} id={i} zone=PLAY zonePos=1 "
                  "cardId={c} player=1]")


def buy_play_leave(cid, name, eid, to):
    """Buy -> into hand -> played onto the board -> leaves the board."""
    return [BUY.format(n=name, c=cid),
            HAND.format(n=name, i=eid, c=cid),
            PLAY.format(n=name, i=eid, c=cid),
            LEAVE.format(n=name, i=eid, c=cid, to=to)]


class TestMagneticPlaysAreNotSells(unittest.TestCase):
    def test_magnetic_attach_is_not_a_sell(self):
        """Prosthetic Hand (BG_DEEP_015, MAGNETIC) played onto a mech leaves
        PLAY into SETASIDE — an attach, not a sell."""
        lines = [GS + STEP] + buy_play_leave(
            "BG_DEEP_015", "Prosthetic Hand", 5, "SETASIDE")
        turns = parse_actions(lines, friendly=1)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["plays"], ["BG_DEEP_015"])
        self.assertEqual(turns[0]["sells"], [])

    def test_non_magnetic_leaver_still_counts(self):
        """The backstop must keep catching real sells: a played non-magnetic
        minion leaving PLAY into GRAVEYARD during the shop phase."""
        lines = [GS + STEP] + buy_play_leave(
            "BG33_886", "Tusked Camper", 6, "GRAVEYARD")
        turns = parse_actions(lines, friendly=1)
        self.assertEqual(turns[0]["plays"], ["BG33_886"])
        self.assertEqual(turns[0]["sells"], ["BG33_886"])

    def test_magnetic_sold_via_drag_to_sell_still_counts(self):
        """A magnetic minion actually sold still goes through the Drag To Sell
        block (the primary detector) — and the zone backstop must not
        double-count it."""
        lines = [GS + STEP] + buy_play_leave(
            "BG_BOT_911", "Annoy-o-Module", 7, "SETASIDE")
        lines.insert(1, DRAG_SELL.format(n="Annoy-o-Module", i=7,
                                         c="BG_BOT_911"))
        turns = parse_actions(lines, friendly=1)
        self.assertEqual(turns[0]["plays"], ["BG_BOT_911"])
        self.assertEqual(turns[0]["sells"], ["BG_BOT_911"])


if __name__ == "__main__":
    unittest.main()
