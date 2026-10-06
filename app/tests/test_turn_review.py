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


class TestSpend(unittest.TestCase):
    """Gold out, with its parts named. Purchases are priced through
    `value._buy_prices`, never at a flat 3 — the bug this class exists for."""

    def test_parts_are_named_and_summed(self):
        s = tr._spend({"buys": ["A", "B"], "refreshes": 3, "upgrades": 1}, 4)
        self.assertEqual(s["cards_bought"], 2)
        self.assertEqual(s["card_gold"], 6, "unpriced minions are a FLAT 3")
        self.assertEqual(s["roll_gold"], 3, "a roll costs 1")
        self.assertEqual(s["level_gold"], 4, "the level cost comes from the log")
        self.assertEqual(s["total"], 13)

    def test_a_tavern_spell_is_priced_at_its_own_cost(self):
        # Measured: 5 of the 24 buys in the 2026-10-06 game were tavern spells.
        # Repair Job costs 2, so pricing it at a flat 3 inflates the total.
        s = tr._spend({"buys": ["MINION", "BG_SPELL"], "refreshes": 0},
                      None, prices={"BG_SPELL": 2, "MINION": 3})
        self.assertEqual(s["card_gold"], 5)
        self.assertEqual(s["card_costs"], [("MINION", 3), ("BG_SPELL", 2)])
        self.assertEqual(s["total"], 5)

    def test_an_unpriced_card_falls_back_to_the_flat_minion_price(self):
        s = tr._spend({"buys": ["UNKNOWN"]}, None, prices={})
        self.assertEqual(s["card_gold"], 3)

    def test_level_gold_is_absent_when_no_level_was_taken(self):
        s = tr._spend({"buys": ["A"], "refreshes": 0, "upgrades": 0}, 4)
        self.assertFalse(s["levelled"])
        self.assertIsNone(s["level_gold"])
        self.assertEqual(s["total"], 3)

    def test_an_unknown_level_cost_does_not_invent_one(self):
        s = tr._spend({"upgrades": 1}, None)
        self.assertIsNone(s["level_gold"])
        self.assertEqual(s["total"], 0)

    def test_nothing_done_is_zero(self):
        self.assertEqual(tr._spend({}, None)["total"], 0)

    def test_sells_are_not_subtracted(self):
        # Sells are gold IN; netting them here would hide the gross spend the
        # player actually committed.
        s = tr._spend({"buys": ["A"], "sells": ["B", "C"]}, None)
        self.assertEqual(s["total"], 3)


class TestCommitment(unittest.TestCase):
    def test_projects_the_analysiss_own_comp_progress(self):
        a = {"target_comp": "Elementals - Livin' Large", "comp_gap": None,
             "comp_progress": [
                 {"name": "Elementals - Livin' Large", "hits": 2, "ready": True,
                  "needs": [{"card": "X"}]},
                 {"name": "Mechs - Y", "hits": 0, "ready": False, "needs": []}]}
        c = tr._commitment(a)
        self.assertEqual(c["target"], "Elementals - Livin' Large")
        self.assertEqual(c["progress"][0]["hits"], 2)
        self.assertTrue(c["progress"][0]["ready"])
        self.assertEqual(c["progress"][0]["owned"], 1)

    def test_a_game_with_no_target_still_projects(self):
        c = tr._commitment({})
        self.assertIsNone(c["target"])
        self.assertEqual(c["progress"], [])


class TestSellQuestions(unittest.TestCase):
    """The maintainer's example, made computable: sold a key card while a
    throwaway stayed."""

    CORE, FILLER = "BG_CORE", "BG_FILLER"
    #: What the real caller passes (`value._load_card_db()`), trimmed. A DB is
    #: required because the role strings come from value.sell_reason, and an
    #: empty or absent one cannot classify anything — see the guard test.
    DB = {CORE: {}, FILLER: {}}

    def _analysis(self, core=(CORE,)):
        return {"target_comp": "Mechs - Y",
                "target_cards": {"core": [{"card": c} for c in core],
                                 "addons": []},
                "playable_comps": {"mechs-y": {"name": "Mechs - Y"}},
                "banned": []}

    def _board(self, *cards):
        return [{"card": c, "atk": 1, "health": 1, "golden": False,
                 "keywords": []} for c in cards]

    def test_selling_a_core_while_a_filler_stays_is_a_question(self):
        qs = tr._sell_questions([self.CORE], self._board(self.FILLER),
                                self._analysis(), card_db=self.DB)
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0]["sold"], self.CORE)
        self.assertEqual(qs[0]["role"], "comp core")
        self.assertEqual(qs[0]["kept_fillers"], [self.FILLER])

    def test_selling_the_filler_is_not_a_question(self):
        qs = tr._sell_questions([self.FILLER], self._board(self.CORE),
                                self._analysis(), card_db=self.DB)
        self.assertEqual(qs, [], "selling the throwaway is what was asked for")

    def test_selling_a_core_with_no_filler_left_is_not_a_question(self):
        # Nothing cheap was kept, so there was no better card to sell.
        qs = tr._sell_questions([self.CORE], self._board(self.CORE),
                                self._analysis(), card_db=self.DB)
        self.assertEqual(qs, [])

    def test_the_same_sell_twice_asks_once(self):
        # Measured: turn 7 of the 10-06 game lists Fire Baller twice.
        qs = tr._sell_questions([self.CORE, self.CORE],
                                self._board(self.FILLER),
                                self._analysis(), card_db=self.DB)
        self.assertEqual(len(qs), 1)

    def test_one_question_per_turn_not_per_card(self):
        """The first version fired per sold card and produced 12 questions in an
        11-turn game, nearly all the SAME sentence: one filler sat on the board
        while four scalers were sold, so it printed that board state four
        times."""
        qs = tr._sell_questions(["BG_A", "BG_B", "BG_C", "BG_D"],
                                self._board(self.FILLER),
                                self._analysis(core=("BG_A", "BG_B", "BG_C", "BG_D")),
                                card_db=self.DB)
        self.assertEqual(len(qs), 1, "one turn is one decision about what to sell")
        self.assertEqual(qs[0]["sold_count"], 4)
        self.assertIn("also_sold", qs[0])

    def test_selling_most_of_the_board_is_labelled_a_rebuild(self):
        # Selling four minions at once is repositioning, not four mistakes: the
        # choice this detector can see (this card over that filler) is not what
        # happened there. The flag lets a renderer say so.
        qs = tr._sell_questions(["BG_A", "BG_B", "BG_C"],
                                self._board(self.FILLER),
                                self._analysis(core=("BG_A", "BG_B", "BG_C")),
                                card_db=self.DB)
        self.assertTrue(qs[0]["rebuild"])

    def test_a_single_sell_is_not_a_rebuild(self):
        qs = tr._sell_questions([self.CORE], self._board(self.FILLER),
                                self._analysis(), card_db=self.DB)
        self.assertFalse(qs[0]["rebuild"])

    def test_without_a_card_db_nothing_is_classified(self):
        # An unclassifiable card is not evidence of a blunder, so the detector
        # returns nothing rather than defaulting it into a role. An EMPTY DB
        # counts as no DB: `{}` classifies every unknown card as a filler, so
        # the kept side would look like it was all throwaways and the detector
        # would fire on nothing at all.
        for db in (None, {}):
            self.assertEqual(
                tr._sell_questions([self.CORE], self._board(self.FILLER),
                                   self._analysis(), card_db=db), [],
                f"a DB of {db!r} must not classify anything")

    def test_nothing_sold_is_no_questions(self):
        self.assertEqual(
            tr._sell_questions([], self._board(self.FILLER),
                               self._analysis(), card_db=self.DB), [])


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
