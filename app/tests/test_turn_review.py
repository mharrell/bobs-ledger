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


class TestTheOpeningBoard(unittest.TestCase):
    """The board the shop opened with, minus the previous fight's leftovers.

    Reported 2026-10-07: *"Sometimes, in battles, extra minions are summoned for
    various reasons that go away once the shop phase starts. These minions are
    showing up in the 'Opened With' section. We should be getting just the
    current ones. A max of 7."* Reproduced on the newest game of that day
    (Tavish Stormpike, Undead, 1st) — turn 15's opening snapshot holds NINE of
    our minions, the four real golden Eternal Knights at 271/116 plus two copies
    the Eternal Summoner's deathrattle left in PLAY. The fixtures below are that
    snapshot, verbatim, down to the entity ids and board positions.
    """

    #: (player, card, atk, health, golden, keywords, eid, pos)
    OURS_ID = 2

    @staticmethod
    def _m(card, atk, hp, eid, pos, golden=False):
        return (2, card, atk, hp, golden, (), eid, pos)

    def _real_board(self):
        return [self._m("BG25_008", 271, 116, 14681, 1, True),
                self._m("BG25_008", 271, 116, 14682, 2, True),
                self._m("BG25_008", 271, 116, 14683, 3, True),
                self._m("BG25_008", 271, 116, 14684, 4, True),
                self._m("BG25_009", 54, 8, 14685, 5),
                self._m("BG36_515", 45, 8, 14688, 6),
                self._m("BG32_324", 41, 7, 14690, 7)]

    def test_the_fights_leftovers_are_not_on_the_opening_board(self):
        snap = {"phase": "buy", "minions": self._real_board() + [
            self._m("BG25_008", 131, 46, 15278, 3),
            self._m("BG25_008", 223, 92, 15281, 4, True)]}
        board, removed = tr._opening_board(snap, self.OURS_ID)
        self.assertEqual(removed, 2)
        self.assertEqual([m["card"] for m in board],
                         ["BG25_008"] * 4 + ["BG25_009", "BG36_515", "BG32_324"])
        self.assertEqual([m["atk"] for m in board[:4]], [271] * 4,
                         "the 131/46 and 223/92 copies are the ones that go")

    def test_the_control_the_same_snapshot_without_the_collision(self):
        """Rehearsal: with the leftovers removed from the FIXTURE, nothing is
        dropped. Without this, the test above would pass for a filter that
        drops two minions for any reason at all."""
        board, removed = tr._opening_board(
            {"phase": "buy", "minions": self._real_board()}, self.OURS_ID)
        self.assertEqual(removed, 0)
        self.assertEqual(len(board), 7)

    def test_a_board_over_the_cap_is_cut_to_seven(self):
        # No slot collision (8..14 are not board slots a real minion holds) and
        # a fight that left summons on free slots: the game's own cap applies.
        snap = {"phase": "buy", "minions": self._real_board() + [
            self._m("BG25_008", 9, 9, 19001, 8),
            self._m("BG25_008", 9, 9, 19002, 9)]}
        board, removed = tr._opening_board(snap, self.OURS_ID)
        self.assertEqual((len(board), removed), (7, 2))
        self.assertNotIn(19001, [m.get("eid") for m in board],
                         "the cap keeps the lowest entity ids — the fight's "
                         "copies are allocated after the board's")

    def test_a_replay_without_ids_is_left_alone(self):
        """A rep saved before 2026-10-07 has no entity id and no position: the
        filter has nothing to reason with and must not guess."""
        snap = {"phase": "buy", "minions": [
            (2, "A", 1, 1, False, []), (2, "B", 2, 2, False, [])]}
        board, removed = tr._opening_board(snap, self.OURS_ID)
        self.assertEqual(removed, 0)
        self.assertEqual([m["card"] for m in board], ["A", "B"])

    def test_no_snapshot_is_not_a_board_of_nothing(self):
        self.assertEqual(tr._opening_board(None, self.OURS_ID), ([], 0))

    def test_turn_rows_report_what_they_removed(self):
        # The row has to CARRY the removal, or the renderer cannot say it and
        # the board reads as a silent edit. The shape is the real game's: a
        # contaminated opening frame, then a settled one. (buy_end is the
        # SETTLED one and is left alone — measured over 88 buy-ends in 7 games,
        # the leftovers never reach the last snapshot of a buy phase.)
        snaps = {14: [{"phase": "buy", "minions": self._real_board()}],
                 15: [{"phase": "buy", "minions": self._real_board() + [
                     self._m("BG25_008", 131, 46, 15278, 3),
                     self._m("BG25_008", 223, 92, 15281, 4, True)]},
                     {"phase": "buy", "minions": self._real_board()}]}
        rows = tr._turn_rows(snaps, {}, self.OURS_ID)
        self.assertEqual(rows[0]["battle_end_removed"], 2,
                         "turn 14's survivors ARE turn 15's opening board")
        self.assertEqual(len(rows[0]["battle_end"]), 7)
        self.assertEqual(rows[1]["buy_start_removed"], 2)
        self.assertEqual(len(rows[1]["buy_start"]), 7)
        self.assertEqual(len(rows[1]["buy_end"]), 7)
        raw = tr._snap_board(snaps[15][0]["minions"], self.OURS_ID, "ours")
        self.assertEqual(len(raw), 9, "the fixture really is the 9-minion "
                                      "snapshot the log wrote")

    def test_an_ordinary_turn_reports_nothing_removed(self):
        snaps = {6: [{"phase": "buy", "minions": [
            (2, "A", 3, 4, False, (), 11, 1), (2, "B", 2, 2, False, (), 12, 2)]}]}
        row = tr._turn_rows(snaps, {}, self.OURS_ID)[0]
        self.assertEqual((row["buy_start_removed"],
                          row["battle_end_removed"]), (0, 0))
        self.assertEqual(len(row["buy_start"]), 2)


class TestTwoFightsInOneTurn(unittest.TestCase):
    """The 2026-10-07 final (Tavish, 1st): the turn staged the round's fight
    vs a 107-stat board and then the game's final duel vs a 1510-stat board.
    A renderer that takes the first combat burst shows the wrong game."""

    @staticmethod
    def _snaps(turn, *entries):
        return {turn: [{"phase": ph, "minions": list(ms)} for ph, ms in entries]}

    def test_two_fights_show_the_last(self):
        snaps = self._snaps(
            15,
            ("buy", [(OURS, "SHOPKEEP", 3, 3, False, [])]),
            ("combat", [(OURS, "ROUND_OURS", 2, 2, False, []),
                        (THEIRS, "ROUND_THEIRS", 8, 10, False, [])]),
            ("combat", []),   # the round fight's teardown
            ("combat", [(OURS, "DUEL_OURS", 282, 119, False, []),
                        (THEIRS, "DUEL_THEIRS", 341, 344, False, [])]),
            ("combat", []),   # the duel's teardown
            ("combat", []),   # trailing zeros are the same teardown
        )
        row = tr._turn_rows(snaps, {}, OURS)[0]
        self.assertEqual([m["card"] for m in row["combat_start"]["theirs"]],
                         ["DUEL_THEIRS"])
        self.assertEqual([m["card"] for m in row["combat_start"]["ours"]],
                         ["DUEL_OURS"])

    def test_multiple_fights_stay_quiet_about_the_choice(self):
        # The last fight is shown and no note is raised: which fight a turn
        # staged is reconstruction plumbing, not something a player asked for
        # (2026-10-07: "I don't think we need this message").
        snaps = self._snaps(
            15,
            ("combat", [(THEIRS, "T1", 3, 3, False, [])]),
            ("combat", []),
            ("combat", [(THEIRS, "T2", 4, 4, False, [])]),
        )
        row = tr._turn_rows(snaps, {}, OURS)[0]
        self.assertEqual([m["card"] for m in row["combat_start"]["theirs"]],
                         ["T2"])
        self.assertFalse([n for n in row["notes"] if "fights were staged" in n],
                         "which fight a turn staged is plumbing, not a note")

    def test_mid_fight_restage_without_a_teardown_is_one_fight(self):
        # Deaths and buffs re-stage continuously inside one fight (the measured
        # turn 4 had four bursts); only the drain-to-zero separates fights.
        snaps = self._snaps(
            5,
            ("combat", [(OURS, "A", 2, 2, False, []),
                        (THEIRS, "T1", 3, 3, False, [])]),
            ("combat", [(OURS, "A", 4, 4, False, []),
                        (THEIRS, "T1", 3, 3, False, []),
                        (THEIRS, "T2", 4, 4, False, [])]),
        )
        row = tr._turn_rows(snaps, {}, OURS)[0]
        self.assertEqual([m["card"] for m in row["combat_start"]["theirs"]],
                         ["T1"])


class TestShopBattleAftermath(unittest.TestCase):
    """The three-view turn card's data: what the shop opened with, the fight
    after beginning-of-combat effects, and what either side survived with."""

    @staticmethod
    def _snaps(turn, *entries):
        return {turn: [{"phase": ph, "minions": list(ms)} for ph, ms in entries]}

    def test_buy_start_is_the_first_buy_snapshot_ours_side(self):
        snaps = self._snaps(
            5,
            ("buy", [(OURS, "SURVIVOR", 3, 3, False, []),
                     (THEIRS, "STALE", 9, 9, False, [])]),   # teardown residue
            ("buy", [(OURS, "SURVIVOR", 3, 3, False, []),
                     (OURS, "BOUGHT", 4, 4, False, [])]),
            ("combat", [(THEIRS, "T1", 3, 3, False, [])]),
        )
        row = tr._turn_rows(snaps, {}, OURS)[0]
        self.assertEqual([m["card"] for m in row["buy_start"]], ["SURVIVOR"],
                         "the shop opened with the survivors, one-sided by "
                         "design — the first buy snapshot's `theirs` is the "
                         "previous fight's teardown (trap 3.4)")
        self.assertEqual([m["card"] for m in row["buy_end"]],
                         ["SURVIVOR", "BOUGHT"])

    def test_battle_peak_is_the_post_proc_burst_not_the_staging(self):
        # Measured shape (2026-10-06, turn 7): the staging burst reads LOW,
        # start-of-combat effects land a burst later, deaths thin it after.
        snaps = self._snaps(
            7,
            ("combat", [(OURS, "A", 13, 6, True, []),
                        (THEIRS, "T1", 4, 4, False, [])]),          # staging
            ("combat", [(OURS, "A", 15, 6, True, []),
                        (THEIRS, "T1", 8, 8, False, [])]),          # procs
            ("combat", [(OURS, "A", 15, 6, True, [])]),             # a death
        )
        row = tr._turn_rows(snaps, {}, OURS)[0]
        self.assertEqual([m["card"] for m in row["combat_peak"]["ours"]], ["A"])
        self.assertEqual([m["atk"] for m in row["combat_peak"]["ours"]], [15])
        self.assertEqual([m["card"] for m in row["combat_peak"]["theirs"]],
                         ["T1"])
        self.assertEqual([m["atk"] for m in row["combat_peak"]["theirs"]], [8])
        # the staging row is still there, honestly low
        self.assertEqual(row["stats"]["combat_ours"], 19)

    def test_a_late_ours_snowball_is_not_the_battle_peak(self):
        # The 2026-10-07 final, abstractly: our side snowballs AFTER the
        # opponent's board is dead. Plain max-combined picked that aftermath
        # burst (4730 vs 448) and showed the duel's ending as its beginning.
        snaps = self._snaps(
            15,
            ("combat", [(OURS, "O_STAGED", 100, 100, False, []),
                        (THEIRS, "T_STAGED", 60, 60, False, [])]),
            ("combat", [(OURS, "O_PROCS", 110, 110, False, []),
                        (THEIRS, "T_PROCS", 70, 70, False, [])]),
            ("combat", [(OURS, "O_SNOWBALL", 500, 500, False, [])]),
        )
        row = tr._turn_rows(snaps, {}, OURS)[0]
        self.assertEqual([m["card"] for m in row["combat_peak"]["ours"]],
                         ["O_PROCS"])
        self.assertEqual([m["card"] for m in row["combat_peak"]["theirs"]],
                         ["T_PROCS"],
                         "both rows read the same burst — the moment after "
                         "procs, before the first death")

    def test_when_we_win_their_side_has_no_survivors(self):
        # Combat ends when a board dies. The next shop's snapshots catch the
        # combat copies MID-TEARDOWN — dead minions still staged — and once
        # produced an aftermath where both sides "survived".
        snaps = {5: [{"phase": "combat", "minions": [
                        (OURS, "A", 2, 2, False, []),
                        (THEIRS, "DIES", 9, 9, False, [])]},
                     {"phase": "combat", "minions": [
                        (OURS, "A", 2, 2, False, [])]}]}
        row = tr._turn_rows(snaps, {}, OURS)[0]
        self.assertEqual(row["winner"], "us")
        self.assertEqual(row["theirs_survivors"], [])

    def test_when_they_win_their_last_staged_board_is_shown(self):
        snaps = {5: [{"phase": "combat", "minions": [
                        (OURS, "DIES", 2, 2, False, []),
                        (THEIRS, "T1", 5, 5, False, [])]},
                     {"phase": "combat", "minions": [
                        (THEIRS, "T2", 6, 6, False, [])]}]}
        row = tr._turn_rows(snaps, {}, OURS)[0]
        self.assertEqual(row["winner"], "them")
        self.assertEqual([m["card"] for m in row["theirs_survivors"]],
                         ["T2"], "their last staged board — combat-time "
                         "stats, from the fight, not the teardown")

    def test_a_double_ko_is_a_tie_with_two_empty_lists(self):
        snaps = self._snaps(
            5,
            ("combat", [(OURS, "A", 2, 2, False, []),
                        (THEIRS, "T", 3, 3, False, [])]),
            ("combat", []),   # both boards died together
        )
        row = tr._turn_rows(snaps, {}, OURS)[0]
        self.assertEqual(row["winner"], "tie")
        self.assertEqual(row["theirs_survivors"], [])
        self.assertEqual(row["battle_end"], [])

    def test_no_result_when_the_fight_was_never_attributed(self):
        snaps = self._snaps(5, ("combat", [(None, "GHOST", 1, 1, False, [])]))
        row = tr._turn_rows(snaps, {}, None)[0]
        self.assertIsNone(row["winner"])

    def test_damage_taken_is_the_eff_hp_delta_to_the_next_turn(self):
        info = {4: {"analysis": {"health": 20, "armor": 5, "gold": 8,
                                 "tier": 3}},
                5: {"analysis": {"health": 12, "armor": 0, "gold": 9,
                                 "tier": 3}}}
        snaps = {4: [{"phase": "combat", "minions": [
                        (THEIRS, "T", 3, 3, False, [])]}],
                 5: [{"phase": "combat", "minions": [
                        (THEIRS, "T", 3, 3, False, [])]}]}
        rows = tr._turn_rows(snaps, info, OURS)
        self.assertEqual(rows[0]["damage_taken"], 13,
                         "20+5 eff -> 12+0 eff = 13 damage")
        self.assertIsNone(rows[1]["damage_taken"],
                          "the last turn has no next turn to measure")

    def test_shop_events_come_off_the_action_parse(self):
        info = {4: {"analysis": {"health": 20, "gold": 8, "tier": 3},
                    "actual": {"plays": ["BG_x", "BG_y"], "upgrades": 1,
                               "hero_power": 1,
                               "choices": ["BG35_MagicItem_823t",
                                           "BG25_008"]}}}
        snaps = self._snaps(4, ("combat", [(THEIRS, "T", 3, 3, False, [])]))
        ev = tr._turn_rows(snaps, info, OURS)[0]["shop_events"]
        self.assertEqual(ev["played"], 2)
        self.assertTrue(ev["tier_up"])
        self.assertTrue(ev["hero_power"])
        self.assertEqual(ev["trinkets"], ["BG35_MagicItem_823t"],
                         "trinket picks carry MagicItem in the id; a hero "
                         "pick or discover in the same turn must not")


class TestTookCarriesTheRailLists(unittest.TestCase):
    """The Summary rail (2026-10-08) renders plays and casts as named chips
    in order — a count cannot. _took carries the two id lists through; old
    saved reps simply lack the keys and the rail degrades."""

    def test_plays_and_spell_ids_are_carried_in_order(self):
        actual = {"buys": ["BG31_815"], "sells": ["BG33_886"],
                  "plays": ["BG31_815", "BG33_886"],
                  "spell_ids": ["BG28_966", "BG20_GEM"],
                  "triples": ["BG33_886"], "spells": 2}
        took = tr._took(actual)
        self.assertEqual(took["bought"], ["BG31_815"])
        self.assertEqual(took["sold"], ["BG33_886"])
        self.assertEqual(took["plays"], ["BG31_815", "BG33_886"])
        self.assertEqual(took["spell_ids"], ["BG28_966", "BG20_GEM"])
        self.assertEqual(took["spells_cast"], 2)

    def test_missing_keys_stay_empty(self):
        took = tr._took({})
        self.assertEqual(took["plays"], [])
        self.assertEqual(took["spell_ids"], [])


class TestRowCarriesEffectiveHp(unittest.TestCase):
    """The Battle face-off's HP line needs the effective HP itself, not only
    the delta the row already saved (2026-10-08)."""

    def test_row_holds_eff(self):
        rows = tr._turn_rows(
            {1: [{"phase": "combat", "minions": [(5, "A", 1, 1, False, [])]}],
             2: [{"phase": "combat", "minions": [(5, "A", 1, 1, False, [])]}]},
            {1: {"analysis": {"health": 20, "armor": 5, "gold": 3}},
             2: {"analysis": {"health": 15, "armor": 5, "gold": 4}}},
            5)
        self.assertEqual(rows[0]["eff"], 25)
        self.assertEqual(rows[0]["damage_taken"], 5)
        self.assertEqual(rows[1]["eff"], 20)

    def test_eff_is_none_where_the_coach_never_advised(self):
        rows = tr._turn_rows(
            {1: [{"phase": "combat", "minions": [(5, "A", 1, 1, False, [])]}]},
            {}, 5)
        self.assertIsNone(rows[0]["eff"])


class TestStepsFor(unittest.TestCase):
    """The Step-through's bridge: an action's board is the last snapshot
    count at or before its own line, filtered to the friendly side and
    trimmed to what a card tile draws."""

    @staticmethod
    def _minion(eid, player):
        return {"card": "BG31_815", "player": player, "atk": 3, "health": 3,
                "golden": False, "eid": eid, "pos": 1, "tribe": "Elemental"}

    def test_board_runs_to_the_next_actions_start(self):
        """The buy's own zone write fires INSIDE its block, lines after the
        block start the event records — so the board for action k runs to
        where action k+1 begins (the slice end for the last one)."""
        actual = {"events": [{"k": "buy", "card": "BG31_815", "at": 3},
                             {"k": "sell", "card": "BG31_815", "at": 7}]}
        # Opened with minion 9; the buy's effect lands at line 5 (10 joins);
        # the sell's effect lands at line 9 (10 leaves). Markers: 1, 2, 3
        # snapshots after lines 0, 5 and 9.
        snaps = [[self._minion(9, 5)],
                 [self._minion(9, 5), self._minion(10, 5)],
                 [self._minion(9, 5)]]
        steps = tr._steps_for(actual, [(0, 1), (5, 2), (9, 3)], snaps, 5,
                              0, 12)
        self.assertEqual([s["k"] for s in steps], ["buy", "sell"])
        # buy: runs to the sell's start (line 7) -> both minions on board
        self.assertEqual([m["eid"] for m in steps[0]["board"]], [9, 10])
        # sell: runs to the slice end (12) -> the sold minion is gone
        self.assertEqual([m["eid"] for m in steps[1]["board"]], [9])

    def test_friendly_filter_and_field_trim(self):
        snaps = [[self._minion(9, 5), self._minion(10, 13)]]
        steps = tr._steps_for({"events": [{"k": "buy", "card": "BG31_815",
                                           "at": 0}]},
                              [(0, 1)], snaps, 5, 0, 4)
        m = steps[0]["board"][0]
        self.assertEqual(sorted(m.keys()),
                         ["atk", "card", "eid", "golden", "health"])
        self.assertEqual(len(steps[0]["board"]), 1,
                         "the opponent's minion is filtered out")

    def test_no_events_yields_no_steps(self):
        self.assertEqual(tr._steps_for({}, [(0, 1)], [[]], 5, 0, 4), [])


if __name__ == "__main__":
    unittest.main()
