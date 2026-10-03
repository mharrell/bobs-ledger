"""The danger band: the 13-16 HP window where every level gate is legal.

Measured failure this exists for (analysis/replay_review_2026-09-18.md §3.1):
t10, 14 effective HP, having bled 10 in two of the last three fights, the plan
led with board deploys then "LEVEL to tier 5 (standard curve) — 1 left". The
player read it as the build being one level from taking off, and died 8th with
10 gold unspent. Every gate was legal: DYING is <= 12, the forecast cap fires at
<= 10, t9's won/tied fight reset the loss streak, and damage_last was 0.

The review's own design candidates are what this implements:
  (a) a FRAGILE band (13-16) where LEVEL renders only WITH the fragility clause;
  (b) damage memory — last-3-fights damage (sum >= 15), which a single good
      round cannot reset the way a streak can.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import value  # noqa: E402


def analysis(**over):
    """A mid-game analysis with nothing else alarming in it."""
    a = {
        "board": [], "playable_comps": {}, "sell_rank": [], "shop_rank": [],
        "buy_this": None, "tier": 5, "gold": 10, "level_cost": 9, "turn": 10,
        "damage_cap": 15,
    }
    a.update(over)
    return a


class TestFragilityBand(unittest.TestCase):
    def test_dying_is_twelve_or_less(self):
        self.assertEqual(value.fragility(analysis(health=12))["band"], "dying")
        self.assertEqual(value.fragility(analysis(health=8, armor=4))["band"],
                         "dying")

    def test_fragile_is_thirteen_to_sixteen(self):
        for eff in (13, 14, 15, 16):
            got = value.fragility(analysis(health=eff))
            self.assertEqual(got["band"], "fragile", f"{eff} HP")
            self.assertEqual(got["eff_health"], eff)

    def test_steady_above_sixteen(self):
        self.assertEqual(value.fragility(analysis(health=17))["band"], "steady")
        self.assertIsNone(value.fragility(analysis(health=17))["note"])

    def test_armor_counts_towards_effective_health(self):
        got = value.fragility(analysis(health=10, armor=6))
        self.assertEqual(got["eff_health"], 16)
        self.assertEqual(got["band"], "fragile")

    def test_no_health_no_band(self):
        self.assertIsNone(value.fragility(analysis()))

    def test_the_note_names_the_next_hit_not_the_hp(self):
        got = value.fragility(analysis(health=14, armor=0, damage_last=9,
                                       damage_recent3=21))
        self.assertIn("a 14-hit ends it", got["note"])
        self.assertIn("took 9 last fight", got["note"])
        self.assertIn("bled 21 over the last 3 fights", got["note"])


class TestThe0918Plan(unittest.TestCase):
    """The exact shape that lost the game must now say something."""

    def test_the_fragility_clause_rides_the_level_lead(self):
        a = analysis(health=16, damage_recent3=0)     # fragile, no bleed memory
        line = value.top_move(a)
        self.assertIn("LEVEL", line)
        self.assertIn("⚠", line, "a fragile level must carry its warning")
        self.assertIn("a 16-hit ends it", line)
        self.assertIn("the board comes first", line)

    def test_a_steady_hero_gets_no_warning(self):
        line = value.top_move(analysis(health=30))
        self.assertNotIn("⚠", line)
        self.assertNotIn("the board comes first", line)

    def test_bleeding_defers_the_level_even_with_no_loss_streak(self):
        """The 09-18 shape: streak reset by a win, damage_last 0, bleed real."""
        a = analysis(health=14, damage_last=0, loss_streak=0, damage_recent3=20)
        line = value.top_move(a)
        self.assertNotIn("1. LEVEL", line, "the level must not lead after a bleed")
        self.assertIn("bled 20 over the last 3 fights", line)
        self.assertIn("buy stats first", line)

    def test_a_small_bleed_does_not_defer_the_level(self):
        line = value.top_move(analysis(health=30, damage_recent3=9))
        self.assertIn("1. LEVEL", line)

    def test_the_bleed_gate_is_mid_game_only(self):
        """Tiers 1-2 stay curve-driven (early losses are cheap and normal)."""
        line = value.top_move(analysis(tier=2, health=30, damage_recent3=20))
        self.assertIn("1. LEVEL", line)

    def test_the_gate_needs_damage_data(self):
        line = value.top_move(analysis(health=30, damage_recent3=None))
        self.assertIn("1. LEVEL", line)

    def test_the_dying_hard_gate_still_outranks_the_band(self):
        a = analysis(health=11, damage_recent3=20)
        self.assertEqual(a["health"] + 0, 11)
        line = value.top_move(a)
        self.assertIn("too fragile to level first", line)
        self.assertNotIn("1. LEVEL", line)

    def test_never_won_still_outranks_the_bleed_gate(self):
        a = analysis(health=30, damage_recent3=20, never_won=True)
        line = value.top_move(a)
        self.assertIn("0 wins so far", line)


class TestSituationDangerLine(unittest.TestCase):
    def test_the_cap_warning_needs_no_lobby_read(self):
        """Whole games logged no opponent at all; gating this on a lobby read
        meant the one line about dying never rendered in them."""
        line = value.situation_line(analysis(health=14, lobby_opp=None,
                                             opp_stats=None))
        self.assertIn("one bad fight ends it", line)

    def test_fragile_without_a_cap_is_still_flagged(self):
        line = value.situation_line(analysis(health=16, damage_cap=None,
                                             damage_recent3=0))
        self.assertIn("16 effective HP", line)
        self.assertIn("the board comes first", line)

    def test_steady_heroes_get_no_danger_clause(self):
        # No lobby, no cap, nothing alive to say — the line may be absent
        # entirely; what matters is that it never claims fragility.
        line = value.situation_line(analysis(health=30)) or ""
        self.assertNotIn("the board comes first", line)
        self.assertNotIn("one bad fight", line)


class TestPlanStepsAreStructured(unittest.TestCase):
    """The overlay renders from split_step, so its contract is the UI contract."""

    def test_the_worst_measured_row_splits_into_one_action_and_clauses(self):
        row = ("LEVEL to tier 4 (standard curve) — 5 left — prices high — "
               "boards ~23 vs lobby ~35; took 6 last fight and lobbies scale up")
        got = value.split_step(row)
        self.assertEqual(got["action"], "LEVEL to tier 4")
        self.assertEqual(got["tag"], "standard curve")
        self.assertEqual(got["reason"], "prices high")
        self.assertIn("5 left", got["details"])
        self.assertIn("boards ~23 vs lobby ~35", got["details"])
        self.assertIn("took 6 last fight and lobbies scale up", got["details"])

    def test_a_cost_figure_is_never_the_reason(self):
        got = value.split_step("LEVEL to tier 5 — 0 left after — prices high")
        self.assertEqual(got["reason"], "prices high")
        self.assertIn("0 left after", got["details"])

    def test_a_caution_outranks_ambient_notes(self):
        got = value.split_step(
            "LEVEL to tier 5 — prices high; only after the buy (bled 20 over "
            "the last 3 fights — buy stats first)")
        self.assertTrue(got["reason"].startswith("only after the buy"))
        self.assertIn("prices high", got["details"])

    def test_a_long_parenthetical_becomes_clauses_not_action(self):
        """Real rows (2026-09-23 tiers 4-5) weld the whole rationale onto the
        verb: 'Play Thorned Trailblazer (golden body — goldens never combine —
        sell to make room)'. The action is the 3 words; the rest is the reason
        and the details."""
        got = value.split_step("Play Thorned Trailblazer (golden body — goldens "
                               "never combine — sell to make room)")
        self.assertEqual(got["action"], "Play Thorned Trailblazer")
        self.assertEqual(got["reason"], "golden body")
        self.assertEqual(got["details"],
                         ["goldens never combine", "sell to make room"])

    def test_a_parenthetical_repeating_the_verb_is_dropped(self):
        got = value.split_step(
            "Hold Unwilling Slacker (hold — 1 regular on board; a 3rd copy "
            "turns it golden)")
        self.assertEqual(got["action"], "Hold Unwilling Slacker")
        self.assertEqual(got["reason"], "1 regular on board",
                         "'hold' is the verb, not a reason")
        self.assertEqual(got["details"], ["a 3rd copy turns it golden"])

    def test_a_bare_parenthetical_is_a_tag_not_a_reason(self):
        """Short, no dash, no semicolon: it labels the action ("golden",
        "growth engine"), so it rides the action as a chip."""
        got = value.split_step("Play Faceless Converter (golden)")
        self.assertEqual(got["action"], "Play Faceless Converter")
        self.assertEqual(got["tag"], "golden")
        self.assertIsNone(got["reason"])

    def test_a_short_trailing_parenthetical_is_a_tag(self):
        got = value.split_step("Buy Glambot (growth engine)")
        self.assertEqual(got["action"], "Buy Glambot")
        self.assertEqual(got["tag"], "growth engine")

    def test_a_plain_step_is_just_an_action(self):
        got = value.split_step("Play Faceless Converter")
        self.assertEqual(got, {"action": "Play Faceless Converter", "tag": None,
                               "reason": None, "details": []})

    def test_steps_ride_the_analysis_and_keep_the_rendered_text(self):
        a = analysis(health=16, damage_recent3=0)
        text = value.top_move(a)
        steps = a["top_move_steps"]
        self.assertEqual(len(steps), len(text.split(" · ")))
        for step in steps:
            self.assertIn(step["kind"],
                          {"level", "pick", "buy", "sell", "roll", "cast",
                           "play", "note"})
            self.assertTrue(step["action"])
        self.assertIn("⚠", steps[0]["reason"] or "",
                      "the fragility warning must be the visible reason")


if __name__ == "__main__":
    unittest.main()
