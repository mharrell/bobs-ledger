"""The zone layer: the shop must stay correct between mid-phase actions.

The options-block parse only commits at phase start: during a roll/buy storm
the client barely re-prints options and the next Refresh/Drag To Buy resets
the buffered block before its deferred commit fires, so between actions the
coach's shop was blank (the 2026-09-10 game: the lobby's only Felfire Conjurer
sat in the shop at 23:27:30 — roll 4 of 9 — invisible to the coach). Entity
writes tell the truth instead: HAS_DRAG_TO_BUY=1 marks an offer (minions and
tavern spells), ZONE REMOVEDFROMGAME / HAND prunes it.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live_coach import LiveCoach
from tests.test_shop_parsing import opt_block

GS = "D 23:27:30.3874527 GameState.DebugPrintPower() - "


def _created(eid, cid, name="Some Minion"):
    """FULL_ENTITY create + controller write, as the log emits a new offer."""
    return [
        GS + f"FULL_ENTITY - Creating ID={eid} CardID={cid}",
        GS + f"TAG_CHANGE Entity=[entityName={name} id={eid} zone=SETASIDE "
             f"zonePos=0 cardId={cid} player=1] tag=CONTROLLER value=15",
    ]


class TestZoneShop(unittest.TestCase):
    def _coach(self):
        c = LiveCoach()
        c.friendly = 7
        return c

    def _phase_start_shop(self, c, offers):
        for line in ["x tag=STEP value=MAIN_ACTION"] + opt_block(1, offers):
            c.feed(line)
        return c

    def test_roll_reveals_offer_without_options_block(self):
        """A mid-phase re-roll: the new generation's entity writes land with
        NO options block — the shop must still update (the Felfire case)."""
        c = self._phase_start_shop(
            self._coach(), [("Old Offer", "BG33_140", 15)])
        # the roll: reset, old offer removed, new offer created — no block
        c.feed("x BlockType=PLAY Entity=[entityName=Refresh "
               "cardId=TB_BaconShop_8p_Reroll_Button player=7] Target=")
        c.feed(GS + "TAG_CHANGE Entity=[entityName=Old Offer id=100 "
                    "zone=PLAY zonePos=1 cardId=BG33_140 player=15] "
                    "tag=ZONE value=REMOVEDFROMGAME")
        for line in _created(200, "BG32_821", "Felfire Conjurer"):
            c.feed(line)
        c.feed(GS + "TAG_CHANGE Entity=200 tag=HAS_DRAG_TO_BUY value=1")
        self.assertEqual(c.tavern_offers(), ["BG32_821"])

    def test_buy_midphase_keeps_remaining_offers(self):
        """A buy used to blank the shop until the next options block (which
        mid-phase never commits) — the rest must stay listed."""
        c = self._phase_start_shop(self._coach(), [
            ("River Skipper", "BG33_140", 15),
            ("Tusked Camper", "BG33_886", 15)])
        c.feed("x BlockType=PLAY Entity=[entityName=Drag To Buy id=120 "
               "cardId=TB_BaconShop_DragBuy player=7] "
               "Target=[entityName=River Skipper id=100 zone=PLAY zonePos=1 "
               "cardId=BG33_140 player=15] SubOption=-1")
        self.assertEqual(c.tavern_offers(), ["BG33_886"])

    def test_removed_write_prunes(self):
        """A re-rolled-away offer leaves via ZONE REMOVEDFROMGAME."""
        c = self._phase_start_shop(self._coach(), [
            ("River Skipper", "BG33_140", 15),
            ("Tusked Camper", "BG33_886", 15)])
        c.feed(GS + "TAG_CHANGE Entity=[entityName=River Skipper id=100 "
                    "zone=PLAY zonePos=1 cardId=BG33_140 player=15] "
                    "tag=ZONE value=REMOVEDFROMGAME")
        self.assertEqual(c.tavern_offers(), ["BG33_886"])

    def test_tavern_spell_offer_tracked(self):
        """Tavern spells carry HAS_DRAG_TO_BUY too (BG28_888 = Misplaced Tea
        Set — BG-form spell id, same gate as the options path)."""
        c = self._phase_start_shop(self._coach(), [("Tusked Camper",
                                                    "BG33_886", 15)])
        for line in _created(201, "BG28_888", "Misplaced Tea Set"):
            c.feed(line)
        c.feed(GS + "TAG_CHANGE Entity=201 tag=HAS_DRAG_TO_BUY value=1")
        self.assertIn("BG28_888", c.tavern_offers())

    def test_sell_options_never_become_offers(self):
        """Storm blocks list the player's own minions (sell options) and
        spell targets as options entries — the mirror must not let them
        pose as offers after a later zone rebuild."""
        c = self._phase_start_shop(self._coach(), [
            ("My Board Minion", "BG33_444", 7),     # sell option
            ("River Skipper", "BG33_140", 15),      # real offer
            ("Spell Target", "BG23_007", 7),        # target pollution
        ])
        c.feed("x BlockType=PLAY Entity=[entityName=Refresh "
               "cardId=TB_BaconShop_8p_Reroll_Button player=7] Target=")
        offers = c.tavern_offers()
        self.assertIn("BG33_140", offers)
        self.assertNotIn("BG33_444", offers)
        self.assertNotIn("BG23_007", offers)

    def test_phase_start_rebuilds_fresh_table(self):
        """A new buy phase clears the zone table; the phase's options block
        re-mirrors the offers (frozen ones included — they get no new
        HAS_DRAG_TO_BUY write)."""
        c = self._phase_start_shop(self._coach(), [("Old Offer", "BG33_140",
                                                    15)])
        for line in (["x tag=STEP value=MAIN_END"]
                     + ["x tag=STEP value=MAIN_ACTION"]
                     + opt_block(2, [("Frozen Offer", "BG23_007", 15)])):
            c.feed(line)
        self.assertEqual(c.tavern_offers(), ["BG23_007"])

    def test_midphase_offer_changes_fingerprint(self):
        """The monitor re-advises when the decision state changes — a mid-roll
        offer landing must move the fingerprint (affordability/core alerts)."""
        c = self._phase_start_shop(self._coach(), [("Old Offer", "BG33_140",
                                                    15)])
        before = c.state_fingerprint()
        c.feed("x BlockType=PLAY Entity=[entityName=Refresh "
               "cardId=TB_BaconShop_8p_Reroll_Button player=7] Target=")
        c.feed(GS + "TAG_CHANGE Entity=[entityName=Old Offer id=100 "
                    "zone=PLAY zonePos=1 cardId=BG33_140 player=15] "
                    "tag=ZONE value=REMOVEDFROMGAME")
        for line in _created(200, "BG32_821", "Felfire Conjurer"):
            c.feed(line)
        c.feed(GS + "TAG_CHANGE Entity=200 tag=HAS_DRAG_TO_BUY value=1")
        self.assertNotEqual(before, c.state_fingerprint())
        self.assertEqual(c.tavern_offers(), ["BG32_821"])

    def test_shop_sightings_recorded(self):
        """Every shop generation feeds the hunt's evidence
        (value._hunt_check): minion cid -> turn last offered, recorded at
        feed time so the per-phase replay harness sees the full history.
        Offered-then-bought cards keep their sighting (they DID show)."""
        c = self._coach()
        # a real GameState MAIN_ACTION line: it's what increments the turn
        # counter the sightings are keyed by (the "x ..." fixture lines of
        # the other tests don't).
        c.feed(GS + "Entity=GameEntity tag=STEP value=MAIN_ACTION")
        for line in opt_block(1, [("River Skipper", "BG33_140", 15),
                                  ("Tusked Camper", "BG33_886", 15)]):
            c.feed(line)
        self.assertCountEqual(c.tavern_offers(), ["BG33_140", "BG33_886"])
        self.assertEqual(c._shop_seen, {"BG33_140": 1, "BG33_886": 1})
        # a mid-phase roll: new generation, same turn, new eid -> recorded
        c.feed("x BlockType=PLAY Entity=[entityName=Refresh "
               "cardId=TB_BaconShop_8p_Reroll_Button player=7] Target=")
        c.feed(GS + "TAG_CHANGE Entity=[entityName=River Skipper id=100 "
                    "zone=PLAY zonePos=1 cardId=BG33_140 player=15] "
                    "tag=ZONE value=REMOVEDFROMGAME")
        for line in _created(200, "BG32_821", "Felfire Conjurer"):
            c.feed(line)
        c.feed(GS + "TAG_CHANGE Entity=200 tag=HAS_DRAG_TO_BUY value=1")
        self.assertEqual(c._shop_seen["BG32_821"], 1)


if __name__ == "__main__":
    unittest.main()
