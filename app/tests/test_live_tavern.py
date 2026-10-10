"""The Live viewer flag, and the rule the Tavern layout is built on.

Live ships STATE (`PIVOT.md`, 2026-10-06) and `LIVE_VIEW_DESIGN.md` §1 draws the
line one notch tighter: the Live page is *reference material*, so it shows facts,
counts and statistics — never a verdict, a ranking or an imperative, and never a
guessed number. The classic page still carries the model's read of the game in
words ("favored — 51 vs ~40", "FRAGILE — a 14-hit ends it"); the Tavern layout
replaces those with the same values as rows.

This file pins the parts a browser cannot see (the flag, the branch, the classic
path's shape). The rendered text — including the verdict-language scan, which is
the real control for §1 — is measured in `test_live_browser.py`, because a
source assertion cannot see what reaches the screen.
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


class TestTheFlag(unittest.TestCase):
    """One toggle, one persisted key, Classic still the default."""

    def test_the_toggle_is_in_the_tab_row(self):
        """ONE Classic | Tavern toggle per page (2026-10-09, player call): the
        live flag moved out of the top nav — where it looked global and rode
        along to the Settle Up tab beside that tab's own toggle, unthemed
        there — and heads the LIVE page, the same place the Settle Up flag
        sits in its header."""
        self.assertIn('id="live-viewer"', coach_ui._HTML)
        self.assertIn('<div id="live-viewer-row">', coach_ui._HTML)
        self.assertNotIn('#tabs #live-viewer', coach_ui._HTML,
                         "the flag is back in the shared nav — two toggles "
                         "again")
        nav = coach_ui._HTML[coach_ui._HTML.index('id="live-viewer"'):]
        self.assertIn('data-v="classic"', nav)
        self.assertIn('data-v="tavern"', nav)
        # Classic is the shipped renderer, so the markup itself says so before
        # any script runs — the same rule the Settle Up flag follows.
        self.assertRegex(nav[:200], r'data-v="classic" class="on"')

    def test_the_choice_persists_under_its_own_key(self):
        self.assertIn("localStorage.getItem('bl-live-viewer')", coach_ui._HTML)
        self.assertIn("localStorage.setItem('bl-live-viewer'", coach_ui._HTML)
        self.assertIn("let _liveViewer = 'classic';", coach_ui._HTML)

    def test_both_buttons_are_wired(self):
        self.assertIn("document.querySelectorAll('#live-viewer button')",
                      coach_ui._HTML)
        self.assertIsNotNone(_function("setLiveViewer"))

    def test_toggling_redraws_the_payload_already_on_screen(self):
        """A toggle that waits up to 300ms for the next poll reads as a control
        that did nothing."""
        src = _function("setLiveViewer")
        self.assertIn("render(_lastParsed)", src)
        self.assertIn("_lastParsed = a;", _function("render"))


class TestTheBranch(unittest.TestCase):
    """The tavern path is a branch, not a rewrite: Classic keeps its shape."""

    def test_the_tavern_branch_sits_after_the_shared_setup(self):
        """The LIVE payload's branch, which is its own route: the game-over card
        is branched earlier, on the welcome payload, because that payload has no
        board for the setup below to work on."""
        src = _function("render")
        branch = "if (_liveViewer === 'tavern') { renderLiveTavern(a); return; }"
        self.assertIn(branch, src)
        # After the ban picker's sync and the art pre-warm (both views need
        # them) and before the classic strip is built (only one draws).
        self.assertLess(src.index("_warmed.add(cid)"), src.index(branch))
        self.assertLess(src.index(branch), src.index("STATE STRIP"))

    def test_the_classic_renderer_is_untouched(self):
        src = _function("render")
        for anchor in ("decide.appendChild(el('h2', 'pane-h', 'Decide'))",
                       "ref.appendChild(el('h2', 'pane-h', 'Reference'))",
                       "statebar.appendChild(statTile('Gold'",
                       "statebar.appendChild(el('span', 'tile', a.hero || '?'))"):
            self.assertIn(anchor, src, "the classic live page changed shape")

    def test_the_tavern_view_is_a_separate_renderer(self):
        src = _function("renderLiveTavern")
        self.assertIsNotNone(src, "renderLiveTavern is missing")
        self.assertIn("el('div', 'tavern live')", src,
                      "the tavern view has to be scoped to .tavern.live, or the "
                      "Settle Up Tavern rules and these leak into each other")
        for part in ("lvStatus", "lvTribes", "lvShop", "lvBoardHand", "lvWaiting",
                     "lvCompsScreen", "lvLobby", "lvFacts"):
            self.assertIn(part, src)

    def test_the_tab_row_is_the_screens_not_the_rail(self):
        self.assertIn("const LIVE_TABS = [['shop', 'Shop'], "
                      "['comps', 'Comps'], ['lobby', 'Lobby']];", coach_ui._HTML)


class TestTheDesignsLanguageRules(unittest.TestCase):
    """The source-level half of §1 (the rendered half is in the browser file).

    These are the strings the design names as verdicts to remove. The classic
    renderer is allowed to keep them — it is the shipped page — so this scans the
    TAVERN functions only.
    """

    TAVERN = ("lvStatus", "lvTribes", "lvFacts", "lvCompsBrowse", "lvCompDetail",
              "lvCompCompare", "lvCompsScreen", "lvCompRow", "lvCompStats",
              "lvCompSortRows", "lvSlot", "lvSlotCap", "lvSlots", "lvSlotLegend",
              "lvOwned", "lvLobby", "lvShop", "lvBoard", "lvHand", "lvBoardHand",
              "lvWaiting", "lvPick", "lvPickControls", "lvTabs", "renderLiveTavern",
              "lvCard", "lvKV", "lvPanel", "lvEmptyRow", "lvVal")

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

    def test_the_comps_screens_never_call_anything_a_ranking(self):
        """The comps screens state where a tier comes from and that the sort is
        the player's, in words a scan for rank language can stay honest about.
        Comments are stripped: the source explains the rule and would otherwise
        fail its own check."""
        src = re.sub(r"//[^\n]*", "", "\n".join(
            _function(n) or "" for n in ("lvCompsBrowse", "lvCompCompare",
                                         "lvCompSortRows", "lvCompStats")))
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
        """§5: 34x46 in Browse, 52x70 in Compare, and a CARD at 88x120 / 76x100
        in Detail. A tile is 88-124px wide, so a slot that inherited the card
        rule would be more than twice the specified size — which is exactly the
        failure mode the design's own §5 table exists to prevent."""
        html = coach_ui._HTML
        self.assertIn("width:34px; height:46px", html)
        self.assertIn(".lv-cmpcol .lv-slot { width:52px; height:70px; }", html)
        self.assertIn(".lv-core { --tcardw:88px; }", html)
        self.assertIn(".lv-flexcards { --tcardw:76px;", html)
        self.assertIn("aspect-ratio:76/100;", html)

    def test_the_browse_cap_and_the_compare_limit_are_named_constants(self):
        self.assertIn("const LIVE_COMP_ROWS = 5;", coach_ui._HTML)
        self.assertIn("const LIVE_COMPARE_MAX = 3;", coach_ui._HTML)
        src = _function("lvCompsBrowse")
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

    def test_the_facts_table_is_the_rail_and_not_a_tab(self):
        """§4.1's tab row is `Shop | Comps | Lobby`; §4.2 puts the facts table in
        the rail. Keeping it there means it is never hidden — and it can only
        say anything once."""
        self.assertIn("const LIVE_TABS = [['shop', 'Shop'], "
                      "['comps', 'Comps'], ['lobby', 'Lobby']];", coach_ui._HTML)
        self.assertIn("let _liveTab = 'shop';", coach_ui._HTML)
        src = _function("renderLiveTavern")
        self.assertIn("rail.appendChild(lvFacts(a));", src)
        self.assertNotIn("_liveTab === 'facts'", src)

    def test_the_focus_ring_and_the_target_sizes_are_declared(self):
        """§8: "Visible focus ring (2px `--sel`, with offset) on all controls;
        44px minimum click targets for buttons and tabs." The ring is scoped to
        `.tavern`, so it reaches both Tavern viewers and leaves the classic pages
        with the browser's own."""
        html = coach_ui._HTML
        self.assertIn(".tavern :focus-visible { outline:2px solid var(--tsel); "
                      "outline-offset:2px; }", html)
        for sel in (".tavern.live .lv-tabs button", ".tavern.live .lv-more",
                    ".tavern.live .lv-back", ".tavern.live .lv-gobtn"):
            block = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", html)
            self.assertIsNotNone(block, f"{sel} lost its rule")
            self.assertIn("min-height:44px", block.group(1),
                          f"{sel} is under the design's 44px minimum target")

    def test_every_screen_switch_is_a_click_away_from_the_list(self):
        src = _function("renderLiveTavern")
        for branch in ("_liveTab === 'comps'", "_liveTab === 'lobby'",
                       "a.choice && a.choice.ranked"):
            self.assertIn(branch, src, f"the tab branch {branch} is missing")
        self.assertIn("_liveComp = null;", src,
                      "switching tabs has to drop the open comp detail")


class TestTheGameOverCard(unittest.TestCase):
    """§6.5, and the route that had to exist for it.

    The end-of-game payload is `welcome: true` with NO board, and `render`
    returned at the welcome branch before consulting the viewer — so the Tavern
    game-over card was unreachable in a real session while a direct render in a
    test made it look alive. The rendered card is measured in `test_live_browser`;
    this pins the route and the merge.
    """

    def test_the_welcome_branch_consults_the_viewer(self):
        src = _function("render")
        self.assertIn("if (_liveViewer === 'tavern' && a.game_over)", src)
        self.assertLess(src.index("renderTavernGameOver(a)"),
                        src.index("renderWelcome(a)"),
                        "the game-over payload has to be routed before the "
                        "classic welcome card claims it")
        self.assertIn("lvClearTavern();", src,
                      "a first-run card must clear the Tavern layout, or it "
                      "draws behind a stale Tavern screen")

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

    def test_the_tavern_layout_is_cleared_from_one_place(self):
        """`lvClearTavern` is the single reset: the classic path and the
        first-run card both need it, and a viewer that is not drawing must not
        leave its last frame on screen."""
        self.assertEqual(coach_ui._HTML.count("lvClearTavern"), 3,
                         "defined once, called from the classic path and from "
                         "the welcome branch")


class TestTheFixListRounds(unittest.TestCase):
    """The two Live fix lists of 2026-10-09, at source level.

    The rendered half of every one of these is measured in `test_live_browser`
    (which is where the layout claims have to be checked, because a rule can
    exist and lose to a more specific one). This is the half a browser cannot
    state: which rule was written, and which call was made from where.
    """

    def test_live_fills_the_window(self):
        """Round 1 item 1. `#app` is a grid above 1200x900 and a flex COLUMN at or
        below it, so the fix has to cover both: one grid column, and a width that
        does not depend on `flex-basis` being a width (measured before the fix:
        815px of a 1384px window)."""
        html = coach_ui._HTML
        self.assertIn("#app.tavern-on { grid-template-columns:minmax(0,1fr);",
                      html)
        self.assertIn("#app.tavern-on #live-tavern { grid-column:1 / -1; "
                      "width:100%;", html)

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

    def test_the_classic_tavern_toggle_is_themed(self):
        """Round 1 item 9 / round 2 item 8. `.vseg` described the ACTIVE state and
        the radii only, so the buttons were whatever the browser draws."""
        html = coach_ui._HTML
        block = re.search(r"\.vseg button \{([^}]*)\}", html)
        self.assertIsNotNone(block)
        for prop in ("background:var(--panel)", "border:1px solid var(--border)",
                     "padding:6px 12px"):
            self.assertIn(prop, block.group(1))
        self.assertIn("#app.tavern-on #live-viewer-row .vseg button", html)
        self.assertIn("background:var(--tsel); color:var(--tonsel);", html)

    def test_the_facts_drop_lethal_at_and_name_the_lobby_average(self):
        """Round 1 item 5 / round 2 item 6."""
        src = _function("lvFacts")
        self.assertNotIn("Lethal at", src)
        self.assertIn("lobby avg", src)
        self.assertIn("'Board stats — you vs lobby avg'", src)

    def test_a_tribe_out_of_play_is_listed_once(self):
        """Round 1 item 3: the roster contains every tribe, `out_of_pool` names
        the rotated ones, and iterating both printed Naga twice."""
        src = _function("lvTribes")
        self.assertIn(".filter(t => !oop.has(t))", src)
        self.assertIn("'lv-chip ' + (on ? 'active' : 'dim')", src)

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
        """Round 1 item 2 / round 2 item 1."""
        src = _function("lvPick")
        self.assertIn("{noname: true}", src)
        self.assertIn("st.pick_rate.toFixed(1) + '%'", src)
        self.assertIn("'Picked'", src)
        # The row that repeated it is gone from the stat rows; the ORDER still
        # reads the stats, so "By picked %" survives.
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

    def test_the_empty_state_strip_is_hidden_where_it_is_empty(self):
        """Round 2 item 7."""
        html = coach_ui._HTML
        self.assertIn("#statebar[hidden] { display:none; }", html)
        self.assertIn("statebar.hidden = true", _function("renderWelcome"))
        self.assertIn("bar.hidden = true", _function("renderLiveTavern"))
        self.assertIn("bar.hidden = false", _function("lvClearTavern"))

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


if __name__ == "__main__":
    unittest.main()
