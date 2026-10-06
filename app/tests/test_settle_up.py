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

    def test_a_cast_led_plan_is_ungraded_not_ignored(self):
        self.assertEqual(settle_up._verdict(_row(lead="cast"))[1], "ungraded")


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


if __name__ == "__main__":
    unittest.main()
