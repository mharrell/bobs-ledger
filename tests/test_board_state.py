"""Golden tests for board_state.py against hand-built Power.log excerpts.

Fixtures reproduce real-log quirks verified in the 2026-08-29 session log:
- PowerTaskList re-describes created entities as `FULL_ENTITY - Updating [...]`;
  the block's tag lines must land on THAT entity, not the previous Creating one.
- Golden minions (`_G`) are real board minions.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from board_state import GameState

GS = "D 21:17:13.7844972 GameState.DebugPrintPower() - "
PTL = "D 21:18:00.0000000 PowerTaskList.DebugPrintPower() - "


def creating(eid, cid):
    return [f"{GS}    FULL_ENTITY - Creating ID={eid} CardID={cid}"]


def tags(prefix, eid, atk, health, zone="PLAY", player=1, cid=""):
    """A Creating/Updating block body. The trailing TAG_CHANGE attributes the
    entity to its player the way real GS TAG_CHANGE lines do (ENTITY_TAG
    carries the full bracket incl. player)."""
    return [
        f"{prefix}        tag=CONTROLLER value={player}",
        f"{prefix}        tag=ZONE value={zone}",
        f"{prefix}        tag=CARDTYPE value=MINION",
        f"{prefix}        tag=ATK value={atk}",
        f"{prefix}        tag=HEALTH value={health}",
        f"{prefix}    TAG_CHANGE Entity=[entityName=Minion id={eid} zone={zone} "
        f"zonePos=0 cardId={cid} player={player}] tag=JUST_PLAYED value=0",
    ]


class TestHand(unittest.TestCase):
    def test_hand_carries_minions_and_spells(self):
        """The hand is a coaching input (2026-09-04: five spells sat in hand
        while the coach said nothing — casting from hand is free). Minions
        and tavern spells both parse, each tagged with a type."""
        gs = GameState()
        lines = (
            creating(30, "BG33_140")
            + tags(GS, 30, 2, 2, zone="HAND", player=1, cid="BG33_140")
            + [f"{GS}    FULL_ENTITY - Creating ID=31 CardID=BG28_897",
               f"{GS}        tag=CONTROLLER value=1",
               f"{GS}        tag=ZONE value=HAND",
               f"{GS}        tag=ZONE_POSITION value=2",
               f"{GS}        tag=CARDTYPE value=SPELL"]
        )
        for line in lines:
            gs.feed(line)
        hand = gs.hand(friendly_player=1)
        types = {m["card"]: m["type"] for m in hand}
        self.assertEqual(types.get("BG33_140"), "minion")
        self.assertEqual(types.get("BG28_897"), "spell")

    def test_cast_spell_leaves_the_hand(self):
        """Casting moves the spell out of HAND — the hand (and the plan)
        must shrink with it."""
        gs = GameState()
        for line in (
            [f"{GS}    FULL_ENTITY - Creating ID=31 CardID=BG28_897",
             f"{GS}        tag=CONTROLLER value=1",
             f"{GS}        tag=ZONE value=HAND",
             f"{GS}        tag=CARDTYPE value=SPELL"]
        ):
            gs.feed(line)
        self.assertEqual(len(gs.hand(friendly_player=1)), 1)
        gs.feed(f"{GS}TAG_CHANGE Entity=[entityName=Spell id=31 zone=HAND "
                f"zonePos=1 cardId=BG28_897 player=1] tag=ZONE "
                f"value=REMOVEDFROMGAME")
        self.assertEqual(gs.hand(friendly_player=1), [])


class TestControllerLock(unittest.TestCase):
    """The bracket's player is a snapshot from BEFORE the block ran: sibling
    writes that follow a same-block CONTROLLER change still carry the old
    player and must not un-move the minion (2026-09-04 beasts ghost: the
    coach said 'play Wrath Weaver' every later turn while the entity sat in
    the other player's hand). Mirror flips carry no CONTROLLER write — their
    bracket must still seed."""

    def test_same_block_bracket_does_not_undo_controller(self):
        gs = GameState()
        gs.feed(f"{GS}TAG_CHANGE Entity=[entityName=Wrath Weaver id=50 "
                f"zone=SETASIDE zonePos=0 cardId=BGS_004 player=5] "
                f"tag=CONTROLLER value=13")
        gs.feed(f"{GS}TAG_CHANGE Entity=[entityName=Wrath Weaver id=50 "
                f"zone=SETASIDE zonePos=0 cardId=BGS_004 player=5] "
                f"tag=ZONE value=HAND")
        self.assertEqual(gs.player.get(50), 13)

    def test_bracket_flip_without_controller_write_still_seeds(self):
        gs = GameState()
        gs.feed(f"{GS}TAG_CHANGE Entity=[entityName=X id=51 zone=PLAY "
                f"zonePos=1 cardId=BG33_140 player=1] tag=ATK value=2")
        self.assertEqual(gs.player.get(51), 1)
        gs.feed(f"{GS}TAG_CHANGE Entity=[entityName=X id=51 zone=PLAY "
                f"zonePos=1 cardId=BG33_140 player=13] tag=ATK value=3")
        self.assertEqual(gs.player.get(51), 13)

    def test_ghost_card_leaves_the_hand(self):
        """Bought into hand, then moved to the other player: hand(friendly)
        must stop listing it the moment the controller write lands."""
        gs = GameState()
        for line in (creating(70, "BG33_140")
                     + tags(GS, 70, 2, 2, zone="HAND", player=5,
                            cid="BG33_140")):
            gs.feed(line)
        self.assertEqual([m["card"] for m in gs.hand(friendly_player=5)],
                         ["BG33_140"])
        gs.feed(f"{GS}TAG_CHANGE Entity=[entityName=Minion id=70 zone=HAND "
                f"zonePos=1 cardId=BG33_140 player=5] tag=CONTROLLER value=13")
        gs.feed(f"{GS}TAG_CHANGE Entity=[entityName=Minion id=70 zone=HAND "
                f"zonePos=1 cardId=BG33_140 player=5] tag=ZONE_POSITION value=2")
        self.assertEqual(gs.hand(friendly_player=5), [])


class TestUpdatingForm(unittest.TestCase):
    def test_updating_block_targets_its_own_entity(self):
        """A Tusked Camper (3/4) followed by a PTL Updating block of a *different*
        entity (2/2, SETASIDE) and then the camper's own re-render (7/9). The
        camper must end 7/9 in PLAY — not corrupted by the other block."""
        gs = GameState()
        lines = (
            creating(10, "BG33_886")
            + tags(GS, 10, 3, 4, cid="BG33_886")
            + [f"{PTL}    FULL_ENTITY - Updating [entityName=Goldrinn id=99 "
               f"zone=SETASIDE zonePos=0 cardId=BGS_127 player=5] CardID=BGS_127"]
            + tags(PTL, 99, 2, 2, zone="SETASIDE", player=5, cid="BGS_127")
            + [f"{PTL}    FULL_ENTITY - Updating [entityName=Tusked Camper id=10 "
               f"zone=PLAY zonePos=1 cardId=BG33_886 player=1] CardID=BG33_886"]
            + tags(PTL, 10, 7, 9, cid="BG33_886")
        )
        for line in lines:
            gs.feed(line)
        board, _ = gs.board(friendly_player=1)
        self.assertEqual(len(board), 1, board)
        m = board[0]
        self.assertEqual(m["card"], "BG33_886")
        self.assertEqual((m["atk"], m["health"]), (7, 9))

    def test_updating_nested_brackets_empty_cardid(self):
        """`[entityName=UNKNOWN ENTITY [cardType=INVALID] id=N ...] CardID=` must
        parse (greedy bracket capture; entityName contains its own brackets)."""
        gs = GameState()
        gs.feed(f"{PTL}    FULL_ENTITY - Updating [entityName=UNKNOWN ENTITY "
                f"[cardType=INVALID] id=7861 zone=SETASIDE zonePos=0 cardId= "
                f"player=5] CardID=")
        self.assertEqual(gs.current_entity, 7861)

    def test_updating_empty_cardid_keeps_existing_card(self):
        gs = GameState()
        for line in creating(10, "BG33_886") + tags(GS, 10, 3, 4, cid="BG33_886") + [
            f"{PTL}    FULL_ENTITY - Updating [entityName=? id=10 zone=PLAY "
            f"zonePos=0 cardId= player=1] CardID=",
        ]:
            gs.feed(line)
        self.assertEqual(gs.card.get(10), "BG33_886")


class TestGolden(unittest.TestCase):
    def test_golden_minion_is_a_board_minion(self):
        board = _board_for(
            creating(11, "BG25_008_G") + tags(GS, 11, 14, 14, cid="BG25_008_G")
            + creating(12, "BG33_886") + tags(GS, 12, 3, 4, cid="BG33_886"))
        cards = {m["card"]: m for m in board}
        self.assertIn("BG25_008", cards)   # stripped _G
        self.assertTrue(cards["BG25_008"]["golden"])
        self.assertIn("BG33_886", cards)

    def test_recreated_golden_not_corrupted_by_following_updating_blocks(self):
        """Snow Baller repro: a re-created minion followed by PTL Updating blocks
        of *other* entities. Before the fix those Updating tags fell through to
        FULL_TAG and were applied to the previous Creating entity (health 4 -> 6,
        PLAY -> SETASIDE)."""
        board = _board_for(
            creating(7406, "BG25_008_G") + tags(GS, 7406, 2, 4, cid="BG25_008_G")
            + [f"{PTL}    FULL_ENTITY - Updating [entityName=Molten Rock id=7860 "
               f"zone=SETASIDE zonePos=0 cardId=BGS_127 player=5] CardID=BGS_127"]
            + tags(PTL, 7860, 2, 6, zone="SETASIDE", player=5, cid="BGS_127")
            + [f"{PTL}    FULL_ENTITY - Updating [entityName=Tavern Tempest id=7862 "
               f"zone=SETASIDE zonePos=0 cardId=BGS_123 player=5] CardID=BGS_123"]
            + tags(PTL, 7862, 4, 4, zone="SETASIDE", player=5, cid="BGS_123"))
        self.assertEqual(len(board), 1, board)
        m = board[0]
        self.assertEqual(m["card"], "BG25_008")
        self.assertEqual((m["atk"], m["health"]), (2, 4))
        self.assertEqual(m["player"], 1)


def _board_for(lines, friendly=1):
    """Feed lines to a GameState; return the friendly board (list of minions)."""
    gs = GameState()
    for line in lines:
        gs.feed(line)
    return gs.board(friendly_player=friendly)[0]


if __name__ == "__main__":
    unittest.main()