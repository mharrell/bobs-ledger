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
        self.assertIn('id="live-viewer"', coach_ui._HTML)
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
        src = _function("render")
        self.assertIn("if (_liveViewer === 'tavern') { renderLiveTavern(a); return; }",
                      src)
        # After the ban picker's sync and the art pre-warm (both views need
        # them) and before the classic strip is built (only one draws).
        self.assertLess(src.index("_warmed.add(cid)"),
                        src.index("_liveViewer === 'tavern'"))
        self.assertLess(src.index("_liveViewer === 'tavern'"),
                        src.index("STATE STRIP"))

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
        for part in ("lvStatus", "lvTribes", "lvShop", "lvBoard", "lvHand"):
            self.assertIn(part, src)

    def test_the_rail_has_the_three_tabs_the_design_names(self):
        self.assertIn("const LIVE_TABS = [['facts', 'Facts'], "
                      "['comps', 'Comps'], ['lobby', 'Lobby']];", coach_ui._HTML)


class TestTheDesignsLanguageRules(unittest.TestCase):
    """The source-level half of §1 (the rendered half is in the browser file).

    These are the strings the design names as verdicts to remove. The classic
    renderer is allowed to keep them — it is the shipped page — so this scans the
    TAVERN functions only.
    """

    TAVERN = ("lvStatus", "lvTribes", "lvFacts", "lvComps", "lvLobby", "lvShop",
              "lvBoard", "lvHand", "lvPick", "lvGameOver", "renderLiveTavern",
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
        """
        src = re.sub(r"//[^\n]*", "", self._tavern_source())
        return " ".join(re.findall(r"'([^']*)'", src))

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

    def test_the_tier_note_does_not_call_anything_a_ranking(self):
        """The comps tab states where the tier comes from, in words a scan for
        rank language can stay honest about."""
        src = _function("lvComps")
        self.assertNotIn("rank", src.lower())


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
