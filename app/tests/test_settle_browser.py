"""The Tavern viewer, RUN in a real browser instead of read as source.

`test_settle_viewer` pins the redesign by reading `coach_ui.py`: `assertIn` on a
function's text, plus `node` runs of the pure helpers. That is worth having, and
it cannot see the thing the maintainer actually looks at — **nothing had ever
executed `renderTavernGame`**. A wrong argument, a field a rep does not carry, or
a branch that throws on the second turn would all have shipped green, which is
the same shape of gap that once let a syntax error live in this page.

So this module does the only thing that counts: it serves the REAL page
(`coach_ui._page_html()` — its own `<style>`, its own `<script>`), runs a rep
through the REAL serve-time join (`_name_timeline_boards`), renders it with the
real `renderSettleGame`, and reads the resulting DOM back. The facts asserted are
the ones a player would see: how many turns are on screen, which rail groups are
open, whether the `NEW` tag and the stat delta landed, the letters on the step
track, the caption's words, the measured card sizes.

**The caption assertion is why this is worth its length.** `stepWords()` reads
`st.cardName || st.card`, so a rep that never met `_name_timeline_boards` renders
"Bought BG31_815" — a raw id on the player's screen. Only running the join and
the renderer together can tell those two worlds apart, and this does.

Two controls keep the harness honest, because a browser check that cannot fail is
worse than none (the lesson `test_overlay_layout` paid for):

* an EMPTY rep must render nothing — otherwise a count of 0 is indistinguishable
  from a hardcoded number that never read the DOM;
* a BROKEN rep (a `took.bought` that is a string, so `flipKinds` throws on
  `forEach`) must come back as a REPORTED error — which is what proves the
  driver's error channel works, so the passing cases are not passing merely
  because their failures were swallowed.

The browser comes from `browser.py`, which SKIPS with the browser's own words
when this session cannot start one: a sandboxed run has `chrome.exe` on disk and
no permission to launch it, and calling that a broken page is a red herring.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed
sys.path.insert(0, os.path.join(HERE, "tests"))   # the shared test helpers

import browser  # noqa: E402
import coach_ui  # noqa: E402

#: The glyphs the page draws, spelled as escapes so an encoding accident in this
#: file cannot quietly turn an assertion into a no-op.
WIN, LOSS = "\u25b2", "\u25bc"
FOLDED, OPENED = "\u25b8", "\u25be"
MIDDOT, MINUS = "\u00b7", "\u2212"
DASH = "\u2014"


def _minion(cid, name, atk, hp, eid, golden=False):
    return {"card": cid, "name": name, "atk": atk, "health": hp,
            "golden": golden, "eid": eid}


#: A game sized to STRESS the layout, in the design doc's own spirit ("in the
#: mocks the 23-action APM log ... is made up to stress-test the layout").
#:
#: Turn 1 carries 11 buys over 9 runs (one of them a x3 collapse, so the group's
#: 8-item cap AND its "show all" both fire), 2 sells, a card BOUGHT AND SOLD in
#: the same phase (the design's "flipped" — it never touches either board), 9
#: rolls, a level-up, 2 casts, an opened/ended board pair whose third minion is
#: NEW and whose first gained +2/+2, and a 3-step action list with a buy, a sell
#: and a cast. Turn 2 is deliberately plain: a viewer that only works on the turn
#: it was written against is exactly what executing it catches.
def _rep():
    opened = [_minion("BG31_815", "Dune Dweller", 3, 3, 9),
              _minion("BG31_820", "Kooky Chemist", 2, 2, 11)]
    ended = [_minion("BG31_815", "Dune Dweller", 5, 5, 9),
             _minion("BG31_820", "Kooky Chemist", 2, 2, 11),
             _minion("BG31_831", "Annoy-o-Module", 4, 8, 14)]
    bought = ([{"card": "BG31_815", "name": "Dune Dweller"}] * 3
              + [{"card": "BG31_90%d" % i, "name": "Buy %d" % i}
                 for i in range(1, 9)])
    turn1 = {
        "turn": 1, "gold": 4, "winner": "us", "damage_taken": 0, "eff": 30,
        "buy_start": opened, "buy_end": ended,
        "buy_end_text": "Dune Dweller 5/5, Kooky Chemist 2/2, "
                        "Annoy-o-Module 4/8",
        "stats": {"buy_end": 40, "growth": 5},
        "commitment": {"target": "Elementals"},
        "spend": {"total": 14, "rolls": 9},
        "shop_events": {"played": 2, "tier_up": True, "hero_power": False,
                        "trinkets": ["Felsteel Cleaver"]},
        "took": {"bought": bought,
                 "sold": [{"card": "BG31_90F", "name": "Sold Away"},
                          {"card": "BG31_815", "name": "Dune Dweller"}],
                 "plays": [{"card": "BG31_815", "name": "Dune Dweller"}],
                 "spell_ids": [{"card": "BG31_700", "name": "Tavern Spell"},
                               {"card": "BG31_701", "name": "Second Spell"}]},
        "sell_questions": [
            # A rebuild note, which the Tavern viewer must show ONCE (the rail
            # carries it; the card's own copy is classic-only as of 2026-10-09).
            {"rebuild": True, "sold_count": 2, "sold_name": "Filler"},
            {"sold_name": "Decoy Conjurer", "role": "filler",
             "kept_filler_names": ["Buy 1", "Buy 2"]}],
        "combat_peak": {
            "ours": [_minion("BG31_815", "Dune Dweller", 5, 5, 9)],
            "theirs": [_minion("BG31_700", "Their Guy", 2, 2, 40)]},
        "combat_ours_text": "Dune Dweller 5/5",
        "combat_theirs_text": "Their Guy 2/2",
        "theirs_survivors": [],
        "steps": [
            {"k": "buy", "card": "BG31_815",
             "board": [_minion("BG31_815", "Dune Dweller", 3, 3, 9),
                       _minion("BG31_820", "Kooky Chemist", 2, 2, 11)]},
            # A LEVEL-UP targets no card: this is the step that used to outline
            # card 1, because it had no previous board to compare against and
            # every tile therefore looked new (2026-10-09).
            {"k": "level", "card": None,
             "board": [_minion("BG31_815", "Dune Dweller", 3, 3, 9),
                       _minion("BG31_820", "Kooky Chemist", 2, 2, 11)]},
            {"k": "sell", "card": "BG31_90F",
             "board": [_minion("BG31_815", "Dune Dweller", 3, 3, 9)]},
            {"k": "cast", "card": "BG31_700",
             "board": [_minion("BG31_815", "Dune Dweller", 5, 5, 9)]},
        ],
    }
    turn2 = {
        "turn": 2, "gold": 7, "winner": "them", "damage_taken": 12, "eff": 18,
        "buy_start": ended, "buy_end": ended, "buy_end_text": "unchanged",
        "stats": {"buy_end": 40, "growth": 0},
        "spend": {"total": 3, "rolls": 0},
        "shop_events": {},
        "took": {"bought": [{"card": "BG31_831", "name": "Annoy-o-Module"}],
                 "sold": [], "plays": [], "spell_ids": []},
    }
    # No winner AND no damage reading: the strip owes a dash here, and the old
    # code put a "?" where the turn's own number is read (2026-10-09).
    turn3 = {"turn": 3, "gold": 2, "winner": None, "damage_taken": None,
             "buy_start": [], "buy_end": [], "buy_end_text": "",
             "stats": {}, "spend": {}, "shop_events": {}, "took": {}}
    return {
        "schema": 2, "hero": "Chenvaala", "placement": 3,
        "created": "2026-10-08T20:00:00", "turns": 3,
        "totals": {"taken": 1, "ignored": 0},
        "phases": [{"turn": 1, "acted": "bought Dune Dweller",
                    "outcome": -4, "verdict": "taken",
                    "plan": "1. Buy Dune Dweller"}],
        "timeline": {"turns": [turn1, turn2, turn3]},
    }


def _named():
    """The fixture as the TAB sees it: through the real serve-time join.

    `_review_game_response` runs every stored rep through this before serving
    it, which is what puts display names on the boards, the rail's action lists
    and each step's action card. Rendering the raw fixture instead would test a
    shape that never reaches a player.
    """
    return coach_ui._name_timeline_boards(_rep())


def _named_single():
    """One cast, one roll: the smallest turn the rail has to word.

    "1 casts" reached the player before this case existed (2026-10-08) — the
    chips are the design's §4.3 summary, so they have to read as English at 1.
    """
    rep = _rep()
    turn = rep["timeline"]["turns"][0]
    turn["took"]["spell_ids"] = [{"card": "BG31_700", "name": "Tavern Spell"}]
    turn["took"]["plays"] = []
    turn["spend"]["rolls"] = 1
    return coach_ui._name_timeline_boards(rep)


#: The driver. Everything it reports lands in `#out` as `name.key=value`
#: records, which `browser.fields()` reads back. It is defensive on purpose:
#: `renderSettleGame` missing, or one shot blowing up, must each come back as a
#: REPORTED error rather than as a mysterious absence of facts.
_DRIVER = r"""
<pre id="out">pending</pre>
<script>
(function () {
  const recs = [];
  const rec = (k, v) => recs.push(k + '=' + String(v));
  const SHOTS = __SHOTS__;
  function facts(name) {
    const box = document.getElementById('settle-game');
    const q = s => box.querySelectorAll(s);
    const one = s => box.querySelector(s);
    const txt = el => el ? el.textContent : '';
    const size = el => el ? (el.offsetWidth + 'x' + el.offsetHeight) : 'none';
    const o = {};
    o.strip = q('.tstrip .tbtn2').length;
    o.stripmk = [...q('.tstrip .tbtn2')].map(b => b.textContent.trim()).join(',');
    o.sel = txt(one('.tstrip .tbtn2.sel')).trim();
    o.markcls = [...q('.tstrip .tbtn2')]
      .map(b => b.classList.contains('win') ? 'win'
              : b.classList.contains('loss') ? 'loss'
              : b.classList.contains('tie') ? 'tie' : '-').join('|');
    o.cards = q('.turn').length;
    o.rail = q('.rail').length;
    o.railhead = txt(one('.rail-h .rt'));
    o.chips = [...q('.rchips .chip')].map(c => c.textContent).join('|');
    o.groups = [...q('.ig-h')].map(g => g.textContent.trim()).join('|');
    o.groupstate = [...q('.ig-h')].map(g => g.nextElementSibling
      && g.nextElementSibling.style.display === 'none' ? 'closed' : 'open')
      .join('|');
    o.items = [...q('.iitem')]
      .map(i => i.className.replace('iitem', '').trim() + ':' + i.textContent)
      .join('|');
    o.showall = txt(one('.ishow'));
    o.flags = [...q('.q')].map(d => d.textContent).join('|');
    o.newtags = q('.tag-new').length;
    o.deltas = [...q('.tdelta')].map(d => d.textContent).join('|');
    o.tray = [...q('.blbl')]
      .filter(l => l.textContent.indexOf('Passed through') === 0).length;
    o.traytiles = q('.brow .tile.ghost').length;
    o.faceoff = q('.faceoff').length;
    o.vs = txt(one('.faceoff .vs'));
    o.fsides = [...q('.faceoff .fside')].length;
    o.fout = txt(one('.fresult .fout'));
    o.tile = size(one('.brow .tile'));
    o.thumb = size(one('.brow .thumb'));
    o.tabs = [...q('.tbtns .tbtn')].map(b => b.textContent).join('|');
    // The Summary | Step through toggle lives in the SETTLE HEADER now, next to
    // the game dropdown (2026-10-09), so it is read from the document, not from
    // the board area.
    o.mode = [...document.querySelectorAll('#settle-mode button')]
      .map(b => b.textContent + (b.disabled ? ':off' : '')).join('|');
    o.modehidden = document.getElementById('settle-mode').hidden ? 1 : 0;
    o.track = q('.steptrack .stick').length;
    o.letters = [...q('.steptrack .stick')].map(b => b.textContent).join('');
    o.titles = [...q('.steptrack .stick')].map(b => b.title).join('|');
    o.cap = txt(one('.stepcap'));
    o.capsize = one('.stepcap')
      ? Math.round(parseFloat(getComputedStyle(one('.stepcap')).fontSize)) : 0;
    o.legend = txt(one('.slegend'));
    o.legendaftertrack = !!one('.steptrack') && !!one('.steptrack + .slegend');
    o.nav = [...q('.stepnav .snav')].map(b => b.textContent).join('|');
    o.capin = one('.stepcap') && one('.stepcap').closest('.stepnav') ? 1 : 0;
    o.sold = q('.stepboard .tag-sold').length;
    o.affected = q('.tile.affected').length;
    o.stepminions = q('.stepboard .tile:not(.ghost)').length;
    o.stepghosts = q('.stepboard .tile.ghost').length;
    o.steptiles = q('.stepboard .tile').length;
    o.steptile = size(one('.stepboard .tile'));
    o.stepthumb = size(one('.stepboard .thumb'));
    o.stepghost = size(one('.stepboard .tile.ghost'));
    o.caveat = txt(one('.ts-caveat'));
    o.head = txt(one('.ts-head'));
    // Layout facts (item 1 and item 8): the rail must sit LEFT of the boards,
    // and a board label must sit ABOVE its own row. Both are measured, because
    // both are stated as positions and a source assertion cannot see a wrap.
    const rail = one('.rail'), card = one('.twrap > .turn');
    if (rail && card) {
      const rb = rail.getBoundingClientRect(), cb = card.getBoundingClientRect();
      o.layout = (rb.right <= cb.left + 2 && Math.abs(rb.top - cb.top) < 4)
        ? 'side' : 'stacked';
      o.railw = Math.round(rb.width);
    } else {
      o.layout = 'none';
      o.railw = 0;
    }
    const stackedRow = [...q('.brow.stacked')]
      .find(r => r.querySelector('.brow-tiles'));
    if (stackedRow) {
      const lbl = stackedRow.querySelector('.blbl');
      const tiles = stackedRow.querySelector('.brow-tiles');
      o.labelabove = lbl.getBoundingClientRect().bottom
                     <= tiles.getBoundingClientRect().top + 1 ? 1 : 0;
    } else {
      o.labelabove = 0;
    }
    o.stackrows = q('.brow.stacked').length;
    // Item 4: the turn's own line is gone from Tavern (the rail's chips carry
    // its numbers) and the rebuild note appears ONCE — the rail's.
    o.theturn = [...q('.blbl')]
      .filter(l => l.textContent === 'The turn').length;
    o.rebuildnotes = [...box.querySelectorAll('.note, .q')]
      .filter(d => d.textContent.indexOf('rebuilt the board') >= 0).length;
    o.deltaatk = [...q('.tdatk')].map(d => d.textContent).join('|');
    o.deltahp = [...q('.tdhp')].map(d => d.textContent).join('|');
    // Counts come back as ints, sizes and words as text. The '#' marks the
    // numeric ones so `browser.fields()` can cast them: without it every count
    // arrives as a string and `assertEqual(got[key], 2)` fails on '2' != 2 —
    // which is how the first run of this harness reported eleven "failures"
    // that were all correct values.
    const NUMERIC = new Set(['strip', 'cards', 'rail', 'newtags', 'tray',
                             'traytiles', 'faceoff', 'fsides', 'track', 'sold',
                             'stepminions', 'stepghosts', 'steptiles',
                             'affected', 'labelabove', 'stackrows', 'theturn',
                             'rebuildnotes', 'modehidden', 'capin', 'railw',
                             'capsize']);
    for (const k of Object.keys(o)) {
      const v = o[k];
      rec(name + '.' + k, NUMERIC.has(k) ? '#' + Number(v)
          : (v === true ? 'yes' : v === false ? 'no' : v));
    }
  }
  function shot(s) {
    if (s.viewer) _viewer = s.viewer;
    if (s.mode) _tavernMode = s.mode;
    _tavernTurn = (s.turn === undefined ? null : s.turn);
    _tavernStep = s.step || 0;
    renderSettleGame(s.rep);
    facts(s.name);
  }
  if (typeof renderSettleGame !== 'function') {
    rec('fatal', 'renderSettleGame is not defined - the page script did not run');
  } else {
    // The Settle Up tab FIRST. The viewer lives inside `#settle`, and the page
    // opens on the live tab with that section hidden — so every offsetWidth in
    // here would read 0 and a size assertion would pass on nothing (measured
    // 2026-10-08: the first run of this harness reported every card as 0x0).
    // The facts are collected synchronously, so the async settle-list fetch
    // that `showTab` kicks off cannot clobber them afterwards.
    showTab('settle');
    _viewer = 'tavern';
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
    """The real page, with the driver injected just before `</body>`."""
    driver = _DRIVER.replace("__SHOTS__", json.dumps(shots))
    return coach_ui._page_html().replace("</body>", driver + "</body>")


def _shot(name, rep, mode=None, turn=None, step=0, viewer=None):
    return {"name": name, "rep": rep, "mode": mode, "turn": turn, "step": step,
            "viewer": viewer}


def _render(shots, size=browser.WIDE):
    """Run the shots and return the facts.

    A browser this session cannot start SKIPS (see browser.py: a sandboxed run
    has chrome.exe and no permission to launch it). A shot that threw inside the
    viewer FAILS — the whole point of executing the renderer is that its
    exceptions stop being invisible.

    Exceptions are raised rather than routed through a TestCase, because the
    callers below include `setUp`, where raising `SkipTest` is how a whole case
    skips.
    """
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
    """Render the shots ONCE per class, then replay that outcome per test.

    A browser launch costs seconds, so the facts are cached on the class. The
    OUTCOME is cached with them — skip or failure included — so a broken
    renderer is reported by every test that depends on it instead of being
    re-rendered once per test.
    """

    _outcome = None
    #: The window the shots are rendered at — the page has a 900px breakpoint,
    #: so a layout claim has to say which side of it it means (2026-10-09).
    SIZE = browser.WIDE

    @classmethod
    def shots(cls):
        raise NotImplementedError

    def setUp(self):
        cls = type(self)
        if cls._outcome is None:
            try:
                cls._outcome = _render(cls.shots(), cls.SIZE)
            except Exception as e:      # noqa: BLE001 - replayed right below
                cls._outcome = e
        if isinstance(cls._outcome, BaseException):
            raise cls._outcome
        self.got = cls._outcome


class TestTheTavernSummaryInABrowser(_Rendered):
    """Summary mode, the default view — what a player sees first."""

    @classmethod
    def shots(cls):
        return [_shot("t1", _named(), mode="summary"),
                _shot("t3", _named_single(), mode="summary"),
                # Classic, for the two things Tavern must not have changed: the
                # mode toggle is Tavern-only, and the classic renderer keeps its
                # own "The turn" line.
                _shot("cl", _named(), viewer="classic")]

    def test_one_turn_at_a_time_with_a_strip_button_for_the_rest(self):
        self.assertEqual(self.got["t1.strip"], 3, "one strip button per turn")
        self.assertEqual(self.got["t1.cards"], 1,
                         "design §1 shows ONE turn at a time, not a scroll")
        self.assertTrue(self.got["t1.sel"].startswith("1"),
                        f"selected strip button reads {self.got['t1.sel']!r}")

    def test_the_strip_marks_what_the_fight_cost(self):
        """§4.1: a glyph AND a bottom border, never color alone — and the glyph
        reports the COST (2026-10-09, player call): HP dropped is the loss
        marker, and a turn with no reading is a dash, never a "?" wedged into
        the turn number."""
        self.assertEqual(self.got["t1.markcls"], "win|loss|-")
        self.assertIn(WIN, self.got["t1.stripmk"])
        self.assertIn(LOSS, self.got["t1.stripmk"])
        self.assertIn("12", self.got["t1.stripmk"], "the HP lost rides line 2")
        self.assertIn(DASH, self.got["t1.stripmk"],
                      "the turn with no reading owes a dash")
        self.assertNotIn("?", self.got["t1.stripmk"])

    def test_the_rail_sits_left_of_the_boards(self):
        """Item 1 (2026-10-09): rail left, ~330px, boards fill the rest. It used
        to wrap ABOVE them — a source assertion cannot see a wrap, so this is
        measured from the two boxes' rectangles."""
        self.assertEqual(self.got["t1.layout"], "side",
                         "the rail wrapped above the boards again")
        self.assertGreaterEqual(self.got["t1.railw"], 320)
        self.assertLessEqual(self.got["t1.railw"], 340)

    def test_the_rail_counts_the_turn_and_keeps_the_designs_group_defaults(self):
        self.assertEqual(self.got["t1.rail"], 1)
        # 11 buys + 2 sells + 1 play + 2 casts + 9 rolls + 1 level-up
        self.assertIn("Turn 1 " + MIDDOT + " 26 action", self.got["t1.railhead"])
        for chip in ("+11 bought", MINUS + "2 sold", "9 rolls", "1 level-up",
                     "2 casts"):
            self.assertIn(chip, self.got["t1.chips"])
        # §4.3's defaults, read TWICE: the header glyph and the body it controls.
        self.assertEqual(self.got["t1.groups"],
                         "|".join([FOLDED + " Economy", OPENED + " Buys",
                                   OPENED + " Sells", FOLDED + " Plays"]))
        self.assertEqual(self.got["t1.groupstate"], "closed|open|open|closed")

    def test_the_turns_own_line_is_gone_and_its_numbers_are_chips(self):
        """Item 4 (2026-10-09): the card's "The turn" line is classic-only, and
        what it said reaches the player as chips — the same facts printed twice
        in two vocabularies was the duplication the rail exists to remove."""
        self.assertEqual(self.got["t1.theturn"], 0,
                         "the classic 'The turn' line is back in Tavern")
        for chip in ("2 cards played", "14g spent", "value +5"):
            self.assertIn(chip, self.got["t1.chips"],
                          "the line's numbers did not move into the chips")
        self.assertEqual(self.got["cl.theturn"], 3,
                         "Classic keeps its own line — one per turn card")

    def test_a_count_of_one_is_worded_as_one(self):
        """The chips are player-facing (§4.3), and a turn really does hold one
        cast or one roll. "1 casts" is what the tab said before this case."""
        self.assertIn("1 cast", self.got["t3.chips"])
        self.assertNotIn("1 casts", self.got["t3.chips"])
        self.assertIn("1 roll", self.got["t3.chips"])
        self.assertNotIn("1 rolls", self.got["t3.chips"])

    def test_repeats_collapse_and_a_long_group_caps_with_show_all(self):
        items = self.got["t1.items"].split("|")
        self.assertTrue(any("Dune Dweller \u00d73" in i for i in items),
                        f"repeats did not collapse: {items}")
        self.assertEqual(self.got["t1.showall"], "show all 9",
                         "11 buys over 9 runs must cap at 8 and offer the rest")
        self.assertEqual(len([i for i in items if "kept:Buy" in i]), 7,
                         "the cap renders 8 items: the collapsed run plus 7")

    def test_the_rail_tells_kept_sold_and_flipped_apart(self):
        items = self.got["t1.items"]
        self.assertIn("sold:Sold Away", items)
        self.assertIn("flipped:Dune Dweller", items,
                      "bought AND sold this phase is the design's flipped")

    def test_the_worth_a_look_flag_is_still_there(self):
        self.assertIn("Decoy Conjurer", self.got["t1.flags"])

    def test_the_ended_board_carries_net_changes_only(self):
        """§4.4: NEW for a minion that was not opened with, a stat delta for one
        that was — matched by entity id, and nothing per-action. The delta is
        attack and health SEPARATELY (item 5, 2026-10-09): "+0/+3", coloured by
        stat, not one green number that reads as two."""
        self.assertEqual(self.got["t1.newtags"], 1)
        self.assertEqual(self.got["t1.deltaatk"], "+2")
        self.assertEqual(self.got["t1.deltahp"], "+2")
        self.assertNotIn("+2+2", self.got["t1.deltas"],
                         "the two stats are joined by a separator and coloured "
                         "separately now, not concatenated")

    def test_the_rebuild_note_appears_once(self):
        """Item 4 (2026-10-09): the "rebuilt the board" note was rendered twice —
        once by the rail and once by the card. The rail keeps it."""
        self.assertEqual(self.got["t1.rebuildnotes"], 1,
                         "the rebuild note is duplicated (or gone)")

    def test_the_board_labels_sit_above_their_rows(self):
        """Item 8 (2026-10-09): OPENED WITH / ENDED WITH label their board from
        above instead of taking a column beside it."""
        self.assertEqual(self.got["t1.labelabove"], 1,
                         "a board label is beside its row, not above it")
        self.assertGreaterEqual(self.got["t1.stackrows"], 3,
                                "opened, ended and the tray are stacked rows")

    def test_flipped_minions_show_in_the_passed_through_tray(self):
        self.assertEqual(self.got["t1.tray"], 1)
        self.assertEqual(self.got["t1.traytiles"], 1, "one ghost card")

    def test_the_battle_tab_is_the_face_off(self):
        self.assertEqual(self.got["t1.faceoff"], 1)
        self.assertEqual(self.got["t1.vs"], "VS")
        self.assertEqual(self.got["t1.fsides"], 2, "their side and yours")
        self.assertEqual(self.got["t1.fout"], "You won the fight")

    def test_the_tabs_and_the_mode_toggle_are_where_the_design_puts_them(self):
        self.assertEqual(self.got["t1.tabs"], "Shop|Battle|Result")
        self.assertEqual(self.got["t1.mode"], "Summary|Step through")
        self.assertEqual(self.got["t1.modehidden"], 0,
                         "the mode toggle is not showing for the Tavern viewer")

    def test_the_mode_toggle_is_tavern_only(self):
        """Item 8 moved it into the Settle Up header next to the game dropdown;
        the classic renderer has no mode, so it must not carry the control."""
        self.assertEqual(self.got["cl.modehidden"], 1,
                         "the Summary | Step through toggle shows in Classic")
        self.assertEqual(self.got["cl.rail"], 0, "classic has no rail")

    def test_the_art_fills_the_card_frame(self):
        """Item 2 (2026-10-09): the art fills the frame, and the frame scales
        with the window — minimum the design's §4.2 sizes (88 Summary, 130 Step
        through, asserted in the step case below).

        Before this, a Tavern tile was the live overlay's fixed box with a 56px
        thumbnail inside: a step-through card was a 130x172 outline around a small
        picture, which is the "oversized empty frame" this fixes."""
        self.assertNotEqual(self.got["t1.tile"], "none",
                            "no card tile rendered in the summary board")
        self.assertEqual(self.got["t1.thumb"], self.got["t1.tile"],
                         "the art does not fill the card frame")
        width = int(self.got["t1.tile"].split("x")[0])
        self.assertGreaterEqual(width, 88,
                                f"summary cards are under the design's 88px "
                                f"minimum: {self.got['t1.tile']}")
        self.assertGreater(width, 88,
                           "the card did not grow with a wider window — the "
                           "width is clamped, not scaling")


class TestTheStepThroughInABrowser(_Rendered):
    """Step-through mode: design §4.6, executed."""

    @classmethod
    def shots(cls):
        rep = _named()
        # The fixture's four steps are buy, level, sell, cast — one of each kind
        # the highlight rule cares about.
        return [_shot("s%d" % i, rep, mode="step", turn=1, step=i)
                for i in range(4)]

    def test_the_track_has_one_lettered_tick_per_action(self):
        self.assertEqual(self.got["s0.track"], 4)
        self.assertEqual(self.got["s0.letters"], "BLSC")
        self.assertIn("R roll", self.got["s0.legend"])

    def test_the_legend_sits_directly_under_the_track(self):
        """Item 7 (2026-10-09): the letters are explained where they are read."""
        self.assertEqual(self.got["s0.legendaftertrack"], "yes",
                         "something sits between the track and its legend")

    def test_every_tick_carries_its_action_as_a_tooltip(self):
        titles = "|" + self.got["s0.titles"] + "|"
        self.assertIn("|Step 2: Leveled up|", titles,
                      f"the level-up tick's tooltip is missing: {titles}")
        self.assertIn("|Step 1: Bought Dune Dweller|", titles)

    def test_the_caption_is_large_and_labels_the_board(self):
        """Item 7 (2026-10-09): the action in plain words, at reading size, above
        the board it labels. It used to be 13px muted text in the control row."""
        self.assertTrue(self.got["s0.cap"].startswith(
            "Your board after step 1 of 4"), f"caption: {self.got['s0.cap']!r}")
        self.assertEqual(self.got["s0.capin"], 0,
                         "the caption is back inside the control row")
        self.assertGreaterEqual(self.got["s0.capsize"], 15,
                                "the caption is not the large line any more")

    def test_the_caption_names_the_card_not_its_id(self):
        """The join and the renderer have to meet for this to be true.

        `stepWords()` falls back to `st.card`, so a rep that never went through
        `_name_timeline_boards` renders "Bought BG31_815" at the player. This is
        the assertion that tells those two worlds apart.
        """
        self.assertIn("Bought Dune Dweller", self.got["s0.titles"])
        self.assertNotIn("BG31_815", self.got["s0.titles"],
                         "a raw card id reached the player's screen")
        self.assertIn("Bought Dune Dweller", self.got["s0.cap"])

    def test_the_board_is_the_one_after_that_action(self):
        """The feature's whole point: the board follows the action, and an action
        that changes no card (the level-up) leaves it alone.

        `stepminions` counts cards and `stepghosts` the sold card's placeholder
        separately — a total that lumped them together would call a sell step
        "two minions"."""
        self.assertEqual(self.got["s0.stepminions"], 2)
        self.assertEqual(self.got["s1.stepminions"], 2)
        self.assertEqual(self.got["s2.stepminions"], 1)
        self.assertEqual(self.got["s3.stepminions"], 1)

    def test_only_an_action_that_targets_a_card_highlights_one(self):
        """Item 3 (2026-10-09): a buy outlines the card it put on the board, and
        the level-up, the sell and the cast outline nothing. The old rule
        outlined card 1 for "Leveled up" — step 1 has no previous board to
        compare against, so every tile looked new."""
        self.assertEqual(self.got["s0.affected"], 1,
                         "the buy must highlight the card it added")
        self.assertEqual(self.got["s1.affected"], 0,
                         "a level-up targets no card")
        self.assertEqual(self.got["s2.affected"], 0,
                         "a sell's card is the ghost, not a highlight")
        self.assertEqual(self.got["s3.affected"], 0,
                         "a cast targets no board card")

    def test_a_sold_card_is_shown_dimmed_and_tagged(self):
        self.assertEqual(self.got["s0.sold"], 0)
        self.assertEqual(self.got["s0.stepghosts"], 0)
        self.assertEqual(self.got["s2.sold"], 1,
                         "the sell step must show the absence it created")
        self.assertEqual(self.got["s2.stepghosts"], 1)

    def test_large_cards_and_prev_play_next(self):
        """Item 2 (2026-10-09): step cards are at least the design's 130px wide
        with the art filling them, and the sold ghost stays smaller than a card —
        the bug that made a sold card look like it was still on the board."""
        width = int(self.got["s2.steptile"].split("x")[0])
        self.assertGreaterEqual(width, 130,
                                f"step cards are under 130px: "
                                f"{self.got['s2.steptile']}")
        self.assertEqual(self.got["s2.stepthumb"], self.got["s2.steptile"],
                         "the art does not fill the step card")
        ghost = int(self.got["s2.stepghost"].split("x")[0])
        self.assertLess(ghost, width,
                        "the sold ghost is as big as a real card")
        self.assertEqual(self.got["s0.nav"],
                         "\u25c0 Prev|\u25b6 Play|Next \u25b6")

    def test_the_rail_is_dropped_so_the_boards_can_grow(self):
        self.assertEqual(self.got["s0.rail"], 0,
                         "design §3: in Step-through mode the rail is dropped")


class TestTheNarrowViewport(_Rendered):
    """The same view at 800px wide: the design's §5 narrow-width rule.

    This case exists because of how the rail bug hid: headless Chromium defaults
    to 800x600, so a "is the rail beside the boards?" check was really asking
    "is 800px narrow?" — and it is. Both widths are asserted now, which is the
    only way to say what the rule IS.
    """

    SIZE = browser.NARROW

    @classmethod
    def shots(cls):
        return [_shot("n", _named(), mode="summary")]

    def test_the_rail_goes_above_the_boards_when_there_is_no_room(self):
        self.assertEqual(self.got["n.layout"], "stacked",
                         "at 800px the 330px rail must go above the boards")

    def test_the_cards_are_at_their_minimum_width_here(self):
        """Item 2's "scales with window": 88px is the floor, and the wide case
        asserts the card is bigger than that — one number here, one there, and
        together they say the width tracks the window."""
        self.assertEqual(self.got["n.tile"].split("x")[0], "88",
                         f"at 800px the summary card should sit on its 88px "
                         f"floor: {self.got['n.tile']}")


class TestTheHarnessItself(unittest.TestCase):
    """The controls. Without these, a passing result above proves nothing."""

    def test_an_empty_rep_renders_nothing(self):
        """If the facts were read from a stale document, 0 would be impossible
        to tell from a hardcoded number."""
        got = _render([_shot("empty", {"timeline": {"turns": []}},
                             mode="summary")])
        self.assertEqual(got["empty.strip"], 0)
        self.assertEqual(got["empty.cards"], 0)
        self.assertEqual(got["empty.rail"], 0)

    def test_a_throwing_renderer_is_reported_not_swallowed(self):
        """The rehearsal. `took.bought` as a string makes `flipKinds` throw on
        `forEach`; the driver has to SAY so, or every passing case above could
        be passing because its errors went nowhere."""
        broken = _named()
        broken["timeline"]["turns"][0]["took"]["bought"] = "not a list"
        browser.require_browser(self)
        try:
            got = browser.fields(_page([_shot("broken", broken, mode="summary")]))
        except browser.BrowserUnavailable as e:
            self.skipTest(str(e))
        self.assertIn("broken.error", got,
                      "a throwing renderer left no error behind — the harness "
                      "would have called that 'rendered fine'")
        self.assertTrue(got["broken.error"], "the error message came back empty")


if __name__ == "__main__":
    unittest.main()
