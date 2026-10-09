"""The Tavern Live layout, RUN in a real browser — and scanned for verdicts.

`LIVE_VIEW_DESIGN.md` §1 is the rule that shapes the whole redesign: the Live
page is reference material, so it shows facts, counts and statistics — never a
verdict, a ranking or an imperative. That rule is about WORDS ON THE SCREEN, and
`CLAUDE.md` records what happens when it is enforced one layer off: the live
wall drops verdict *keys* from the payload, so a verdict inside a fact *string*
walked straight through for a day (`choices._rank_discover` shipping
"best available"). A source assertion cannot see it either.

So this file renders the real page with the real payload and reads the text back,
then fails on a verdict vocabulary — the same shape as
`test_choices.TestTheFactsNameNoRank`, applied to a whole view instead of one
ranker. The rest of the facts are the layout's own: six numbers in the status
bar, one tribe row, the cards with their captions, the three rail tabs, the dash
for a value nobody read, and the skeleton the shop shows before it parses.

The payload comes from `coach_ui.render_json` itself — the producer — rather than
a hand-written dict, so the fixture cannot drift into a shape no game produces.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed
sys.path.insert(0, os.path.join(HERE, "tests"))

import browser  # noqa: E402
import coach_ui  # noqa: E402


def _analysis(**over):
    """An analysis shaped like the live loop's, for `render_json` to consume."""
    a = {
        "hero": "Chenvaala", "gold": 7, "tier": 3, "health": 26, "armor": 4,
        "board": [{"card": "BG31_815", "atk": 5, "health": 5,
                   "tribe": "ELEMENTAL"},
                  {"card": "BG31_820", "atk": 2, "health": 2, "tribe": "BEAST"}],
        "board_stats": 14, "opp_stats": 19, "opp_age": 1,
        # value.fragility's own shape: the numbers the facts table renders.
        "fragility": {"band": "fragile", "eff_health": 30, "health": 26,
                      "armor": 4, "last_hit": 4, "recent3": 21, "cap": 10,
                      "note": "30 effective HP, took 4 last fight"},
        "scenario": {"turns": 9},
        "current_place": 3,
        "level_cost": 7,
        "damage_last": 4, "damage_recent3": 21, "damage_cap": 10,
        "sell_rank": [("BG31_815", 40), ("BG31_820", 12)],
        "hand": [{"card": "BG31_831", "score": 9}],
        # The shop as the analysis carries it: (card, score) pairs, which
        # render_json turns into the payload's named rows.
        "shop_rank": [("BG31_820", 32), ("BG31_831", 18)],
        "tribe_roster": ["BEAST", "ELEMENTAL", "MECH", "UNDEAD", "PIRATE",
                         "NAGA"],
        "out_of_pool": ["NAGA"],
        "banned": ["BEAST", "MECH"], "bans_manual": True, "tribes_seen": 5,
        "tribe_pressure": [{"tribe": "Beast", "seats": 2, "of": 3}],
        "game_comps": {"elementals": {
            "name": "Elementals", "meta_tier": "S", "tribe": "ELEMENTAL",
            "core": ["BG31_815", "BG31_820"], "addons": ["BG31_831"]}},
        "opp_comp": {"hero": "X", "hero_name": "Reno", "name": "SomeHandle",
                     "turn": 8, "cards": {"BG31_815": 1}},
    }
    a.update(over)
    return a


def _payload(**over):
    """The real payload, through the real producer."""
    return coach_ui.render_json(_analysis(**over))


#: The driver: set the viewer, run the REAL render(), report what is on screen.
#: It is defensive the same way the Settle Up driver is — a renderer that throws
#: has to SAY so, or a passing case proves nothing.
_DRIVER = r"""
<pre id="out">pending</pre>
<script>
(function () {
  const recs = [];
  const rec = (k, v) => recs.push(k + '=' + String(v));
  const SHOTS = __SHOTS__;
  function facts(name) {
    const root = document.querySelector('.tavern.live');
    const q = s => root ? root.querySelectorAll(s) : [];
    const one = s => root ? root.querySelector(s) : null;
    const txt = el => el ? el.textContent : '';
    const o = {};
    o.tavern = root ? 1 : 0;
    o.hero = txt(one('.lv-hero'));
    o.stats = [...q('.lv-st')]
      .map(d => txt(d.querySelector('small')) + ':' + txt(d.querySelector('b')))
      .join('|');
    o.chips = [...q('.lv-chip')].map(c => c.textContent).join('|');
    o.outchips = [...q('.lv-chip.out')].map(c => c.textContent).join('|');
    o.tabs = [...q('.lv-tabs button')].map(b => b.textContent).join('|');
    o.tabon = txt(one('.lv-tabs button.on'));
    o.panels = [...q('.lv-pn > h3')].map(h => h.textContent).join('|');
    // Label/value from the row's FIRST and LAST child: the comps row's label is
    // itself a <b> wrapping the name, so a bare querySelector('b') read the name
    // back as the value (measured 2026-10-09).
    o.kv = [...q('.lv-kv')].map(d => {
      const k = d.children;
      return txt(k[0]) + '=' + txt(k[k.length - 1]);
    }).join('|');
    o.caps = [...q('.lv-cap')].map(c => c.textContent).join('|');
    o.cards = q('.lv-card').length;
    // Cards inside the TAVERN panel only, so "the shop is not parsed" is not
    // confused with the board and hand rows, which are cards too.
    const panes = q('.lv-pn');
    o.taverncards = panes.length
      ? panes[0].querySelectorAll('.lv-card').length : 0;
    o.skel = q('.lv-skel').length;
    o.empty = [...q('.lv-empty')].map(d => d.textContent).join('|');
    o.notes = [...q('.lv-note')].map(d => d.textContent).join('|');
    o.pick = q('.lv-stats').length;
    o.pickfirst = txt((one('.lv-stats') || {}).firstChild || null);
    o.gobtn = txt(one('.lv-gobtn'));
    o.label = txt(one('.lv-lbl'));
    o.opplabel = txt(one('.lv-opp'));
    o.classic = document.getElementById('col-decide').children.length;
    // EVERY word the view puts on screen, for the §1 scan. The panel headers
    // and the status labels are in here too — a verdict can hide in a label.
    o.alltext = root ? root.textContent.replace(/\s+/g, ' ').trim() : '';
    for (const k of Object.keys(o))
      rec(name + '.' + k, ['tavern', 'cards', 'skel', 'pick', 'classic',
                           'taverncards']
          .includes(k) ? '#' + Number(o[k]) : o[k]);
  }
  function shot(s) {
    _liveViewer = s.viewer || 'tavern';
    _liveTab = s.tab || 'facts';
    render(s.rep);
    facts(s.name);
  }
  if (typeof render !== 'function' || typeof renderLiveTavern !== 'function') {
    rec('fatal', 'render/renderLiveTavern missing - the page script did not run');
  } else {
    showTab('live');
    for (const s of SHOTS) {
      try {
        shot(s);
      } catch (e) {
        rec(s.name + '.error', (e && e.message) || String(e));
      }
    }
  }
  document.getElementById('out').textContent = recs.join(' ;; ');
})();
</script>
"""


def _page(shots):
    driver = _DRIVER.replace("__SHOTS__", __import__("json").dumps(shots))
    return coach_ui._page_html().replace("</body>", driver + "</body>")


def _shot(name, rep, viewer="tavern", tab="facts"):
    return {"name": name, "rep": rep, "viewer": viewer, "tab": tab}


def _render(shots, size=browser.WIDE):
    if browser.browser() is None:
        raise unittest.SkipTest("no Chromium browser on this machine, so the "
                                "page cannot be laid out")
    try:
        got = browser.fields(_page(shots), size=size)
    except browser.BrowserUnavailable as e:
        raise unittest.SkipTest(str(e))
    for shot in shots:
        where = shot["name"] + ".error"
        if where in got:
            raise AssertionError(f"{shot['name']} threw inside the viewer: "
                                 f"{got[where]}")
    if "fatal" in got:
        raise AssertionError(got["fatal"])
    return got


class _Rendered(unittest.TestCase):
    _outcome = None

    @classmethod
    def shots(cls):
        raise NotImplementedError

    def setUp(self):
        cls = type(self)
        if cls._outcome is None:
            try:
                cls._outcome = _render(cls.shots())
            except Exception as e:      # noqa: BLE001 - replayed right below
                cls._outcome = e
        if isinstance(cls._outcome, BaseException):
            raise cls._outcome
        self.got = cls._outcome


class TestTheTavernLiveInABrowser(_Rendered):
    """The shop screen, the tribe row and the three rail tabs."""

    @classmethod
    def shots(cls):
        return [_shot("t", _payload()),
                _shot("comps", _payload(), tab="comps"),
                _shot("nocomps", _payload(game_comps={}, tribe_pressure=[]),
                      tab="comps"),
                _shot("lobby", _payload(), tab="lobby"),
                _shot("notread", _payload(fragility=None, level_cost=None,
                                          board_stats=None, opp_stats=None,
                                          opp_lobby=None)),
                _shot("noshop", _payload(shop_rank=[])),
                _shot("classic", _payload(), viewer="classic")]

    def test_the_status_bar_is_the_hero_and_six_numbers(self):
        self.assertEqual(self.got["t.tavern"], 1)
        self.assertEqual(self.got["t.hero"], "Chenvaala")
        # The labels are uppercase through CSS (text-transform), which is the
        # design's spec — the text itself stays as written.
        self.assertEqual(self.got["t.stats"],
                         "Gold:7|Tier:3|HP:26+4|Turn:9|Place:3rd")

    def test_the_tribe_row_is_one_row_and_out_of_play_is_struck_not_banned(self):
        self.assertIn("BEAST", self.got["t.chips"])
        self.assertIn("PIRATE", self.got["t.chips"])
        self.assertEqual(self.got["t.outchips"], "NAGA",
                         "out-of-play tribes are their own state, never a ban "
                         "the player could undo")
        self.assertIn("tap to correct", self.got["t.label"])

    def test_the_rail_has_three_tabs_and_opens_on_facts(self):
        self.assertEqual(self.got["t.tabs"], "Facts|Comps|Lobby")
        self.assertEqual(self.got["t.tabon"], "Facts")
        self.assertEqual(self.got["t.panels"],
                         "Tavern|Your board|Your hand|Facts")

    def test_the_facts_are_the_numbers_behind_the_classic_verdicts(self):
        kv = self.got["t.kv"]
        for row in ("Effective HP=30", "Took last fight=4", "Last 3 fights=−21",
                    "Lethal at=30 damage", "Damage cap=10",
                    "Board stats=14 vs 19 (seen 1 round ago)",
                    "Level up=tier 3 → 4 for 7g"):
            self.assertIn(row, kv, f"missing facts row: {row}")
        self.assertIn("observational, not causal", self.got["t.notes"])

    def test_a_value_nobody_read_is_a_dash(self):
        """§6.4. The fixture drops the fragility block and the level cost, so
        every row that depended on them is GONE rather than guessed, and the one
        row that always exists says so with a dash."""
        self.assertNotIn("Effective HP", self.got["notread.kv"])
        self.assertNotIn("Level up", self.got["notread.kv"])
        self.assertIn("Board stats=—", self.got["notread.kv"])
        self.assertNotIn("?", self.got["notread.alltext"])

    def test_the_shop_before_it_parses_is_a_skeleton_with_a_sentence(self):
        self.assertEqual(self.got["noshop.skel"], 4)
        self.assertIn("Reading the shop. This updates when your next shop opens.",
                      self.got["noshop.notes"])
        self.assertEqual(self.got["noshop.taverncards"], 0,
                         "the skeleton is not a card row")
        self.assertGreaterEqual(self.got["t.taverncards"], 2,
                                "a parsed shop renders its cards")

    def test_cards_carry_a_caption_below_them(self):
        self.assertGreaterEqual(self.got["t.cards"], 3)
        self.assertTrue(self.got["t.caps"], "no captions rendered")
        self.assertIn("hand", self.got["t.caps"], "the hand row is captioned")
        self.assertIn("scaler", self.got["t.caps"],
                      "the board caption is the comp role, which is a fact "
                      "about membership")

    def test_the_comps_tab_counts_core_cards_owned(self):
        kv = self.got["comps.kv"]
        self.assertIn("Elementals", kv)
        self.assertIn("2 of 2 core owned", kv,
                      "ownership is a count against the core, not a verdict")
        self.assertIn("S tier", kv)
        self.assertIn("not this app's", self.got["comps.notes"])

    def test_an_empty_comps_tab_says_why_rather_than_showing_nothing(self):
        self.assertIn("No comps read yet", self.got["nocomps.empty"])

    def test_the_lobby_tab_is_sightings_and_the_last_seen_board(self):
        got = self.got
        self.assertEqual(got["lobby.tabon"], "Lobby")
        self.assertIn("Beast=2 of 3 seen seats (2+ copies)", got["lobby.kv"])
        self.assertIn("as of round 8", got["lobby.opplabel"])

    def test_classic_still_renders_after_a_tavern_render(self):
        """The flag's contract, and the way BACK.

        These shots run in order, so by the time this one renders Classic the
        page has already drawn the Tavern view — which is what caught the first
        version: it cleared `#app`, destroying `#col-decide`/`#col-ref`, so the
        toggle to Tavern worked and the toggle back threw. The tavern view has
        its own container now and the classic panes are only hidden.
        """
        self.assertEqual(self.got["classic.tavern"], 0)
        self.assertGreater(self.got["classic.classic"], 0,
                           "the classic panes are empty after a tavern render — "
                           "the way back to Classic is broken")


class TestTheViewCarriesNoVerdict(_Rendered):
    """§1, measured on the text that actually reaches the screen.

    The list is the design's own: its §1 table names the verdict phrasings to
    remove (`fits your board`, `closest comp`, `commit when`, and the
    favored/behind/strong scale), and §4.2 replaces `FRAGILE`/`DYING` with the
    numbers themselves.
    """

    VERDICTS = ("best", "favored", "behind", "strong", "weak", "fragile",
                "dying", "should", "recommend", "must ", "you want", "aim ",
                "hunt", "priorit", "worth ", "commit when", "one core card",
                "tribe signal", "fits your board", "closest comp", "rank")

    @classmethod
    def shots(cls):
        return [_shot("t", _payload()),
                _shot("lobby", _payload(), tab="lobby"),
                _shot("comps", _payload(), tab="comps")]

    def test_no_verdict_vocabulary_reaches_the_screen(self):
        for name in ("t", "lobby", "comps"):
            text = self.got[name + ".alltext"].lower()
            self.assertTrue(text, f"{name} rendered nothing to scan")
            for word in self.VERDICTS:
                self.assertNotIn(
                    word, text,
                    f"the Tavern live view says {word!r} — LIVE_VIEW_DESIGN.md §1 "
                    f"allows facts, counts and statistics, nothing else. Text: "
                    f"{self.got[name + '.alltext'][:200]}")

    def test_the_pick_screen_shows_the_game_order_and_never_a_ranking(self):
        """§4.3: the server returns the options score-ordered (row 0 is the pick
        the review grades), so rendering them as they arrive would hand the
        player the model's ranking."""
        rep = _payload(choice={"ranked": [
            ["Zed", "BG31_820", 90, "picked in 60% of games", 2],
            ["Ann", "BG31_815", 10, "picked in 5% of games", 1]],
            "guides": {}})
        got = _render([_shot("pick", rep)])
        self.assertEqual(got["pick.pick"], 2, "both options rendered")
        # Option 1 in the game's order comes first, whatever the scores say.
        self.assertEqual(got["pick.pickfirst"], "picked in 5% of games")


class TestTheHarnessItself(unittest.TestCase):
    def test_a_broken_payload_is_reported_rather_than_swallowed(self):
        """The rehearsal, and it has to break something THIS view reads: a shop
        the renderer iterates. (Breaking `board` would prove nothing — the
        classic renderer walks it and the tavern view never does.)"""
        bad = _payload()
        bad["shop_rank"] = "not a list"
        browser.require_browser(self)
        try:
            got = browser.fields(_page([_shot("bad", bad)]))
        except browser.BrowserUnavailable as e:
            self.skipTest(str(e))
        self.assertIn("bad.error", got,
                      "a throwing renderer left no error behind — the harness "
                      "would have called that 'rendered fine'")
        self.assertTrue(got["bad.error"])


if __name__ == "__main__":
    unittest.main()
