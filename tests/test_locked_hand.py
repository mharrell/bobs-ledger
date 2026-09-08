"""Locked hand cards and pending-pick advice — the 2026-09-05 replay findings.

1. Thorim's hero-power discover (Stone Age Slab, BG34_950) sits in hand with
   LITERALLY_UNPLAYABLE=1 until 60 gold is spent. The coach ranked it move #1
   for 8 straight turns — including "board is full — sell to make room",
   advising the player to sell real minions for an unplayable card.
2. Between-rounds picks (dark gifts, triple rewards) sat in quiet-log windows
   where the monitor's data-gated advise check never ran; no pick advice fired.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from board_state import GameState
from value import hand_plan

GS = "D 12:21:11.4519526 GameState.DebugPrintPower() - "


def hand_card_lines(eid, cid, zone="HAND", cardtype="SPELL", locked=True):
    """A hand spell entity with the lock tags the real log carries."""
    lines = [
        f"{GS}    FULL_ENTITY - Creating ID={eid} CardID={cid}",
        f"{GS}        tag=CONTROLLER value=1",
        f"{GS}        tag=ZONE value={zone}",
        f"{GS}        tag=ZONE_POSITION value=1",
        f"{GS}        tag=CARDTYPE value={cardtype}",
    ]
    if locked:
        lines.append(f"{GS}        tag=LITERALLY_UNPLAYABLE value=1")
    return lines


class TestLockedHandCards(unittest.TestCase):
    def test_hand_flags_locked_card(self):
        gs = GameState()
        for line in hand_card_lines(371, "BG34_950", locked=True):
            gs.feed(line)
        hand = gs.hand(1)
        self.assertEqual(len(hand), 1)
        self.assertTrue(hand[0]["locked"])

    def test_unlock_tag_clears_the_lock(self):
        """LITERALLY_UNPLAYABLE value=0 (the 60-gold payoff) unlocks."""
        gs = GameState()
        for line in hand_card_lines(371, "BG34_950", locked=True):
            gs.feed(line)
        gs.feed(f"{GS}    TAG_CHANGE Entity=[entityName=Stone Age Slab "
                f"id=371 zone=HAND zonePos=1 cardId=BG34_950 player=1] "
                f"tag=LITERALLY_UNPLAYABLE value=0")
        self.assertFalse(gs.hand(1)[0]["locked"])

    def test_hand_plan_excludes_locked_cards(self):
        """A locked card can't be played or cast — the plan must not advise
        either (it ranked score 49 and said 'sell to make room' for it)."""
        gs = GameState()
        for line in hand_card_lines(371, "BG34_950", locked=True):
            gs.feed(line)
        hand = gs.hand(1)
        self.assertEqual(hand_plan(hand, []), [])

    def test_unlocked_card_returns_to_the_plan(self):
        """An unlocked known card is planned again (BG34_950 itself isn't in
        the card DB, so use a real minion id for this direction)."""
        gs = GameState()
        for line in hand_card_lines(5933, "BGS_104", cardtype="MINION",
                                    locked=False):
            gs.feed(line)
        hand = gs.hand(1)
        plan = hand_plan(hand, [])
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["card"], "BGS_104")


if __name__ == "__main__":
    unittest.main()