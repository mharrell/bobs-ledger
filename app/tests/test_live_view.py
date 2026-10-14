"""THE LIVE VIEW CONTRACT: the overlay ships state, never a verdict.

2026-10-06, PIVOT.md. The product split in two: the live path reads the board,
and the model's actual plan — the numbered steps, the buy it names, the pick —
is shown only after the fact, in the review, where the decision it describes
can no longer be acted on. `render_json` is the ONE place the page's view is
built, so it is the one place the split has to hold.

**REVERSED 2026-10-13, and STRONGER for it.** The live page had two renderers
behind a `Classic | Tavern` toggle, and half of this file's pins were phrased
against that pair — the review of the day that read them put it as "the classic
page shows the model's read, the Tavern one must not". The maintainer removed
the choice and the classic renderer was DELETED, so there is one live page and
it shows no verdict AT ALL: every pin below is now unconditional, and the pins
that used to be conditional on the viewer (which renderer the payload reaches,
which page may carry the model's words) are assertions about the ONE page. The
review is still the opposite by design — it is where the verdict ships — which
is why `LIVE_VERDICT_KEYS` and the review's own grading tests both still have to
hold together.

**SECOND SET, 2026-10-14 (`LIVE_UNREAD_KEYS`).** Deleting half of this file's
subject would have been the tidy move and the wrong one. The overlay had two
renderers until 2026-10-13; when the Classic one went (`bebfb4f`), seven analysis
keys lost their only page reader and kept shipping anyway — the payload is
`dict(analysis)` plus `render_json`'s own derivations, and nothing had ever
asked, key by key, which of those a page could still render. Those seven are a
SECOND list, dropped at a second choke point, for a different reason, and this
file extends all three halves to them. The difference between the two lists is
the point: "is the model's plan off the page" is not the question "can any page
code still read this".

Why this file is worth its length: the pivot is only real if it cannot quietly
revert. Deleting the plan from the page while leaving `top_move` in the payload
would pass every other test in this suite while shipping the same advice with a
different label. Three independent halves have to hold, and each is asserted
here for BOTH dropped sets:

  1. `LIVE_VERDICT_KEYS` / `LIVE_UNREAD_KEYS` are dropped from what the page
     receives;
  2. the ANALYSIS keeps every one of them — it is what the decision log writes
     and what the review reads back, so a "fix" that deletes the producer
     instead of the rendering would break the product's only real asset;
  3. the page does not READ any of them, and none of the directive wordings
     survive in the page source.

Half 2 is honest about a wrinkle the second set brought with it: four of those
seven (`thresholds`, `engine`, `scout`, `target_comp_guide`) are `render_json`'s
own creations — `live_coach.analyze()` never produced them — so for those it
pins that the analysis HANDED IN comes back whole, which is the copy-not-edit
rule the decision log depends on.

There is no `HEARTH_REAL_SESSION_TESTS` gate on any of this: it is pure
function behaviour over a fixture, so it runs everywhere, including in a
release zip with no logs on disk.
"""
import os
import re
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import coach_ui  # noqa: E402
from coach_ui import LIVE_UNREAD_KEYS, LIVE_VERDICT_KEYS  # noqa: E402

_HTML = coach_ui._HTML


def _without_comments(html):
    """The page with /* */ blocks and full-line // comments removed.

    See TestTheDirectiveWordingsAreGone for why this exists rather than a
    plain substring search.
    """
    body = re.sub(r"/\*.*?\*/", "", html, flags=re.S)
    return "\n".join(ln for ln in body.splitlines()
                     if not ln.strip().startswith("//"))


def _page_reads(key):
    """A regex matching PAGE CODE that reads `key` off an object.

    `a.shop_offers` and `a['scout']` both count; a bare mention in prose does
    not. The property form requires a character before the dot, so a CSS
    selector (`.engine { … }`) is not read as an access — the page's stylesheet
    lives in the same string as its script.
    """
    return re.compile(r"[\w$)\]]\s*\.\s*" + re.escape(key) + r"\b"
                      r"|\[\s*['\"]" + re.escape(key) + r"['\"]\s*\]")


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

#: The second dropped set, with a realistic value each (2026-10-14). The values
#: matter for the same reason as above: a key mapped to None could be "absent"
#: for the wrong reason. Three of these are `live_coach.analyze()` fields
#: (`comp_progress`, `shop_offers`, `target_cards`); the other four are
#: `render_json`'s own derivations, which is why they are shaped like the payload
#: rows they end up as rather than like an analysis row.
_UNREAD_VALUES = {
    "thresholds": {"dying_hp": 12},
    "comp_progress": [{"name": "Mechs - Y", "tribe": "MECHANICAL",
                       "meta_tier": "S", "hits": 2, "ready": True,
                       "needs": [], "tribe_hits": 2}],
    "engine": {"on_board": True, "space": True, "charging": 0},
    "scout": "you 120 stats · ~90 theirs",
    "shop_offers": ["BG28_810", "BG36_116"],
    "target_cards": {"core": [], "addons": []},
    "target_comp_guide": {"slug": "mechs-y", "difficulty": "Easy",
                          "when_to_commit": "commit by tier 4",
                          "how_to_play": "shop for Mechs", "enablers": []},
}

#: The state the page is FOR. If the pivot ever removes the product instead of
#: the verdict, these are what fails. `scout` and `comp_progress` moved out of
#: this dict on 2026-10-14 — the classic strip and the meter row were their last
#: readers, so they are no longer state the page keeps.
_STATE_VALUES = {
    "situation": "turning point — you lead the lobby",
    "board_stats": 120,
    "lobby_opp": 90,
    "fragility": {"band": "steady", "eff_health": 30},
    "forecast": "favored",
}


def _analysis(**over):
    a = {"board": [{"card": "BG23_318", "atk": 3, "health": 4},
                   {"card": "BG36_114", "atk": 1, "health": 2}],
         "sell_rank": [("BG23_318", 12.0), ("BG36_114", 4.0)],
         "hand": [{"card": "BG36_114", "name": "X", "verb": "play",
                   "score": 4.0, "why": "a free body"}],
         "shop_rank": [("BG36_116", 9.0), ("BG28_810", 3.0)],
         "comps": [], "playable_comps": {},
         "target_comp": "Mechs - Y"}
    a.update(_VERDICT_VALUES)
    a.update(_UNREAD_VALUES)
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
        exact silent failure the old KIND_CHIP drift guard existed to catch.

        Comments are stripped first, like every absence check on this page: its
        own source EXPLAINS what was removed and names the keys it removed, so a
        raw search fails on the explanation instead of on a regression.
        """
        body = _without_comments(_HTML)
        reads = sorted(k for k in LIVE_VERDICT_KEYS if _page_reads(k).search(body))
        self.assertEqual(reads, [],
                         "the page still reads dropped fields: " + ", ".join(reads))

    def test_the_read_search_itself_can_see_a_read(self):
        """The control for the search above, not for the page: a regex that
        matched nothing would pass every absence check in this file while
        measuring nothing, which is the empty scan `62fb33d` repaired. Both
        spellings a page could use are exercised, on a page that HAS the read.
        """
        planted = _without_comments(
            "var t = a.top_move;\nvar s = a['buy_this'];\n"
            "// a.hunt_targets is only named in this comment")
        self.assertTrue(_page_reads("top_move").search(planted))
        self.assertTrue(_page_reads("buy_this").search(planted))
        # ...and a mention in a comment is not a read.
        self.assertFalse(_page_reads("hunt_targets").search(planted))


class TestTheKeysNoPageReadsAreNotShipped(unittest.TestCase):
    """`LIVE_UNREAD_KEYS`, the second drop (2026-10-14) — NOT the pivot's.

    Seven keys lost their only page reader when the Classic renderer was deleted
    on 2026-10-13 (`bebfb4f`) and went on shipping: the payload is
    `dict(analysis)` plus `render_json`'s own derivations, so a key with no
    reader is invisible unless something asks. These assert the same three
    halves as the pivot's class above, on the other choke point.
    """

    def test_no_unread_key_reaches_the_page(self):
        out = coach_ui.render_json(_analysis())
        leaked = sorted(k for k in LIVE_UNREAD_KEYS if k in out)
        self.assertEqual(leaked, [],
                         "keys no page reads are in the live payload: "
                         + ", ".join(leaked))

    def test_the_fixture_covers_the_whole_dropped_set(self):
        """The guard that keeps the test above honest, as with the verdict set:
        a key added to `LIVE_UNREAD_KEYS` without a fixture value would make the
        absence assertion pass on a key nobody ever supplied."""
        self.assertEqual(set(_UNREAD_VALUES), set(LIVE_UNREAD_KEYS))

    def test_the_drop_is_what_removes_them(self):
        """THE POSITIVE CONTROL, and what makes the assertion above a
        measurement rather than a shape of the source.

        With the drop set emptied, every one of the seven comes back in the same
        payload: `render_json` still BUILDS each of them (the derivations are
        deliberately untouched), so a key missing from the shipped payload is
        missing because it was dropped and not because its name stopped existing
        anywhere. Without this, "the key is absent" cannot be told apart from a
        check that now searches for nothing — the failure `62fb33d` fixed in two
        places, and the one a deletion-shaped "fix" to this task would create.
        """
        self.assertTrue(LIVE_UNREAD_KEYS)
        with mock.patch.object(coach_ui, "LIVE_UNREAD_KEYS", frozenset()):
            out = coach_ui.render_json(_analysis())
        present = sorted(k for k in LIVE_UNREAD_KEYS if k in out)
        self.assertEqual(present, sorted(LIVE_UNREAD_KEYS),
                         "the drop set no longer causes the absence")
        # The control is only meaningful while the OTHER drop still holds:
        # emptying one list must not be a way to see the plan.
        leaked = sorted(k for k in LIVE_VERDICT_KEYS if k in out)
        self.assertEqual(leaked, [])

    def test_the_analysis_keeps_them(self):
        """The pivot's rule where it applies, and the copy-not-edit rule where it
        does not.

        Three of the seven are `live_coach.analyze()`'s own fields and must
        survive: `comp_progress` is read back by `replay_review` and
        `turn_review` and is named in `session_report`'s whitelist,
        `target_cards` by `turn_review` and `value`'s planner, and
        `shop_offers` by `render_json` itself. The other four (`thresholds`,
        `engine`, `scout`, `target_comp_guide`) are `render_json`'s own creations
        that the analysis never carried; for those this pins that the dict HANDED
        IN is not stripped, which is what `live._advise` depends on when it hands
        the same object to `decision_log.record()` one line later.
        """
        a = _analysis()
        coach_ui.render_json(a)
        missing = sorted(k for k in LIVE_UNREAD_KEYS if k not in a)
        self.assertEqual(missing, [], "the analysis lost: " + ", ".join(missing))
        self.assertEqual(a["shop_offers"], _UNREAD_VALUES["shop_offers"])
        self.assertEqual(a["comp_progress"], _UNREAD_VALUES["comp_progress"])

    def test_the_derivations_that_read_the_analysis_still_run(self):
        """The drop is LAST for a reason: two of these keys are what OTHER
        payload fields are derived from, so a drop at the top would take the
        page's own state with it. `shop_offers` orders the tavern row and
        `comp_progress` feeds the pre-commit "leads" tag — both are asserted
        through their RESULT, on a fixture with no target comp committed."""
        a = _analysis(target_comp=None, shop_entities=None,
                      comp_progress=[{"name": "Mech - Y",
                                      "needs": ["BG36_116"], "hits": 0,
                                      "ready": False, "meta_tier": "S",
                                      "tribe_hits": 0}])
        out = coach_ui.render_json(a)
        # `shop_offers` is the log's order, and the row follows it rather than
        # the score order it arrived in.
        self.assertEqual([r["card"] for r in out["shop_rank"]],
                         ["BG28_810", "BG36_116"])
        # ...and the unowned core card of the leading candidate carries the tag
        # the deleted classic page's comp meter drew from `comp_progress`.
        tags = {r["card"]: r["tag"] for r in out["shop_rank"]}
        self.assertEqual(tags["BG36_116"], "leads Mech - Y")
        self.assertNotEqual(tags["BG28_810"], "leads Mech - Y")

    def test_no_page_code_reads_a_dropped_key(self):
        """The third half, on the real page source, comments stripped — the
        failure prevented is a JS line reading `a.thresholds` and rendering
        nothing forever, five minutes after the payload stopped carrying it."""
        body = _without_comments(_HTML)
        reads = sorted(k for k in LIVE_UNREAD_KEYS if _page_reads(k).search(body))
        self.assertEqual(reads, [],
                         "the page still reads keys with no reader: "
                         + ", ".join(reads))


class TestTheStateStillShips(unittest.TestCase):
    def test_state_fields_survive(self):
        """`scout`, `comp_progress` and `thresholds` were in this tuple until
        2026-10-14: the classic strip and the comp meter were their last page
        readers, so they are no longer state the page keeps and they moved to
        `TestTheKeysNoPageReadsAreNotShipped`. What is left here is what the
        page is FOR, which is why this list must keep failing if the pivot ever
        removes the product instead of the verdict."""
        out = coach_ui.render_json(_analysis())
        for key in ("board", "situation", "fragility", "forecast",
                    "sell_rank", "shop_rank", "hand", "board_cards",
                    "cards", "generated"):
            self.assertIn(key, out, f"{key} left the live payload")


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
        """The same dedupe lived in the board row: it drew the grouped
        `sell_rank` row, which is BY CARD ("×2"). `board_cards` is one entry per
        board minion, so two copies of one minion are two cards. The grouped row
        stays in the payload — `board_cards` is derived from it, and old records
        and the corpus read `sell_rank` — but no page renders it since the
        classic Sell box was deleted (2026-10-13)."""
        a = _analysis(board=[{"card": "BG36_116", "atk": 5, "health": 5,
                              "tribe": "BEAST"},
                             {"card": "BG36_116", "atk": 9, "health": 9,
                              "tribe": "BEAST"}],
                      sell_rank=[("BG36_116", 12), ("BG36_116", 30)])
        out = coach_ui.render_json(a)
        self.assertEqual([r["atk"] for r in out["board_cards"]], [5, 9],
                         "two identical minions are one entity each")
        self.assertEqual(len(out["sell_rank"]), 1,
                         "the grouped Sell row (no page renders it; the corpus "
                         "and `board_cards` read it) still groups by card")
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
             mock.patch.object(live.coach_ui, "latest_manual_in_play",
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
