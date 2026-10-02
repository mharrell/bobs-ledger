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


class TestHeldTrinkets(unittest.TestCase):
    """Held trinkets (BGxx_MagicItem_NNN) sit in PLAY once chosen â€” the
    value function's W_TRINKET term and the simulator's requires_trinket
    steps read this (both were dead code in the live loop, 2026-09-08).
    The real log path: the placeholder Lesser/Greater Trinket entity
    (BG30_Trinket_1st/2nd, always controller 7) CHANGE_ENTITYs to the
    chosen trinket id (2026-09-08 13:33 session, entity 420)."""

    def test_friendly_play_trinket_found(self):
        gs = GameState()
        for line in (
            [f"{GS}    FULL_ENTITY - Creating ID=88 CardID=BG30_MagicItem_416",
             f"{GS}        tag=CONTROLLER value=1",
             f"{GS}        tag=ZONE value=PLAY",
             f"{GS}        tag=CARDTYPE value=TRINKET"]
        ):
            gs.feed(line)
        self.assertEqual(gs.held_trinkets(1), ["BG30_MagicItem_416"])
        self.assertEqual(gs.held_trinkets(2), [])

    def test_other_zones_and_players_excluded(self):
        gs = GameState()
        for zone, player in (("SETASIDE", 1), ("PLAY", 2)):
            eid = 90 + player
            for line in (
                [f"{GS}    FULL_ENTITY - Creating ID={eid} CardID=BG36_MagicItem_390",
                 f"{GS}        tag=CONTROLLER value={player}",
                 f"{GS}        tag=ZONE value={zone}",
                 f"{GS}        tag=CARDTYPE value=TRINKET"]
            ):
                gs.feed(line)
        self.assertEqual(gs.held_trinkets(1), [])

    def test_placeholder_change_entity_becomes_the_trinket(self):
        """The 2026-09-08 13:33 log's exact shape: BG30_Trinket_1st swaps to
        BG35_MagicItem_301 via CHANGE_ENTITY â€” the block's own tag lines
        (CARDTYPE, COST) land on the same entity, and stale stats from the
        placeholder don't survive the swap."""
        gs = GameState()
        for line in (
            creating(420, "BG30_Trinket_1st")
            + [f"{GS}        tag=CONTROLLER value=7",
               f"{GS}        tag=ZONE value=PLAY",
               f"{GS}        tag=CARDTYPE value=BATTLEGROUND_TRINKET"]
        ):
            gs.feed(line)
        gs.feed(f"{GS}CHANGE_ENTITY - Updating Entity=[entityName=Lesser Trinket "
                f"id=420 zone=PLAY zonePos=0 cardId=BG30_Trinket_1st player=7] "
                f"CardID=BG35_MagicItem_301")
        gs.feed(f"{GS}    tag=CARDTYPE value=BATTLEGROUND_TRINKET")
        self.assertEqual(gs.card[420], "BG35_MagicItem_301")
        self.assertEqual(gs.held_trinkets(7), ["BG35_MagicItem_301"])


class TestDarkGifts(unittest.TestCase):
    """Dark Discovery's random grant is recoverable: the gift NAME rides the
    entityName of a generic BGxx_MidGameEffect_* marker attached to its host
    minion via tag=1234 (2026-09-08 13:33 log: marker 872 'Charisma' -> host
    871, controller 7). The marker drops to REMOVEDFROMGAME while the gift
    stays active â€” zone is not the filter."""

    def test_marker_name_and_host_link(self):
        gs = GameState()
        for line in (
            [f"{GS}    FULL_ENTITY - Creating ID=871 CardID=BG35_142",
             f"{GS}        tag=CONTROLLER value=7",
             f"{GS}        tag=ZONE value=PLAY",
             f"{GS}        tag=CARDTYPE value=MINION"],
            [f"{GS}    FULL_ENTITY - Creating ID=872 CardID=",
             f"{GS}        tag=CONTROLLER value=7",
             f"{GS}        tag=ZONE value=SETASIDE",
             f"{GS}        tag=CARDTYPE value=INVALID"],
        ):
            for l in line:
                gs.feed(l)
        gs.feed(f"{GS}    SHOW_ENTITY - Updating Entity=872 "
                f"CardID=BG36_MidGameEffect_000t3e2")
        # The name resolves on a later bracket line (HIDE_ENTITY's shape).
        gs.feed(f"{GS}    HIDE_ENTITY - Entity=[entityName=Charisma id=872 "
                f"zone=PLAY zonePos=0 cardId=BG36_MidGameEffect_000t3e2 "
                f"player=7] tag=ZONE value=PLAY")
        gs.feed(f"{GS}    TAG_CHANGE Entity=[entityName=Charisma id=872 "
                f"zone=PLAY zonePos=0 cardId=BG36_MidGameEffect_000t3e2 "
                f"player=7] tag=1234 value=871")
        gs.feed(f"{GS}    TAG_CHANGE Entity=[entityName=Charisma id=872 "
                f"zone=PLAY zonePos=0 cardId=BG36_MidGameEffect_000t3e2 "
                f"player=7] tag=ZONE value=REMOVEDFROMGAME")
        got = gs.dark_gift_effects()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["name"], "Charisma")
        self.assertEqual(got[0]["host"], 871)
        self.assertEqual(got[0]["host_player"], 7)

    def test_non_gift_tag_1234_ignored(self):
        # tag=1234 on a non-MidGameEffect entity is not a host link.
        gs = GameState()
        for line in (
            [f"{GS}    FULL_ENTITY - Creating ID=500 CardID=BG33_140",
             f"{GS}        tag=CONTROLLER value=7"]
        ):
            for l in line:
                gs.feed(l)
        gs.feed(f"{GS}    TAG_CHANGE Entity=[entityName=Minion id=500 "
                f"zone=PLAY zonePos=0 cardId=BG33_140 player=7] "
                f"tag=1234 value=42")
        self.assertEqual(gs.dark_gift_effects(), [])
        self.assertNotIn(500, gs.dark_gift_host)


class TestHand(unittest.TestCase):
    def test_hand_carries_minions_and_spells(self):
        """The hand is a coaching input (2026-09-04: five spells sat in hand
        while the coach said nothing â€” casting from hand is free). Minions
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
        """Casting moves the spell out of HAND â€” the hand (and the plan)
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
    the other player's hand). Mirror flips carry no CONTROLLER write â€” their
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
        camper must end 7/9 in PLAY â€” not corrupted by the other block."""
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


class TestBareEntityTagChanges(unittest.TestCase):
    """The GameState stream prints the friendly player's own actions as bare
    `TAG_CHANGE Entity=<id> tag=... value=...` (no bracket, so no player=).
    These were matched by NAME_TAG's Entity=([^ ]+) and dropped, so plays
    never left the tracked hand (2026-09-14 morning: "play four spells from
    my hand when my hand was empty"; 586 bare ->PLAY writes in game 2)."""

    @staticmethod
    def _hand_card_lines(eid, cid, player=1):
        return [f"{GS}    FULL_ENTITY - Creating ID={eid} CardID={cid}",
                f"{GS}        tag=CONTROLLER value={player}",
                f"{GS}        tag=ZONE value=HAND",
                f"{GS}        tag=CARDTYPE value=SPELL",
                f"{GS}        tag=ZONE_POSITION value=1"]

    def test_bare_zone_play_empties_hand(self):
        gs = GameState()
        for line in self._hand_card_lines(7333, "BG36_520"):
            gs.feed(line)
        self.assertEqual(len(gs.hand(1)), 1)
        # The exact 2026-09-14 shape: bare numeric entity, no bracket.
        gs.feed(f"{GS}    TAG_CHANGE Entity=7333 tag=ZONE value=PLAY")
        self.assertEqual(gs.hand(1), [])
        self.assertEqual(gs.zone[7333], "PLAY")

    def test_numeric_entity_not_swallowed_by_account_branch(self):
        # RESOURCES-style writes live on NAMED entities; a numeric id must
        # not be mistaken for one (and gold parsing must keep working).
        gs = GameState()
        for line in self._hand_card_lines(7333, "BG36_520"):
            gs.feed(line)
        gs.feed(f"{GS}    TAG_CHANGE Entity=7333 tag=COST value=2")
        self.assertEqual(gs.cost[7333], 2)
        gs.feed(f"{GS}    TAG_CHANGE Entity=Tester#1234 "
                f"tag=RESOURCES value=10")
        self.assertEqual(gs.gold["Tester#1234"], 10)

    def test_damage_cap_on_numeric_gameentity(self):
        # The authoritative GameState damage-cap write arrives on the
        # bare-numeric GameEntity (`Entity=1`); it must survive the routing.
        gs = GameState()
        gs.feed(f"{GS}    TAG_CHANGE Entity=1 "
                f"tag=BACON_COMBAT_DAMAGE_CAP value=15")
        self.assertEqual(gs.damage_cap, 15)

    def test_bare_entity_retargets_continuation_lines(self):
        # The block's indented tag lines belong to the bare-entity, not to
        # whatever entity current_entity was stale from.
        gs = GameState()
        for line in self._hand_card_lines(1111, "BG28_810"):
            gs.feed(line)
        gs.feed(f"{GS}    FULL_ENTITY - Creating ID=2222 CardID=BG26_135")
        gs.feed(f"{GS}        tag=CONTROLLER value=1")
        gs.feed(f"{GS}        tag=ZONE value=SETASIDE")
        gs.feed(f"{GS}        tag=CARDTYPE value=MINION")
        gs.feed(f"{GS}    TAG_CHANGE Entity=1111 tag=ZONE_POSITION value=2")
        self.assertEqual(gs.zone_pos[1111], 2)


class TestShowEntityBracketed(unittest.TestCase):
    """GameState prints `SHOW_ENTITY - Updating Entity=[bracket] CardID=...`
    (reveals); the block's indented tag lines must land on the bracketed
    entity, not the stale current_entity (real-log shape: Bartend Bob /
    hero-power reveals carrying tag=ZONE continuations, 2026-09-14)."""

    def test_continuation_tags_land_on_revealed_entity(self):
        gs = GameState()
        for line in self._make_stale_current(999, "BG26_135"):
            gs.feed(line)
        gs.feed(f"{GS}    SHOW_ENTITY - Updating Entity=[entityName="
                f"Slimy Shield id=1766 zone=SETASIDE zonePos=0 "
                f"cardId=BG27_002t player=1] CardID=BG27_002t")
        gs.feed(f"{GS}        tag=CONTROLLER value=1")
        gs.feed(f"{GS}        tag=CARDTYPE value=SPELL")
        gs.feed(f"{GS}        tag=ZONE value=HAND")
        gs.feed(f"{GS}        tag=ZONE_POSITION value=3")
        # 1766 is now a HAND spell of player 1; the stale 999 was untouched.
        self.assertEqual(gs.card[1766], "BG27_002t")
        self.assertEqual(gs.zone[1766], "HAND")
        self.assertEqual(gs.zone_pos[1766], 3)
        self.assertEqual(gs.zone[999], "SETASIDE")
        self.assertEqual(gs.zone_pos.get(999), None)

    @staticmethod
    def _make_stale_current(eid, cid):
        return [f"{GS}    FULL_ENTITY - Creating ID={eid} CardID={cid}",
                f"{GS}        tag=CONTROLLER value=1",
                f"{GS}        tag=ZONE value=SETASIDE",
                f"{GS}        tag=CARDTYPE value=MINION"]


class TestHandPositionZeroExit(unittest.TestCase):
    """Discover options and next-opponent staging bursts transit zone=HAND
    (bracketed, controller=friendly) for a few seconds, then leave via
    ZONE_POSITION=0 with no ZONE write â€” the ghost cards the coach told the
    player to cast all of game 2 t5 (2026-09-14). Position 0 = leaving."""

    def test_position_zero_clears_hand(self):
        gs = GameState()
        for line in TestBareEntityTagChanges._hand_card_lines(1764,
                                                              "BG35_951"):
            gs.feed(line)
        self.assertEqual(len(gs.hand(1)), 1)
        gs.feed(f"{GS}    TAG_CHANGE Entity=[entityName=Might of Stormwind "
                f"id=1764 zone=HAND zonePos=1 cardId=BG35_951 player=1] "
                f"tag=ZONE_POSITION value=0")
        self.assertEqual(gs.hand(1), [])

    def test_real_hand_card_at_position_one_stays(self):
        gs = GameState()
        for line in TestBareEntityTagChanges._hand_card_lines(6396,
                                                              "BG25_354"):
            gs.feed(line)
        gs.feed(f"{GS}    TAG_CHANGE Entity=[entityName=Titus Rivendare "
                f"id=6396 zone=HAND zonePos=2 cardId=BG25_354 player=1] "
                f"tag=ZONE_POSITION value=1")
        self.assertEqual(len(gs.hand(1)), 1)
        self.assertEqual(gs.hand(1)[0]["pos"], 1)


if __name__ == "__main__":
    unittest.main()