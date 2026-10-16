"""The Live page's one layout, and the rule it is built on.

Live ships STATE (`PIVOT.md`, 2026-10-06) and `LIVE_VIEW_DESIGN.md` §1 draws the
line one notch tighter: the Live page is *reference material*, so it shows facts,
counts and statistics — never a verdict, a ranking or an imperative, and never a
guessed number.

**REVERSED 2026-10-13.** This file was "the Live viewer flag, and the rule the
Tavern layout is built on": it pinned a `Classic | Tavern` toggle, its
`bl-live-viewer` key and the branch that chose between two renderers, and the
verdict rule could only be asserted OF THE TAVERN ONE — the classic page was
allowed the model's read in words ("favored — 51 vs ~40", "FRAGILE — a 14-hit
ends it"). The maintainer made Tavern the only style and the classic renderer was
deleted rather than left unreachable, so the rule is now UNCONDITIONAL: there is
one live page and it shows no verdict at all. What is pinned below is that shape
— no control, no key, no branch, no second renderer — instead of the flag.

This file pins the parts a browser cannot see. The rendered text — including the
verdict-language scan, which is the real control for §1 — is measured in
`test_live_browser.py`, because a source assertion cannot see what reaches the
screen.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed
sys.path.insert(0, os.path.join(HERE, "tests"))

import coach_ui  # noqa: E402


def _function(name):
    m = re.search(rf"function {name}\(.*?\n\}}", coach_ui._HTML, re.S)
    return m.group(0) if m else None


def _without_comments(html=None):
    """The page with its comments removed.

    Every absence check below reads this rather than the raw string: the page's
    own source EXPLAINS what was removed and names what it removed ("the
    `_viewer`/`_liveViewer` variables are gone"), so a check on raw text fails on
    the explanation instead of on a regression. Only `/* */` blocks, `<!-- -->`
    blocks and `//` comments are removed, so live code is never removed with
    them — the stripping errs toward searching too much, never too little.
    """
    body = html if html is not None else coach_ui._HTML
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    return re.sub(r"//[^\n]*", "", body)


class TestThereIsNoViewerChoice(unittest.TestCase):
    """REVERSED 2026-10-13 from `TestTheFlag`.

    That class pinned the Live page's `Classic | Tavern` toggle, its
    `bl-live-viewer` key and "Classic is the default" — the contract of a choice
    that was about to be exercised. The maintainer decided the Tavern style is
    the only one, so there is no control, no key and no default left to assert;
    and the honest replacement is NOT a deletion, because "there is no viewer
    choice" is exactly the claim a later branch would break by adding the toggle
    back. These fail if the choice returns, and they fail if a stale
    `bl-live-viewer` value in a player's browser ever has something to read it.
    """

    def test_the_control_is_gone_from_the_markup(self):
        html = coach_ui._HTML
        for dead in ('id="live-viewer"', 'id="live-viewer-row"',
                     'data-v="classic"', 'data-v="tavern"'):
            self.assertNotIn(dead, html,
                             "the Classic | Tavern toggle is back on the page")

    def test_neither_key_survives_with_a_reader(self):
        code = _without_comments()
        for dead in ("bl-live-viewer", "bl-settle-viewer"):
            self.assertNotIn(dead, code,
                             "a viewer key outlived the control that wrote it")

    def test_there_is_no_viewer_variable_and_no_setter(self):
        code = _without_comments()
        for dead in ("_liveViewer", "_viewer", "setLiveViewer",
                     "setSettleViewer", "renderSettleGame", "hideSettleMode"):
            self.assertNotIn(dead, code, f"{dead} is back — there is one style")

    def test_a_live_payload_reaches_the_tavern_renderer(self):
        """Unconditional now: the payload that used to consult the flag draws
        the Tavern view, and nothing else draws a page."""
        src = _function("render")
        self.assertIsNotNone(src)
        self.assertEqual(src.count("renderLiveTavern(a);"), 1)
        self.assertNotIn("if (_liveViewer", src)


class TestTheBranch(unittest.TestCase):
    """REVERSED 2026-10-13 from "the tavern path is a branch, not a rewrite".

    There is no branch any more: the classic renderer was DELETED, not left
    unreachable, so these assert the shape the deletion was supposed to leave —
    one renderer, reached unconditionally, with the classic page's entry points
    and helpers gone from the file rather than dark.
    """

    def test_the_payload_draws_the_view_with_no_branch(self):
        """REVERSED from `test_the_tavern_branch_sits_after_the_shared_setup`,
        which pinned `if (_liveViewer === 'tavern') { renderLiveTavern(a); return; }`
        and the shared setup above it. The setup is still there — CARDS and the
        art pre-warm are what make hovers instant — and the page is now drawn
        once, for every live payload.
        """
        src = _function("render")
        self.assertLess(src.index("_warmed.add(cid)"),
                        src.index("renderLiveTavern(a);"))
        self.assertNotIn("if (_liveViewer", src)
        self.assertEqual(src.count("renderLiveTavern("), 1)
        # The classic page's own first two lines were its pane headers.
        self.assertNotIn("pane-h", src)

    def test_the_classic_renderer_is_gone_and_not_merely_unchosen(self):
        """REVERSED 2026-10-13 from `test_the_classic_renderer_is_untouched`.

        That test asserted four anchors of the classic live page were STILL
        PRESENT ("the classic live page changed shape"), because a toggle could
        still reach it and the shipped renderer had to be protected. The
        maintainer chose "delete it, tests included" instead, so every one of
        those anchors is an ABSENCE now — and so are the helpers and entry
        points that only that page could reach.
        """
        src = _function("render")
        for anchor in ("decide.appendChild(el('h2', 'pane-h', 'Decide'))",
                       "ref.appendChild(el('h2', 'pane-h', 'Reference'))",
                       "statebar.appendChild(statTile('Gold'",
                       "statebar.appendChild(el('span', 'tile', a.hero || '?'))"):
            self.assertNotIn(anchor, src, "the classic live page came back")
        code = _without_comments()
        for gone in ("function statTile", "function compRow", "function compBody",
                     "function compTiles", "function loadGuide", "function box(",
                     "function setLiveViewer", "function renderSettleGame",
                     "function phaseRow", "_compBodyCache", "_openComps"):
            self.assertNotIn(gone, code, f"{gone} survived the deletion")

    def test_the_view_is_one_renderer_scoped_to_the_tavern_palette(self):
        src = _function("renderLiveTavern")
        self.assertIsNotNone(src, "renderLiveTavern is missing")
        self.assertIn("el('div', 'tavern live')", src,
                      "the view has to be scoped to .tavern.live, or the Settle "
                      "Up rules and the live view's leak into each other")
        for part in ("lvStatus", "lvTribes", "lvBody"):
            self.assertIn(part, src)
        # The sections themselves (fix list round 4 item 5): the renderer builds
        # the page from ONE list of section names, so a section cannot mean one
        # thing in a column and another in the accordion.
        body = _function("lvPanelBody")
        for part in ("lvShop", "lvBoardHand", "lvWaiting", "lvCompsScreen",
                     "lvLobbyBody", "lvFacts", "lvOpponent", "lvPick"):
            self.assertIn(part, body)

    def test_the_tab_row_is_gone_and_the_sections_are_the_page(self):
        """REVERSED 2026-10-13 (fix list round 4 item 5) from
        `test_the_tab_row_is_the_screens_not_the_rail`, which pinned §4.1's
        `Shop | Comps | Lobby` row. The row selected between exclusive screens;
        in the three-column layout every section is on screen at once and
        everywhere else they are all sections of one accordion, so there is
        nothing left for it to select — the row, its constant and its CSS are all
        gone, and the live rule for a class nothing carries is how a removed
        control comes back."""
        html = coach_ui._HTML
        self.assertNotIn("LIVE_TABS", html)
        self.assertNotIn("_liveTab", html)
        # The CSS for the removed row is gone, and the ONE surviving mention is
        # the comment in its place — a rule is what could bring the row back.
        self.assertNotIn(".tavern.live .lv-tabs", html)
        self.assertIn("has no element to style at any width now", html)
        # The tab row's successor: the section names, in one place.
        self.assertIn("lvSection('Tavern'", _function("lvColumns"))
        self.assertIn("lvSection('Facts'", _function("lvAccordion"))


class TestTheDesignsLanguageRules(unittest.TestCase):
    """The source-level half of §1 (the rendered half is in the browser file).

    These are the strings the design names as verdicts to remove. The scope is
    the LIVE view's functions: since 2026-10-13 that is the whole live page (the
    classic renderer that used to be allowed them is gone), but NOT the review,
    which shares this file and is where the model's verdict is supposed to
    ship — `settleTurnCard` and `tavernRail` are deliberately not in TAVERN.
    """

    TAVERN = ("lvStatus", "lvTribes", "lvFacts", "lvCompsBody",
              "lvCompDetail", "lvCompCompare", "lvCompsScreen", "lvCompRow",
              "lvCompStats", "lvCompSortRows", "lvSlot", "lvSlotCap", "lvSlots",
              "lvSlotLegend", "lvOwned", "lvLobbyBody", "lvShop",
              "lvBoard", "lvHand", "lvBoardHand",
              "lvWaiting", "lvPick", "lvPickControls", "renderLiveTavern",
              "lvCard", "lvKV", "lvPanel", "lvEmptyRow", "lvVal",
              # Fix list round 4 items 3 and 4: the rolled-past row, the panel's
              # read age, the tavern/opponent mix and the next-opponent panel.
              # They are in this tuple because the scan below is the control for
              # §1, and a function it does not know about is a screen it does
              # not check.
              "lvPassed", "lvMix", "lvMixRow", "lvReadAge", "lvAgeText",
              "lvOpponent", "oppStatsLine", "oppMixLine",
              # Fix list round 4 item 5: the layout. `lvSectionLine` is the one
              # that matters most — a one-line summary in a header is exactly
              # where a verdict would sneak onto the page.
              "lvBody", "lvColumns", "lvAccordion", "lvSection", "lvSectionLine",
              "lvPanelBody", "lvCompsNote", "lvPicking")

    def _tavern_source(self):
        return "\n".join(filter(None, (_function(n) for n in self.TAVERN)))

    def _tavern_strings(self):
        """Only the STRING LITERALS the tavern view can put on screen.

        Scanning the whole source would flag the comments that name the words
        they exist to avoid ("never 'favored' or 'strong'") — a check that fails
        on its own documentation is a check nobody keeps. Comments are stripped
        first for the same reason, and because an apostrophe inside one ("the
        classic page's ...") pairs with a later quote and swallows live code.

        The literal pattern SKIPS ESCAPED QUOTES. Without that, a string holding
        an apostrophe (`'this project\\'s own corpus'`) closes the match early,
        the pairing shifts by one, and live source code lands inside what the
        scan thinks is a string — measured 2026-10-09, when the new comps copy
        made this check report a `?` that exists only inside a ternary.
        """
        src = re.sub(r"//[^\n]*", "", self._tavern_source())
        found = re.findall(r"'((?:[^'\\\n]|\\.)*)'", src)
        return " ".join(f.replace("\\'", "'") for f in found)

    def test_the_verdict_words_the_design_names_are_absent(self):
        text = self._tavern_strings()
        for word in ("favored", "behind", "strong", "weak", "fits your board",
                     "closest comp", "one core card away", "tribe signal",
                     "commit when", "DYING", "FRAGILE"):
            self.assertNotIn(word, text,
                             f"the Tavern live view can render {word!r} — "
                             f"LIVE_VIEW_DESIGN.md §1 replaces verdicts with facts")

    def test_no_number_is_a_question_mark(self):
        """§6.4: a value that was not read is a dash. The classic strip renders
        `?` for gold, tier and HP, and a `?` beside a number reads as part of
        the number."""
        self.assertIn("—", self._tavern_strings(), "the dash is gone")
        self.assertNotIn("?", self._tavern_strings(),
                         "a question mark reached the view")

    def test_a_row_appears_only_when_its_data_does(self):
        """§5's data rule, which is what lets the design ship before the stat
        fields are final: `fr.cap != null` guards the damage-cap row."""
        src = _function("lvFacts")
        for guard in ("fr.eff_health != null", "fr.last_hit != null",
                      "fr.recent3 != null", "fr.cap != null",
                      "a.level_cost != null"):
            self.assertIn(guard, src)

    def test_the_facts_footer_says_what_the_numbers_are(self):
        src = _function("lvFacts")
        self.assertIn("Reference only. Numbers are observational, not causal.",
                      src)

    def test_the_pick_screen_renders_the_order_the_game_offered(self):
        """§4.3: "Order defaults to As offered. The screen never ranks for the
        player." The server returns `ranked` score-ordered — row 0 is the pick
        the review grades — so rendering it as it arrives would hand the player
        the model's ranking while the wording pretended otherwise."""
        src = _function("lvPick")
        self.assertIn(".sort((x, y) => (x[4] ?? 0) - (y[4] ?? 0))", src,
                      "the options must sort by the game's own offer order")
        self.assertIn("Shown in the order offered", src)

    def test_the_comps_view_is_recut_and_reset(self):
        """Item B.1's second sentence: "Recompute the list on every tribe change
        and reset it when a game ends."

        The rows are derived from the payload, so the RECOMPUTE is about the view
        state that points into the list — which groups are expanded and which
        comps are ticked for Compare. It runs from `renderLiveTavern` (before the
        body is built, so no frame draws a list that no longer exists), and a game
        ending drops all of it. The rendered half is
        `test_live_browser...test_a_tribe_change_recuts_the_view_state`; this is
        the half a browser cannot see, because the reset happens on a payload with
        no comps list on it.
        """
        body = _function("lvSyncCompsView") or ""
        self.assertIn("_liveCompMore = new Set();", body)
        self.assertIn("_liveCompare.delete", body)
        self.assertIn("lvInLobby(a)", body)
        live = _function("renderLiveTavern") or ""
        self.assertIn("lvSyncCompsView(a);", live,
                      "the tribe state is not re-cut before the body renders")
        self.assertLess(live.index("lvSyncCompsView(a);"),
                        live.index("lvBody(a)"),
                        "the list is built before the view state is re-cut")
        # A GAME OVER resets it, and `lvResetCompsView` is the one owner of that.
        over = _function("renderTavernGameOver") or ""
        self.assertIn("lvResetCompsView();", over)
        reset = _function("lvResetCompsView") or ""
        for piece in ("_liveComp = null;", "_liveCompSort = 'tier';",
                      "_liveCompMore = new Set();", "_liveCompare = new Set();",
                      "_lvTribeKey = null;"):
            self.assertIn(piece, reset,
                          f"the game-over reset no longer clears {piece}")

    def test_the_comps_screens_never_call_anything_a_ranking(self):
        """The comps screens state where a tier comes from and that the sort is
        the player's, in words a scan for rank language can stay honest about.
        Comments are stripped: the source explains the rule and would otherwise
        fail its own check.

        `lvCompsBrowse` was in this tuple until 2026-10-14, when it was deleted
        as dead: it was a two-line wrapper (`lvPanel('Comps', lvCompsBody(a),
        …)`) that predated the classic removal, `lvPanel`/`lvPanelBody` now wrap
        the section itself, and nothing in the page or the suite called it. Its
        subject is `lvCompsBody`, which is what the Comps screen actually
        renders (`lvCompsScreen` calls it, and `lvCompDetail` instead when a row
        is open) — and which was ALREADY in this scan, so the deletion takes no
        coverage with it.
        """
        names = ("lvCompsBody", "lvCompCompare", "lvCompSortRows", "lvCompStats")
        # POSITIVE CONTROL, for the reason 62fb33d documents twice over: a name
        # that resolves to nothing contributes an empty string, and a scan whose
        # functions were all renamed or deleted would pass the two absence
        # checks below on "" — a measurement that cannot fail is not one. Each
        # name has to RESOLVE, and the comps screen's own sort control has to be
        # in the text this scans.
        for n in names:
            self.assertIsNotNone(_function(n),
                                 f"{n} is gone — this scan is measuring nothing")
        src = re.sub(r"//[^\n]*", "", "\n".join(_function(n) for n in names))
        self.assertIn("Sort", src, "the comps screen's sort control is missing")
        self.assertNotIn("rank", src.lower())
        self.assertNotIn("best", src.lower())


class TestTheCompStatistics(unittest.TestCase):
    """§4.4/§5's comp numbers, which are the only stats in `meta/` this project
    generated itself (`meta/corpus_stats.json`, written by `replay_stats.py
    --save`) — and therefore the only ones with a games count to hang §5's
    low-sample rule on. The rendered side is in `test_live_browser`."""

    def test_a_record_becomes_the_components_the_design_names(self):
        st = coach_ui._comp_stats({"games": 4, "wins": 1, "top4": 2,
                                   "avg_place": 4.0, "places": [1, 3, 5, 7]})
        self.assertEqual(st["games"], 4)
        self.assertEqual(st["avg_place"], 4.0)
        self.assertEqual(st["dist"], {"1": 25.0, "2": 0.0, "3": 25.0,
                                      "4": 0.0, "5": 25.0, "6": 0.0,
                                      "7": 25.0, "8": 0.0})
        self.assertEqual(st["top4_pct"], 50)
        self.assertEqual(st["first_pct"], 25)
        self.assertTrue(st["low_sample"], "4 games is under the threshold")

    def test_a_comp_nobody_has_played_yields_nothing(self):
        """§5: a row appears only when the data exists. A comp the corpus has
        never seen must not arrive as a zero — it arrives as None."""
        for empty in (None, {}, {"games": 0}, {"games": None}):
            self.assertIsNone(coach_ui._comp_stats(empty))

    def test_the_low_sample_threshold_is_a_games_count(self):
        """§11 asks what the minimum games count is; the answer is a named
        constant, so the flag and the figure cannot drift apart."""
        self.assertEqual(coach_ui.COMP_LOW_SAMPLE_GAMES, 10)
        edge = coach_ui._comp_stats(
            {"games": coach_ui.COMP_LOW_SAMPLE_GAMES, "places": [2] * 10})
        self.assertFalse(edge["low_sample"])
        under = coach_ui._comp_stats(
            {"games": coach_ui.COMP_LOW_SAMPLE_GAMES - 1,
             "places": [2] * (coach_ui.COMP_LOW_SAMPLE_GAMES - 1)})
        self.assertTrue(under["low_sample"])

    def test_the_real_corpus_file_has_the_shape_this_reads(self):
        """The fixture in `test_live_browser` replaces the reader, so this is
        the control on the real file: if `replay_stats.py` ever writes a
        different shape, the comps screens would silently show dashes forever."""
        import meta
        data = meta.corpus_stats()
        self.assertIsInstance(data, dict)
        comps = data.get("comps") or {}
        self.assertIsInstance(comps, dict, "corpus_stats.comps is not a mapping")
        for name, rec in comps.items():
            st = coach_ui._comp_stats(rec)
            self.assertIsNotNone(st, f"{name} has a record this cannot read")
            self.assertGreater(st["games"], 0)
            self.assertEqual(len(st["dist"]), 8)
            self.assertIsInstance(st.get("avg_place"), float)


class TestTheCompScreensAtSource(unittest.TestCase):
    """§4.4's rules that a browser cannot state on its own: where the numbers
    come from, and which of the design's sizes are actually declared."""

    def test_the_payload_row_carries_the_tribe_and_the_hand_flag(self):
        """§4.4's Browse filters by tribe and counts a core card owned when it
        is on the board OR IN HAND. The payload's `owned` is the classic
        panel's board-only rule, so the second flag has to exist."""
        src = open(os.path.join(HERE, "coach_ui.py"), encoding="utf-8").read()
        self.assertIn('"tribe": comp.get("tribe"),', src)
        self.assertIn('"in_hand": cid in hand_ids,', src)
        self.assertIn('hand_ids = {s["card"] for s in (analysis.get("hand") or [])',
                      src)

    def test_the_mini_card_slot_sizes_are_the_designs(self):
        """§5: 52x70 in Compare, and a CARD at 88x120 / 76x100 in Detail. A tile
        is 88-124px wide, so a slot that inherited the card rule would be more
        than twice the specified size — which is exactly the failure mode the
        design's own §5 table exists to prevent.

        The BROWSE slot is 34x46 from 2026-10-16 (item B.2 put it at 40x54 on
        2026-10-14; the comp NAME was truncating behind it, measured, so it
        narrowed — see `test_the_core_slots_are_the_designs_34_by_46`). The pin
        moves with it rather than being deleted: the size is still a declared
        number a rule can lose.
        """
        html = coach_ui._HTML
        self.assertIn("width:34px; height:46px", html)
        self.assertIn(".lv-cmpcol .lv-slot { width:52px; height:70px; }", html)
        self.assertIn(".lv-core { --tcardw:88px; }", html)
        self.assertIn(".lv-flexcards { --tcardw:76px;", html)
        self.assertIn("aspect-ratio:76/100;", html)
        # ...and the not-owned art is DIMMED at 75%, not at the 35% that read as
        # an empty box.
        self.assertIn("opacity:.75; filter:grayscale(1);", html)

    def test_the_browse_cap_and_the_compare_limit_are_named_constants(self):
        self.assertIn("const LIVE_COMP_ROWS = 6;", coach_ui._HTML)
        self.assertIn("const LIVE_COMPARE_MAX = 3;", coach_ui._HTML)
        # The cap lives in the BROWSE BODY (fix list round 4 item 5: the panel
        # wrapper moved to `lvSection`, the list did not).
        src = _function("lvCompsBody")
        self.assertIn("LIVE_COMP_ROWS", src)
        src = _function("lvCompRow")
        self.assertIn("LIVE_COMPARE_MAX", src)

    def test_the_guide_is_collapsed_until_it_is_asked_for(self):
        """§4.4 Detail: "`Guide text ▸` collapsed by default", and the fetch
        waits for the expand rather than riding every redraw."""
        src = _function("lvCompDetail")
        self.assertIn("document.createElement('details')", src)
        self.assertIn("det.ontoggle", src)
        self.assertNotIn("det.open = true", src)
        self.assertIn("lvLoadGuide", src)
        # Its own node, not the classic panel's: that one is built from the
        # classic classes and is cached page-wide.
        self.assertIn("_lvGuideCache", coach_ui._HTML)

    def test_the_facts_table_is_a_section_and_never_a_screen_of_its_own(self):
        """REVERSED 2026-10-13 (fix list round 4 item 5) from
        `test_the_facts_table_is_the_rail_and_not_a_tab`. The rail is gone with
        the tab row it sat beside: the facts table is column 3 of the
        three-column layout and the PINNED strip of the accordion, and it is one
        panel either way — `lvFacts` returns the table and `lvSection` wraps it,
        so there is exactly one `.lv-pn` and one heading for it. `_liveTab` and
        `LIVE_TABS` are gone with the row, so "the facts table is not one of the
        tabs" is now true by there being no tabs.
        """
        self.assertNotIn("LIVE_TABS", coach_ui._HTML)
        self.assertNotIn("_liveTab", coach_ui._HTML)
        # One section per arrangement, and the facts table is one of them.
        cols = _function("lvColumns") or ""
        acc = _function("lvAccordion") or ""
        self.assertEqual(cols.count("lvSection('Facts'"), 1)
        self.assertEqual(acc.count("lvSection('Facts'"), 1)
        # `lvFacts` builds the TABLE, not a panel: a panel here would nest one
        # `.lv-pn` inside another and give the section two headings.
        self.assertNotIn("'lv-pn'", _function("lvFacts") or "")

    def test_the_focus_ring_and_the_target_sizes_are_declared(self):
        """§8: "Visible focus ring (2px `--sel`, with offset) on all controls;
        44px minimum click targets for buttons and tabs." The ring is scoped to
        `.tavern`, so it reaches both Tavern viewers and leaves the classic pages
        with the browser's own.

        The tab row's own entry went with the tab row (round 4 item 5); its
        successor is the accordion section header, which is a `<h3>` carrying a
        click handler, so it is in this list instead.
        """
        html = coach_ui._HTML
        self.assertIn(".tavern :focus-visible { outline:2px solid var(--tsel); "
                      "outline-offset:2px; }", html)
        for sel in (".tavern.live .lv-acc > h3", ".tavern.live .lv-more",
                    ".tavern.live .lv-back", ".tavern.live .lv-gobtn"):
            block = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", html)
            self.assertIsNotNone(block, f"{sel} lost its rule")
            self.assertIn("min-height:44px", block.group(1),
                          f"{sel} is under the design's 44px minimum target")

    def test_every_section_switch_is_a_click_away_from_the_list(self):
        """REVERSED 2026-10-13 (fix list round 4 item 5) from
        `test_every_screen_switch_is_a_click_away_from_the_list`, which pinned
        `_liveTab`'s three branches. The screens are sections now, and the click
        that reaches one is the header's own — in the accordion it is the only
        way (the section is `display:none` until it is opened), and in the
        three-column layout every section is visible, so the equivalent claim is
        that the comps list is one click from its own Detail and back.

        RE-POINTED 2026-10-14: `lvPicking` moved OUT of `lvColumns` and into
        `lvBody` (the pick screen is a full-width strip above both arrangements
        now), so the predicate is asserted where it lives. The claim is the same
        one — the pick replaces nothing, and every dashboard section is on the
        page either way, which is why the Tavern section is in the COLUMNS
        unconditionally rather than only when nothing is being picked.
        """
        cols = _function("lvColumns") or ""
        for section in ("'Tavern'", "'Board and hand'", "'Comps'",
                        "'Next opponent'", "'Lobby'"):
            self.assertIn(section, cols,
                          f"the layout lost its {section} section")
        body = _function("lvBody") or ""
        self.assertIn("lvPicking(a)", body,
                      "the pick strip has no predicate of its own")
        self.assertIn("'Choose one'", body)
        self.assertIn("lv-pickstrip", body,
                      "the pick strip cannot be found by name")
        # The accordion header is a real control: clickable, keyboard-reachable,
        # and it carries the state it toggles.
        sec = _function("lvSection") or ""
        self.assertIn("h.onclick = flip;", sec)
        self.assertIn("h.onkeydown", sec)
        self.assertIn("aria-expanded", sec)
        self.assertIn("_liveComp = null;", _function("lvCompDetail") or "",
                      "the back link has to drop the open comp detail")


class TestTheRoundsFourthList(unittest.TestCase):
    """Fix list round 4, items 3 and 4, at the source.

    Item 3(c) is the one this class exists for: the tavern lists, per turn, the
    offers that were ROLLED PAST, keyed by OFFER ENTITY — two copies of one
    minion are two entries, which no card-keyed record can express. The rendered
    half of each claim is measured in `test_live_browser`
    (`TestWhatTheShopKeepsSaying`); these are the parts a browser cannot see.
    """

    def setUp(self):
        import live_coach  # noqa: F401  (the circular-import primer)
        self.code = open(os.path.join(HERE, "coach_ui.py"),
                         encoding="utf-8").read()
        self.producer = open(os.path.join(HERE, "live_coach.py"),
                             encoding="utf-8").read()

    def test_the_producer_records_an_offer_ENTITY_leaving_the_shop(self):
        """One entry per offer entity, and the hunt's card-keyed evidence left
        exactly as it was: `_shop_seen` feeds `value._hunt_check` and is not
        this feature's business."""
        src = self.producer
        self.assertIn("self.shop_passed.append({", src)
        self.assertIn('"eid": _eid, "card": _cid', src)
        self.assertIn('"shop_passed": list(self.shop_passed),', src)
        # The sightings dict keeps its shape and its one writer.
        self.assertIn('self._shop_seen[cid] = self.actions.turn', src)

    def test_a_bought_offer_is_not_recorded_as_passed(self):
        """Both ways an offer is TAKEN — the Drag To Buy target and the ZONE=HAND
        write that follows it — mark it, and the recorder skips it."""
        src = self.producer
        self.assertEqual(src.count("self._shop_taken_eids.add("), 2)
        self.assertIn("if _eid in _new_eids or _eid in self._shop_taken_eids:",
                      src)

    def test_the_tavern_closing_is_not_a_roll(self):
        """Measured on the 2026-10-08 07:45 game: the phase-start wipe clears
        the previous turn's UNSOLD offers, and the turn counter has already
        advanced when it does — 132 of 212 naive departures were that, stamped
        with the new turn. The wipe clears the comparison snapshot so the diff
        reads "nothing left", and the recorder only runs inside an open shop."""
        src = self.producer
        self.assertIn("self._shop_prev = {}", src)
        self.assertIn('if self._phase == "buy":', src)

    def test_the_report_still_names_the_new_analysis_field(self):
        """`session_report.SPEC` has teeth in both directions: a new analysis key
        the report neither ships nor drops REFUSES the send."""
        import session_report
        self.assertIn("shop_passed", session_report.DROPPED_FROM_ANALYSIS)
        self.assertTrue(any("shop_passed[]" in s
                            for s in session_report.DROPPED_ON_PURPOSE))

    def test_the_rolled_past_payload_row_keeps_the_entity_id(self):
        """The page cannot draw two cards without two entity ids, and the key is
        this turn's rows only — the analysis keeps the whole game."""
        import test_live_browser as tlb
        out = coach_ui.render_json(tlb._comps_analysis(
            turn=9, shop_passed=[{"eid": 11, "card": "BG31_815", "turn": 9},
                                 {"eid": 12, "card": "BG31_815", "turn": 9},
                                 {"eid": 13, "card": "BG31_815", "turn": 8}]))
        self.assertEqual([r["eid"] for r in out["shop_passed"]], [11, 12])

    def test_the_row_is_built_from_the_entity_list_and_never_keyed_by_card(self):
        src = _function("lvPassed") or ""
        self.assertIn("a.shop_passed", src)
        self.assertIn("s.card", src)
        for bad in ("shop_eids", r"\.get(s\.card", "names[s.card]"):
            self.assertNotIn(bad, src,
                             "the rolled-past row keys something by card id")
        # §5's data rule and item 3's "never empty without a state".
        self.assertIn("Nothing rolled past yet this turn.", src)

    def test_the_panel_carries_its_own_read_age(self):
        """Item 3(b): the age belongs on the panel, not only in the window's
        freshness strip — and it ticks, because the payload does not change
        while the player is thinking."""
        self.assertIn("tickReadAge();", _function("tickFreshness") or "")
        self.assertIn("tickReadAge();", _function("renderLiveTavern") or "")
        self.assertIn("read just now", _function("lvAgeText") or "")
        self.assertIn("lvReadAge()", _function("lvPanel") or "")
        self.assertIn("lvReadAge()", _function("lvWaiting") or "",
                      "the empty shop is the panel where the age matters most")
        # A CLASS, not an id (fix list round 4 item 5): the Tavern panel is built
        # in BOTH arrangements, so an id would be duplicated in one document and
        # `getElementById` would fill whichever came first, leaving the other
        # line empty forever.
        self.assertIn("querySelectorAll('.lv-read')",
                      _function("tickReadAge") or "")
        self.assertNotIn(".id = 'lv-read'", coach_ui._HTML)

    def test_the_mix_is_counted_per_offer_where_the_cards_are_known(self):
        """§5's data rule: a card neither DB carries contributes NOTHING rather
        than a guessed tribe, and a spell is its own row so the counts add up
        to the cards on screen."""
        import test_live_browser as tlb
        out = coach_ui.render_json(tlb._comps_analysis(
            shop_offers=["BG31_815", "BG31_815"],
            shop_entities=[{"eid": 1, "card": "BG31_815"},
                           {"eid": 2, "card": "BG31_815"}]))
        self.assertEqual(out["shop_mix"], [{"tribe": "Elemental", "n": 2}])
        out2 = coach_ui.render_json(tlb._comps_analysis(
            shop_offers=["BG31_815", "BG31_880"],
            shop_entities=[{"eid": 1, "card": "BG31_815"},
                           {"eid": 2, "card": "BG31_880"}]))
        self.assertEqual(out2["shop_mix"], [{"tribe": "Elemental", "n": 1},
                                            {"tribe": "Spell", "n": 1}],
                         "a tavern spell is counted, not dropped")

    def test_the_opponent_panel_is_built_from_the_analysis_and_says_no_verdict(self):
        """Item 4: hero, board, number, age, mix — and NOT the seat's handle,
        which stays on the Lobby tab because this panel is the one that ends up
        in a screenshot, and the repo's rule for those is to eyeball exactly
        this field before one ships (no gate reads a picture)."""
        src = _function("lvOpponent") or ""
        for anchor in ("oc.hero_name", "oppStatsLine(a)", "oc.turn",
                       "oc.tribes", "oc.cards"):
            self.assertIn(anchor, src)
        self.assertNotIn("oc.name", src,
                         "the opponent's BattleTag reached the panel")
        self.assertNotIn("favored", src)
        # The number and its age come from ONE builder, so the Tavern panel and
        # the classic Reference box cannot word the same facts differently.
        line = _function("oppStatsLine") or ""
        self.assertIn("a.opp_stats", line)
        self.assertIn("a.opp_age", line)
        self.assertIn("lobby avg", line)
        self.assertIn("oppStatsLine(a)",
                      (self.code.split("//: THE NEXT OPPONENT")[1])[:2500])

    def test_the_opponent_panel_is_the_only_one_left(self):
        """REVERSED 2026-10-13 from
        `test_the_classic_opponent_box_gained_the_same_two_facts`, which pinned
        the classic Reference pane's copy of the mix and the number-with-age.
        That pane is gone, so the constraint it satisfied — two boxes wording the
        same facts identically — is satisfied by there being one box: the mix
        formatter the classic box called (`oppMixLine`) is gone too, and the panel
        reads the payload's own `oc.tribes`.
        """
        self.assertNotIn("function oppMixLine", self.code)
        panel = self.code.split("function lvOpponent")[1][:2000]
        self.assertIn("oppStatsLine(a)", panel)
        self.assertIn("oc.tribes", panel)
        self.assertIn("'round ' + oc.turn", panel)


class TestTheGameOverCard(unittest.TestCase):
    """§6.5, and the route that had to exist for it.

    The end-of-game payload is `welcome: true` with NO board, and `render`
    returned at the welcome branch before consulting the viewer — so the Tavern
    game-over card was unreachable in a real session while a direct render in a
    test made it look alive. The rendered card is measured in `test_live_browser`;
    this pins the route and the merge.
    """

    def test_the_welcome_branch_routes_on_the_card_not_a_viewer(self):
        """REVERSED 2026-10-13 from `test_the_welcome_branch_consults_the_viewer`.

        The welcome payload has no board, so the branch used to need the viewer
        flag to know WHICH game-over card to draw — and the Tavern one was
        unreachable in a real session until that branch consulted it. There is
        one card now, so the only question left is whether the payload carries
        one; a first run gets the shell card, and `lvClearTavern` still runs for
        it, or it draws behind a stale Tavern frame.
        """
        src = _function("render")
        self.assertIn("if (a.game_over) {", src)
        self.assertNotIn("_liveViewer", src)
        self.assertLess(src.index("renderTavernGameOver(a)"),
                        src.index("renderWelcome(a)"),
                        "the game-over payload has to be routed before the "
                        "first-run card claims it")
        self.assertIn("lvClearTavern();", src,
                      "a first-run card must clear the live view, or it draws "
                      "behind a stale frame")

    def test_the_card_owns_its_own_entry_point(self):
        src = _function("renderTavernGameOver")
        self.assertIsNotNone(src)
        self.assertIn("app.classList.add('tavern-on')", src)
        self.assertIn("'Open in Settle Up'", src)
        self.assertIn("showTab('settle')", src)
        # The page chrome, which the early return in `render` skips.
        self.assertIn("renderShareToggle(a.share)", src)
        self.assertIn("renderRelease(a.release)", src)
        # And it is NOT drawn by the live renderer, which never sees this
        # payload shape.
        self.assertNotIn("lvGameOver",
                         _function("renderLiveTavern") or "")

    def test_the_save_row_holds_the_control_and_its_answer(self):
        src = re.sub(r"//[^\n]*", "", _function("lvSaveRow"))
        self.assertIn("row.appendChild(cb);", src)
        self.assertIn("row.appendChild(lbl);", src)
        self.assertIn("row.appendChild(el('span', 'lv-saved',", src)
        self.assertIn("row.appendChild(save);", src)

    def test_each_post_lives_in_exactly_one_place(self):
        """The classic card and the Tavern card offer the same two actions, so
        the endpoints and the 409 race have to be shared rather than copied —
        two copies is how one of them loses the retry."""
        for call in ("fetch(auth('/review/save')", "fetch(auth('/review/auto-save')"):
            self.assertEqual(coach_ui._HTML.count(call), 1,
                             f"{call} is posted from more than one place")
        self.assertIn("postSaveReplay(save);", _function("lvSaveRow"))
        self.assertIn("postAutoSave(cb,", _function("lvSaveRow"))
        classic = _function("renderWelcome")
        self.assertIn("postSaveReplay(save);", classic)
        self.assertIn("postAutoSave(cb,", classic)

    def test_the_live_view_is_cleared_from_one_place(self):
        """`lvClearTavern` is the single reset: a view that is no longer drawing
        must not leave its last frame on screen, and the first-run card has no
        design of its own so it is drawn over the shell.

        REVERSED 2026-10-13 from a count of THREE (the definition, the classic
        path and the welcome branch): the classic path was the other caller and
        it is gone, so the count is two.
        """
        self.assertEqual(coach_ui._HTML.count("lvClearTavern"), 2,
                         "defined once, called from the welcome branch")


class TestTheFixListRounds(unittest.TestCase):
    """The two Live fix lists of 2026-10-09, at source level.

    The rendered half of every one of these is measured in `test_live_browser`
    (which is where the layout claims have to be checked, because a rule can
    exist and lose to a more specific one). This is the half a browser cannot
    state: which rule was written, and which call was made from where.
    """

    def test_live_fills_the_window(self):
        """Round 1 item 1. `#app` is a grid above 1200x900 and a flex COLUMN at or
        below it, so the fix has to cover both: a width that does not depend on
        `flex-basis` being a width (measured before the fix: 815px of a 1384px
        window).

        REVERSED 2026-10-13: the fix used to be a `grid-template-columns`
        override on `#app.tavern-on` — the shell was two columns for the classic
        page's two panes, and the view had to be collapsed into one. The shell is
        ONE column at the base rule now (the second pane went with the classic
        page), so the override had nothing left to override and the surviving half
        is the width, which is what holds in the flex branch too.
        """
        html = coach_ui._HTML
        self.assertIn("#app { display:grid; grid-template-columns:minmax(0,1fr);",
                      html)
        self.assertIn("#app.tavern-on #live-tavern { width:100%; min-width:0; }",
                      html)
        self.assertNotIn("#app.tavern-on { grid-template-columns", html,
                         "the one-column override is back with nothing to "
                         "override — the base rule is one column")

    def test_the_breakpoints_are_the_ones_asked_for(self):
        """Round 2 item 9: main + 340px rail at >=1200px, stacked 700-1200, and a
        single-column pick grid under 700."""
        html = coach_ui._HTML
        self.assertIn("@media (min-width: 1200px) {", html)
        self.assertIn(".tavern.live .lv-main { grid-template-columns:"
                      "minmax(0,1fr) 340px; }", html)
        self.assertIn("@media (max-width: 699.98px) {", html)
        self.assertIn(".tavern.live .lv-opts { grid-template-columns:1fr; }", html)
        # The stacked default is the base rule, not a media query: 700-1200 is
        # the common laptop window.
        self.assertIn(".tavern.live .lv-main { display:grid; "
                      "grid-template-columns:minmax(0,1fr);", html)

    def test_the_segment_control_is_themed(self):
        """Round 1 item 9 / round 2 item 8: `.vseg` described the ACTIVE state and
        the radii only, so the buttons were whatever the browser draws.

        REVERSED 2026-10-13 from `test_the_classic_tavern_toggle_is_themed`. The
        one segment control left is the Settle Up header's `Summary | Step
        through`, and the tavern-palette rules that rode the nav row went with
        the live flag: the nav is a SIBLING of `#app`, so a `.tavern` rule could
        never reach it — those rules were only ever about the deleted control,
        which is why they are absences now.

        CHANGED 2026-10-15 (maintainer): "the formatting is inconsistent at the
        top of each page … it should all be the more recent brown tavern style."
        It was: the chrome (`#freshness`, `#tabs`, `.s-head`) sits outside both
        views, so it kept the old cool shell tokens while everything under it was
        brown. The palette reaches it now by putting `.tavern` ON those elements
        rather than on a shared ancestor — on `#wrap` it also handed
        `--tcardw`/`--tstepw` to containers that were `width:auto` without them,
        and the page grew a scrollbar (the layout tests caught it: the 1400px
        box went from 1356 to 1332, and back).
        """
        html = coach_ui._HTML
        block = re.search(r"\.vseg button \{([^}]*)\}", html)
        self.assertIsNotNone(block)
        for prop in ("background:var(--tpanel)", "border:1px solid var(--tline)",
                     "padding:6px 12px"):
            self.assertIn(prop, block.group(1))
        self.assertIn('id="settle-mode" class="vseg"', html)
        code = _without_comments(html)
        self.assertNotIn("#tabs.tavern #live-viewer-row .vseg button", code)
        self.assertNotIn("#live-viewer-row", code)

    def test_the_chrome_wears_the_tavern_palette(self):
        """The other half of the 2026-10-15 change: the top of the page.

        The palette is scoped to `.tavern`, so the chrome has to CARRY it — and
        each element has to carry it itself, because the token rule must keep its
        exact `.tavern` selector for the token-discipline test to recognise it.
        """
        html = coach_ui._HTML
        for el in ('<div id="freshness" class="tavern">',
                   '<nav id="tabs" class="tavern">',
                   '<div class="s-head tavern">'):
            self.assertIn(el, html, f"{el} no longer carries the palette")

        tabs = re.search(r"#tabs \.tab \{([^}]*)\}", html)
        self.assertIsNotNone(tabs)
        self.assertIn("background:var(--tpanel)", tabs.group(1))
        self.assertIn("color:var(--tmute)", tabs.group(1))
        head = re.search(r"\.s-head select \{([^}]*)\}", html)
        self.assertIsNotNone(head)
        self.assertIn("background:var(--tcard)", head.group(1))
        self.assertIn("color:var(--ttext)", head.group(1))

    def test_the_nav_row_carries_no_control_for_the_live_view(self):
        """REVERSED 2026-10-13 from
        `test_the_live_viewer_toggle_lives_on_the_nav_row`, which pinned the
        right-aligned flag, the `showTab` line that hid it on the Settle Up tab
        and the line in `setLiveViewer` that themed the nav from it. All three
        were the toggle; with the toggle gone the nav row carries the two tabs
        and the sharing control, and nothing about the live view's style.

        CHANGED 2026-10-15: the nav now carries `class="tavern"` so the chrome
        wears the palette (see `test_the_chrome_wears_the_tavern_palette`). This
        test is about the JS TOGGLE, which is still what it refuses — a static
        class on the element is not a control that needs something to theme.
        """
        html = coach_ui._HTML
        nav = html[html.index('<nav id="tabs"'):html.index("</nav>")]
        # The CODE, not the comments: the page's own notes name the removed
        # `#live-viewer-row` and the two keys on purpose, so a raw search fails
        # on the explanation rather than on a regression.
        self.assertNotIn("live-viewer", _without_comments(nav))
        code = _without_comments(html)
        self.assertNotIn("live-viewer", code)
        self.assertNotIn("viewer.hidden", _function("showTab"))
        self.assertNotIn("classList.toggle('tavern'", code,
                         "the nav theming came back with no control to theme")


class TestTheEntityRows(unittest.TestCase):
    """Round 3 item 1: the tavern is a list of ENTITIES, not a card-keyed list.

    One row per OFFER, one row per board minion — two identical cards are two
    cards, because that is what the game showed. The payload's `shop_rank` was
    built by keying the offers onto a card-keyed ranking (one entry per distinct
    card), so the second copy of an offer was dropped on the floor.
    """

    def setUp(self):
        import live_coach  # noqa: F401  (the circular-import primer)
        self.code = open(os.path.join(HERE, "coach_ui.py"), encoding="utf-8").read()

    def _analysis(self, **over):
        import test_live_browser as tlb
        return tlb._comps_analysis(**over) if False else tlb._analysis(**over)

    def test_the_offers_reach_the_payload_as_entities(self):
        out = coach_ui.render_json(self._analysis(
            shop_offers=["BG31_820", "BG31_820"],
            shop_entities=[{"eid": 7, "card": "BG31_820"},
                           {"eid": 8, "card": "BG31_820"}]))
        self.assertEqual([(r["card"], r["eid"]) for r in out["shop_rank"]],
                         [("BG31_820", 7), ("BG31_820", 8)])

    def test_the_pool_chip_is_the_cards_number_on_both_copies(self):
        """...and it is not summed or halved: the pool is a property of the
        CARD, and the row says the same thing about both copies. `BG31_815` is a
        real pool card (an unknown id has no chip at all, which is why the
        fixture uses one)."""
        out = coach_ui.render_json(self._analysis(
            shop_offers=["BG31_815", "BG31_815"],
            shop_entities=[{"eid": 7, "card": "BG31_815"},
                           {"eid": 8, "card": "BG31_815"}],
            own_pool={"BG31_815": 1}))
        pools = [r["pool"] for r in out["shop_rank"]]
        self.assertEqual(pools[0], pools[1])
        self.assertIn("pool left", pools[0] or "")

    def test_the_board_row_is_built_from_the_board_itself(self):
        src = _function("lvBoard") or ""
        self.assertIn("a.board_cards", src)
        self.assertIn("sell_rank", src, "the old payload still has a fallback")
        self.assertIn("passedThrough(", self.code,
                      "the Settle Up tray still walks an id-keyed map")

    def test_the_producer_keeps_a_per_offer_entity_list(self):
        code = open(os.path.join(HERE, "live_coach.py"), encoding="utf-8").read()
        self.assertIn("self.shop_offer_entities = [", code)
        self.assertIn('"shop_entities": list(self.shop_offer_entities),', code)

    def test_the_report_still_names_the_new_analysis_field(self):
        """`session_report.SPEC` has teeth in both directions: a new analysis key
        the report neither ships nor drops REFUSES the send."""
        import session_report
        self.assertIn("shop_entities", session_report.DROPPED_FROM_ANALYSIS)
        self.assertTrue(any("shop_entities[]" in s
                            for s in session_report.DROPPED_ON_PURPOSE))


class TestTheShippedCompsDb(unittest.TestCase):
    """A tier refresh is a DATA change, and nothing else checks that the shipped
    DB's own records survive the producer.

    Every other comps test runs on a fixture, so a bad refresh (a comp with no
    tribe, a core that no longer resolves, a hand-added field that went missing)
    would ship and only show up on a player's screen. This runs the REAL
    `meta/comps.json` through `render_json` and requires every comp in it to come
    out the other side as a row with a name, a tier label and a core list.
    """

    def test_every_comp_in_the_shipped_db_renders(self):
        import meta
        import test_live_browser as tlb
        real = meta.comps()
        self.assertGreater(len(real), 20)
        out = coach_ui.render_json(tlb._analysis(game_comps=real))
        self.assertEqual(len(out["comps"]), len(real),
                         "a comp in the shipped DB has no row in the payload")
        for row in out["comps"]:
            self.assertTrue(row["name"], row)
            self.assertTrue(row["core"], f"{row['slug']} has no core cards")
            self.assertIsInstance(row["stats"], (dict, type(None)))
            self.assertIn(row["tribe_available"], (True, False))

    def test_every_comp_in_the_shipped_db_has_a_canonical_tribe(self):
        """`scrape_comps.py` never writes `tribe` — it is hand-added on every new
        comp, and a refresh that forgets it is a comp no tribe filter can find.
        `check_meta.py` enforces this too; this is the same rule where the suite
        will see it fail."""
        import meta
        import tribes
        real = meta.comps()
        for slug, comp in real.items():
            if comp.get("name") == "Menagerie":
                continue          # mixed by definition, and check_meta says so
            self.assertIn(comp.get("tribe"), tribes.DISPLAY_TRIBES,
                          f"{slug} has tribe {comp.get('tribe')!r}")

    def test_the_facts_drop_lethal_at_and_name_the_lobby_average(self):
        """Round 1 item 5 / round 2 item 6."""
        src = _function("lvFacts")
        self.assertNotIn("Lethal at", src)
        self.assertIn("lobby avg", src)
        self.assertIn("'Board stats — you vs lobby avg'", src)

    def test_a_tribe_out_of_play_is_listed_once(self):
        """Round 1 item 3: the roster contains every tribe, `out_of_pool` names
        the rotated ones, and iterating both printed Naga twice.

        Round 4 item 1 moved the chip's meaning: AVAILABLE is the mark (`avail`),
        a tribe this game cannot offer is `dim`, and a tribe whose chip the
        player has set is `active` on top of that.

        REVERSED 2026-10-13: what the player has set is the five IN THE TAVERN,
        so the seed is `tribes_available` — the old line was
        `new Set(a.bans_manual ? (a.banned || []) : [])`, which marked the
        complement amber. Measured on the released install (session
        2026-10-13_12_01_10, 181 records): every one of that game's shop offers
        came from the tribes the amber chips named, i.e. the row read "these
        five are in" over the five the lobby could not offer. Both halves are
        pinned here, the class rule and the seed, because the seed was the half
        no test read.
        """
        src = _function("lvTribes")
        self.assertIn(".filter(t => !oop.has(t))", src)
        self.assertIn("'lv-chip ' + (on ? 'active' : (can ? 'avail' : 'dim'))",
                      src)
        self.assertIn("a.tribes_available", src)
        self.assertIn("const picked = new Set(a.bans_manual ? "
                      "(a.tribes_available || []) : []);", src)
        self.assertNotIn("? (a.banned || [])", src,
                         "the row seeds its amber set from the banned list "
                         "again — the direction 2026-10-13 fixed")
        # The tooltips say the direction in words too: a tapped chip is in the
        # tavern, a green one is what the pool can offer, and neither is a ban.
        self.assertIn("'In the tavern — tap to clear'", src)
        self.assertIn("'In play — tap to say it is in the tavern'", src)
        self.assertNotIn("tap to ban", src)

    def test_the_comps_slots_carry_art_and_a_legend(self):
        """Round 1 item 6."""
        src = _function("lvSlot")
        self.assertIn("thumb(x.card, x.name)", src)
        legend = _function("lvSlotLegend")
        self.assertIsNotNone(legend, "the slot legend is missing")
        for label in ("on board", "in hand", "not owned", "banned this game"):
            self.assertIn(label, legend)
        self.assertIn("lvSlot({", legend)
        row = _function("lvCompRow")
        self.assertIn("cb.type = 'checkbox'", row)
        self.assertIn("'lv-cmpbox'", row)

    def test_the_pick_screen_shows_one_name_and_a_one_decimal_headline(self):
        """Round 1 item 2 / round 2 item 1, and the compact card's own shape
        (2026-10-14).

        The `{noname: true}` pin is GONE rather than renamed: the option art is
        no longer a `tile()` at all, so "suppress the tile's own caption" is not
        a thing the code can get wrong any more — `.lv-pickart` holds the image
        and nothing else, and `.lv-pname` is the ONE name. What replaces it is
        the pair of assertions that would catch the regression the old pin
        guarded: the card builds no `.tname`, and the name is emitted once.
        """
        src = _function("lvPick")
        self.assertNotIn("tile(", src,
                         "the option art is a tile again, so it can carry a "
                         "second, truncated name")
        self.assertIn("el('span', 'lv-pickart')", src)
        self.assertEqual(src.count("'lv-pname'"), 1,
                         "the option's name is not emitted exactly once")
        self.assertIn("st.pick_rate.toFixed(1) + '%'", src)
        self.assertIn("'Picked'", src)
        # One decimal everywhere: the stat rows too.
        self.assertIn("st.avg_placement.toFixed(1)", _function("lvStatRows"))
        # The row that repeated the headline is gone from the stat rows; the
        # ORDER still reads the stats, so "By picked %" survives.
        self.assertNotIn("'Picked in'", _function("lvStatRows"))
        self.assertIn("orderKeys.includes('pick_rate')",
                      _function("lvPickControls"))

    def test_the_waiting_state_has_no_skeleton_bars(self):
        """Round 2 item 2: the design's §6.1 dashed skeletons are gone, and the
        hero slot says what the page is waiting for."""
        html = coach_ui._HTML
        self.assertNotIn("lv-skel", html)
        self.assertNotIn("lv-skel", _function("lvWaiting") or "")
        self.assertIn("Waiting for the next shop to open", _function("lvStatus"))
        self.assertIn("Reading the shop", _function("lvWaiting"))

    def test_there_is_no_state_strip_at_all(self):
        """REVERSED 2026-10-13 from `test_the_empty_state_strip_is_hidden_where_it_is_empty`
        (round 2 item 7), which hid a strip the classic renderer filled. The
        classic renderer is gone, so nothing filled it either — the fix-list
        workaround (hide what nothing writes to) is replaced by the element,
        its rules and its writers not existing.
        """
        code = _without_comments()
        self.assertNotIn("statebar", code,
                         "the strip is back — with one renderer nothing can "
                         "fill it but the Tavern view's own status bar")

    def test_one_art_treatment_and_a_tag_for_what_a_card_is(self):
        """Round 2 item 3."""
        self.assertIn("if (!opts.noname) {", coach_ui._HTML)
        self.assertIn("t.title = name || '';", coach_ui._HTML)
        src = _function("lvShop")
        self.assertIn("s.tag === 'spell' ? {kind: 'Spell'} : null", src)
        self.assertIn("-webkit-line-clamp:2", coach_ui._HTML)
        self.assertIn(".tavern .tile .tag-kind", coach_ui._HTML)

    def test_the_board_and_the_hand_share_one_panel(self):
        """Round 1 item 4 / round 2 item 4."""
        src = _function("lvBoardHand")
        self.assertIsNotNone(src)
        self.assertIn("'Your board'", src)
        self.assertIn("'Your hand'", src)
        self.assertIn("'lv-bh'", src)
        self.assertIn("'empty'", _function("lvBoard"))
        self.assertIn("'empty'", _function("lvHand"))

    def test_the_banned_tribe_caption_is_built_from_data(self):
        """Round 1 item 7 / round 2 item 5. The value pass's own string stays as
        it is — the classic Sell box shows it and `test_hand_engine` pins it — so
        the payload carries the tribe and the flag instead."""
        src = _function("lvBoard")
        self.assertIn("s.off_play", src)
        self.assertIn("' — out of play'", src)
        self.assertNotIn("can't grow", src)
        # The producer side.
        code = open(os.path.join(HERE, "coach_ui.py"), encoding="utf-8").read()
        self.assertIn('g["off_play"] = (g["why"] == "banned tribe — can\'t grow")',
                      code)
        self.assertIn('g["tribe"] = _canon_tribe(board_minion.get("tribe"))', code)
        self.assertIn("def _canon_tribe(raw):", code)

    def test_the_game_over_card_is_labelled(self):
        """Round 1 item 8."""
        src = _function("renderTavernGameOver")
        self.assertIn("'lv-overlabel', 'Game over'", src)
        self.assertIn(".lv-overlabel {", coach_ui._HTML)


class TestTheOptionsStatistics(unittest.TestCase):
    """`choices.option_stats` is the NUMBER side of the pick screen (§4.3).

    The classic panel's rows are sentences, and the trinket ones mix a statistic
    with phrasing the design bans ("fits your board"). These are the same data as
    numbers, and the rule that shapes them is §5's: a key appears only when the
    DB actually has it, because a row that cannot be filled is dropped rather
    than zeroed.
    """

    def setUp(self):
        import choices
        self.choices = choices

    def test_a_trinket_yields_its_population_numbers(self):
        db = self.choices._load_trinket_db()
        name = next(iter(db))
        st = self.choices.option_stats("trinket", [(name, "TEST_ID")])["TEST_ID"]
        if db[name].get("pick_rate") is None:
            self.skipTest("this checkout's trinket DB carries no population data")
        self.assertIsInstance(st["pick_rate"], float)
        self.assertIn("avg_placement", st)
        self.assertEqual(len(st["dist"]), 8, "the whole distribution, 1 to 8")

    def test_a_top4_share_needs_all_four_of_the_top_placements(self):
        """A partial distribution would under-report and read as a real number."""
        import choices
        saved = choices._load_trinket_db

        class _Fake(dict):
            pass

        fake = _Fake({"Half": {"pick_rate": 10.0, "avg_placement": 4.0,
                               "placement_distribution": {"1": 5.0, "2": 5.0}}})
        choices._load_trinket_db = lambda: fake
        try:
            st = choices.option_stats("trinket", [("Half", "ID")])["ID"]
            self.assertNotIn("top4", st)
            self.assertEqual(st["dist"], {"1": 5.0, "2": 5.0})
        finally:
            choices._load_trinket_db = saved

    def test_an_option_with_no_data_contributes_nothing(self):
        st = self.choices.option_stats("trinket", [("No Such Trinket", "X")])
        self.assertEqual(st, {}, "an unknown option gets no zeroes")
        self.assertEqual(self.choices.option_stats("mystery", [("A", "B")]), {})

    def test_a_discover_yields_the_card_data_the_design_asks_for(self):
        """§4.3: "discover options add `[tier] · [tribe]`"."""
        import meta
        cards = meta.cards()
        cid = next(c for c, v in cards.items()
                   if v.get("tier") is not None and v.get("tribe"))
        st = self.choices.option_stats("discover", [("X", cid)])[cid]
        self.assertEqual(st["tier"], cards[cid]["tier"])
        self.assertEqual(st["tribe"], cards[cid]["tribe"])


class TestTheWaitingStateHoldsNoTribeState(unittest.TestCase):
    """Fix list round 4 item 2, on the client half.

    The server drops the finished game's ban set where the game ends
    (`test_game_over_state`). REVERSED 2026-10-13: the client used to keep its
    own copy for the classic picker (`_inPlayPick`), and the welcome branch had
    to clear it so the 5/5 set of a finished game could not be drawn across the
    between-games gap. The client copy is gone — the Tavern tribe row reads
    `tribes_available` from the payload every render — so the state has ONE
    owner and the bug the clearing fixed is not reachable at all.
    """

    def _render_src(self):
        src = coach_ui._HTML
        start = src.index("function render(a) {")
        return src[start:start + 1200]

    def test_no_client_copy_of_the_tap_set_exists(self):
        """The reversed half: `_inPlayPick` and its two companions are gone, so
        there is nothing for a welcome payload to leave behind."""
        code = _without_comments()
        for dead in ("_inPlayPick", "_inPlayPickGame", "_inPlayPickAt"):
            self.assertNotIn(dead, code,
                             "a client copy of the tribe set came back — the "
                             "payload is the only owner")
        self.assertIn("postInPlay", code,
                      "the tap still has to reach /bans")

    def test_the_welcome_card_still_carries_no_tribe_field(self):
        """The other half of the same claim: there is nothing to draw from."""
        card = __import__("json").loads(coach_ui.welcome_payload(
            game_over={"placement": 2, "turn": 11}))
        for key in ("banned", "tribe_roster", "tribes_available",
                    "tribes_seen"):
            self.assertNotIn(key, card)


if __name__ == "__main__":
    unittest.main()
