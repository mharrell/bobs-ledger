"""The Sell row links to the hand's destroy-cost casts: with a Butchering
held, safe-to-sell Undead read 'cast, not sell' (the cast gives permanent
board-wide Attack and frees the same slot; selling gives 1 gold)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import coach_ui


class TestButcheringFuelTag(unittest.TestCase):
    BUTCHER = "BG28_604"
    UNDEAD = "BG36_511"    # Dead Bellringer, Undead
    BEAST = "BG26_162"     # Dancing Barnstormer, Beast

    def _analysis(self, hand, sell_rank):
        return {"board": [], "sell_rank": sell_rank, "hand": hand,
                "shop_rank": [], "hero": "T", "tier": 5, "gold": 3}

    def test_safe_undead_tagged_as_fuel(self):
        a = self._analysis(
            hand=[{"card": self.BUTCHER, "verb": "cast"}],
            sell_rank=[(self.UNDEAD, 8.0), (self.BEAST, 9.0)])
        out = coach_ui.render_json(a)
        by_card = {r["card"]: r for r in out["sell_rank"]}
        self.assertTrue(by_card[self.UNDEAD]["fuel"])
        self.assertFalse(by_card[self.BEAST].get("fuel"))

    def test_no_butchering_no_fuel_tag(self):
        a = self._analysis(hand=[], sell_rank=[(self.UNDEAD, 8.0)])
        out = coach_ui.render_json(a)
        self.assertFalse(out["sell_rank"][0].get("fuel"))

    def test_keep_group_not_tagged(self):
        # Do-not-sell minions aren't fuel candidates.
        a = self._analysis(
            hand=[{"card": self.BUTCHER, "verb": "cast"}],
            sell_rank=[(self.UNDEAD, 40.0)])
        out = coach_ui.render_json(a)
        self.assertFalse(out["sell_rank"][0].get("fuel"))


if __name__ == "__main__":
    unittest.main()