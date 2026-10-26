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

GS = "D 21:17:13.7844972 GameState.DebugPrintPower() - "


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


class TestTheLogsOwnNames(unittest.TestCase):
    """The name DBs cannot be complete, so the LOG's names come first.

    MEASURED 2026-10-19 on four saved games (23,991 card references): 498 of them
    printed a raw id because `meta/` holds the CURRENT pool only — a rotated minion
    (`BG_GIL_681`, Nightmare Amalgam, 234 references), another set's tavern spell
    (`EBG_Spell_014`, Pointy Arrow, 48), a summoned token, a triple reward. Every
    one of them had its name in the log's own bracket entityName, which
    `board_state.GameState` already parses and dropped on the floor.
    """

    #: A minion id no shipped DB carries, so the test cannot start passing because
    #: a refresh added the row. Verified absent from meta/ on 2026-10-19.
    UNKNOWN = "BG_GIL_681"
    KNOWN = "BG27_000"

    def _gs(self):
        from board_state import GameState
        gs = GameState()
        gs.feed(f"{GS}    FULL_ENTITY - Creating ID=1312 CardID={self.UNKNOWN}")
        gs.feed(f"{GS}    TAG_CHANGE Entity=[entityName=Nightmare Amalgam id=1312 "
                f"zone=PLAY zonePos=0 cardId={self.UNKNOWN} player=1] "
                f"tag=ZONE value=PLAY")
        gs.feed(f"{GS}    TAG_CHANGE Entity=[entityName=Iron Groundskeeper id=1313 "
                f"zone=PLAY zonePos=0 cardId={self.KNOWN} player=1] "
                f"tag=ZONE value=PLAY")
        return gs

    def test_the_parser_keeps_the_name_the_log_gave_a_card(self):
        names = self._gs().entity_names()
        self.assertEqual(names.get(self.UNKNOWN), "Nightmare Amalgam",
                         "the log named the card and the parser dropped it")
        self.assertEqual(names.get(self.KNOWN), "Iron Groundskeeper")

    def test_the_log_name_reaches_every_surface(self):
        """One merge, so the board rows, the step tiles AND the id->name table the
        client resolves hand/tavern tiles from all see it."""
        rep = coach_ui._name_timeline_boards({
            "timeline": {
                "log_names": {self.UNKNOWN: "Nightmare Amalgam"},
                "turns": [{
                    "turn": 2,
                    "buy_end": [{"card": self.UNKNOWN, "atk": 2, "health": 3}],
                    "steps": [{"k": "buy", "card": self.UNKNOWN,
                               "board": [{"card": self.UNKNOWN}]}],
                }],
            },
        })
        row = rep["timeline"]["turns"][0]
        self.assertEqual(row["buy_end"][0]["name"], "Nightmare Amalgam",
                         "a board tile still shows the id")
        self.assertEqual(row["steps"][0]["board"][0]["name"],
                         "Nightmare Amalgam", "a step tile still shows the id")
        self.assertEqual(row["steps"][0]["cardName"], "Nightmare Amalgam",
                         "the step caption still shows the id")
        self.assertEqual((rep.get("names") or {}).get(self.UNKNOWN),
                         "Nightmare Amalgam",
                         "the client-side hand/tavern table cannot name it")

    def test_a_name_the_dbs_know_still_wins(self):
        """The log's name is the FALLBACK, not an override: the DB's spelling is the
        curated one and it is the only place "(golden)" is spelled out."""
        rep = coach_ui._name_timeline_boards({
            "timeline": {
                "log_names": {"TB_BaconUps_159": "Crackling Cyclone"},
                "turns": [{"turn": 1, "buy_end": [{"card": "TB_BaconUps_159"}]}],
            },
        })
        self.assertEqual(rep["timeline"]["turns"][0]["buy_end"][0]["name"],
                         "Crackling Cyclone (golden)",
                         "a log name replaced the DB's golden spelling")

    def test_the_review_records_the_names_it_measured(self):
        """`turn_review.timeline` puts `log_names` on the timeline, so a SAVED
        review keeps them: the log rotates, and a review opened next week has only
        what the rep carries."""
        import inspect
        import turn_review
        src = inspect.getsource(turn_review.timeline_from_drive)
        self.assertIn('"log_names"', src,
                      "timeline() stopped recording the log's names")
        self.assertIn("_log_names(", inspect.getsource(turn_review))
        # Only the MISSES, or a saved replay grows by every name it already had.
        helper = inspect.getsource(turn_review._log_names)
        self.assertIn("display_name(known, cid) == cid", helper,
                      "the log-name map is not limited to the DB's misses")


if __name__ == "__main__":
    unittest.main()
