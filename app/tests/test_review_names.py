"""Review display labels: no raw ids for special actions, and a name table.

The Step-through prints the ACTION's card in the caption/track. Hero powers and
the triple's own 0-cost reward spell have no id->name row in the shipped DBs, so
they used to reach the player as `TB_BaconShop_HP_022` / `TB_BaconShop_Triples_01`
(2026-10-18). The hand and tavern tiles are built from ids too, and a saved game
has no live CARDS payload — so the review carries its own name table.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import live_coach  # noqa: E402,F401  (circular-import primer, as in test_art)
import coach_ui     # noqa: E402
import value        # noqa: E402


class TestActionLabels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.names = value._load_bg_names()

    def label(self, cid):
        return coach_ui._action_label(self.names, cid)

    def test_the_triple_reward_is_not_an_id(self):
        self.assertEqual(self.label("TB_BaconShop_Triples_01"), "Triple Reward")

    def test_a_battlegrounds_hero_power_is_named_as_a_kind(self):
        self.assertEqual(self.label("TB_BaconShop_HP_022"), "hero power")
        # The per-hero spelling the old rule already covered.
        self.assertEqual(self.label("BG32_HERO_001p"), "hero power")

    def test_a_premium_tier_zero_minion_resolves_to_its_name(self):
        """TB_BaconUps_159 is Crackling Cyclone's golden (NOT BGS_119_G)."""
        self.assertEqual(self.label("TB_BaconUps_159"),
                         "Crackling Cyclone (golden)")

    def test_a_normal_card_still_uses_the_name_db(self):
        self.assertEqual(self.label("BG27_000"), "Iron Groundskeeper")


class TestTheReviewCarriesNames(unittest.TestCase):
    def test_names_cover_the_hand_tavern_and_special_cards(self):
        rep = coach_ui._name_timeline_boards({
            "timeline": {"turns": [{"turn": 1, "steps": []}]},
        })
        names = rep.get("names") or {}
        self.assertEqual(names.get("BG27_000"), "Iron Groundskeeper",
                         "a hand/tavern id has no name in the review")
        self.assertEqual(names.get("TB_BaconUps_159"),
                         "Crackling Cyclone (golden)")
        self.assertEqual(names.get("BG36_342"), "Clever Castaway")


if __name__ == "__main__":
    unittest.main()
