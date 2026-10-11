"""THE LIVE VIEW CONTRACT: the overlay ships state, never a verdict.

2026-10-06, PIVOT.md. The product split in two: the live path reads the board,
and the model's actual plan — the numbered steps, the buy it names, the pick —
is shown only after the fact, in the review, where the decision it describes
can no longer be acted on. `render_json` is the ONE place the page's view is
built, so it is the one place the split has to hold.

Why this file is worth its length: the pivot is only real if it cannot quietly
revert. Deleting the plan from the page while leaving `top_move` in the payload
would pass every other test in this suite while shipping the same advice with a
different label. Three independent halves have to hold, and each is asserted
here:

  1. `LIVE_VERDICT_KEYS` is dropped from what the page receives;
  2. the ANALYSIS keeps every one of them — it is what the decision log writes
     and what the review reads back, so a "fix" that deletes the producer
     instead of the rendering would break the product's only real asset;
  3. the page does not READ any of them, and none of the directive wordings
     survive in the page source.

There is no `HEARTH_REAL_SESSION_TESTS` gate on any of this: it is pure
function behaviour over a fixture, so it runs everywhere, including in a
release zip with no logs on disk.
"""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import coach_ui  # noqa: E402
from coach_ui import LIVE_VERDICT_KEYS  # noqa: E402

_HTML = coach_ui._HTML


def _without_comments(html):
    """The page with /* */ blocks and full-line // comments removed.

    See TestTheDirectiveWordingsAreGone for why this exists rather than a
    plain substring search.
    """
    import re
    body = re.sub(r"/\*.*?\*/", "", html, flags=re.S)
    return "\n".join(ln for ln in body.splitlines()
                     if not ln.strip().startswith("//"))

#: Every verdict key, with a realistic value. The values matter: a key mapped
#: to None could be "absent" for the wrong reason, so each carries the payload
#: it would really hold.
_VERDICT_VALUES = {
    "top_move": "1. LEVEL (access to tier 4) · 2. Buy Bronze Warden",
    "top_move_steps": [{"text": "LEVEL", "kind": "level", "action": "LEVEL",
                        "tag": "access to tier 4", "reason": "",
                        "details": [], "card": None}],
    "buy_this": "BG36_116",
    "buy_step_card": "BG36_116",
    "buy_step_roll": None,
    "buy_step_swap_veto": "Underrot Spawn",
    "buy_roll_text": "Roll for a better shop",
    "discard_target": {"card": "BG36_114", "name": "Parasitic Fleshling"},
    "hand_plan": [{"card": "BG36_114", "name": "X", "verb": "play",
                   "score": 4.0, "why": "a free body"}],
    "hunt_targets": ["BG36_116"],
    "target_state": "pivot",
}

#: The state the page is FOR. If the pivot ever removes the product instead of
#: the verdict, these are what fails.
_STATE_VALUES = {
    "situation": "turning point — you lead the lobby",
    "board_stats": 120,
    "lobby_opp": 90,
    "scout": "you 120 stats · ~90 theirs",
    "fragility": {"band": "steady", "eff_health": 30},
    "forecast": "favored",
    "comp_progress": [{"name": "Mechs - Y", "hits": 2, "ready": True,
                       "needs": []}],
}


def _analysis(**over):
    a = {"board": [{"card": "BG23_318", "atk": 3, "health": 4},
                   {"card": "BG36_114", "atk": 1, "health": 2}],
         "sell_rank": [("BG23_318", 12.0), ("BG36_114", 4.0)],
         "hand": [{"card": "BG36_114", "name": "X", "verb": "play",
                   "score": 4.0, "why": "a free body"}],
         "shop_rank": [("BG36_116", 9.0), ("BG28_810", 3.0)],
         "shop_offers": ["BG28_810", "BG36_116"],
         "comps": [], "comp_progress": [], "playable_comps": {},
         "target_comp": "Mechs - Y", "target_cards": {"core": [], "addons": []},
         "thresholds": {}}
    a.update(_VERDICT_VALUES)
    a.update(_STATE_VALUES)
    a.update(over)
    return a


class TestTheVerdictNeverReachesThePage(unittest.TestCase):
    def test_every_verdict_key_is_dropped(self):
        out = coach_ui.render_json(_analysis())
        leaked = sorted(k for k in LIVE_VERDICT_KEYS if k in out)
        self.assertEqual(leaked, [],
                         "verdict keys in the live payload: " + ", ".join(leaked))

    def test_the_fixture_covers_the_whole_dropped_set(self):
        """The guard that keeps the test above honest: if value.py or
        live_coach grows a verdict field and someone adds it to
        LIVE_VERDICT_KEYS without a fixture value, this fails instead of the
        absence test silently passing on a key nobody supplied."""
        self.assertEqual(set(_VERDICT_VALUES), set(LIVE_VERDICT_KEYS))

    def test_the_analysis_keeps_every_verdict(self):
        """The other half of the pivot, and the one a careless "fix" breaks:
        dropping these from the payload must NOT touch the analysis. It is
        what decision_log.record() writes and what replay_review/outcome_audit
        read back."""
        a = _analysis()
        coach_ui.render_json(a)
        missing = sorted(k for k in LIVE_VERDICT_KEYS if k not in a)
        self.assertEqual(missing, [],
                         "the analysis lost: " + ", ".join(missing))
        self.assertEqual(a["top_move"], _VERDICT_VALUES["top_move"])

    def test_no_page_code_reads_a_dropped_key(self):
        """A JS line reading `a.top_move` would render nothing forever — the
        exact silent failure the old KIND_CHIP drift guard existed to catch."""
        reads = sorted(k for k in LIVE_VERDICT_KEYS if "a." + k in _HTML)
        self.assertEqual(reads, [],
                         "the page still reads dropped fields: " + ", ".join(reads))


class TestTheStateStillShips(unittest.TestCase):
    def test_state_fields_survive(self):
        out = coach_ui.render_json(_analysis())
        for key in ("board", "situation", "fragility", "scout", "forecast",
                    "sell_rank", "shop_rank", "hand", "comp_progress",
                    "thresholds", "generated"):
            self.assertIn(key, out, f"{key} left the live payload")

    def test_dying_hp_threshold_still_ships(self):
        from value import DYING_HEALTH
        self.assertEqual(coach_ui.render_json(_analysis())["thresholds"]["dying_hp"],
                         DYING_HEALTH)

    def test_sell_safe_below_is_gone(self):
        """It only ever fed the "Safe to sell | Do not sell" split, which was
        the verdict itself. An unused key is the `dark_gifts` trade again:
        leaving it would keep shipping payload the page has no use for."""
        self.assertNotIn("sell_safe_below",
                         coach_ui.render_json(_analysis())["thresholds"])


class TestTavernIsNotRanked(unittest.TestCase):
    """A tier score beside a card is a fact. A row ORDERED by it, with the
    top one lit up, is a recommendation — and the recommendation is what the
    live path gives up. The row follows the log's own offer order."""

    def test_row_follows_the_games_offer_order(self):
        # shop_rank arrives score-sorted (9.0 then 3.0); shop_offers is the
        # log's order and is the opposite, so input order cannot pass by luck.
        out = coach_ui.render_json(_analysis())
        self.assertEqual([s["card"] for s in out["shop_rank"]],
                         ["BG28_810", "BG36_116"])

    def test_score_and_price_survive_as_facts(self):
        out = coach_ui.render_json(_analysis())
        row = {s["card"]: s for s in out["shop_rank"]}
        self.assertEqual(row["BG36_116"]["score"], 9)
        self.assertIsNotNone(row["BG36_116"].get("price"))

    def test_no_offer_order_never_falls_back_to_best_first(self):
        # An analysis recorded before `shop_offers` existed (the review renders
        # old records), or a shop that has not parsed. The input arrives
        # score-sorted, so keeping it would quietly restore the ranking — the
        # one thing this row must never be again. Arbitrary is fine.
        a = _analysis()
        a.pop("shop_offers")
        out = coach_ui.render_json(a)
        self.assertEqual([s["card"] for s in out["shop_rank"]],
                         sorted(["BG36_116", "BG28_810"]))

    def test_a_duplicated_offer_renders_twice(self):
        # Two copies of one minion can sit in one tavern, and the game shows two
        # cards. The row used to be keyed onto the card-keyed `shop_rank`, so the
        # second copy vanished (round-3 fix list item 1): it is built from the
        # per-OFFER entity list now, so the row keeps the game's own count.
        a = _analysis(shop_offers=["BG36_116", "BG28_810", "BG36_116"],
                      shop_entities=[{"eid": 1, "card": "BG36_116"},
                                     {"eid": 2, "card": "BG28_810"},
                                     {"eid": 3, "card": "BG36_116"}])
        out = coach_ui.render_json(a)
        self.assertEqual([s["card"] for s in out["shop_rank"]],
                         ["BG36_116", "BG28_810", "BG36_116"])
        self.assertEqual([s["eid"] for s in out["shop_rank"]], [1, 2, 3])

    def test_an_offer_list_without_entities_still_renders_its_copies(self):
        """A payload recorded before `shop_entities` existed (the review renders
        old records) still has the offer ORDER and its duplicates: the row is one
        card per offer, with no entity id to key it by."""
        a = _analysis(shop_offers=["BG36_116", "BG28_810", "BG36_116"])
        out = coach_ui.render_json(a)
        self.assertEqual([s["card"] for s in out["shop_rank"]],
                         ["BG36_116", "BG28_810", "BG36_116"])
        self.assertEqual([s["eid"] for s in out["shop_rank"]], [None, None, None])

    def test_the_board_row_is_one_card_per_minion(self):
        """The same dedupe lived in the board row: it drew the classic Sell row,
        which groups BY CARD ("×2"). `board_cards` is one entry per board
        minion, so two copies of one minion are two cards."""
        a = _analysis(board=[{"card": "BG36_116", "atk": 5, "health": 5,
                              "tribe": "BEAST"},
                             {"card": "BG36_116", "atk": 9, "health": 9,
                              "tribe": "BEAST"}],
                      sell_rank=[("BG36_116", 12), ("BG36_116", 30)])
        out = coach_ui.render_json(a)
        self.assertEqual([r["atk"] for r in out["board_cards"]], [5, 9],
                         "two identical minions are one entity each")
        self.assertEqual(len(out["sell_rank"]), 1,
                         "the classic Sell row still groups by card")
        self.assertEqual(out["sell_rank"][0]["n"], 2)


class TestHandRowsAreFacts(unittest.TestCase):
    def test_hand_has_no_action_verb_and_no_plan_reason(self):
        out = coach_ui.render_json(_analysis())
        self.assertTrue(out["hand"])
        for row in out["hand"]:
            self.assertNotIn("verb", row, "an action verb is an instruction")
            self.assertNotIn("why", row, "the plan's reason is an instruction")
            self.assertIn("name", row)

    def test_the_plan_still_has_them(self):
        a = _analysis()
        coach_ui.render_json(a)
        self.assertEqual(a["hand"][0]["verb"], "play")


class TestTheDirectiveWordingsAreGone(unittest.TestCase):
    """The wordings a player would read as an instruction. Cheap, and they are
    the ones a later branch is most likely to reintroduce by hand.

    Comments are stripped first, and that is not a loophole: the page's own
    source EXPLAINS what was removed — "this pane was headed 'Do this now'" —
    so a naive text search fails on the explanation rather than on a
    regression, which is exactly what it did the first time this test ran.
    Only `/* */` blocks and full-line `//` comments are removed, so an inline
    `x = 'Do this now'` would still be caught: the stripping errs toward
    searching too much, never too little.
    """

    _GONE = ("Do this now", "Safe to sell", "Do not sell", "Tavern (ranked)",
             "Looking for (", "play your chargers", "cast, not sell")

    def test_page_carries_no_directive_wording(self):
        body = _without_comments(_HTML)
        for text in self._GONE:
            self.assertNotIn(text, body, f"the page still says {text!r}")

    def test_the_step_chip_vocabulary_is_gone(self):
        self.assertNotIn("KIND_CHIP", _without_comments(_HTML))

    def test_value_still_types_its_steps(self):
        "The plan is not deleted — it is only kept off the live page."
        from value import _STEP_KINDS
        self.assertTrue({k for _prefix, k in _STEP_KINDS})


class TestThePickIsNotNamed(unittest.TestCase):
    """The hero pick is the most consequential decision of the game, and
    live._advise_pick hand-built "1. PICK X — if locked, Y" into a minimal
    payload for it. This asserts BEHAVIOUR rather than source text, for the
    same reason as above: the source explains the removal.
    """

    class _Coach:
        choice = {"picked": None, "options": ["A", "B"], "ctype": "hero",
                  "source": "hero pick"}
        game_no = 1
        tribes_seen = 0
        _bans_ready = True

    def _advise(self):
        import live
        ranked = [["Alpha", "A", 7.5, "best fit"], ["Beta", "B", 6.0, ""]]
        pushed = {}
        # The dedup key is a module global: a second call with the same state
        # returns early and pushes nothing, which would make an empty payload
        # look like a clean result.
        live._last_state = None
        with mock.patch.object(live, "rank_choices", return_value=ranked), \
             mock.patch.object(live, "choice_kind", return_value="hero"), \
             mock.patch.object(live.coach_ui, "latest_manual_bans",
                               return_value=[]), \
             mock.patch.object(live.coach_ui, "update_analysis",
                               side_effect=lambda a: pushed.update(a)), \
             mock.patch.object(live.decision_log, "record"):
            live._advise_pick(self._Coach(), log_path="P.log", log_offset=1,
                              game_no=1)
        return pushed, ranked

    def test_no_pick_is_named_in_the_payload(self):
        pushed, _ranked = self._advise()
        self.assertTrue(pushed, "the pick pushed no payload at all")
        self.assertNotIn("top_move", pushed)
        self.assertNotIn("top_move_steps", pushed)

    def test_the_options_still_ride_along(self):
        pushed, ranked = self._advise()
        self.assertEqual(pushed["choice"]["ranked"], ranked,
                         "the panel needs the options to list them")


if __name__ == "__main__":
    unittest.main()
