"""render_json payload contract for the overlay's Phase-1 perf work:
thresholds come from value.py's constants (the JS no longer hard-codes its
own copies), the dead buy_label is gone, and the fuel gate keys on the
same threshold the sell split uses."""
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


if __name__ == "__main__":
    unittest.main()
