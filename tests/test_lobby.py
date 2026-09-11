"""Seat-level opponent tracking (phase 2, analysis/pool_availability.md).

The scout resolves a seat's board as: staged combat burst (CREATOR = the
TB_BaconShop_8P_PlayerE enchant, CARDTYPE=MINION, combat-slot controller)
minus our exact holdings at the buy-phase close, clamped at zero. These
tests pin that math, the round scoping (a round never re-counts earlier
rounds' staged copies), the seat-tag naming, and the two consumers
(fresh-seat merge for the Market chips, tribe commitment for pressure).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lobby
from tribes import matches


def L(body):
    """A GameState-shaped log line (the scout filters on the prefix)."""
    return f"D 12:00:00.0000000 GameState.DebugPrintPower() - {body}"


def create(eid, cid):
    return L(f"    FULL_ENTITY - Creating ID={eid} CardID={cid}")


def stag(eid, ctrl, cid, creator=45, cardtype="MINION", premium=0, pos=None):
    """A staged entity: creation line + its block tags."""
    lines = [create(eid, cid),
             L(f"        tag=CONTROLLER value={ctrl}"),
             L(f"        tag=CARDTYPE value={cardtype}"),
             L(f"        tag=CREATOR value={creator}"),
             L(f"        tag=PREMIUM value={premium}")]
    if pos:
        lines.append(L(f"        tag=ZONE_POSITION value={pos}"))
    return lines


# Real card ids; the scout is id-agnostic but tribe tests want real ones.
# M1 = Meteorite Crasher (Elemental), M2 = Aureate Laureate (Pirate).
M1, M2, M3 = "BG31_843", "BG32_236", "BG36_511"


class TestScout(unittest.TestCase):
    def setUp(self):
        self.s = lobby.LobbyScout()
        # The staging enchantment is created once per game.
        self.s.feed(create(45, lobby.STAGED_CREATOR))

    def feed_all(self, lines):
        for ln in lines:
            self.s.feed(ln)

    def test_staged_burst_resolves_to_opp_board(self):
        # Staging happens INSIDE the open window (after the buy-phase
        # MAIN_END, phase 0) — the fixture order mirrors that.
        self.s.open_round(3, {})
        self.feed_all(stag(100, 9, M1) + stag(101, 9, M2)
                      + stag(102, 9, M3))
        self.s.close_round()
        self.s.resolve_completed(4, {3: 7}, friendly=1)
        rec = self.s.seats[7]
        self.assertEqual(rec["cards"], {M1: 1, M2: 1, M3: 1})
        self.assertEqual(rec["turn"], 3)

    def test_subtracts_our_holdings(self):
        # Our own board stages in the same burst under OUR controller;
        # shared cards also appear in the opponent's staged group.
        self.s.open_round(3, {M1: 1})
        self.feed_all(stag(100, 1, M1)           # our copy, our controller
                      + stag(101, 9, M1)         # theirs
                      + stag(102, 9, M2))
        self.s.close_round()
        self.s.resolve_completed(4, {3: 7}, friendly=1)
        # Their M1 (1) minus our held M1 (1) nets out; M2 stands.
        self.assertEqual(self.s.seats[7]["cards"], {M2: 1})

    def test_golden_weights_three_and_flags(self):
        self.s.open_round(3, {})
        self.feed_all(stag(100, 9, M1, premium=1)
                      + stag(101, 9, M1 + "_G")  # golden via _G id
                      + stag(102, 9, M2))
        self.s.close_round()
        self.s.resolve_completed(4, {3: 7}, friendly=1)
        rec = self.s.seats[7]
        self.assertEqual(rec["cards"][M1], 6)    # 3 + 3
        self.assertEqual(rec["cards"][M2], 1)
        self.assertEqual(rec["goldens"], {M1})

    def test_round_scoping_no_recount(self):
        # Round 3 stages M1; round 4 stages M2. Round 4's resolution must
        # see only its own window's entities.
        self.s.open_round(3, {})
        self.feed_all(stag(100, 9, M1))
        self.s.close_round()
        self.s.open_round(4, {})
        self.feed_all(stag(200, 9, M2))
        self.s.close_round()
        self.s.resolve_completed(5, {3: 7, 4: 7}, friendly=1)
        self.assertEqual(self.s.seats[7]["cards"], {M2: 1})

    def test_unstaged_turn_resolves_nothing(self):
        self.s.open_round(3, {})
        self.s.close_round()                      # nothing staged
        self.s.resolve_completed(4, {3: 7}, friendly=1)
        self.assertNotIn(7, self.s.seats)

    def test_seat_tag_names_and_fights(self):
        self.s.feed(L("TAG_CHANGE Entity=Space2000 "
                      "tag=BACON_CURRENT_COMBAT_PLAYER_ID value=5"))
        self.s.feed(L("TAG_CHANGE Entity=Space2000 "
                      "tag=BACON_CURRENT_COMBAT_PLAYER_ID value=0"))
        self.s.open_round(3, {})
        self.feed_all(stag(100, 9, M1))
        self.s.close_round()
        self.s.resolve_completed(4, {3: 5}, friendly=1)
        self.assertEqual(self.s.seats[5]["name"], "Space2000")

    def test_shop_offers_and_summons_excluded(self):
        # Shop offers have no staging CREATOR; combat summons are created
        # by other minions. Neither may enter the board counter.
        self.s.open_round(3, {})
        self.feed_all(stag(100, 9, M1)             # staged: in
                      + stag(101, 9, M2, creator=999)   # summon: out
                      + [create(300, M2),
                         L("        tag=CONTROLLER value=9"),
                         L("        tag=CARDTYPE value=MINION")])
        self.s.close_round()
        self.s.resolve_completed(4, {3: 7}, friendly=1)
        self.assertEqual(self.s.seats[7]["cards"], {M1: 1})

    def test_final_duel_stages_opponent_only(self):
        # No friendly-side staging at all (the game-end quirk): the whole
        # staged group is the opponent's, minus what we hold.
        self.s.open_round(12, {M2: 1})
        self.feed_all(stag(100, 9, M1) + stag(101, 9, M2))
        self.s.close_round()
        self.s.resolve_completed(13, {12: 5}, friendly=1)
        self.assertEqual(self.s.seats[5]["cards"], {M1: 1})


class TestConsumers(unittest.TestCase):
    def setUp(self):
        self.s = lobby.LobbyScout()
        self.s.feed(create(45, lobby.STAGED_CREATOR))
        self.s.open_round(3, {})
        for lines in (stag(100, 9, M1), stag(101, 9, M1),
                      stag(102, 9, M2), stag(103, 9, M3)):
            self.feed_all(lines)
        self.s.close_round()
        self.s.resolve_completed(4, {3: 7}, friendly=1)

    def feed_all(self, lines):
        for ln in lines:
            self.s.feed(ln)

    def test_merged_holdings_fresh_only(self):
        self.assertEqual(self.s.merged_holdings(4), {M1: 2, M2: 1, M3: 1})
        # 3 rounds later the seat is stale and stops subtracting.
        self.assertEqual(self.s.merged_holdings(7), {})

    def test_fresh_seats_age_window(self):
        self.assertEqual(self.s.fresh_seats(4), {7})
        self.assertEqual(self.s.fresh_seats(5), {7})
        self.assertEqual(self.s.fresh_seats(6), set())

    def test_committed_uses_tribe_membership(self):
        # M1 = Meteorite Crasher (Elemental) x2 commits Elemental; M2 =
        # Aureate Laureate (Pirate) x1 does not.
        self.assertEqual(self.s.committed("Elemental", min_copies=2,
                                          matches=matches), {7})
        self.assertEqual(self.s.committed("Pirate", min_copies=2,
                                          matches=matches), set())
        # A second Pirate copy would commit.
        s2 = lobby.LobbyScout()
        s2.feed(create(45, lobby.STAGED_CREATOR))
        s2.open_round(3, {})
        for ln in stag(100, 9, M2) + stag(101, 9, M2):
            s2.feed(ln)
        s2.close_round()
        s2.resolve_completed(4, {3: 7}, friendly=1)
        self.assertEqual(s2.committed("Pirate", min_copies=2,
                                      matches=matches), {7})

    def test_committed_unknown_tribe_is_silent(self):
        self.assertEqual(self.s.committed("NotATribe", min_copies=1,
                                          matches=matches), set())


if __name__ == "__main__":
    unittest.main()
