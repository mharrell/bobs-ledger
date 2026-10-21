"""The model-vs-player comparison derived at build (2026-10-20).

Four things are worth pinning harder than usual here, because each of them is a
way the comparison could quietly become a claim it cannot support:

  * `not_reached` is about the PLAN's own purse, not the player's choice. A
    phase where the plan could not pay for a step must not read "you didn't do
    it" (COACHING_PLAN §3.5.1);
  * `not_comparable` is inherited from `outcome_audit.disagreement_rows`: a card
    the coach never priced is not evidence of anything, and a sell step names no
    id at all (§3.5, §5.1);
  * a turn that took the model's card and ALSO bought something else is `same` —
    the `taken` lesson settle_up.py:224-230, which the summary must not undo;
  * nothing here may reach the Live page. The module is build-time only, and the
    guard is that the three live-path modules never import it.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import coach_diff  # noqa: E402
import replay_store  # noqa: E402


def _row(**over):
    """One `outcome_audit.audit_game` row, minimal but realistic."""
    r = {"turn": 5, "tier": 3, "gold": 9, "level_cost": 7,
         "lead": "buy", "card": None, "steps": [],
         "player_buys": [], "player_actions": {},
         "spells_cast": [], "plays": [],
         "shop_rank": [], "shop_costs": {}}
    r.update(over)
    return r


def _step(kind, card=None, reason=None, text=None):
    s = {"kind": kind, "card": card}
    if reason:
        s["reason"] = reason
    if text:
        s["text"] = text
    return s


def _by_kind(rows):
    return {r["kind"]: r for r in rows}


class TestBuy(unittest.TestCase):
    def test_a_named_card_bought_beside_a_second_buy_is_same(self):
        """The `taken` lesson: taking the model's card is not a difference
        because the player also bought a second thing."""
        rows = coach_diff.for_phase(_row(
            steps=[_step("buy", "BG_A")],
            player_buys=["BG_A", "BG_B"]))
        buy = _by_kind(rows)["buy"]
        self.assertEqual(buy["state"], "same")
        self.assertEqual(buy["player"]["cards"], ["BG_A", "BG_B"])

    def test_skipping_one_of_two_named_cards_differs(self):
        """The summary lists both sides, so a replaced card IS a difference —
        but only when a named card is missing, not when an extra one was added."""
        rows = coach_diff.for_phase(_row(
            steps=[_step("buy", "BG_A"), _step("buy", "BG_B")],
            player_buys=["BG_A", "BG_C"]))
        buy = _by_kind(rows)["buy"]
        self.assertEqual(buy["state"], "differs")
        self.assertEqual(buy["model"]["cards"], ["BG_A", "BG_B"])

    def test_a_buy_the_plan_never_asked_for_differs(self):
        rows = coach_diff.for_phase(_row(steps=[], player_buys=["BG_A"]))
        self.assertEqual(_by_kind(rows)["buy"]["state"], "differs")
        self.assertFalse(_by_kind(rows)["buy"]["model"]["asked"])

    def test_an_unaffordable_buy_is_not_reached_not_not_taken(self):
        rows = coach_diff.for_phase(_row(
            gold=2, steps=[_step("buy", "BG_A")], player_buys=[]))
        self.assertEqual(_by_kind(rows)["buy"]["state"], "not_reached")

    def test_buying_it_anyway_makes_it_same_whatever_the_purse_said(self):
        """`not_reached` is about the plan's arithmetic. If the player bought
        the card, they paid for it — a short purse does not override that."""
        rows = coach_diff.for_phase(_row(
            gold=2, steps=[_step("buy", "BG_A")], player_buys=["BG_A"]))
        self.assertEqual(_by_kind(rows)["buy"]["state"], "same")

    def test_a_buy_step_with_no_resolved_card_is_not_comparable(self):
        rows = coach_diff.for_phase(_row(steps=[_step("buy", None)],
                                         player_buys=["BG_A"]))
        self.assertEqual(_by_kind(rows)["buy"]["state"], "not_comparable")

    def test_margin_is_model_best_minus_player_best(self):
        rows = coach_diff.for_phase(_row(
            steps=[_step("buy", "BG_A")], player_buys=["BG_B"],
            shop_rank=[["BG_A", 9.0], ["BG_B", 7.0]]))
        buy = _by_kind(rows)["buy"]
        self.assertEqual(buy["state"], "differs")
        self.assertAlmostEqual(buy["margin"], 2.0)
        self.assertIn("9.0", buy["why"])
        self.assertIn("7.0", buy["why"])

    def test_a_close_margin_has_no_why_line(self):
        rows = coach_diff.for_phase(_row(
            steps=[_step("buy", "BG_A")], player_buys=["BG_B"],
            shop_rank=[["BG_A", 7.2], ["BG_B", 7.0]]))
        buy = _by_kind(rows)["buy"]
        self.assertIsNotNone(buy["margin"])
        self.assertIsNone(buy["why"], "a 0.2 gap is not a preference")

    def test_an_unpriced_player_buy_has_no_margin(self):
        """The player rolled before buying; the card is not on the coach's
        ranking and the subtraction would be meaningless."""
        rows = coach_diff.for_phase(_row(
            steps=[_step("buy", "BG_A")], player_buys=["BG_X"],
            shop_rank=[["BG_A", 9.0]]))
        buy = _by_kind(rows)["buy"]
        self.assertEqual(buy["state"], "differs")
        self.assertIsNone(buy["margin"])
        self.assertIsNone(buy["why"])

    def test_a_negative_margin_keeps_the_number_but_writes_no_why(self):
        """The plan may name a card its score ranks BELOW the player's buy —
        that is the model having a reason the score cannot carry, and the
        reason is on the row instead."""
        rows = coach_diff.for_phase(_row(
            steps=[_step("buy", "BG_A", reason="committing to Mech")],
            player_buys=["BG_B"],
            shop_rank=[["BG_A", 5.0], ["BG_B", 8.0]]))
        buy = _by_kind(rows)["buy"]
        self.assertEqual(buy["margin"], -3.0)
        self.assertIsNone(buy["why"])
        self.assertEqual(buy["reason"], "committing to Mech")


class TestLevel(unittest.TestCase):
    def test_asked_and_done_is_same_and_carries_the_tier(self):
        rows = coach_diff.for_phase(_row(
            steps=[_step("level")], tier=4,
            player_actions={"upgrades": 1}))
        level = _by_kind(rows)["level"]
        self.assertEqual(level["state"], "same")
        self.assertTrue(level["player"]["did"])
        self.assertEqual(level["tier"], {"from": 4, "to": 5})
        self.assertIsNone(level["margin"], "a yes/no has no score margin")

    def test_asked_and_not_done_is_differs(self):
        rows = coach_diff.for_phase(_row(steps=[_step("level")], tier=4))
        self.assertEqual(_by_kind(rows)["level"]["state"], "differs")

    def test_an_unaffordable_level_is_not_reached(self):
        rows = coach_diff.for_phase(_row(
            gold=5, level_cost=7, steps=[_step("level")]))
        self.assertEqual(_by_kind(rows)["level"]["state"], "not_reached")

    def test_levelling_with_no_plan_step_differs(self):
        rows = coach_diff.for_phase(_row(
            steps=[], player_actions={"upgrades": 1}))
        self.assertEqual(_by_kind(rows)["level"]["state"], "differs")
        self.assertTrue(_by_kind(rows)["level"]["player"]["did"])


class TestSellPlayCast(unittest.TestCase):
    def test_a_sell_both_sides_made_is_not_comparable(self):
        """A sell step names its victim in prose only — there is no id to match
        the log's sell against, and guessing is 'formatting used as data'."""
        rows = coach_diff.for_phase(_row(
            steps=[_step("sell", text="sell Glambot")],
            player_actions={"sells": ["BG_D"]}))
        sell = _by_kind(rows)["sell"]
        self.assertEqual(sell["state"], "not_comparable")
        self.assertEqual(sell["player"]["cards"], ["BG_D"])

    def test_a_sell_only_the_player_made_differs(self):
        rows = coach_diff.for_phase(_row(
            steps=[], player_actions={"sells": ["BG_D"]}))
        self.assertEqual(_by_kind(rows)["sell"]["state"], "differs")

    def test_play_and_cast_match_on_the_plan_s_own_card(self):
        rows = coach_diff.for_phase(_row(
            steps=[_step("play", "BG_P"), _step("cast", "BG_S1")],
            plays=["BG_P"], spells_cast=["BG_S2"]))
        got = _by_kind(rows)
        self.assertEqual(got["play"]["state"], "same")
        self.assertEqual(got["cast"]["state"], "differs")

    def test_an_unresolved_cast_is_not_comparable(self):
        rows = coach_diff.for_phase(_row(
            steps=[_step("cast", None)], spells_cast=["BG_S"]))
        self.assertEqual(_by_kind(rows)["cast"]["state"], "not_comparable")

    def test_a_pick_is_never_comparable(self):
        """A pick names a hero power or trinket the shop ranking never prices,
        and the audit row carries no player pick."""
        rows = coach_diff.for_phase(_row(steps=[_step("pick")]))
        self.assertEqual(_by_kind(rows)["pick"]["state"], "not_comparable")


class TestOrderAndEmpty(unittest.TestCase):
    def test_rows_come_in_the_display_order(self):
        rows = coach_diff.for_phase(_row(
            steps=[_step("buy", "BG_A"), _step("level"), _step("roll")],
            player_buys=["BG_A"], player_actions={"upgrades": 1}))
        self.assertEqual([r["kind"] for r in rows], ["level", "buy", "roll"])

    def test_no_plan_and_no_actions_is_no_rows(self):
        self.assertEqual(coach_diff.for_phase(_row()), [])

    def test_an_unknown_purse_makes_no_affordability_claim(self):
        rows = coach_diff.for_phase(_row(
            gold=None, steps=[_step("level")], level_cost=7))
        self.assertNotEqual(_by_kind(rows)["level"]["state"], "not_reached")


class TestConfidence(unittest.TestCase):
    def test_a_strong_positive_margin_is_high(self):
        self.assertEqual(coach_diff.confidence(
            [{"margin": 3.5}, {"margin": -2.0}]), "high")

    def test_a_clear_but_small_margin_is_medium(self):
        self.assertEqual(coach_diff.confidence([{"margin": 2.0}]), "medium")

    def test_a_small_margin_is_no_confidence_at_all(self):
        self.assertIsNone(coach_diff.confidence([{"margin": 0.4}]))
        self.assertIsNone(coach_diff.confidence([{"margin": 0.0}]))

    def test_a_negative_margin_never_raises_confidence(self):
        self.assertIsNone(coach_diff.confidence([{"margin": -4.0}]))

    def test_no_margins_is_none(self):
        self.assertIsNone(coach_diff.confidence([]))


class TestEvidence(unittest.TestCase):
    """Decision 3: difference counts from the player's OWN saved games, as a
    floor on how often the two disagreed — never a claim the model was right."""

    def setUp(self):
        coach_diff._EVIDENCE.clear()
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = self.td.name

    def _save(self, phases, rid=None):
        rep = {"schema": 2, "created": "2026-10-20T10:00:00", "hero": "Reno",
               "placement": 2, "game": 1, "session": "Hearthstone_x",
               "log": "Power.log", "phases": phases}
        replay_store.save(rep, root=self.root, rid=rid)

    def test_a_rebuilt_save_counts_each_differing_kind_once(self):
        self._save([{"kind": "ignored", "lead": "buy", "coach_diff": [
            {"kind": "buy", "state": "differs"},
            {"kind": "level", "state": "differs"},
            {"kind": "play", "state": "same"},
        ]}])
        ev = coach_diff.saved_evidence(root=self.root)
        self.assertEqual(ev["games"], 1)
        self.assertEqual(ev["by_kind"], {"buy": 1, "level": 1})

    def test_an_old_save_contributes_its_un_taken_lead(self):
        self._save([
            {"kind": "ignored", "lead": "level"},
            {"kind": "taken", "lead": "buy"},
            {"kind": "ignored", "lead": "hunt-roll"},
        ])
        ev = coach_diff.saved_evidence(root=self.root)
        self.assertEqual(ev["by_kind"], {"level": 1, "roll": 1})

    def test_the_count_is_cached_on_the_store_signature(self):
        self._save([{"kind": "ignored", "lead": "level"}])
        first = coach_diff.saved_evidence(root=self.root)
        with mock.patch.object(replay_store, "list",
                               side_effect=AssertionError("rescanned")):
            again = coach_diff.saved_evidence(root=self.root)
        self.assertIs(first, again)

    def test_an_empty_store_says_nothing(self):
        ev = coach_diff.saved_evidence(root=self.root)
        self.assertEqual(ev["games"], 0)
        self.assertIsNone(coach_diff.evidence_line(ev, "level"))

    def test_the_line_names_the_kind_and_the_game_count(self):
        line = coach_diff.evidence_line(
            {"games": 18, "by_kind": {"level": 9}}, "level")
        self.assertEqual(line, "we differed on 9 level-ups across your 18 "
                               "saved games")
        self.assertIn("1 saved game",
                      coach_diff.evidence_line({"games": 1,
                                                "by_kind": {"buy": 1}}, "buy"))


class TestTheWall(unittest.TestCase):
    """The comparison is build-time only. The live path must not import it —
    a third mechanism beside LIVE_VERDICT_KEYS/LIVE_UNREAD_KEYS is how the wall
    gets a door in it (COACHING_PLAN §4)."""

    def test_no_live_path_module_imports_coach_diff(self):
        for name in ("live.py", "live_coach.py", "coach_ui.py"):
            with open(os.path.join(HERE, name), encoding="utf-8") as fh:
                src = fh.read()
            self.assertNotIn("import coach_diff", src, name)
            self.assertNotIn("from coach_diff", src, name)


if __name__ == "__main__":
    unittest.main()
