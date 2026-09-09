"""The overlay's per-card metadata: render_json attaches a cards map
({card id: {tier, text}}) covering every card id on screen — the '*N'
tier badge in tile names and the hover tooltip's text fallback come
from it. Golden ids resolve to their base card (golden minions share
the pool tier; /card/ serves the base render)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import coach_ui


class TestCardMetaMap(unittest.TestCase):
    MINION = "BG36_508"      # tier 4 in meta/minions.json
    SPELL = "BG34_689"       # tier 3 tavern spell

    def _analysis(self, extra=None):
        a = {"board": [], "sell_rank": [(self.MINION, 8.0)],
             "hand": [], "shop_rank": [(self.SPELL, 5.0)],
             "hero": "T", "tier": 5, "gold": 3}
        if extra:
            a.update(extra)
        return a

    def test_minion_and_spell_tier_in_map(self):
        out = coach_ui.render_json(self._analysis())
        self.assertEqual(out["cards"][self.MINION]["tier"], 4)
        self.assertEqual(out["cards"][self.SPELL]["tier"], 3)
        self.assertTrue(out["cards"][self.MINION].get("text"))
        self.assertTrue(out["cards"][self.SPELL].get("text"))

    def test_golden_id_resolves_to_base(self):
        a = self._analysis({"sell_rank": [(self.MINION + "_G", 8.0)]})
        out = coach_ui.render_json(a)
        self.assertEqual(out["cards"][self.MINION]["tier"], 4)

    def test_hero_pick_row_gets_no_badge(self):
        # Heroes carry no tier in the DBs — the choice rows pass through the
        # map collection without producing an entry, so the UI shows bare
        # names for hero picks (an unknown tier must never read as *1).
        a = self._analysis({"choice": {"kind": "hero",
                                       "ranked": [("Some Hero", "BG22_HERO_001", 4.2, "")]}})
        out = coach_ui.render_json(a)
        self.assertNotIn("BG22_HERO_001", out["cards"])

    def test_unknown_card_absent(self):
        # An id outside every DB (a log-only hero power, say) just doesn't
        # appear — the UI must not invent a tier for it.
        a = self._analysis({"shop_rank": [("NOT_A_REAL_ID", 5.0)]})
        out = coach_ui.render_json(a)
        self.assertNotIn("NOT_A_REAL_ID", out["cards"])


if __name__ == "__main__":
    unittest.main()