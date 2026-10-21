"""The Settle Up review's one layout.

REVERSED 2026-10-13. This file was "the Settle Up viewer flag (2026-10-08): a
styling toggle that keeps the shipped Classic renderer as the default while the
REPLAY_VIEWER_DESIGN.md build grows behind the Tavern branch" — the flag, its
`bl-settle-viewer` key and its `_viewer` default WERE the contract under test.
The maintainer made the Tavern style the only one and deleted the classic
reviewer rather than leaving it unreachable, so the contract is now the absence
of that choice plus the part that must not be lost with it: the review is where
the model's plan and its GRADING ship, and `tavernRail` carries both.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import coach_ui  # noqa: E402


def _function(name):
    m = re.search(rf"function {name}\(.*?\n\}}", coach_ui._HTML, re.S)
    return m.group(0) if m else None


def _js_const(name):
    """A top-level `const NAME = ...;` from the page (objects included)."""
    m = re.search(rf"const {name} = .*?;", coach_ui._HTML, re.S)
    return m.group(0) if m else None


class TestThereIsNoReviewerChoice(unittest.TestCase):
    """REVERSED 2026-10-13 from `TestTheFlag`.

    Every test in that class was about the flag itself — the control, its key,
    "Classic is the default", the branch and the classic renderer the branch
    protected. The flag, the branch and the classic renderer are gone, and the
    absence is what is asserted now: this is the shape a later branch would have
    to break to bring the choice back.
    """

    def _code(self):
        """The page's CODE, with its comments removed.

        The page explains what it removed and names the identifiers it removed
        ("`bl-settle-viewer` ... are gone"), so an absence check on raw text
        fails on the explanation rather than on a regression.
        """
        import re
        body = re.sub(r"/\*.*?\*/", "", coach_ui._HTML, flags=re.S)
        body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
        return re.sub(r"//[^\n]*", "", body)

    def test_the_toggle_is_gone_from_the_settle_header(self):
        code = self._code()
        for dead in ('id="settle-viewer"', 'data-v="classic"', 'data-v="tavern"'):
            self.assertNotIn(dead, code,
                             "the Classic | Tavern control is back in the "
                             "Settle Up header")
        # The header's ONE control left is the mode toggle.
        self.assertIn('id="settle-mode"', code)

    def test_the_choice_persists_nowhere(self):
        for dead in ("bl-settle-viewer", "bl-live-viewer"):
            self.assertNotIn(dead, self._code(),
                             "a viewer key outlived the control that wrote it")

    def test_there_is_no_viewer_variable_and_no_dispatcher(self):
        code = self._code()
        for dead in ("let _viewer", "_viewer ===", "function renderSettleGame",
                     "function setSettleViewer", "if (_viewer",
                     "hideSettleMode"):
            self.assertNotIn(dead, code, f"{dead} is back")

    def test_the_saved_game_reaches_the_review_renderer(self):
        """The dispatcher is gone, so this is unconditional: the dropdown's
        fetch goes straight to `renderTavernGame`."""
        src = _function("loadSettleGame")
        self.assertIn("renderTavernGame(j.rep || j);", src)
        self.assertNotIn("renderSettleGame", src)

    def test_the_review_renderer_remembers_the_rep(self):
        """Reversed from `test_render_settle_game_branches_and_remembers_the_rep`,
        which pinned that the rep was remembered BEFORE the viewer branch. There
        is no branch; what matters is unchanged — the mode toggle and the
        keyboard re-render from this rep rather than refetching the game."""
        src = _function("renderTavernGame")
        self.assertIsNotNone(src, "renderTavernGame is missing")
        self.assertIn("_settleRep = rep;", src)
        self.assertLess(src.index("_settleRep = rep;"),
                        src.index("refreshSettleMode"),
                        "the rep has to be remembered before anything reads it")

    def test_the_classic_reviewer_is_gone_and_not_merely_unchosen(self):
        """Reversed from `test_the_classic_renderer_is_unchanged`, which pinned
        the shipped path's shape — one card per timeline turn, the sticky
        header, the final-duel phases attached to the last card. None of it can
        be reached now, so all of it is an absence, together with the phase row
        that carried the model's line on that page."""
        code = self._code()
        for dead in ("s-sticky", "turn .phase", "phases.filter(p => p.turn === r.turn)",
                     "phaseRow", "lastCard.appendChild"):
            self.assertNotIn(dead, code, f"{dead} survived the classic reviewer")

    def test_the_card_renderer_is_the_only_one(self):
        """`settleTurnCard` is still the real card — not forked — and with the
        classic reviewer gone it has no `opts.tavern` flag left: one caller, and
        the tavern-only extras are simply what it renders. The model's plan rides
        the rail, which carries its grading on the Plan summary."""
        src = _function("renderTavernGame")
        self.assertIsNotNone(src, "renderTavernGame is missing")
        self.assertIn("settleTurnCard(row, {hero: rep.hero,", src)
        self.assertIn("tavernRail(row, railPhases, hasCoach)", src)
        self.assertIn("className = 'tavern'", src)
        self.assertIn("stripMark(r.winner, r.damage_taken)", src)
        card = _function("settleTurnCard")
        self.assertNotIn("opts.tavern", card)
        self.assertIn("'Plan — ' + p.verdict", _function("tavernRail"))

    def test_tavern_tokens_are_scoped_not_global(self):
        """The Tavern palette lives on `.tavern`; the shell and the standalone
        review pages keep the tokens in `:root`."""
        self.assertRegex(coach_ui._HTML, r"\.tavern \{[^}]*--tbg:#17110d")
        for root_rule in re.findall(r":root \{[^}]*\}", coach_ui._HTML):
            self.assertNotIn("--tbg", root_rule,
                             "the Tavern palette leaked into :root")

    def test_the_rebuild_button_and_its_endpoint_are_wired(self):
        """Old saves upgrade in place: the header button POSTs the selected
        id to /review/rebuild, which re-derives the rep from the log the
        store's pointer names.

        The fetch rides auth() because it has to (2026-10-08): every request
        the overlay's own page makes carries the run's access key, and this
        endpoint answers 403 without it.
        """
        self.assertIn('id="settle-rebuild"', coach_ui._HTML)
        self.assertIn("fetch(auth('/review/rebuild')", coach_ui._HTML)
        self.assertIn("await loadSettleGame(id)", coach_ui._HTML,
                      "a rebuilt game re-renders immediately")
        # The server side: the response builder exists and the handler
        # dispatches the route to it (python side, not the page string).
        self.assertTrue(callable(coach_ui._review_rebuild_response))
        mod_src = open(coach_ui.__file__, encoding="utf-8").read()
        self.assertIn('"/review/rebuild"', mod_src)
        self.assertIn("settle_up.rebuild(rid)", mod_src)


class TestTheRailData(unittest.TestCase):
    """The Summary rail's inputs: the serve-time join names the action lists
    (one shape regardless of save age), and the tavern-gated extras stay
    behind the flag in the shared card renderer."""

    def _rep(self, took_bought, took_sold):
        return {"hero": "H", "totals": {}, "phases": [],
                "timeline": {"turns": [
                    {"turn": 1, "notes": [],
                     "took": {"bought": took_bought, "sold": took_sold}}]}}

    def test_the_join_names_the_rail_lists(self):
        import unittest.mock as mock
        rep = self._rep(["BG31_815"], ["BG33_886"])
        with mock.patch.object(coach_ui.value, "display_name",
                               lambda names, cid: {"BG31_815": "Dune Dweller"}
                               .get(cid, cid)):
            out = coach_ui._name_timeline_boards(rep)
        took = out["timeline"]["turns"][0]["took"]
        self.assertEqual(took["bought"],
                         [{"card": "BG31_815", "name": "Dune Dweller"}])
        self.assertEqual(took["sold"],
                         [{"card": "BG33_886", "name": "BG33_886"}],
                         "an id the name DB lacks degrades to the id")

    def test_old_plain_string_lists_are_converted_too(self):
        """Every rep saved before the rail carried plain id strings; the join
        converts them so the renderer sees one shape regardless of age."""
        import unittest.mock as mock
        rep = self._rep(["BG31_815"], [])
        with mock.patch.object(coach_ui.value, "display_name",
                               lambda names, cid: {"BG31_815": "Dune Dweller"}
                               .get(cid, cid)):
            out = coach_ui._name_timeline_boards(rep)
        self.assertEqual(out["timeline"]["turns"][0]["took"]["bought"],
                         [{"card": "BG31_815", "name": "Dune Dweller"}])

    def test_the_tray_and_tags_are_unconditional_now(self):
        """REVERSED 2026-10-13 from `test_the_tray_and_tags_are_tavern_gated`,
        which pinned the passed-through tray and the Ended net tags behind
        `opts.tavern` because the shared card also served the classic reviewer
        (which never set it). That reviewer is gone, so the extras are simply
        what the one card renders, and the flag itself is gone with it.
        """
        src = _function("settleTurnCard")
        self.assertIsNotNone(src)
        self.assertNotIn("opts.tavern", src, "the gate is back with one caller")
        self.assertIn("Passed through", src)
        self.assertIn("boardDelta(r.buy_start, r.buy_end)", src)
        self.assertIn("faceSide(", src, "the Battle face-off is the one view")


class TestTheRailHelpers(unittest.TestCase):
    """runLength / flipKinds / boardDelta, run under node (skipped without
    it). The rail's grouping, flipped detection and Ended tags are pure
    functions; the wording tests the glyphs, these test the grouping."""

    def setUp(self):
        if shutil.which("node") is None:
            self.skipTest("node is not installed, so the page's script cannot "
                          "be executed")
        sources = [_function(n) for n in
                   ("runLength", "flipKinds", "boardDelta", "outcomeText",
                    "hpLine", "minionsLeft", "stepWords", "stepLetter",
                    "stepKindClass", "stepDiff")]
        for name, src in zip(("runLength", "flipKinds", "boardDelta",
                              "outcomeText", "hpLine", "minionsLeft",
                              "stepWords", "stepLetter", "stepKindClass",
                              "stepDiff"), sources):
            self.assertIsNotNone(src, name + " is missing")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        driver = os.path.join(self.tmp.name, "drive.js")
        with open(driver, "w", encoding="utf-8") as f:
            f.write("\n".join(sources) + "\n"
                    + "const out = [];\n"
                    "out.push(runLength(['A', 'A', 'B']));\n"
                    "out.push(runLength([{name: 'Rolled ×9'}]));\n"
                    "out.push(runLength([]));\n"
                    "out.push(flipKinds([{card: 'X', name: 'Wolf'}, "
                    "{card: 'Y', name: 'Elk'}], "
                    "[{card: 'X', name: 'Wolf'}, {card: 'Z', name: 'Owl'}]));\n"
                    "out.push(flipKinds([], []));\n"
                    "out.push(boardDelta("
                    "[{eid: 1, atk: 3, health: 3}, {eid: 2, atk: 2, health: 2}], "
                    "[{eid: 1, atk: 5, health: 3}, {eid: 9, atk: 4, health: 4}]));\n"
                    "out.push(boardDelta([], [{eid: 3, atk: 1, health: 1}]));\n"
                    "out.push(outcomeText('us') + '|' + outcomeText('them') + '|"
                    + "' + outcomeText('tie') + '|' + outcomeText(undefined));\n"
                    "out.push(hpLine(25, 20) + '|' + hpLine(25, null) + '|"
                    + "' + hpLine(null, null));\n"
                    "out.push(String(minionsLeft('us', [1, 2, 3], [])) + '|"
                    + "' + String(minionsLeft('them', [], [1])) + '|"
                    + "' + String(minionsLeft('tie', [1], [2])));\n"
                    "out.push(stepWords({k: 'buy', cardName: 'Wolf Pup'}) + '|"
                    + "' + stepWords({k: 'roll'}) + '|"
                    + "' + stepWords({k: 'sell', card: 'BG31_816'}));\n"
                    "out.push(stepLetter('buy') + stepLetter('roll') + "
                    "stepLetter('level') + stepLetter('sell') + "
                    "stepLetter('play') + stepLetter('cast') + "
                    "stepLetter('mystery'));\n"
                    "out.push(stepKindClass('buy') + '|' + "
                    "stepKindClass('mystery'));\n"
                    "out.push(JSON.stringify(stepDiff("
                    "[{eid: 1, card: 'A'}, {eid: 2, card: 'B'}], "
                    "'buy', 'B')));\n"
                    "out.push(JSON.stringify(stepDiff("
                    "[{eid: 1, card: 'A'}], 'level', null)));\n"
                    "out.push(JSON.stringify(stepDiff("
                    "[{eid: 1, card: 'A'}], 'sell', 'A')));\n"
                    # Whole-group grouping (2026-10-09, player call): the same
                    # card bought at steps 2 and 9 is ONE row, first-seen
                    # order, whatever sits between the two buys. Then the
                    # hero-power label (same date): the server names the kind,
                    # and the step says what the action WAS — "Cast hero
                    # power" reads backwards.
                    "out.push(runLength(['A', 'B', 'A']));\n"
                    "out.push(runLength(['A', 'A', 'B', 'A']));\n"
                    "out.push(stepWords({k: 'cast', cardName: 'hero power'})"
                    " + '|' + stepWords({k: 'play', cardName: 'hero power'})"
                    " + '|' + stepWords({k: 'cast', cardName: 'Tavern Spell'}));\n"
                    "console.log(JSON.stringify(out));\n")
        # Bytes in, UTF-8 decoded here: text=True reads node's pipe as cp1252
        # and mojibakes the non-ASCII labels (measured 2026-10-08).
        proc = subprocess.run(["node", driver], capture_output=True,
                              timeout=30)
        self.assertEqual(proc.returncode, 0,
                         f"node could not run the helpers: "
                         f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
        self.out = json.loads(proc.stdout.decode("utf-8"))

    def test_runs_collapse_consecutive_repeats(self):
        self.assertEqual([(r["label"], r["n"]) for r in self.out[0]],
                         [("A", 2), ("B", 1)])
        self.assertEqual(self.out[1][0]["label"], "Rolled ×9")
        self.assertEqual(self.out[2], [])

    def test_runs_group_by_name_across_the_whole_group(self):
        """2026-10-09, player call: Buys listed En-Djinn Blazer twice and
        several Sells twice, because only ADJACENT repeats merged. The same
        card bought at steps 2 and 9 is one row — "×2" — in first-seen
        order, whatever sits between the two buys."""
        self.assertEqual([(r["label"], r["n"]) for r in self.out[16]],
                         [("A", 2), ("B", 1)],
                         "a non-adjacent repeat split into two rows")
        self.assertEqual([(r["label"], r["n"]) for r in self.out[17]],
                         [("A", 3), ("B", 1)],
                         "a third non-adjacent repeat did not join its run")

    def test_a_hero_power_step_says_what_happened_not_its_id(self):
        """2026-10-09, player call: "Cast BG32_HERO_001p" reached the
        Step-through. No DB this ships carries a hero-power id's name (the
        power table is keyed by hero NAME with the power's text), so the
        serve-time join names the kind and the step words say what the
        action was."""
        self.assertEqual(self.out[18],
                         "Used hero power|Used hero power|Cast Tavern Spell")

    def test_flipped_is_bought_and_sold_same_phase(self):
        kinds = self.out[3]
        self.assertEqual(kinds["X"], "flipped")
        self.assertEqual(kinds["Z"], "sold")
        self.assertEqual(self.out[4], {})

    def test_delta_matches_by_entity_id(self):
        d = self.out[5]
        self.assertEqual(d["1"], {"isNew": False, "datk": 2, "dhealth": 0})
        self.assertEqual(d["9"], {"isNew": True, "datk": 0, "dhealth": 0})
        self.assertEqual(self.out[6]["3"]["isNew"], True)

    def test_outcome_hp_and_minion_lines(self):
        self.assertEqual(
            self.out[7],
            "You won the fight|You lost the fight|A tie — both boards died"
            "|Outcome not readable")
        self.assertEqual(self.out[8], "HP 25 → 20|HP 25 → ?|")
        self.assertEqual(self.out[9], "3|1|null")

    def test_step_captions_letters_and_diff(self):
        self.assertEqual(self.out[10],
                         "Bought Wolf Pup|Rolled the tavern|Sold BG31_816")
        self.assertEqual(self.out[11], "BRLSPC•")
        self.assertEqual(self.out[12], "k-buy|")
        # Only an action that TARGETS a card highlights one (2026-10-09): a buy
        # highlights the card it put on the board, and a level-up, a roll or a
        # sell highlights nothing at all.
        self.assertEqual(self.out[13], '{"highlight":2}',
                         "a buy highlights the card it added")
        self.assertEqual(self.out[14], '{"highlight":null}',
                         "a level-up targets no card")
        self.assertEqual(self.out[15], '{"highlight":null}',
                         "a sell's card is the ghost, not a highlight")


class TestTheStripMarker(unittest.TestCase):
    """stripMark is the strip's result line, run under node (skipped without
    it). Result is never color-only, so the glyph and the HP text are the
    contract.

    The marker says what the fight COST, not who won (2026-10-09, player call):
    HP dropped is a loss marker, no drop cost nothing, and an unreadable cost
    falls back to the winner. Nothing renders a "?" — it sat inside the turn
    number ("1? −5"), where it read as part of the number."""

    def setUp(self):
        if shutil.which("node") is None:
            self.skipTest("node is not installed, so the page's script cannot "
                          "be executed")
        source = _function("stripMark")
        self.assertIsNotNone(
            source, "stripMark() is no longer a function in the page")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cases = [["us", 10], ["them", 10], ["tie", None], [None, None],
                 [None, 5], ["us", -3], ["them", 0], ["us", None]]
        driver = os.path.join(self.tmp.name, "drive.js")
        with open(driver, "w", encoding="utf-8") as f:
            f.write(f"{source}\n"
                    f"const cases = {json.dumps(cases)};\n"
                    "console.log(JSON.stringify("
                    "cases.map(([w, d]) => stripMark(w, d))));\n")
        # Bytes in, UTF-8 decoded here: node writes UTF-8 to the pipe and
        # text=True would decode it with the Windows locale (cp1252), which
        # mojibakes every glyph this test exists to pin (▲/▼/− measured
        # scrambled on 2026-10-08).
        proc = subprocess.run(["node", driver], capture_output=True,
                              timeout=30)
        self.assertEqual(proc.returncode,
                         0, f"node could not run stripMark: "
                            f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
        self.out = json.loads(proc.stdout.decode("utf-8"))

    def test_hp_dropped_is_the_loss_marker(self):
        """A turn you WON but that cost 10 HP shows the loss marker: the line
        reports the cost, and the Result tab is where the winner lives."""
        self.assertEqual(self.out[0]["ch"], "▼ −10")
        self.assertEqual(self.out[0]["cls"], "loss")
        self.assertEqual(self.out[1]["ch"], "▼ −10")
        self.assertEqual(self.out[1]["cls"], "loss")
        self.assertEqual(self.out[4]["ch"], "▼ −5")

    def test_no_drop_cost_nothing_and_no_data_is_a_dash(self):
        self.assertEqual(self.out[5]["ch"], "▲ +3")
        self.assertEqual(self.out[5]["cls"], "win")
        self.assertEqual(self.out[6]["ch"], "▲ 0")
        self.assertEqual(self.out[6]["cls"], "win")
        self.assertEqual(self.out[2]["ch"], "=")
        self.assertEqual(self.out[2]["cls"], "tie")
        self.assertEqual(self.out[3]["ch"], "—")
        self.assertEqual(self.out[3]["cls"], "")

    def test_the_winner_is_the_fallback_when_the_cost_is_unreadable(self):
        self.assertEqual(self.out[7]["ch"], "▲")
        self.assertEqual(self.out[7]["cls"], "win")

    def test_a_turn_number_never_carries_a_question_mark(self):
        for line in self.out:
            self.assertNotIn("?", line["ch"])


class TestTheActionLabels(unittest.TestCase):
    """The serve-time join names an ACTION's card, and a hero power — whose
    name no shipped DB carries — comes out as the kind, never the raw id
    (2026-10-09, player call: "Cast BG32_HERO_001p" reached the caption).

    The fallback lives HERE and not in `value.display_name` on purpose: that
    function's contract is "unknown ids come back as themselves", which is
    what `_acted`'s raw-id rule relies on ("bought BG36_318" beats a buy
    that vanishes). A caption has a better move available — name the kind —
    and only the caption takes it."""

    def _named(self, steps, spell_ids=None):
        rep = {"hero": "H", "totals": {}, "phases": [],
               "timeline": {"turns": [
                   {"turn": 1, "notes": [], "steps": steps,
                    "took": {"spell_ids": spell_ids or []}}]}}
        return coach_ui._name_timeline_boards(rep)

    def test_a_hero_power_step_never_shows_its_id(self):
        out = self._named([{"k": "cast", "card": "BG32_HERO_001p"}])
        st = out["timeline"]["turns"][0]["steps"][0]
        self.assertEqual(st["cardName"], "hero power")

    def test_the_rails_spell_list_gets_the_same_treatment(self):
        out = self._named([], spell_ids=["BG32_HERO_001p"])
        row = out["timeline"]["turns"][0]["took"]["spell_ids"][0]
        self.assertEqual(row["name"], "hero power")

    def test_an_unknown_minion_id_stays_raw(self):
        """The hero-power rewrite is about the POWER shape only. A minion id
        the DB cannot name still renders itself — the review's own rule
        (test_settle_up's raw-id fallback), and a hero-power-looking rewrite
        of it would be its own invention."""
        out = self._named([{"k": "sell", "card": "BG99_999"}])
        st = out["timeline"]["turns"][0]["steps"][0]
        self.assertEqual(st["cardName"], "BG99_999")

    def test_a_golden_power_shape_is_caught_too(self):
        out = self._named([{"k": "cast", "card": "BG31_HERO_100p2"}])
        st = out["timeline"]["turns"][0]["steps"][0]
        self.assertEqual(st["cardName"], "hero power")


class TestTheCoachingComparison(unittest.TestCase):
    """The comparison box's wording, run under node (skipped without it), plus
    the switch's contract read off the page source.

    Pass 2 (2026-10-20): the box is BELOW the action groups, folded, with a
    summary line above the fold — and the switch is OFF by default and gates
    rendering only, so the payload can never depend on it.
    """

    def setUp(self):
        if shutil.which("node") is None:
            self.skipTest("node is not installed, so the page's script cannot "
                          "be executed")
        names = ("coachRows", "coachSummary", "coachName", "coachCell",
                 "coachWhy", "coachCount", "coachEvidence", "coachLeadRow",
                 "coachDiffers", "phasesForTurn", "stepDiffFlags")
        sources = [_function(n) for n in names]
        for name, src in zip(names, sources):
            self.assertIsNotNone(src, name + " is missing")
        consts = [_js_const("COACH_PLURALS"), _js_const("COACH_LEAD_KIND")]
        for name, src in zip(("COACH_PLURALS", "COACH_LEAD_KIND"), consts):
            self.assertIsNotNone(src, name + " is missing")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        driver = os.path.join(self.tmp.name, "coach.js")
        with open(driver, "w", encoding="utf-8") as f:
            f.write("\n".join(consts) + "\n" + "\n".join(sources) + "\n"
                    "const NAMES = {BG_A: 'Dune Dweller', BG_B: 'Kooky Chemist'};\n"
                    "function cardMeta(c) { return NAMES[c] ? {name: NAMES[c]} : {}; }\n"
                    "const rows = [\n"
                    " {kind:'level', state:'differs', model:{asked:true,cards:[]},\n"
                    "  player:{did:false,cards:[]}, tier:{from:4,to:5}},\n"
                    " {kind:'buy', state:'differs', model:{asked:true,cards:['BG_A']},\n"
                    "  player:{did:true,cards:['BG_B']}, margin:2.8,\n"
                    "  why:'its ranking gives 9.0 against 6.2'},\n"
                    " {kind:'sell', state:'differs', model:{asked:false,cards:[]},\n"
                    "  player:{did:true,cards:['BG_B']}},\n"
                    " {kind:'roll', state:'same', model:{asked:true,cards:[]},\n"
                    "  player:{did:true,cards:[]}},\n"
                    " {kind:'play', state:'not_comparable',\n"
                    "  model:{asked:true,cards:['BG_A']},\n"
                    "  player:{did:true,cards:['BG_B']}}];\n"
                    "const turnz = [{turn:1},{turn:2}];\n"
                    "const flipped = "
                    "[{k:'buy',card:'BG_A'},{k:'buy',card:'BG_B'},{k:'level'},\n"
                    " {k:'sell',card:'BG_B'},{k:'roll'}];\n"
                    "const out = {\n"
                    " rows: coachRows([{coach_diff: rows}, "
                    "{coach_diff: [{kind: 'cast'}]}]),\n"
                    " sum: [coachSummary(rows), coachSummary([{state:'same'},"
                    "{state:'not_reached'}])],\n"
                    " cells: rows.map(r => [coachCell(r, 'model'), "
                    "coachCell(r, 'player')]),\n"
                    " why: [coachWhy(rows), coachWhy([{why: null}])],\n"
                    " ev: [coachEvidence({games:18, by_kind:{buy:38,level:29}}),"
                    " coachEvidence({games:1, by_kind:{buy:1}}),"
                    " coachEvidence({games:18, by_kind:{}}), coachEvidence(null)],\n"
                    " evkind: [coachEvidence({games:18, by_kind:{buy:38,level:29}},"
                    " [{kind:'level'},{kind:'buy'}]),\n"
                    "  coachEvidence({games:18, by_kind:{buy:1,level:3}},"
                    " [{kind:'buy'}])],\n"
                    " lead: [coachDiffers({lead:'buy', coach_diff:[{kind:'buy',"
                    "state:'differs'}]}),\n"
                    "  coachDiffers({lead:'level', coach_diff:[{kind:'buy',"
                    "state:'differs'}]}),\n"
                    "  coachDiffers({lead:'hunt-roll', coach_diff:[{kind:'roll',"
                    "state:'same'}]}),\n"
                    "  coachDiffers({lead:'pass', coach_diff:[{kind:'level',"
                    "state:'differs'}]})],\n"
                    " turnphases: phasesForTurn(turnz, [{turn:1},{turn:2},"
                    "{turn:9}], turnz[1]).map(p => p.turn),\n"
                    " stepflags: stepDiffFlags(flipped, [{coach_diff: [\n"
                    "  {kind:'buy', state:'differs', model:{asked:true,"
                    "cards:['BG_A']}},\n"
                    "  {kind:'level', state:'differs', model:{asked:true,cards:[]}},\n"
                    "  {kind:'roll', state:'same', model:{asked:true,cards:[]}}]}])"
                    "};\n"
                    "console.log(JSON.stringify(out));\n")
        proc = subprocess.run(["node", driver], capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 0,
                         f"node could not run the coaching helpers: "
                         f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
        self.out = json.loads(proc.stdout.decode("utf-8"))

    def test_rows_flatten_across_the_turn_s_phases(self):
        self.assertEqual(len(self.out["rows"]), 6)
        self.assertEqual(self.out["rows"][-1]["kind"], "cast")

    def test_the_summary_counts_only_real_differences(self):
        """`not_reached` is not a choice and `not_comparable` is not a
        comparison — neither inflates the collapsed line's number."""
        self.assertEqual(self.out["sum"][0], "3 differ")
        self.assertEqual(self.out["sum"][1], "no differences")

    def test_the_cells_read_as_the_mockups_do(self):
        cells = self.out["cells"]
        self.assertEqual(cells[0], ["Yes · tier 4 → 5", "No"])
        self.assertEqual(cells[1], ["Dune Dweller", "Kooky Chemist"])
        self.assertEqual(cells[2], ["—", "Kooky Chemist"],
                         "it asked for no sell, so the Model cell is a dash")
        self.assertEqual(cells[3], ["Yes", "Yes"])

    def test_why_needs_a_number(self):
        self.assertEqual(self.out["why"][0],
                         "its ranking gives 9.0 against 6.2")
        self.assertIsNone(self.out["why"][1])

    def test_the_evidence_line_is_a_difference_count(self):
        self.assertEqual(self.out["ev"][0],
                         "we differed on 67 moves across your 18 saved games")
        self.assertEqual(self.out["ev"][1],
                         "we differed on 1 move across your 1 saved game")
        self.assertIsNone(self.out["ev"][2])   # no counts -> no claim
        self.assertIsNone(self.out["ev"][3])

    def test_the_evidence_line_names_the_kinds_the_rows_show(self):
        """A box with level and buy rows says "29 level-ups and 38 buys", not a
        total: the line has to speak to what is on screen."""
        self.assertEqual(self.out["evkind"][0],
                         "we differed on 29 level-ups and 38 buys across your "
                         "18 saved games")
        self.assertEqual(self.out["evkind"][1],
                         "we differed on 1 buy across your 18 saved games")

    def test_the_strip_mark_follows_the_phase_lead_only(self):
        """A difference in a kind the plan did NOT lead with is not a turn
        where the plan differed (COACHING_PLAN §5.3)."""
        self.assertEqual(self.out["lead"], [True, False, False, False])

    def test_the_last_turn_owns_the_unmatched_phases(self):
        self.assertEqual(self.out["turnphases"], [2, 9])

    def test_a_step_is_judged_against_the_cards_named_for_its_kind(self):
        self.assertEqual(self.out["stepflags"],
                         [False, True, True, False, False])

    # --- the switch, from the page source -------------------------------
    def test_the_switch_is_a_real_switch_and_defaults_off(self):
        src = coach_ui._HTML
        self.assertIn('id="coach-switch"', src)
        self.assertIn('role="switch"', src)
        self.assertIn('aria-checked="false"', src)
        self.assertIn('aria-label="Show coaching"', src)
        self.assertIn("let _coachOn = false;", src)

    def test_the_state_word_is_not_the_accessible_name(self):
        """`aria-checked` carries the state; folding "On"/"Off" into the name
        would make a screen reader announce a switch whose name changes."""
        src = coach_ui._HTML
        self.assertIn('aria-label="Show coaching"', src)
        self.assertNotIn('aria-label="Show coaching: ', src)

    def test_the_work_in_progress_text_comes_from_one_constant(self):
        src = coach_ui._HTML
        self.assertIn("const COACH_WIP = '(work in progress)';", src)
        # The visible span is EMPTY in the markup and filled from that constant
        # at startup, so there is no second copy to drift.
        self.assertIn('<span class="cs-wip" id="coach-wip"></span>', src)

    def test_the_switch_gates_rendering_only(self):
        """Decision 1: the payload shape never depends on the switch. The box
        is appended under `_coachOn` and nothing else reads it in a payload."""
        src = coach_ui._HTML
        self.assertIn("if (_coachOn) {", _function("tavernRail"))
        self.assertIn("localStorage.setItem('bl-coaching'", src)
        self.assertIn("localStorage.getItem('bl-coaching')", src)

    def test_the_box_sits_below_the_action_groups(self):
        """The maintainer's shape (2026-10-20): a NEW box below the actions,
        never inside them — folding a group must not hide the comparison."""
        rail = _function("tavernRail")
        self.assertIsNotNone(rail)
        groups = rail.index("group('Plays'")
        box = rail.index("coachBox(phases, hasCoach)")
        plan = rail.index("rplan")
        self.assertLess(groups, box)
        self.assertLess(box, plan, "the plan stays the rail's last section")

    def test_off_renders_nothing_and_leaves_no_gap(self):
        """Off builds no node at all, so there is no header and no gap to
        collapse — the rail is byte-for-byte what it was before the feature."""
        rail = _function("tavernRail")
        self.assertIn("if (_coachOn) {", rail)
        self.assertIn("const cbox = coachBox(phases, hasCoach);", rail)
        # The box's own CSS margin only exists on the box that is built: a
        # spacer rule outside it would leave the gap the switch must not.
        self.assertIn(".tavern .cbox { border-top:1px solid var(--tline);",
                      coach_ui._HTML)
        self.assertIn(".tavern .cbox-b { margin-top:8px; }", coach_ui._HTML)

    def test_the_strip_and_step_marks_are_gated_by_the_switch(self):
        """Off must draw no mark anywhere, not just an empty box: the strip and
        the step track read `_coachOn` before they decorate anything."""
        strip = _function("renderTavernGame")
        self.assertIn("if (_coachOn && phasesForTurn(turns, phases, r)"
                      ".some(coachDiffers))", strip)
        steps = _function("renderTavernSteps")
        self.assertIn("_coachOn ? stepDiffFlags(steps, phases) : []", steps)
        self.assertIn("'differs from the model'", steps)

    def test_the_turn_mark_is_a_glyph_with_words_behind_it(self):
        """A mark that is only a colour fails in greyscale and says nothing to a
        screen reader; the `≠` is text and the hidden words name it."""
        strip = _function("renderTavernGame")
        self.assertIn("'≠'", strip)
        self.assertIn("'vhidden', 'differs from the model'", strip)


class TestTheCoachingBoxAssembles(unittest.TestCase):
    """`coachBox`'s DOM assembly, run under node against a minimal shim.

    The browser tests are the real measurement (sizes, colours, fold state), but
    they SKIP wherever Chromium cannot start — and a skipped test cannot tell a
    wiring bug from a passing check. This runs the assembly itself: how many
    rows, which classes, and the two cases where the box must NOT appear empty
    (no rows in a new save) or must explain itself (a save that predates it).
    """

    SHIM = r"""
class N {
  constructor(tag) { this.tag = tag; this.children = []; this.className = '';
    this.style = {}; this.attrs = {}; this._text = ''; }
  appendChild(c) { this.children.push(c); return c; }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k]; }
  set textContent(v) { this._text = v; this.children = []; }
  get textContent() {
    return this._text + this.children.map(c => c.textContent).join('');
  }
}
globalThis.document = {
  createElement: t => new N(t),
  createTextNode: t => ({tag: '#text', children: [], _text: t,
                         get textContent() { return this._text; }}),
};
globalThis.localStorage = {setItem() {}, getItem() { return null; }};
let _coachOpen = false;
let _settleRep = {coach_evidence: {games: 18, by_kind: {buy: 38, level: 29}}};
function cardMeta(c) { return {Dune: 'BG_A', Kooky: 'BG_B'}[c]
  ? {name: 'Kooky Chemist'} : {name: 'Dune Dweller'}; }
"""

    def setUp(self):
        if shutil.which("node") is None:
            self.skipTest("node is not installed, so the page's script cannot "
                          "be executed")
        names = ("el", "coachRows", "coachSummary", "coachName", "coachCell",
                 "coachWhy", "coachCount", "coachEvidence", "coachBox")
        sources = [_function(n) for n in names]
        for name, src in zip(names, sources):
            self.assertIsNotNone(src, name + " is missing")
        m = re.search(r"const COACH_KINDS = \{.*?\};", coach_ui._HTML, re.S)
        self.assertIsNotNone(m, "COACH_KINDS is missing")
        plurals = _js_const("COACH_PLURALS")
        self.assertIsNotNone(plurals, "COACH_PLURALS is missing")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        driver = os.path.join(self.tmp.name, "box.js")
        with open(driver, "w", encoding="utf-8") as f:
            f.write(self.SHIM + "\n" + plurals + "\n" + m.group(0) + "\n"
                    + "\n".join(sources)
                    + "\n"
                    "const rows = [\n"
                    " {kind:'level', state:'differs', model:{asked:true,cards:[]},\n"
                    "  player:{did:false,cards:[]}, tier:{from:2,to:3}},\n"
                    " {kind:'buy', state:'differs', model:{asked:true,cards:['BG_A']},\n"
                    "  player:{did:true,cards:['BG_B']}, margin:2.8,\n"
                    "  why:'its ranking gives 9.0 against 6.2'},\n"
                    " {kind:'sell', state:'differs', model:{asked:false,cards:[]},\n"
                    "  player:{did:true,cards:['BG_B']}},\n"
                    " {kind:'roll', state:'same', model:{asked:true,cards:[]},\n"
                    "  player:{did:true,cards:[]}}];\n"
                    "const walk = n => n.children || [];\n"
                    "const box = coachBox([{coach_diff: rows, confidence: 'medium'}],"
                    " true);\n"
                    "const body = box.children[1];\n"
                    "const rowsIn = body.children.filter(c => c.className"
                    " .indexOf('cdrow') === 0);\n"
                    "const out = {\n"
                    " box: box.className,\n"
                    " head: box.children[0].textContent,\n"
                    " ariafold: box.children[0].getAttribute('aria-expanded'),\n"
                    " bodydisplay: body.style.display,\n"
                    " kids: body.children.map(c => c.className || c.tag),\n"
                    " rows: rowsIn.length,\n"
                    " cls: rowsIn.map(r => r.className.replace('cdrow', '').trim()),\n"
                    " eq: body.children.filter(c => c.className === 'cdrow differs')\n"
                    "   .length,\n"
                    " why: (body.children.find(c => c.className === 'cd-why') || {})\n"
                    "   .textContent || null,\n"
                    " ev: (body.children.find(c => c.className === 'cd-ev') || {})\n"
                    "   .textContent || null,\n"
                    " noRowsNew: coachBox([], true),\n"
                    " old: (() => { const b = coachBox([], false);\n"
                    "   const n = b.children[1].children.find(c => c.className"
                    " === 'cd-note'); return n ? n.textContent : null; })(),\n"
                    "};\n"
                    "console.log(JSON.stringify(out));\n")
        proc = subprocess.run(["node", driver], capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 0,
                         f"node could not assemble the box: "
                         f"{proc.stderr.decode('utf-8', 'replace')[:400]}")
        self.out = json.loads(proc.stdout.decode("utf-8"))

    def test_the_box_has_a_folded_header_and_a_body(self):
        self.assertEqual(self.out["box"], "cbox")
        self.assertEqual(self.out["bodydisplay"], "none")
        self.assertEqual(self.out["ariafold"], "false")
        self.assertIn("3 differ", self.out["head"])
        self.assertIn("confidence: medium", self.out["head"])

    def test_one_row_per_kind_and_the_glyph_on_the_differences(self):
        self.assertEqual(self.out["rows"], 4)
        self.assertEqual(self.out["cls"], ["differs", "differs", "differs", ""])
        self.assertEqual(self.out["eq"], 3)
        self.assertEqual(self.out["kids"][0], "cd-head")

    def test_the_why_and_the_evidence_lines_are_built(self):
        self.assertEqual(self.out["why"],
                         "Why: its ranking gives 9.0 against 6.2")
        self.assertEqual(self.out["ev"],
                         "we differed on 29 level-ups and 38 buys across your "
                         "18 saved games")

    def test_no_rows_in_a_new_save_draws_no_box(self):
        """A turn with no advised phase must not claim the save is old."""
        self.assertIsNone(self.out["noRowsNew"])

    def test_a_save_that_predates_the_comparison_says_so(self):
        self.assertIn("before the comparison existed", self.out["old"])
        self.assertIn("Rebuild", self.out["old"])


if __name__ == "__main__":
    unittest.main()
