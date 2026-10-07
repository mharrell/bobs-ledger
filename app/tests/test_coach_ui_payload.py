"""render_json payload contract for the overlay's Phase-1 perf work:
thresholds come from value.py's constants (the JS no longer hard-codes its
own copies), the dead buy_label is gone, and the fuel gate keys on the
same threshold the sell split uses."""
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import coach_ui  # noqa: E402
from value import DYING_HEALTH, SELL_FILLER_SCORE  # noqa: E402


def _base_analysis():
    return {
        "board": [],
        "sell_rank": [],
        "hand": [],
        "shop_rank": [],
        "comps": [],
        "comp_progress": [],
        "playable_comps": {},
    }


class TestThresholdsPayload(unittest.TestCase):
    def test_thresholds_match_value_constants(self):
        out = coach_ui.render_json(_base_analysis())
        self.assertEqual(out["thresholds"]["dying_hp"], DYING_HEALTH)

    def test_the_sell_split_threshold_is_gone(self):
        """It existed only to draw the "Safe to sell | Do not sell" split, and
        that split WAS the verdict (2026-10-06, PIVOT.md). SELL_FILLER_SCORE is
        still a value.py constant and still gates the destroy-spell fuel tag —
        the payload just has no consumer for it now."""
        self.assertNotIn("sell_safe_below",
                         coach_ui.render_json(_base_analysis())["thresholds"])

    def test_the_plan_is_not_in_the_payload(self):
        """Was `buy_label`; the whole plan went in the same direction, and
        test_live_view.py owns the full contract."""
        a = _base_analysis()
        a["top_move"] = "1. LEVEL to tier 5"
        a["top_move_steps"] = [{"text": "LEVEL", "kind": "level"}]
        out = coach_ui.render_json(a)
        self.assertNotIn("buy_label", out)
        self.assertNotIn("top_move", out)
        self.assertNotIn("top_move_steps", out)
        self.assertIn("top_move", a, "the analysis keeps the plan")


class TestFuelGate(unittest.TestCase):
    """The Butchering-fuel annotation must key on the SAME threshold the
    safe/keep split uses — one constant, not a re-hard-coded literal."""

    def _run_fuel(self, score):
        analysis = {
            "board": [{"card": "ZZZ_TEST_UNDEAD"}],
            "sell_rank": [("ZZZ_TEST_UNDEAD", score)],
            "hand": [{"card": "ZZZ_TEST_SPELL"}],
            "shop_rank": [],
            "comps": [],
            "comp_progress": [],
            "playable_comps": {},
        }
        with mock.patch.object(coach_ui, "_load_spell_db") as sdb, \
             mock.patch.object(coach_ui, "_load_card_db") as cdb:
            sdb.return_value = {"ZZZ_TEST_SPELL": {
                "text": "Destroy a friendly minion."}}
            cdb.return_value = {"ZZZ_TEST_UNDEAD": {"race": "Undead"}}
            return coach_ui.render_json(analysis)["sell_rank"][0]

    def test_undead_below_threshold_is_fuel(self):
        self.assertTrue(self._run_fuel(SELL_FILLER_SCORE - 1).get("fuel"))

    def test_undead_at_threshold_is_not_fuel(self):
        self.assertIsNone(self._run_fuel(SELL_FILLER_SCORE).get("fuel"))


class TestSharingRidesEveryPayload(unittest.TestCase):
    """The consent answer is reachable for the whole session, not just on the
    welcome card (2026-10-07).

    The "stop sharing" control used to live on the welcome/end-of-game card,
    which is on screen only at a game's start or end — so during the game it
    described, sharing could not be turned off from the page at all. It is a
    quiet line in the top-right corner now, and the corner renders from EVERY
    payload, so every payload has to carry the state.
    """

    def test_the_live_payload_carries_the_consent_state(self):
        out = coach_ui.render_json(_base_analysis())
        self.assertIn("share", out)
        self.assertIn(out["share"]["status"], ("on", "off", "undecided"))
        self.assertIn("toggle", out["share"], "the corner needs its label")
        self.assertEqual(out["share"]["ask"],
                         out["share"]["status"] == "undecided")

    def test_the_welcome_card_and_the_live_page_agree(self):
        """One builder: a player must never see the card say one thing and the
        corner another. `welcome_payload` returns the serialized body, so this
        reads it back the way the page does."""
        live = coach_ui.render_json(_base_analysis())["share"]
        welcome = json.loads(coach_ui.welcome_payload())["share"]
        self.assertEqual(live, welcome)

    def test_the_consent_key_is_not_an_analysis_field(self):
        """It is added in render_json, so it never reaches decision_log and
        never reaches session_report.SPEC — whose whitelist REFUSES any
        analysis key it does not name (the 2026-10-07 hand_step_cards lesson)."""
        a = _base_analysis()
        coach_ui.render_json(a)
        self.assertNotIn("share", a)


if __name__ == "__main__":
    unittest.main()
