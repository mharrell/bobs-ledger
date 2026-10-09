"""Settle Up: the post-game review's own logic.

This is the one place in the product that is ALLOWED to say "the model would
have bought X" (PIVOT.md §4, Phase 2), which makes two things worth pinning
harder than usual:

  * the verdicts are honest — "taken" means the card the model NAMED, not a
    card from its shortlist, and a move this review cannot grade says so
    instead of being counted either way;
  * the summary cannot be read as a score. The followed/ignored split carries
    the observational caveat wherever it appears, and the ungraded count is
    printed so a review that graded three phases out of sixteen cannot look
    like one that graded sixteen.

No real Power.log is needed: the logic under test is all pure, over rows of the
shape `outcome_audit.audit_game` produces. The log-level test at the bottom
builds a two-game stub from `CREATE_GAME` markers, which is exactly the split
`extract_game.split_game_chunks` keys on — and the bounds check it exercises is
the bug this module shipped with its first run (the splitter yields (start, end)
PAIRS, not chunks).
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import settle_up  # noqa: E402


def _row(**over):
    """One phase row, in outcome_audit's shape."""
    r = {"turn": 3, "tier": 2, "gold": 5, "eff_hp": 40, "lead": "buy",
         "card": "BG36_116", "card_name": "Glim Guardian",
         "followed_buy": False, "followed_level": False,
         "followed_roll": False, "player_buys": [], "player_actions": {},
         "steps": [], "hp_delta_next_fight": -4, "shop_rank": []}
    r.update(over)
    return r


class TestPlanLine(unittest.TestCase):
    def test_numbers_the_steps_and_keeps_the_tag(self):
        steps = [{"action": "LEVEL", "tag": "access to tier 4"},
                 {"action": "Buy Bronze Warden", "tag": "surviving"}]
        self.assertEqual(settle_up._plan_line(steps),
                         "1. LEVEL (access to tier 4) · "
                         "2. Buy Bronze Warden (surviving)")

    def test_empty_steps_render_empty(self):
        self.assertEqual(settle_up._plan_line([]), "")

    def test_a_step_with_no_text_is_skipped_not_numbered(self):
        # Numbering a blank step would leave a hole in the sequence ("1. · 3.").
        steps = [{"action": "LEVEL"}, {"action": "", "text": ""},
                 {"action": "Buy X"}]
        self.assertEqual(settle_up._plan_line(steps), "1. LEVEL · 2. Buy X")


class TestVerdicts(unittest.TestCase):
    def test_the_named_card_bought_is_taken(self):
        label, kind = settle_up._verdict(
            _row(player_buys=["BG36_116"], followed_buy=True))
        self.assertEqual((label, kind), ("taken", "taken"))

    def test_a_shortlist_card_is_not_taken(self):
        """The 2026-10-06 t4 read "taken" because outcome_audit's `followed_buy`
        counts the headline plus the next three ranked offers. For an aggregate
        accuracy number that is the right question; for a review it is not —
        the model said "Buy Flighty Scout" and the player bought two other
        things from the shortlist."""
        label, kind = settle_up._verdict(
            _row(card="BG36_116", player_buys=["BG99_999"],
                 followed_buy=True))
        self.assertEqual(label, "shortlist only")
        self.assertEqual(kind, "ignored",
                         "a shortlist buy must not count as following")

    def test_ignored_buy(self):
        self.assertEqual(settle_up._verdict(_row(followed_buy=False)),
                         ("not taken", "ignored"))

    def test_level_and_roll(self):
        self.assertEqual(
            settle_up._verdict(_row(lead="level", followed_level=True),
                               ), ("taken", "taken"))
        self.assertEqual(
            settle_up._verdict(_row(lead="hunt-roll", followed_roll=False)),
            ("not taken", "ignored"))

    def test_pass_is_its_own_class(self):
        self.assertEqual(settle_up._verdict(_row(lead="pass")),
                         ("as planned", "pass"))
        self.assertEqual(
            settle_up._verdict(_row(lead="pass", player_buys=["X"])),
            ("not as planned", "pass"))

    def test_no_plan_is_distinct_from_cannot_grade(self):
        self.assertEqual(settle_up._verdict(_row(lead=None)), ("no plan", "none"))
        self.assertEqual(settle_up._verdict(_row(lead="note")),
                         ("no plan", "none"))

    def test_a_swap_led_plan_is_a_plan_not_no_plan(self):
        """t8 of the 10-06 game reads "1. Swap: play Holy Vanguard, sell
        Crackling Cyclone" — a real plan, and the first version called it
        "no plan"."""
        label, kind = settle_up._verdict(_row(lead="swap"))
        self.assertEqual(kind, "ungraded")
        self.assertIn("swap", label)

    def test_a_cast_led_plan_is_graded_now(self):
        """It was UNGRADED until 2026-10-06 — `value.top_move` left `card` None
        on a cast step and `player_actions` only counted spells, so 8 of the 16
        phases in the 2026-10-06 game could not be judged. Both now carry ids."""
        self.assertEqual(
            settle_up._verdict(_row(lead="cast", card="SPELL_A",
                                    spells_cast=["SPELL_A"])),
            ("cast as planned", "taken"))
        self.assertEqual(
            settle_up._verdict(_row(lead="cast", card="SPELL_A",
                                    spells_cast=["SPELL_B"])),
            ("cast something else", "ignored"))
        self.assertEqual(
            settle_up._verdict(_row(lead="cast", card="SPELL_A", spells_cast=[])),
            ("not cast", "ignored"))

    def test_a_cast_with_no_resolved_card_stays_ungraded(self):
        # An Activate step parses as kind `discard`, and a token the card DB
        # cannot name leaves no card to match. "Cast something else" would be a
        # guess dressed as a judgement.
        label, kind = settle_up._verdict(_row(lead="cast", card=None,
                                              spells_cast=["SPELL_B"]))
        self.assertEqual(kind, "ungraded")
        self.assertIn("unresolved", label)

    def test_a_play_led_plan_is_graded(self):
        self.assertEqual(
            settle_up._verdict(_row(lead="play", card="MINION_A",
                                    plays=["MINION_A"])),
            ("played as planned", "taken"))
        self.assertEqual(
            settle_up._verdict(_row(lead="play", card="MINION_A", plays=[])),
            ("not played", "ignored"))

    def test_a_swap_is_still_ungraded(self):
        # Grading a swap needs the sell AND the play that replaced it; the row
        # carries neither as a pair, so it stays out of the counts.
        label, kind = settle_up._verdict(_row(lead="swap", card="X"))
        self.assertEqual(kind, "ungraded")
        self.assertIn("swap", label)


class TestActed(unittest.TestCase):
    def _names(self):
        return {"BG36_116": "Glim Guardian", "BG28_810": "Tavern Coin"}

    def test_buys_upgrades_rolls_sells_and_freezes(self):
        row = _row(player_buys=["BG36_116"],
                   player_actions={"upgrades": 1, "refreshes": 2,
                                   "sells": ["BG28_810"], "freezes": 1})
        self.assertEqual(
            settle_up._acted(self._names(), row),
            "bought Glim Guardian, levelled up, rolled x2, sold Tavern Coin, froze")

    def test_nothing_is_said_as_nothing(self):
        self.assertEqual(settle_up._acted(self._names(), _row()), "nothing")

    def test_an_unknown_id_renders_raw_rather_than_vanishing(self):
        # A review that silently omits a buy is worse than one showing the id
        # (the rule review_kit's pre-flight applies).
        self.assertEqual(
            settle_up._acted(self._names(), _row(player_buys=["BG36_318"])),
            "bought BG36_318")


class TestTotals(unittest.TestCase):
    def test_counts_and_bleed(self):
        phases = [
            {"kind": "taken", "outcome": -6},
            {"kind": "ignored", "outcome": -2},
            {"kind": "taken", "outcome": 0},
            {"kind": "ungraded", "outcome": None},
        ]
        t = settle_up._totals(phases, {})
        self.assertEqual(t["counts"]["taken"], 2)
        self.assertEqual(t["counts"]["ignored"], 1)
        self.assertEqual(t["counts"]["ungraded"], 1)
        self.assertEqual(t["bled_total"], 8, "only damage counts as cost")
        self.assertEqual(t["graded_phases"], 3, "a None outcome is not graded")
        self.assertEqual(t["ungraded_phases"], 1)
        self.assertEqual(t["taken_mean"], -3.0)     # (-6 + 0) / 2
        self.assertEqual(t["ignored_mean"], -2.0)
        self.assertEqual(t["taken_n"], 2)

    def test_no_phases_does_not_divide_by_zero(self):
        t = settle_up._totals([], {})
        self.assertEqual(t["counts"]["phases"], 0)
        self.assertIsNone(t["taken_mean"])

    def test_the_caveat_is_in_the_totals(self):
        # The summary must never travel without it.
        self.assertIn("Observational", settle_up._totals([], {})["caveat"])

    def test_graded_phases_are_broken_down_by_lead(self):
        """Cast-led phases are gradable now, and they are NOT interchangeable
        with buy-led ones — the split has to be able to say so."""
        phases = [
            {"kind": "taken", "outcome": -6, "lead": "buy"},
            {"kind": "taken", "outcome": 0, "lead": "cast"},
            {"kind": "ignored", "outcome": -2, "lead": "cast"},
            {"kind": "ungraded", "outcome": None, "lead": "swap"},
        ]
        t = settle_up._totals(phases, {})
        self.assertEqual(t["graded_by_lead"], {"buy": 1, "cast": 2})
        self.assertEqual(t["graded_phases"], 3,
                         "an ungraded phase is not in the breakdown either")

class TestReport(unittest.TestCase):
    def _report(self, **over):
        rep = {
            "schema": settle_up.SCHEMA, "created": "2026-10-06T12:00:00",
            # NOT a real session directory name. The first version of this
            # fixture carried the one from the run I was looking at, and the
            # publish gate refused the release: privacy_scan flags
            # `Hearthstone_YYYY_MM_DD_HH_MM_SS` as session_dir, and app/tests
            # SHIPS. A fixture that has to look realistic to be valid would be
            # a fixture worth having; this one only has to render.
            "session": "test-session", "log": "Power.log",
            "game": 1, "hero": "Chenvaala", "placement": 2,
            "phases": [{"turn": 1, "tier": 1, "gold": 3, "eff_hp": 45,
                        "plan": "1. Buy <Buzzing> Vermin (tempo)",
                        "lead": "buy", "kind": "taken",
                        "verdict": "taken", "named": "X",
                        "reasons": ["it grows"], "acted": "bought it",
                        "buys": ["it"], "outcome": -2,
                        "outcome_note": None}],
            "totals": settle_up._totals([{"kind": "taken", "outcome": -2}], {}),
            "caveat": settle_up.CAVEAT,
        }
        rep.update(over)
        return rep

    def test_html_escapes_card_names(self):
        html = settle_up.render_html(self._report())
        self.assertIn("&lt;Buzzing&gt;", html)
        self.assertNotIn("<Buzzing>", html)

    def test_html_is_self_contained(self):
        html = settle_up.render_html(self._report())
        self.assertNotIn("<script", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)

    def test_html_carries_the_caveat_and_the_plan(self):
        html = settle_up.render_html(self._report())
        self.assertIn("Observational", html)
        self.assertIn("1. Buy", html)

    def test_text_says_the_ungraded_count_out_loud(self):
        rep = self._report(phases=[
            {"turn": 1, "tier": 1, "gold": 3, "eff_hp": 45, "plan": "x",
             "lead": "cast", "kind": "ungraded", "verdict": "not graded (cast)",
             "named": None, "reasons": [], "acted": "nothing", "buys": [],
             "outcome": None, "outcome_note": "no fight after this phase"},
        ])
        rep["totals"] = settle_up._totals(rep["phases"], {})
        text = settle_up.render_text(rep)
        self.assertIn("1 of 1 phases", text)
        self.assertIn("cannot grade", text)
        self.assertIn("no fight after this phase", text)
        self.assertIn("Observational", text)

    def test_the_cast_signal_is_weaker_and_the_text_says_so(self):
        # A turn that casts several spells can satisfy "Cast X" incidentally, so
        # a summary that mixed cast-led and buy-led phases would overstate the
        # cast-led ones. The line only appears when such a phase was graded.
        rep = self._report(phases=[
            {"turn": 5, "tier": 5, "gold": 9, "eff_hp": 30, "plan": "1. Cast X",
             "lead": "cast", "kind": "taken", "verdict": "cast as planned",
             "named": "X", "reasons": [], "acted": "cast X", "buys": [],
             "outcome": -4, "outcome_note": None},
        ])
        rep["totals"] = settle_up._totals(rep["phases"], {})
        text = settle_up.render_text(rep)
        self.assertIn("led with a cast", text)
        self.assertIn("incidentally", text)

        rep["phases"][0]["lead"] = "buy"
        rep["totals"] = settle_up._totals(rep["phases"], {})
        self.assertNotIn("led with a cast", settle_up.render_text(rep))


class TestTheRemovedSummonsIsDisclosed(unittest.TestCase):
    """A survivor board that dropped the fight's leftovers says so.

    `turn_review._opening_board` removes a fight's summoned copies from the
    opening and surviving boards (reported and fixed 2026-10-07, trap 3.6 of
    `analysis/SETTLE_UP_BOARDS.md`). The count rides on the row as
    `battle_end_removed`, and both reports have to print it: a board that reads
    shorter than the log wrote must never be a silent edit.
    """

    @staticmethod
    def _rep(removed):
        turn = {"turn": 15, "gold": 9, "stats": {"buy_end": 30, "growth": 0},
                "spend": {"total": 9}, "sell_questions": [],
                "commitment": {"target": None}, "notes": [],
                "combat_start": {"ours": [], "theirs": []},
                "combat_ours_text": "", "combat_theirs_text": "",
                "buy_end": [], "buy_end_text": "Eternal Knight 282/119 (golden)",
                "battle_end": [], "battle_end_text": "Eternal Knight 282/119 (golden)",
                "battle_end_removed": removed}
        return {"schema": settle_up.SCHEMA, "created": "2026-10-07T00:00:00",
                "session": "test-session", "log": "Power.log", "game": 1,
                "hero": "Tavish Stormpike", "placement": 1,
                # One advised phase, because a report with none stops at
                # "nothing to settle" and never reaches the boards at all.
                "phases": [{"turn": 15, "tier": 6, "gold": 9, "eff_hp": 30,
                            "plan": "1. Buy X", "lead": "buy", "kind": "taken",
                            "verdict": "taken", "named": "X", "reasons": [],
                            "acted": "bought it", "buys": ["it"],
                            "outcome": -3, "outcome_note": None}],
                "timeline": {"turns": [turn]}, "timeline_error": None,
                "totals": settle_up._totals([{"kind": "taken", "outcome": -3}],
                                            {}),
                "caveat": settle_up.CAVEAT}

    def test_the_text_report_says_how_many_were_removed(self):
        text = settle_up.render_text(self._rep(2))
        self.assertIn("survived", text)
        self.assertIn("2 leftover summon(s)", text)
        self.assertIn("a board holds 7", text)

    def test_the_html_report_says_it_too(self):
        html = settle_up.render_html(self._rep(2))
        self.assertIn("2 leftover summon(s)", html)
        self.assertIn("a board holds 7", html)

    def test_the_control_an_untouched_board_prints_nothing(self):
        # Rehearsal: the line must come from the COUNT, not from rendering a
        # timeline at all — otherwise it would appear on every turn and read as
        # noise the player learns to skip.
        self.assertNotIn("leftover summon(s)", settle_up.render_text(self._rep(0)))
        self.assertNotIn("leftover summon(s)", settle_up.render_html(self._rep(0)))


class TestSessionAggregation(unittest.TestCase):
    """The session and history views: pure aggregation over full reports."""

    def _rep(self, game=1, placement=2, hero="Chenvaala", boards=(10, 30, 52),
             sells=(2, 0, 1), phases=("taken", "ignored", "taken"),
             bled=9, level=None, timeline=True, error=None, blank_turn=False):
        turns = []
        for i, b in enumerate(boards):
            # The STRUCTURED board must be present for the turn to count: the
            # summary filters on it, not on the stat number, so a turn whose
            # board could not be read is left out of the peak rather than
            # counted as a zero.
            board = [] if (blank_turn and i == 0) else [
                {"card": "X", "atk": b, "health": 0, "golden": False,
                 "keywords": []}]
            turns.append({"turn": i + 1,
                          "stats": {"buy_end": b, "growth": None,
                                    "theirs": 0, "combat_ours": b},
                          "spend": {"total": 5, "cards_bought": 1,
                                    "card_gold": 3, "card_costs": [],
                                    "rolls": 1, "roll_gold": 1,
                                    "levelled": False, "level_gold": None},
                          "sell_questions": [{"sold": f"S{j}", "role": "scaler",
                                              "kept_fillers": ["F"]}
                                             for j in range(sells[i])],
                          "commitment": {"target": None, "progress": []},
                          "combat_start": {"ours": [], "theirs": []},
                          "buy_end": board, "battle_end": [], "lag": 0,
                          "notes": []})
        counts = {"phases": len(phases), "taken": 0, "ignored": 0, "none": 0,
                  "pass": 0, "ungraded": 0}
        for k in phases:
            counts[k] = counts.get(k, 0) + 1
        return {"game": game, "hero": hero, "placement": placement,
                "timeline": ({"turns": turns} if timeline else None),
                "timeline_error": error,
                "totals": {"counts": counts, "bled_total": bled}}

    def test_summarise_reads_the_report_not_a_second_pass(self):
        s = settle_up._summarise(self._rep())
        self.assertEqual(s["turns"], 3)
        self.assertEqual(s["spent"], 15, "5 gold per turn x 3")
        self.assertEqual(s["peak_board"], 52)
        self.assertEqual(s["final_board"], 52, "the last buy-end board")
        self.assertEqual(s["sell_questions"], 3)
        self.assertEqual(s["taken"], 2)
        self.assertEqual(s["phases_tracked"], 3)

    def test_a_turn_with_no_board_read_is_left_out_of_the_peak(self):
        # Not counted as a zero: "we could not read the board" is not "the board
        # was worth nothing", and a zero would drag the peak down.
        s = settle_up._summarise(self._rep(boards=(0, 30, 52), blank_turn=True))
        self.assertEqual(s["peak_board"], 52)
        self.assertEqual(s["final_board"], 52)

    def test_summarise_survives_a_missing_timeline(self):
        s = settle_up._summarise(self._rep(timeline=False, error="boom"))
        self.assertEqual(s["turns"], 0)
        self.assertEqual(s["spent"], 0)
        self.assertIsNone(s["final_board"])
        self.assertEqual(s["timeline_error"], "boom")
        self.assertEqual(s["taken"], 2, "the phase rows still summarise")

    def test_median_handles_odd_even_and_empty(self):
        self.assertEqual(settle_up._median([3, 1, 2]), 2)
        self.assertEqual(settle_up._median([2, 4]), 3)
        self.assertIsNone(settle_up._median([]))
        self.assertIsNone(settle_up._median([None, None]),
                          "an unknown placement is not a zero")

    def test_session_totals_sum_and_do_not_rank(self):
        t = settle_up._session_totals([
            settle_up._summarise(self._rep(game=1, placement=2)),
            settle_up._summarise(self._rep(game=2, placement=7, hero="Tickatus",
                                           bled=20, sells=(0, 0, 0))),
        ])
        self.assertEqual(t["games"], 2)
        self.assertEqual(t["placements"], [2, 7])
        self.assertEqual(t["best"], 2)
        self.assertEqual(t["median_placement"], 4.5)
        self.assertEqual(t["phases"], 6)
        self.assertEqual(t["bled"], 29)
        self.assertEqual(t["spent"], 30)
        self.assertEqual(t["sell_questions"], 3)
        self.assertEqual(t["median_final_board"], 52)
        self.assertIn("Observational", t["caveat"])

    def test_session_totals_of_nothing_is_safe(self):
        t = settle_up._session_totals([])
        self.assertEqual(t["games"], 0)
        self.assertIsNone(t["best"])
        self.assertEqual(t["phases"], 0)

    def test_a_game_with_no_placement_does_not_break_the_median(self):
        t = settle_up._session_totals([
            settle_up._summarise(self._rep(placement=None)),
            settle_up._summarise(self._rep(game=2, placement=1)),
        ])
        self.assertEqual(t["placements"], [1])
        self.assertEqual(t["best"], 1)


class TestHistoryWiring(unittest.TestCase):
    """`build_history` over a stub log: the shape, not the numbers."""

    def _log(self, games=1):
        lines = []
        for g in range(games):
            lines.append(f"D 10:0{g}:00.0000000 GameState.DebugPrintPower() - CREATE_GAME")
            lines.append("D 10:0%d:01.0000000 GameState.DebugPrintPower() - TAG_CHANGE" % g)
        return lines

    def test_history_aggregates_every_log_it_is_given(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            paths = []
            for i in (1, 2):
                p = os.path.join(td, f"Power{i}.log")
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(self._log()))
                paths.append(p)
            rep = settle_up.build_history(paths)
        self.assertEqual(len(rep["logs"]), 2)
        self.assertEqual([lg["games"] for lg in rep["logs"]], [1, 1],
                         "a CREATE_GAME counts as a game even when nothing in it "
                         "is playable — the summariser reports it with zeroes")
        self.assertEqual(rep["totals"]["games"], 2)
        self.assertIn("Observational", rep["caveat"])
        self.assertIn("session(s)", settle_up.render_history_text(rep))


class TestBuildWalksALog(unittest.TestCase):
    """The cheap log-level test: a stub built from CREATE_GAME markers, which
    is what the splitter keys on. It pins the bounds check — the first version
    of build() treated `split_game_chunks` as a list of chunks when it yields
    (start, end) index PAIRS, and died with `TypeError: object of type
    'generator' has no len()`."""

    def _log(self, games=2):
        lines = []
        for g in range(games):
            lines.append(f"D 10:0{g}:00.0000000 GameState.DebugPrintPower() - "
                         f"CREATE_GAME")
            lines.append("D 10:0%d:00.1000000 PowerTaskList.DebugPrintPower() - "
                         "CREATE_GAME" % g)
            lines.append("D 10:0%d:01.0000000 GameState.DebugPrintPower() - TAG_CHANGE"
                         % g)
        return lines

    def test_a_log_with_no_heroes_still_returns_a_report(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "Power.log")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(self._log()))
            rep = settle_up.build(path, 1)
        self.assertEqual(rep["schema"], settle_up.SCHEMA)
        self.assertEqual(rep["game"], 1)
        self.assertEqual(rep["phases"], [],
                         "no playable game -> no phases, not a crash")
        self.assertIn("nothing to settle", settle_up.render_text(rep))

    def test_an_out_of_range_game_says_how_many_there_are(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "Power.log")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(self._log(games=2)))
            with self.assertRaises(SystemExit) as cm:
                settle_up.build(path, 9)
        # The PowerTaskList duplicate must NOT be counted as a third game.
        self.assertIn("has 2 game(s)", str(cm.exception))

    def test_the_report_carries_the_game_stable_id(self):
        """The gid is what makes a reprocessed game save over itself instead
        of beside itself (the 2026-10-09 restart bug — the old filename came
        from `created`, which is the wall clock of the build). It is derived
        from the pointer, so the same game twice names itself the same way
        and a different game does not."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "Power.log")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(self._log(games=2)))
            first = settle_up.build(path, 1)
            again = settle_up.build(path, 1)
            second = settle_up.build(path, 2)
        self.assertTrue(first["gid"])
        self.assertEqual(first["gid"], again["gid"])
        self.assertNotEqual(first["gid"], second["gid"])


class TestRebuild(unittest.TestCase):
    """Re-derive a saved replay from its own source log (2026-10-08). The
    store's session/log/game pointer is the whole mechanism; Hearthstone
    rotating its session dirs is the expected failure, returned as a reason
    and never raised into the tab.

    The session name is the registered placeholder
    (`privacy_scan.SYNTHETIC_SESSIONS`), not the session this was written
    against: this file SHIPS, and the first version of it carried the real
    directory name in three places, so the privacy gate refused the 2026-10-08
    release ("app/tests/test_settle_up.py: session_dir x1"). That is the THIRD
    time a real session name has been committed in a shipped fixture.

    Worth knowing about that "x1": one of the three was written as two
    adjacent string literals to fit the line, so the concatenated value never
    appears contiguously in the file and `privacy_scan` — which reads TEXT —
    could not see it. Two of the three were real, one was visible, and the
    gate's count said one. Keep a fixture name on ONE line, or the scan's
    number is not the whole picture.
    """

    def setUp(self):
        import replay_store
        self.replay_store = replay_store
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.rid = replay_store.save(
            {"created": "2026-10-07T20:53:01",
             "session": "Hearthstone_2026_01_01",
             "log": "Power.log", "game": 2, "hero": "H", "placement": 1,
             "phases": [], "totals": {}, "timeline": {"turns": []},
             "timeline_error": None, "caveat": "x"},
            root=self.root.name)["id"]

    def test_unknown_id_is_a_reason_not_a_raise(self):
        rep, err = settle_up.rebuild("no-such-id")
        self.assertIsNone(rep)
        self.assertIn("no saved replay", err)

    def test_rep_without_a_pointer_says_so(self):
        import replay_store
        replay_store.save({"created": "x", "phases": [], "totals": {},
                           "timeline": {"turns": []}},
                          root=self.root.name, rid="pointless")
        rep, err = settle_up.rebuild("pointless", root=self.root.name)
        self.assertIsNone(rep)
        self.assertIn("does not record which log", err)

    def test_missing_log_names_the_rotation(self):
        import glob as globmod
        from unittest import mock
        import config
        with mock.patch.object(config, "HS_LOG_GLOBS",
                               ("C:/x/Logs/Hearthstone_*/Power.log",)), \
             mock.patch.object(globmod, "glob", return_value=[]):
            rep, err = settle_up.rebuild(self.rid, root=self.root.name)
        self.assertIsNone(rep)
        self.assertIn("rotates", err)

    def test_happy_path_rebuilds_under_the_same_id(self):
        import glob as globmod
        from unittest import mock
        import config
        fresh = {"created": "2026-10-08T12:00:00",
                 "session": "Hearthstone_2026_01_01",
                 "log": "Power.log", "game": 2, "hero": "H2", "placement": 1,
                 "phases": [{"turn": 1}], "totals": {"phases": 1},
                 "timeline": {"turns": [{"turn": 1, "steps": [{"k": "buy"}]}]},
                 "timeline_error": None, "caveat": "x"}
        with mock.patch.object(config, "HS_LOG_GLOBS",
                               ("C:/x/Logs/Hearthstone_*/Power.log",)), \
             mock.patch.object(globmod, "glob",
                               return_value=["C:/x/Logs/Hearthstone_2026_01_01/"
                                             "Power.log"]), \
             mock.patch.object(settle_up, "build",
                               return_value=fresh) as b:
            rep, err = settle_up.rebuild(self.rid, root=self.root.name)
        self.assertIsNone(err)
        self.assertEqual(rep, fresh)
        b.assert_called_once_with(
            "C:/x/Logs/Hearthstone_2026_01_01/Power.log", 2)
        stored = self.replay_store.load(self.rid, root=self.root.name)
        self.assertEqual(stored["rep"]["hero"], "H2",
                         "the rebuild lands under the SAME id")
        self.assertEqual(stored["rep"]["timeline"]["turns"][0]["steps"],
                         [{"k": "buy"}])


if __name__ == "__main__":
    unittest.main()
