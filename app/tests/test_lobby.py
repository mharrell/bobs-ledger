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

# app/ is where the code lives; deriving it from this file
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed

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


def stats(eid, atk, hp):
    """Live ATK/HEALTH for a staged entity.

    The real log writes these as BARE-entity TAG_CHANGE lines — never as
    indented block tags (verified against a real session: 2662 bare ATK
    writes, 0 block-form). Fixtures must use the same shape or they would
    pin a form the log does not produce.
    """
    return [L(f"        TAG_CHANGE Entity={eid} tag=ATK value={atk}"),
            L(f"        TAG_CHANGE Entity={eid} tag=HEALTH value={hp}")]


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


class TestSeatStats(unittest.TestCase):
    """A seat's board STRENGTH, which `cards` cannot supply.

    `cards` counts copies; joining those to the card DB gives BASE stats, and a
    buffed board reads roughly 10x low. The staged entity's live ATK/HEALTH is
    the honest number, and it must be captured at the CLOSE of the combat
    window — the log writes it several times per entity (staged, then combat
    wear, then a zeroed pair at teardown).
    """

    def setUp(self):
        self.s = lobby.LobbyScout()
        self.s.feed(create(45, lobby.STAGED_CREATOR))

    def feed_all(self, lines):
        for ln in lines:
            self.s.feed(ln)

    def test_seat_stats_sum_live_atk_health(self):
        self.s.open_round(3, {})
        self.feed_all(stag(100, 9, M1, pos=1) + stats(100, 4, 5)
                      + stag(101, 9, M2, pos=2) + stats(101, 7, 3))
        self.s.close_round()
        self.s.resolve_completed(4, {3: 7}, friendly=1)
        rec = self.s.seats[7]
        # (4+5) + (7+3)
        self.assertEqual(rec["stats"], 19)
        self.assertEqual(rec["stats_n"], 2)

    def test_seat_stats_are_base_independent(self):
        """Stats come from the log, not from the card ids.

        M1 and M2 have their own base stats in the DB; the fixture's VALUES are
        deliberately unrelated to them, so a base-stat join cannot pass this.
        """
        self.s.open_round(3, {})
        self.feed_all(stag(100, 9, M1, pos=1) + stats(100, 40, 40))
        self.s.close_round()
        self.s.resolve_completed(4, {3: 7}, friendly=1)
        self.assertEqual(self.s.seats[7]["stats"], 80)

    def test_combat_wear_is_not_recorded(self):
        """The snapshot is the window CLOSE, not the last write of all.

        A staged 4/5 that takes 5 damage and is then torn down to 1/1 must read
        9, not 2 and not the 27 a max-of-writes rule would take.
        """
        self.s.open_round(3, {})
        self.feed_all(stag(100, 9, M1, pos=1) + stats(100, 4, 5))
        self.s.close_round()                     # window closes HERE
        # everything below is the fight itself and the teardown
        self.feed_all(stats(100, 12, 15)          # a combat-only buff
                      + stats(100, 1, 1))         # teardown remnant
        self.s.resolve_completed(4, {3: 7}, friendly=1)
        self.assertEqual(self.s.seats[7]["stats"], 9)

    def test_stats_exclude_our_own_side(self):
        """Our controller's minions are never counted as theirs."""
        self.s.open_round(3, {})
        self.feed_all(stag(100, 1, M1, pos=1) + stats(100, 30, 30)     # ours
                      + stag(101, 9, M2, pos=2) + stats(101, 5, 5))    # theirs
        self.s.close_round()
        self.s.resolve_completed(4, {3: 7}, friendly=1)
        self.assertEqual(self.s.seats[7]["stats"], 10)
        self.assertEqual(self.s.seats[7]["stats_n"], 1)

    def test_stats_absent_when_nothing_staged_stats(self):
        """No ATK/HEALTH writes means no number, not a zero.

        Zero is a claim about the board; absent is the truth about our
        knowledge, and the two must not be confused.
        """
        self.s.open_round(3, {})
        self.feed_all(stag(100, 9, M1, pos=1))     # no stats() lines
        self.s.close_round()
        self.s.resolve_completed(4, {3: 7}, friendly=1)
        self.assertIsNone(self.s.seats[7]["stats"])
        self.assertIsNone(self.s.seats[7]["stats_n"])
        # the composition read is unaffected
        self.assertEqual(self.s.seats[7]["cards"], {M1: 1})

    def test_blended_record_carries_no_strength(self):
        """A blended counter is an upper bound, so its total would be one too."""
        self.s.open_round(3, {})
        # 8 distinct kinds exceed the 7-minion board limit -> blended
        lines = []
        for i, cid in enumerate([M1, M2, M3] * 3):
            lines += stag(200 + i, 9, cid, pos=i + 1) + stats(200 + i, 5, 5)
        self.feed_all(lines)
        self.s.close_round()
        self.s.resolve_completed(4, {3: 7}, friendly=1)
        rec = self.s.seats[7]
        self.assertTrue(rec["blended"])
        self.assertIsNone(rec["stats"])
        self.assertIsNone(rec["stats_n"])


class TestGameBoundary(unittest.TestCase):
    """The scout must not outlive the game it describes.

    Found 2026-10-04: live_coach._reset() rebuilt gs/actions but left the scout
    standing, so `seats` held the PREVIOUS game's boards. Because seat ids are
    account slots they line up across games, and the freshness test
    (`cur_turn - rec["turn"] <= max_age`) goes NEGATIVE early in a new game —
    so a stranger's comp was rendered as the announced opponent.
    """

    def setUp(self):
        self.s = lobby.LobbyScout()
        self.s.feed(create(45, lobby.STAGED_CREATOR))

    def feed_all(self, lines):
        for ln in lines:
            self.s.feed(ln)

    def _resolve_one_round(self, turn, seat):
        self.s.open_round(turn, {})
        self.feed_all(stag(100, 9, M1, pos=1) + stats(100, 9, 9))
        self.s.close_round()
        self.s.resolve_completed(turn + 1, {turn: seat}, friendly=1)

    def test_stale_seat_is_not_fresh(self):
        """A seat from a LATER turn than cur_turn is not fresh.

        This is the arithmetic that made the leak silent: the age is negative
        and `<= max_age` accepts it. The guard is independent of reset(), so
        the same mistake cannot hide again.
        """
        self._resolve_one_round(10, 7)
        self.assertEqual(self.s.fresh_seats(11), {7})
        self.assertEqual(self.s.fresh_seats(12), {7})
        self.assertEqual(self.s.fresh_seats(13), set())
        # a NEW game at turn 2 must not see it at all
        self.assertEqual(self.s.fresh_seats(2), set())
        self.assertEqual(self.s.merged_holdings(2), {})

    def test_reset_forgets_the_game(self):
        self._resolve_one_round(10, 7)
        self.assertTrue(self.s.seats)
        self.s.reset()
        self.assertEqual(self.s.seats, {})
        self.assertEqual(self.s._names, {})
        self.assertEqual(self.s._rounds, {})
        self.assertEqual(self.s._resolved, set())
        self.assertEqual(self.s._creators, set())
        self.assertEqual(self.s._stats, {})
        self.assertEqual(self.s.fresh_seats(2), set())

    def test_reset_equals_a_fresh_scout(self):
        """reset() must leave nothing behind — the _reset() contract."""
        self._resolve_one_round(10, 7)
        self.s.reset()
        self.assertEqual(self.s, lobby.LobbyScout())


class TestLiveCoachResetsScout(unittest.TestCase):
    """_reset() (on CREATE_GAME) must clear the scout, not just gs/actions."""

    def test_new_game_clears_seats(self):
        import live_coach
        coach = live_coach.LiveCoach()
        coach.feed(create(45, lobby.STAGED_CREATOR))
        coach._scout.open_round(4, {})
        for ln in stag(100, 9, M1, pos=1) + stats(100, 9, 9):
            coach._scout.feed(ln)
        coach._scout.close_round()
        coach._scout.resolve_completed(5, {4: 7}, friendly=1)
        self.assertIn(7, coach._scout.seats)
        # a new game starts
        coach.feed("D 12:00:00.0000000 GameState.DebugPrintPower() - "
                   "CREATE_GAME")
        self.assertEqual(coach._scout.seats, {})


if __name__ == "__main__":
    unittest.main()
