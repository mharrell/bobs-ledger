"""The turn timeline extractor: three board states per turn.

The reconstruction itself can only be verified against a real `Power.log` (see
`analysis/SETTLE_UP_BOARDS.md` for the measurements), and this suite deliberately
does not pretend otherwise — there is no synthetic log that stages a combat
burst. What IS pinned here is everything around it: the snapshot→board transform
(including its tolerance for short tuples and its side split), the stat total,
and the two invariants that would make the reconstruction silently WRONG rather
than merely absent.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import turn_review as tr  # noqa: E402

#: Snapshots are 6-tuples — (player, card, atk, health, golden, keywords).
OURS, THEIRS = 5, 13


def _snap(*minions):
    return {"phase": "combat", "minions": list(minions)}


class TestTheSnapshotTransform(unittest.TestCase):
    def test_splits_by_player_id(self):
        minions = [(OURS, "A", 2, 1, False, []), (THEIRS, "B", 3, 3, False, ["TAUNT"])]
        ours = tr._snap_board(minions, OURS, "ours")
        theirs = tr._snap_board(minions, OURS, "theirs")
        self.assertEqual([m["card"] for m in ours], ["A"])
        self.assertEqual([m["card"] for m in theirs], ["B"])
        self.assertEqual(theirs[0]["keywords"], ["TAUNT"])

    def test_a_none_player_is_not_ours(self):
        # Combat-created minions used to arrive with player None before
        # board_state resolved CONTROLLER; an unattributed minion must never be
        # counted on our side (that is how a board of ten becomes five and five).
        minions = [(None, "A", 1, 1, False, [])]
        self.assertEqual(tr._snap_board(minions, OURS, "ours"), [])
        self.assertEqual(len(tr._snap_board(minions, OURS, "theirs")), 0,
                         "None is 'unknown', not 'theirs' either")

    def test_short_tuples_are_tolerated_not_dropped(self):
        # A missing keyword list is not a reason to lose a minion.
        board = tr._snap_board([(OURS, "A", 2, 1)], OURS, "ours")
        self.assertEqual(len(board), 1)
        self.assertEqual(board[0]["golden"], False)
        self.assertEqual(board[0]["keywords"], [])

    def test_golden_survives(self):
        board = tr._snap_board([(OURS, "A", 6, 9, True, [])], OURS, "ours")
        self.assertTrue(board[0]["golden"])

    def test_an_empty_snapshot_is_an_empty_board(self):
        self.assertEqual(tr._snap_board(None, OURS, "ours"), [])
        self.assertEqual(tr._snap_board([], OURS, "theirs"), [])


class TestStatTotal(unittest.TestCase):
    def test_sums_atk_plus_health(self):
        board = [{"atk": 2, "health": 1}, {"atk": 6, "health": 3}]
        self.assertEqual(tr.stats(board), 12)

    def test_none_stats_do_not_crash(self):
        # A staged entity can carry a stat the log never printed.
        self.assertEqual(tr.stats([{"atk": None, "health": 4}]), 4)
        self.assertEqual(tr.stats([]), 0)


class TestTheTimelineInvariants(unittest.TestCase):
    """The decisions that make the reconstruction honest rather than merely
    present. These go through `_turn_rows`, the real assembler — a test that
    builds a row by hand and asserts the fields it just wrote is not a control.
    """

    @staticmethod
    def _snaps(turn, *entries):
        return {turn: [{"phase": ph, "minions": list(ms)} for ph, ms in entries]}

    def test_buy_end_is_the_LAST_buy_snapshot(self):
        # The FIRST buy snapshot of a turn carries the previous fight's teardown
        # (its `theirs` is the last opponent's survivors). Using it would show
        # the player the wrong opponent on every single turn.
        snaps = self._snaps(3, ("buy", [(OURS, "OLD", 1, 1, False, [])]),
                            ("buy", [(OURS, "NEW", 5, 5, False, []),
                                     (THEIRS, "ENEMY", 9, 9, False, [])]))
        rows = tr._turn_rows(snaps, {}, OURS)
        self.assertEqual([m["card"] for m in rows[0]["buy_end"]], ["NEW"],
                         "the last buy snapshot wins")

    def test_battle_end_is_the_NEXT_turns_opening_board(self):
        snaps = {3: [{"phase": "combat", "minions": [(OURS, "DIED", 1, 1, False, [])]},
                     {"phase": "combat", "minions": []}],
                 4: [{"phase": "buy", "minions": [(OURS, "KEPT", 5, 5, False, [])]}]}
        rows = tr._turn_rows(snaps, {}, OURS)
        self.assertEqual([m["card"] for m in rows[0]["battle_end"]], ["KEPT"],
                         "survivors come from the next turn's opening board, "
                         "not from the combat burst that drained to nothing")

    def test_the_final_turn_falls_back_to_the_final_board(self):
        snaps = self._snaps(9, ("combat", [(OURS, "LAST", 3, 3, False, [])]))
        rows = tr._turn_rows(snaps, {}, OURS,
                             final_board=[{"card": "SURVIVOR", "atk": 4,
                                           "health": 4, "golden": False,
                                           "keywords": []}])
        self.assertEqual([m["card"] for m in rows[-1]["battle_end"]], ["SURVIVOR"])

    def test_no_final_board_is_a_note_not_a_silent_empty(self):
        snaps = self._snaps(9, ("combat", [(OURS, "LAST", 3, 3, False, [])]))
        rows = tr._turn_rows(snaps, {}, OURS, final_board=[])
        self.assertEqual(rows[-1]["battle_end"], [])
        self.assertIn("final board not recoverable", rows[-1]["notes"])

    def test_the_lag_note_fires_when_plays_followed_the_last_snapshot(self):
        # Measured on turn 4 of the 2026-10-06 game: last buy snapshot 1 minion,
        # combat staging 3. The old claim ("the last buy snapshot IS the end of
        # the buy phase") was wrong, and this is what says so.
        snaps = self._snaps(4,
                            ("buy", [(OURS, "A", 2, 1, False, [])]),
                            ("combat", [(OURS, "A", 2, 1, False, []),
                                        (OURS, "B", 6, 3, False, []),
                                        (OURS, "C", 2, 1, False, [])]))
        row = tr._turn_rows(snaps, {}, OURS)[0]
        self.assertEqual(row["lag"], 2)
        self.assertEqual(len(row["buy_end"]), 1)
        self.assertEqual(len(row["combat_start"]["ours"]), 3)
        self.assertTrue(any("played after the last buy-phase snapshot" in n
                            for n in row["notes"]))

    def test_no_lag_note_when_the_buy_board_is_complete(self):
        snaps = self._snaps(4, ("buy", [(OURS, "A", 2, 1, False, [])]),
                            ("combat", [(OURS, "A", 2, 1, False, [])]))
        row = tr._turn_rows(snaps, {}, OURS)[0]
        self.assertEqual(row["lag"], 0)
        self.assertFalse([n for n in row["notes"] if "played after" in n])

    def test_growth_is_measured_on_persistent_stats_not_combat_buffs(self):
        # Turn 7 of the same game: 13/6G at buy end, 15/6G in combat. Combat
        # snapshots carry non-persistent buffs, so the growth series must read
        # the buy boards and the two totals are reported separately.
        snaps = {1: [{"phase": "buy", "minions": [(OURS, "A", 2, 1, False, [])]},
                     {"phase": "combat", "minions": [(OURS, "A", 90, 90, False, [])]}],
                 2: [{"phase": "buy", "minions": [(OURS, "A", 6, 3, False, [])]},
                     {"phase": "combat", "minions": [(OURS, "A", 500, 500, False, [])]}]}
        rows = tr._turn_rows(snaps, {}, OURS)
        self.assertEqual(rows[0]["stats"]["buy_end"], 3)
        self.assertEqual(rows[0]["stats"]["combat_ours"], 180)
        self.assertEqual(rows[1]["stats"]["buy_end"], 9)
        self.assertEqual(rows[1]["stats"]["growth"], 6,
                         "growth reads the buy boards, so a 500-stat combat "
                         "buff cannot inflate it")

    def test_a_turn_with_no_combat_says_so(self):
        snaps = self._snaps(2, ("buy", [(OURS, "A", 2, 1, False, [])]))
        row = tr._turn_rows(snaps, {}, OURS)[0]
        self.assertEqual(row["combat_start"], {"ours": [], "theirs": []})
        self.assertIn("no combat staged for this turn", row["notes"])

    def test_an_unattributed_minion_never_lands_on_our_side(self):
        # The failure mode that made a first probe report "our=0, their=10" on a
        # board that was really five and five.
        snaps = self._snaps(1, ("combat", [(None, "GHOST", 1, 1, False, [])]))
        row = tr._turn_rows(snaps, {}, None)[0]
        self.assertEqual(row["combat_start"]["ours"], [])
        self.assertEqual(row["combat_start"]["theirs"], [])


if __name__ == "__main__":
    unittest.main()
