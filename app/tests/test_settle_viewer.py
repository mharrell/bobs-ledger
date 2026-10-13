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
        self.assertIn("tavernRail(row, railPhases)", src)
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


if __name__ == "__main__":
    unittest.main()
