"""The Tavern Live layout, RUN in a real browser — and scanned for verdicts.

`LIVE_VIEW_DESIGN.md` §1 is the rule that shapes the whole redesign: the Live
page is reference material, so it shows facts, counts and statistics — never a
verdict, a ranking or an imperative. That rule is about WORDS ON THE SCREEN, and
the working notes record what happens when it is enforced one layer off: the
live wall drops verdict *keys* from the payload, so a verdict inside a fact
*string* walked straight through for a day (`choices._rank_discover` shipping
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
        # The Tavern row on top, board and hand in ONE panel under it (fix list
        # round 1 item 4 / round 2 item 4), and one of the shop rows is a real
        # tavern spell so the Spell tag has something to tag.
        "shop_rank": [("BG31_820", 32), ("BG31_880", 18), ("BG31_831", 12)],
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


#: A fixed corpus record for the comps fixture. `render_json` reads the REAL
#: `meta/corpus_stats.json` — this project's own played games — and its values
#: change every time a game is played, so the fixture that pins §4.4's numbers
#: replaces the reader instead of borrowing today's numbers. The real file's own
#: shape is pinned in `test_live_tavern`.
_CORPUS = {"comps": {
    "Elementals": {"games": 12, "wins": 2, "top4": 8, "avg_place": 3.83,
                   "places": [1, 1, 2, 2, 3, 3, 4, 4, 5, 6, 7, 8]},
    "Beasts": {"games": 4, "wins": 1, "top4": 2, "avg_place": 4.0,
               "places": [1, 3, 5, 7]},
    "Aardvark": {"games": 20, "wins": 0, "top4": 20, "avg_place": 2.0,
                 "places": [2] * 20},
}}


def _comps_analysis(**over):
    """A lobby's comps, as `game_comps` carries them (ban window: every comp).

    Chosen to exercise §4.4's rules in one payload: a Mixed comp (no tribe), a
    comp of an OUT-OF-PLAY tribe (Naga), more tier-A comps than the cap allows,
    a core card that is on the board, one in hand and one nobody owns, and a
    corpus record that makes the default order and the opt-in sorts differ.
    """
    comps = {
        "elementals": {"name": "Elementals", "meta_tier": "S",
                       "tribe": "ELEMENTAL", "difficulty": "Easy",
                       "core": ["BG31_815", "BG31_820", "BG31_831"],
                       "addons": ["BG31_999"]},
        "menagerie": {"name": "Menagerie", "meta_tier": "S", "tribe": None,
                      "difficulty": "Medium",
                      "core": ["BG31_815", "BG31_998"], "addons": []},
        "aardvark": {"name": "Aardvark", "meta_tier": "A", "tribe": "MECH",
                     "core": ["BG31_997"], "addons": []},
        "beasts": {"name": "Beasts", "meta_tier": "A", "tribe": "BEAST",
                   "difficulty": "Hard",
                   "core": ["BG31_815", "BG31_820"], "addons": []},
        "nagas": {"name": "Nagas", "meta_tier": "A", "tribe": "NAGA",
                  "core": ["BG31_815"], "addons": []},
    }
    for i in range(1, 6):
        comps["filler%d" % i] = {"name": "Filler %d" % i, "meta_tier": "A",
                                 "tribe": "MECH", "core": ["BG31_99%d" % i],
                                 "addons": []}
    a = _analysis(**over)
    if "game_comps" not in over:
        a["game_comps"] = comps
    return a


def _comps_payload(corpus=None, **over):
    """The comps payload, with the corpus reader replaced by `_CORPUS` — or by
    whatever a test hands in: `{}` is "the corpus has never seen these comps",
    which is what the avg-placement column hides itself for (round 3 item 5)."""
    import meta
    saved = meta.corpus_stats
    meta.corpus_stats = lambda: (_CORPUS if corpus is None else corpus)
    try:
        return coach_ui.render_json(_comps_analysis(**over))
    finally:
        meta.corpus_stats = saved


def _game_over_payload(enabled=False, game_over=None, sent=None):
    """The end-of-game card's payload — the REAL `welcome_payload`.

    `welcome_payload` returns the serialized body (it is what the handler
    writes), so it is decoded here. `auto_save_enabled()` is replaced rather
    than read: it is a file on the machine, so the card's shape would otherwise
    depend on who is running the suite. `sent` replaces the SHARING ANSWER the
    same way — the count of games shared so far lives on this machine too.
    """
    import json
    import replay_store
    saved = replay_store.auto_save_enabled
    saved_status = coach_ui.share_status
    replay_store.auto_save_enabled = lambda: enabled
    if sent is not None:
        coach_ui.share_status = lambda: ("on", sent)
    try:
        body = coach_ui.welcome_payload(
            game_over=game_over if game_over is not None
            else {"placement": 3, "turn": 12})
    finally:
        replay_store.auto_save_enabled = saved
        coach_ui.share_status = saved_status
    return json.loads(body)


def _welcome_payload():
    """A FIRST-RUN welcome: no game over, so the classic card, in either viewer."""
    import json
    import replay_store
    saved = replay_store.auto_save_enabled
    replay_store.auto_save_enabled = lambda: False
    try:
        body = coach_ui.welcome_payload()
    finally:
        replay_store.auto_save_enabled = saved
    return json.loads(body)


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
  const txt = el => el ? el.textContent : '';
  function facts(name) {
    const root = document.querySelector('.tavern.live');
    const q = s => root ? root.querySelectorAll(s) : [];
    const one = s => root ? root.querySelector(s) : null;
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
    // The first panel's own text, for claims about ONE panel rather than the
    // page: "Lobby tribes" belongs to the page's tribe row, and the comps panel
    // must not have a second copy of it (round 3 item 4).
    o.paneltext = (function () {
      const p = one('.lv-pn');
      return p ? p.textContent.replace(/\\s+/g, ' ').trim() : '';
    })();
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
    o.pick = q('.lv-opt').length;
    o.picknames = [...q('.lv-optname')].map(n => n.textContent).join('|');
    o.pickhead = [...q('.lv-head b')].map(b => b.textContent).join('|');
    o.pickvs = [...q('.lv-vs')].map(v => v.textContent).join('|');
    o.pickbars = q('.lv-bar').length;
    o.pickrows = [...q('.lv-opt .lv-kv')]
      .map(d => txt(d.children[0]) + '=' + txt(d.children[d.children.length - 1]))
      .join('|');
    o.pickctl = [...q('.lv-pickctl .lv-chip')]
      .map(c => c.textContent + (c.classList.contains('on') ? ':on' : ':off'))
      .join('|');
    // The source line under the pick controls. Guarded: the comps Compare block
    // reuses `.lv-opts` for its columns and has no `.lv-pickctl` at all, so an
    // unguarded read threw on that screen and took the whole shot with it.
    const pickctl = one('.lv-pickctl');
    o.picknote = pickctl ? txt(pickctl.parentNode.querySelector('.lv-note')) : '';
    o.gobtn = txt(one('.lv-gobtn'));
    o.overbig = txt(one('.lv-overbig'));
    // §6.5's merged save row: ONE row, and the checkbox has to be inside it —
    // the classic card's two rows are exactly what the design asks to merge.
    o.saverows = q('.lv-saverow').length;
    o.saverowtext = txt(one('.lv-saverow'));
    o.saved = txt(one('.lv-saved'));
    o.checkboxin = (function () {
      const row = one('.lv-saverow'), cb = document.getElementById('lv-save-all');
      return row && cb && cb.parentNode === row ? 1 : 0;
    })();
    o.tavernon = document.getElementById('app')
      .classList.contains('tavern-on') ? 1 : 0;
    o.decidehidden = getComputedStyle(
      document.getElementById('col-decide')).display === 'none' ? 1 : 0;
    o.decidekids = document.getElementById('col-decide').children.length;
    o.label = txt(one('.lv-lbl'));
    o.opplabel = txt(one('.lv-opp'));
    o.tabh = (function () {
      const b = one('.lv-tabs button');
      return b ? Math.round(b.getBoundingClientRect().height) : 0;
    })();
    o.classic = document.getElementById('col-decide').children.length;
    // --- the fix lists' own facts (rounds 1 and 2, 2026-10-09) ------------
    // 1. Live fills the window: the tavern container against the viewport, and
    //    where the main column and the rail actually sit (>=1200 side by side).
    //    Measured on the ROOT: `root.querySelector('.tavern.live')` looks for a
    //    DESCENDANT of it and finds nothing, which read as a 0px-wide view.
    o.tavernw = root ? Math.round(root.getBoundingClientRect().width) : 0;
    o.vpw = window.innerWidth;
    o.colat2 = (function () {
      const a = one('.lv-col'), b = one('.lv-rail');
      if (!a || !b) return '';
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      return Math.round(ra.left) + ',' + Math.round(ra.top) + '|'
           + Math.round(rb.left) + ',' + Math.round(rb.top);
    })();
    // 2. The waiting state, and the empty strip that used to sit above it.
    o.statebarhidden = document.getElementById('statebar').hidden ? 1 : 0;
    o.herocls = one('.lv-hero') ? one('.lv-hero').className : '';
    o.missvals = q('.lv-st b.miss').length;
    o.inline = [...q('.lv-inline')].map(d => d.textContent).join('|');
    o.bhlabels = [...q('.lv-bh .lv-lbl')].map(d => d.textContent).join('|');
    o.bhhalf = q('.lv-bh > div').length;
    // 3. One art treatment, spell tags, names.
    o.kinds = [...q('.tile .tag-kind')].map(d => d.textContent).join('|');
    o.renameless = q('.lv-opt .tname').length;
    o.tiletitles = q('.tile[title]').length;
    o.tnamewrap = (function () {
      const n = one('.tavern .tile .tname') || one('.tile .tname');
      return n ? getComputedStyle(n).whiteSpace : '';
    })();
    o.noart = q('.tile .thumb').length;
    // 4. The tribe row: one chip per tribe, amber when set, dimmed when not.
    o.chipcls = [...q('.lv-tribes .lv-chip')]
      .map(c => c.textContent + ':' + (c.classList.contains('active') ? 'active'
             : c.classList.contains('dim') ? 'dim'
             : c.classList.contains('out') ? 'out' : '?')).join('|');
    o.nagacount = [...q('.lv-tribes .lv-chip')]
      .filter(c => c.textContent === 'NAGA' || c.textContent === 'Naga').length;
    // 5. The pick screen's own numbers and layout.
    o.picklbl = [...q('.lv-head small')].map(d => d.textContent).join('|');
    o.pickcolw = (function () {
      const n = one('.lv-opt');
      return n ? Math.round(n.getBoundingClientRect().width) : 0;
    })();
    o.pickctlvp = (function () {
      const n = one('.lv-pickctl');
      return n ? Math.round(n.getBoundingClientRect().height) : 0;
    })();
    o.picknameh = (function () {
      const n = one('.lv-optname');
      return n ? Math.round(n.getBoundingClientRect().height) : 0;
    })();
    o.pickcardw = (function () {
      const n = one('.lv-opt .tile');
      return n ? Math.round(n.getBoundingClientRect().width) : 0;
    })();
    // 6. The Classic | Tavern toggle's own colours (round 1 item 9).
    o.vsegbg = (function () {
      const b = document.querySelector('#live-viewer button');
      return b ? getComputedStyle(b).backgroundColor : '';
    })();
    o.vsegon = (function () {
      const b = document.querySelector('#live-viewer button.on');
      return b ? getComputedStyle(b).backgroundColor : '';
    })();
    o.vsegpad = (function () {
      const b = document.querySelector('#live-viewer button');
      return b ? getComputedStyle(b).padding : '';
    })();
    // 7. Game over: the label, and the sharing counter in its sentence.
    o.overlabel = txt(one('.lv-overlabel'));
    o.fine = [...q('.lv-fine')].map(d => d.textContent).join('|');
    // §4.4: the comp rows, their tier columns, the mini-card slots with the
    // size actually laid out, the controls, and the Detail/Compare shapes.
    o.comprows = [...q('.lv-crow')].map(r => {
      const n = r.querySelector('.lv-copen'), own = r.querySelector('.lv-owned'),
            ap = r.querySelector('.lv-ap');
      return txt(n) + '|' + txt(own) + '|' + txt(ap)
           + (r.classList.contains('low') ? '|low' : '');
    }).join(' ; ');
    o.comptiers = [...q('.lv-ctier > h4')].map(h => h.textContent).join('|');
    o.compslots = q('.lv-slot').length;
    o.slotsmiss = q('.lv-slot.miss').length;
    o.slotshand = q('.lv-slot.hand').length;
    o.slotart = q('.lv-slot .thumb').length;
    o.legend = [...q('.lv-legend .lv-leglbl')].map(d => d.textContent).join('|');
    o.legendslots = q('.lv-legend .lv-slot').length;
    o.cmpboxes = q('.lv-cmpbox').length;
    o.cmpchecked = q('.lv-cmpbox:checked').length;
    o.cmpdisabled = q('.lv-cmpbox:disabled').length;
    o.rowcols = (function () {
      const r = one('.lv-crow');
      if (!r) return '';
      return getComputedStyle(r).display;
    })();
    // Round 3: the columns, the strip, the name, the avg track and the toggle.
    o.cmptracks = (function () {
      const r = one('.lv-crow');
      if (!r) return '';
      return getComputedStyle(r).gridTemplateColumns;
    })();
    o.colw = [...q('.lv-ctier')].map(c => Math.round(c.getBoundingClientRect().width)).join('|');
    o.colx = [...q('.lv-ctier')].map(c => Math.round(c.getBoundingClientRect().left)).join('|');
    o.cols = [...q('.lv-ctier')].length;
    o.h4pos = (function () {
      const h = one('.lv-ctier > h4');
      return h ? getComputedStyle(h).position : '';
    })();
    o.stripwrap = (function () {
      const s = one('.lv-slots');
      return s ? getComputedStyle(s).flexWrap : '';
    })();
    o.slotflex = (function () {
      const s = one('.lv-slot');
      return s ? getComputedStyle(s).flex : '';
    })();
    o.nameclamp = (function () {
      const n = one('.lv-copen');
      return n ? getComputedStyle(n).webkitLineClamp : '';
    })();
    o.nameunder = (function () {
      const n = one('.lv-copen');
      return n ? getComputedStyle(n).textDecorationLine : '';
    })();
    o.avgcells = q('.lv-ap').length;
    o.hasavg = q('.lv-ctier.has-avg').length;
    o.hnote = [...q('.lv-hnote')].map(n => n.textContent).join('|');
    o.unconfirmed = q('.lv-crow .lv-tier').length
      ? [...q('.lv-crow .lv-tier')].filter(t => /unconfirmed/.test(t.textContent)).length
      : 0;
    o.ctlchips = [...q('.lv-ctl .lv-chip')].map(c => c.textContent).join('|');
    o.ctlrows = q('.lv-ctl').length;
    // The compare control's own theming, and where the toggle lives.
    o.cmpskin = (function () {
      const b = one('.lv-cmpbox');
      if (!b) return '';
      const s = getComputedStyle(b);
      return s.appearance + ',' + s.backgroundColor;
    })();
    o.toggleinnav = document.querySelector('#tabs #live-viewer') ? 1 : 0;
    // A COMMA, not an angle bracket: the harness reads `#out` with
    // `id="out">([^<]*)<`, so a '<' inside a value ends the capture early
    // (measured 2026-10-09 — it came back as a one-field value).
    o.toggleright = (function () {
      const r = document.querySelector('#live-viewer-row');
      if (!r) return '';
      const b = r.getBoundingClientRect();
      return Math.round(window.innerWidth - b.right) + ','
           + Math.round(b.left);
    })();
    o.togglehidden = (function () {
      const r = document.querySelector('#live-viewer-row');
      return r && r.hidden ? 1 : 0;
    })();
    // One row per OFFER / per board minion (round 3 item 1). Scoped to the FIRST
    // panel (the tavern), because the board and hand rows are cards too.
    o.shopcards = panes.length
      ? panes[0].querySelectorAll('.lv-card').length : 0;
    o.shopkeys = panes.length
      ? [...panes[0].querySelectorAll('.tname')].map(n => n.textContent).join('|')
      : '';
    o.boardcards = (function () {
      const halves = q('.lv-bh > div');
      return halves.length ? halves[0].querySelectorAll('.lv-card').length : 0;
    })();
    o.poolchips = [...q('.lv-pn .lv-cap')].map(c => c.textContent).join('|');
    o.ctl = [...q('.lv-ctl .lv-chip')]
      .map(c => c.textContent + (c.classList.contains('on') ? ':on' : ''))
      .join('|');
    o.more = [...q('.lv-more')].map(b => b.textContent).join('|');
    o.lowsamp = [...q('.lv-chip.lowsamp')].map(c => c.textContent).join('|');
    o.detail = txt(one('.lv-cdname'));
    o.detailchips = [...q('.lv-cdhead .lv-chip')].map(c => c.textContent).join('|');
    o.cmpcols = [...q('.lv-cmpcol .lv-optname')].map(n => n.textContent).join('|');
    o.stathead = [...q('.lv-cstat .lv-head b')].map(b => b.textContent).join('|');
    o.statrows = [...q('.lv-cstat .lv-kv')].map(d => txt(d.children[0]) + '='
      + txt(d.children[d.children.length - 1])).join('|');
    // Per compare column: the stat rows in their own order, then the headline.
    o.cmpstats = [...q('.lv-cmpcol')].map(col =>
      [...col.querySelectorAll('.lv-cstat .lv-kv')]
        .map(d => txt(d.children[0])).join('>')
      + '#' + txt(col.querySelector('.lv-cstat .lv-head b'))).join(' ~ ');
    o.guideopen = q('.lv-guide').length ? (one('.lv-guide').open ? 1 : 0) : -1;
    o.guidesum = txt(one('.lv-guide summary'));
    // The layout the design specifies in px, measured rather than assumed: a
    // rule can exist and still lose to a more specific one (the sold-ghost bug).
    const box = s => {
      const n = one(s);
      if (!n) return '';
      const r = n.getBoundingClientRect();
      return Math.round(r.width) + 'x' + Math.round(r.height);
    };
    o.slotpx = box('.lv-slot');
    o.cmpslotpx = box('.lv-cmpcol .lv-slot');
    // The CARD, not the wrapper that also holds its caption: §5 sizes the art
    // frame at 88x116, and the caption line is not part of it.
    o.corepx = box('.lv-core .tile');
    o.flexpx = box('.lv-flexcards .tile');
    // Where each tier column actually sits, so "two columns" is measured rather
    // than inferred from a rule that might be losing to another one.
    o.colat = [...q('.lv-ctier')].map(c => {
      const r = c.getBoundingClientRect();
      return Math.round(r.left) + ',' + Math.round(r.top);
    }).join('|');
    o.panelw = (function () {
      const n = one('.lv-pn');
      return n ? Math.round(n.getBoundingClientRect().width) : 0;
    })();
    // EVERY word the view puts on screen, for the §1 scan. The panel headers
    // and the status labels are in here too — a verdict can hide in a label.
    o.alltext = root ? root.textContent.replace(/\s+/g, ' ').trim() : '';
    for (const k of Object.keys(o))
      rec(name + '.' + k, ['tavern', 'cards', 'skel', 'pick', 'classic',
                           'taverncards', 'pickbars', 'compslots', 'slotsmiss',
                           'slotshand', 'guideopen', 'panelw', 'saverows',
                           'checkboxin', 'tavernon', 'decidehidden',
                           'decidekids', 'tabh', 'tavernw', 'vpw', 'slotart',
                           'legendslots', 'cmpboxes', 'cmpchecked', 'cmpdisabled',
                           'missvals', 'bhhalf', 'renameless', 'tiletitles',
                           'noart', 'nagacount', 'pickcolw', 'pickctlvp',
                           'picknameh', 'pickcardw', 'statebarhidden', 'cols',
                           'avgcells', 'hasavg', 'unconfirmed', 'ctlrows',
                           'toggleinnav', 'togglehidden', 'shopcards',
                           'boardcards']
          .includes(k) ? '#' + Number(o[k]) : o[k]);
  }
  function clickCtl(sel, label, row) {
    // A control is only tested by using it: find it by its label and click it
    // for real, then read the facts back from what the redraw produced. `row`
    // scopes the search to one comp row, because the Browse rows all carry a
    // control with the same label and the first match would always be the same
    // one. A NULL label matches the first element (a checkbox has no text).
    let scope = document;
    if (row) {
      scope = [...document.querySelectorAll('.lv-crow')]
        .find(x => txt(x.querySelector('.lv-copen')) === row);
      if (!scope) throw new Error('no comp row named ' + row);
    }
    const node = [...scope.querySelectorAll(sel)]
      .find(c => label === null || c.textContent === label);
    if (!node) throw new Error('no control labelled ' + label + ' in ' + sel);
    node.click();
  }
  function shot(s) {
    // Each shot states its own preconditions. The page keeps this view state
    // between renders (a redraw rebuilds the DOM, not the module), so without
    // this a shot that filtered, sorted or opened a Detail hands that state to
    // the next one — measured 2026-10-09: the "more" shot inherited the tribe
    // filter and so had nothing to expand, and the shot after "detail" was
    // still inside Detail.
    _liveComp = null;
    _liveCompSort = 'tier';
    _liveCompFilter = new Set();
    _liveCompMore = new Set();
    _liveCompare = new Set();
    _livePickOrder = 'offered';
    _livePickHidden = new Set();
    _liveViewer = s.viewer || 'tavern';
    // `pre` is the screen the player was looking at before this payload arrived
    // (a live payload, then the end-of-game one) — the only way to test that the
    // new card replaces it rather than leaving it behind.
    if (s.pre) {
      _liveTab = s.pretab || 'shop';
      render(s.pre);
      (s.preclicks || []).forEach(c => clickCtl(c[0], c[1], c[2]));
    }
    _liveTab = s.tab || 'shop';
    render(s.rep);
    if (s.click) clickCtl('.lv-pickctl .lv-chip', s.click);
    (s.clicks || []).forEach(c => clickCtl(c[0], c[1], c[2]));
    // `settle`: the payload renders on the live tab and the SETTLE tab is then
    // opened, which is how "the live viewer flag is out of the way over there"
    // is measured rather than asserted from the source.
    if (s.settle) showTab('settle');
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


def _shot(name, rep, viewer="tavern", tab="shop", click=None, clicks=None,
          pre=None, pretab=None, preclicks=None, settle=False):
    return {"name": name, "rep": rep, "viewer": viewer, "tab": tab,
            "click": click, "clicks": clicks or [], "pre": pre,
            "pretab": pretab, "preclicks": preclicks or [], "settle": settle}


#: Clicking a Browse row's control by the COMP it belongs to: every row carries
#: a control with the same label, so "the compare box" has to name its row.
def _open(name):
    return [".lv-copen", name, name]


def _compare(name):
    # The compare control is a CHECKBOX since fix list round 1 item 6, so there
    # is no label to match — `null` means "the first one in this row".
    return [".lv-cmpbox", None, name]


#: A choice whose facts carry the phrasing the design BANS, and whose
#: statistics are structured. Both matter: the first is the rehearsal (the
#: Tavern view must reach its numbers through `option_stats` and never through
#: the classic fact string), the second is the screen the design describes.
def _choice_payload():
    return _payload(choice={
        "kind": "trinket", "source": "Lesser Trinket",
        "ranked": [["Zed", "BG31_820", 90,
                    "picked in 60% of games · fits your board", 2],
                   ["Ann", "BG31_815", 10,
                    "picked in 30% of games · fits your comp direction", 1]],
        "option_stats": {
            "BG31_820": {"pick_rate": 60.0, "avg_placement": 3.2,
                         "top4": 62.0,
                         "dist": {"1": 10.0, "2": 22.0, "3": 16.0, "4": 14.0,
                                  "5": 12.0, "6": 11.0, "7": 8.0, "8": 7.0}},
            "BG31_815": {"pick_rate": 30.0, "avg_placement": 4.6,
                         "top4": 41.0},
        },
        "guides": {}})


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
                _shot("comps", _comps_payload(), tab="comps"),
                _shot("nocomps", _comps_payload(game_comps={}, tribe_pressure=[]),
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

    def test_a_tribe_out_of_play_appears_once_and_the_chips_are_marked(self):
        """Fix list round 1 item 3. The roster is every tribe the game has, so
        Naga is in it AND in `out_of_pool`: iterating both printed it twice. And
        the set state has to be visible at a glance — amber outline when the
        tribe is banned, dimmed when it is in play."""
        got = self.got
        self.assertEqual(got["t.nagacount"], 1,
                         "the out-of-play tribe is listed twice")
        self.assertIn("BEAST:active", got["t.chipcls"],
                      "a banned tribe is not marked as set")
        self.assertIn("PIRATE:dim", got["t.chipcls"],
                      "an in-play tribe is not marked as unset")
        self.assertIn("NAGA:out", got["t.chipcls"])
        self.assertEqual(got["t.chipcls"].count(":?"), 0,
                         "a chip with no state class at all")

    def test_the_tab_row_selects_the_screen_and_opens_on_shop(self):
        """§4.1's second tab row: `Shop | Comps | Lobby`. The facts table is not
        one of them — it is the rail beside every screen (§4.2 lists it there),
        so it is never hidden and never says anything twice."""
        self.assertEqual(self.got["t.tabs"], "Shop|Comps|Lobby")
        self.assertEqual(self.got["t.tabon"], "Shop")
        self.assertEqual(self.got["t.panels"], "Tavern|Board and hand|Facts")
        self.assertEqual(self.got["comps.panels"], "Comps|Facts")
        self.assertEqual(self.got["lobby.panels"], "Lobby|Facts")
        # §8: 44px minimum targets, measured rather than declared.
        self.assertGreaterEqual(self.got["t.tabh"], 44)

    def test_the_page_fills_the_window_and_the_rail_sits_beside_it(self):
        """Fix list round 1 item 1: the tavern container was a flex rule inside a
        two-column GRID — and inside the flex COLUMN the page falls back to below
        1200x900, `flex-basis` is a height, so it did not stretch either.
        Measured before the fix: 815px of a 1384px window.
        Round 2 item 9 sets the breakpoints: main + 340px rail at >=1200px,
        stacked below it."""
        # BOTH branches of `#app`'s layout: the grid (a tall window) and the flex
        # column (a short one).
        for size in ((1400, 1000), (1400, 900)):
            got = _render([_shot("f", _payload())], size=size)
            self.assertGreater(got["f.tavernw"], got["f.vpw"] * 0.9,
                               f"the tavern view is {got['f.tavernw']}px wide in "
                               f"a {got['f.vpw']}px window at {size}")
            # The two columns of the page itself: main left, rail right.
            left, right = got["f.colat2"].split("|")
            self.assertEqual(left.split(",")[1], right.split(",")[1],
                             f"the rail is not level with the main column at {size}")
            self.assertLess(int(left.split(",")[0]), int(right.split(",")[0]))
        # 700-1200 stacks them (round 2 item 9).
        mid = _render([_shot("m", _payload())], size=(1000, 900))
        mleft, mright = mid["m.colat2"].split("|")
        self.assertNotEqual(mleft.split(",")[1], mright.split(",")[1],
                            "at 1000px the rail should be under the main column")
        # ...and below 700 the pick grid is a single column, with the board and
        # hand stacked rather than squeezed.
        narrow = _render([_shot("n", _choice_payload())], size=(600, 900))
        self.assertGreater(narrow["n.pickcolw"], 400,
                           "the pick grid is not a single column under 700px")
        bhn = _render([_shot("b", _payload())], size=(600, 900))
        self.assertEqual(bhn["b.bhhalf"], 2)
        self.assertNotEqual(bhn["b.colat2"].split("|")[0].split(",")[1],
                            bhn["b.colat2"].split("|")[1].split(",")[1],
                            "the rail should be under the main column at 600px")

    def test_the_facts_are_the_numbers_behind_the_classic_verdicts(self):
        """...minus "Lethal at", which printed effective HP a second time under a
        second name (fix list round 1 item 5 / round 2 item 6)."""
        kv = self.got["t.kv"]
        for row in ("Effective HP=30", "Took last fight=4", "Last 3 fights=−21",
                    "Damage cap=10",
                    "Board stats — you vs lobby avg=14 vs 19 (seen 1 round ago)",
                    "Level up=tier 3 → 4 for 7g"):
            self.assertIn(row, kv, f"missing facts row: {row}")
        self.assertNotIn("Lethal at", kv,
                         "the row that repeats effective HP is still there")
        self.assertIn("observational, not causal", self.got["t.notes"])

    def test_the_lobby_figure_is_named_as_an_average(self):
        """The estimate half of the same row: "~59 (lobby)" did not say WHAT
        about the lobby was being compared. `lobby_opp` is the analysis field
        the scout strip falls back to — `opp_lobby` is DERIVED from it in
        `render_json`, so setting that directly proves nothing."""
        got = _render([_shot("lb", _payload(opp_stats=None, lobby_opp=59))])
        self.assertIn("Board stats — you vs lobby avg=14 vs ~59 lobby avg",
                      got["lb.kv"])

    def test_a_value_nobody_read_is_a_dash(self):
        """§6.4. The fixture drops the fragility block and the level cost, so
        every row that depended on them is GONE rather than guessed, and the one
        row that always exists says so with a dash."""
        self.assertNotIn("Effective HP", self.got["notread.kv"])
        self.assertNotIn("Level up", self.got["notread.kv"])
        self.assertIn("Board stats — you vs lobby avg=—", self.got["notread.kv"])
        self.assertNotIn("?", self.got["notread.alltext"])

    def test_the_shop_before_it_parses_is_a_sentence_and_not_dash_bars(self):
        """Fix list round 2 item 2: the design's §6.1 asked for four dashed
        skeleton cards; the player's call replaces them, because they read as
        thick dash bars carrying nothing."""
        got = self.got
        self.assertEqual(got["noshop.skel"], 0, "the dash bars are still drawn")
        self.assertIn("Reading the shop. This updates when your next shop opens.",
                      got["noshop.notes"])
        self.assertEqual(got["noshop.taverncards"], 0)
        self.assertGreaterEqual(got["t.taverncards"], 2,
                                "a parsed shop renders its cards")

    def test_the_waiting_state_dashes_the_numbers_and_names_the_slot(self):
        """Fix list round 2 item 2: before the first shop of a game the status
        bar shows muted dashes, and the hero slot says what the page is waiting
        for instead of a dash with no noun."""
        got = _render([_shot("w", _payload(hero=None, gold=None, tier=None,
                                           health=None, scenario={},
                                           current_place=None))])
        self.assertEqual(got["w.hero"], "Waiting for the next shop to open")
        self.assertIn("waiting", got["w.herocls"])
        self.assertEqual(got["w.missvals"], 5, "every unread number is a dash")
        self.assertEqual(got["w.stats"],
                         "Gold:—|Tier:—|HP:—|Turn:—|Place:—")

    def test_the_empty_strip_at_the_top_is_hidden(self):
        """Fix list round 2 item 7: `#statebar` has a background and a radius, so
        blanking it left a rounded empty bar above the card. The classic live
        view is the one that fills it."""
        got = self.got
        self.assertEqual(got["t.statebarhidden"], 1,
                         "the tavern view draws its own status bar, so the "
                         "classic strip must not be there at all")
        self.assertEqual(got["classic.statebarhidden"], 0,
                         "the classic view needs the strip")
        # The welcome card is the one that leaves it empty.
        welcome = _render([_shot("wel", _welcome_payload(), viewer="classic")])
        self.assertEqual(welcome["wel.statebarhidden"], 1,
                         "an empty state strip is a rounded bar with nothing in "
                         "it")

    def test_board_and_hand_share_one_panel_side_by_side(self):
        """Fix list round 1 item 4 / round 2 item 4: the taverner's row on top,
        then one panel holding the board and the hand in two columns."""
        got = self.got
        self.assertEqual(got["t.bhlabels"], "Your board|Your hand")
        self.assertEqual(got["t.bhhalf"], 2)
        self.assertGreaterEqual(got["t.cards"], 3)

    def test_an_empty_board_or_hand_says_empty_inline(self):
        # The board is a list of ENTITIES now (round 3 item 1), so an empty
        # board is an empty `board` list — not an empty sell_rank.
        got = _render([_shot("e", _payload(board=[], sell_rank=[], hand=[]))])
        self.assertEqual(got["e.inline"], "empty|empty")

    def test_cards_carry_a_caption_below_them(self):
        self.assertTrue(self.got["t.caps"], "no captions rendered")
        self.assertIn("hand", self.got["t.caps"], "the hand row is captioned")
        self.assertIn("scaler", self.got["t.caps"],
                      "the board caption is the comp role, which is a fact "
                      "about membership")

    def test_the_comps_screen_counts_core_cards_owned(self):
        """§4.4's row: the name, the slots, `N of M owned`, the average
        placement. "Elementals" owns all three of its core cards because the
        third is IN HAND — the payload's classic `owned` flag is board-only."""
        row = self.got["comps.comprows"]
        self.assertIn("Elementals|3 of 3 owned|3.83", row)
        self.assertGreaterEqual(self.got["comps.slotshand"], 1,
                                "a hand core card is owned, and says so")
        self.assertIn("own game corpus", self.got["comps.notes"])

    def test_an_empty_comps_tab_says_why_rather_than_showing_nothing(self):
        self.assertIn("No comps read yet", self.got["nocomps.empty"])

    def test_the_lobby_tab_is_sightings_and_the_last_seen_board(self):
        got = self.got
        self.assertEqual(got["lobby.tabon"], "Lobby")
        self.assertIn("Beast=2 of 3 seen seats (2+ copies)", got["lobby.kv"])
        self.assertIn("as of round 8", got["lobby.opplabel"])

    def test_a_spell_is_tagged_rather_than_framed_differently(self):
        """Round 2 item 3: one art treatment for every card, and the one kind that
        is not a minion says so in a tag. `BG31_880` is a real tavern spell in the
        shipped DB, so the tag comes from the payload's own `tag` field rather
        than from anything this test invents."""
        got = self.got
        self.assertEqual(got["t.kinds"], "Spell",
                         "the spell in the shop row is not tagged")
        # Every card drawn the same way: art in the frame, name below it.
        self.assertGreaterEqual(got["t.noart"], 1)
        self.assertEqual(got["t.tnamewrap"], "normal",
                         "card names are still clamped to one line")

    def test_two_identical_offers_are_two_cards(self):
        """Round 3 item 1: the tavern is a list of ENTITIES. The row used to be
        built by keying the offers onto a card-keyed ranking, so a tavern
        offering the same minion twice drew ONE card. The pool chip is the
        CARD's number and is the same on both — it is not halved, and the two
        copies are not added up into it."""
        rep = _payload(shop_entities=[{"eid": 101, "card": "BG31_820"},
                                      {"eid": 102, "card": "BG31_820"},
                                      {"eid": 103, "card": "BG31_831"}],
                       shop_offers=["BG31_820", "BG31_820", "BG31_831"])
        self.assertEqual([r["eid"] for r in rep["shop_rank"]], [101, 102, 103])
        got = _render([_shot("dup", rep)])
        self.assertEqual(got["dup.taverncards"], 3,
                         "two identical offers did not render two cards")
        pools = got["dup.poolchips"].split("|")
        self.assertEqual(pools[0], pools[1],
                         "the two copies of one card report different pools")
        names = got["dup.shopkeys"].split("|")
        self.assertEqual(len(names), 3)
        self.assertEqual(names[0], names[1],
                         "the two copies of the duplicated offer are not the "
                         "same card")
        self.assertNotEqual(names[1], names[2])

    def test_two_identical_board_minions_are_two_cards(self):
        """The same dedupe lived in the board row: it drew the classic Sell row,
        which groups BY CARD ("×2"), so a board with two copies of one minion
        showed one card. `board_cards` is per entity — and the fallback for a
        payload recorded before it keeps the ×N badge."""
        rep = _payload(board=[{"card": "BG31_815", "atk": 5, "health": 5,
                               "tribe": "Beast", "eid": 11},
                              {"card": "BG31_815", "atk": 9, "health": 9,
                               "tribe": "Beast", "eid": 12}])
        self.assertEqual([r["eid"] for r in rep["board_cards"]], [11, 12])
        self.assertEqual(rep["board_cards"][1]["atk"], 9,
                         "the second copy is not its own entity")
        got = _render([_shot("dup", rep)])
        self.assertEqual(got["dup.boardcards"], 2)

    def test_the_classic_tavern_toggle_sits_on_the_nav_row(self):
        """Round 3 item 7: right-aligned on the nav row, and out of the way while
        Settle Up is open — that page has its own viewer toggle in its header."""
        got = self.got
        self.assertEqual(got["t.toggleinnav"], 1,
                         "the live viewer flag is not on the nav row")
        right, left = [int(v) for v in got["t.toggleright"].split(",")]
        self.assertLess(right, 60, f"the toggle is {right}px from the right edge")
        self.assertGreater(left, 200,
                           "the toggle is not pushed to the right of the nav")
        self.assertEqual(got["t.togglehidden"], 0)
        # ...and it is out of the way over there: switching to Settle Up hides
        # it, because that page has its own viewer toggle in its header.
        settle = _render([_shot("s", _payload(), settle=True)])
        self.assertEqual(settle["s.togglehidden"], 1,
                         "the live viewer flag is still on screen over Settle Up, "
                         "beside that page's own toggle")

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
                _shot("comps", _comps_payload(), tab="comps"),
                # §4.4's Detail and Compare are screens too, and the guide block
                # is prose from the meta DB: if a verdict can reach this view,
                # these are the two places it would.
                _shot("detail", _comps_payload(), tab="comps",
                      clicks=[_open("Elementals")]),
                _shot("compare", _comps_payload(), tab="comps",
                      clicks=[_compare("Elementals"), _compare("Beasts"),
                              _compare("Menagerie")]),
                # The pick screen too: it is the screen whose classic facts
                # carry the banned phrasing, so it is the one worth scanning.
                _shot("pick", _choice_payload()),
                # §6.5's card carries the app's own sentences — the coach line
                # and the sharing summary — so it is scanned too.
                _shot("over", _game_over_payload())]

    def test_no_verdict_vocabulary_reaches_the_screen(self):
        for name in ("t", "lobby", "comps", "detail", "compare", "pick", "over"):
            text = self.got[name + ".alltext"].lower()
            self.assertTrue(text, f"{name} rendered nothing to scan")
            for word in self.VERDICTS:
                self.assertNotIn(
                    word, text,
                    f"the Tavern live view says {word!r} — LIVE_VIEW_DESIGN.md §1 "
                    f"allows facts, counts and statistics, nothing else. Text: "
                    f"{self.got[name + '.alltext'][:200]}")

    def test_the_pick_screen_shows_the_game_order_and_never_a_ranking(self):
        """§4.3: "Order defaults to As offered. The screen never ranks for the
        player." The server returns the options score-ordered (row 0 is the pick
        the review grades), so rendering them as they arrive would hand the
        player the model's ranking."""
        got = _render([_shot("pick", _choice_payload()),
                       _shot("sorted", _choice_payload(), click="By picked %")])
        self.assertEqual(got["pick.pick"], 2, "both options rendered")
        self.assertEqual(got["pick.picknames"], "Ann|Zed",
                         "the game's offer order, not the score order")
        self.assertEqual(got["pick.pickctl"].count("As offered:on"), 1,
                         "As offered is the default and is shown as active")
        # The opt-in sort, clicked for real.
        self.assertEqual(got["sorted.picknames"], "Zed|Ann",
                         "clicking By picked % did not re-order")
        self.assertIn("By picked %:on", got["sorted.pickctl"])

    def test_the_pick_screen_reads_numbers_not_the_fact_string(self):
        """The rehearsal for §1, and the reason `option_stats` exists.

        The classic rows in this fixture say "fits your board" and "fits your
        comp direction" — phrasing the design bans. The Tavern screen must show
        the numbers those sentences were built from, and the sentences
        themselves must not be able to reach it.
        """
        got = _render([_shot("pick", _choice_payload())])
        text = got["pick.alltext"]
        for banned in ("fits your board", "fits my comp direction",
                       "fits your comp direction"):
            self.assertNotIn(banned, text)
        self.assertIn("Avg place=3.20", got["pick.pickrows"])
        self.assertIn("Top 4=62%", got["pick.pickrows"])
        # Game order again: Ann was offered first, so her 30.0% leads even though
        # Zed's 60.0% would win any ranking.
        self.assertEqual(got["pick.pickhead"], "30.0%|60.0%",
                         "the headline figures follow the option order, and carry "
                         "one decimal (fix list round 1 item 2)")
        self.assertEqual(got["pick.picklbl"], "Picked|Picked",
                         "the headline figure says what it is")
        self.assertIn("+15.0 vs offered avg", got["pick.pickvs"],
                      "the distance from the offered average, stated")
        self.assertEqual(got["pick.pickbars"], 8,
                         "the distribution is eight bars, one per placement")
        # The offered average itself is on the source line: the ± figure has to
        # be relative to something the player can see.
        self.assertIn("Offered average: 45.0% picked", got["pick.picknote"])

    def test_the_pick_screen_names_each_option_once(self):
        """Fix list round 1 item 2 / round 2 item 1: the tile's own caption is a
        second, width-clamped copy of the name, and the headline used to repeat
        the pick rate as a row as well."""
        got = self.got
        self.assertEqual(got["pick.renameless"], 0,
                         "the option's art still carries its own name caption")
        self.assertEqual(got["pick.picknames"], "Ann|Zed")
        self.assertNotIn("Picked in", got["pick.pickrows"],
                         "the pick rate is still repeated as a stat row")
        self.assertGreaterEqual(got["pick.tiletitles"], 2,
                                "the full name is not on the tile's title")

    def test_the_pick_columns_and_the_controls_are_sized_as_asked(self):
        """>=200px columns, a fixed-height name, the 130px art, and the controls
        on one row (fix list round 1 item 2 / round 2 item 1)."""
        got = self.got
        self.assertGreaterEqual(got["pick.pickcolw"], 200,
                                "an option column is narrower than 200px")
        self.assertGreaterEqual(got["pick.picknameh"], 30,
                                "the name line is not tall enough to hold two "
                                "lines at a fixed height")
        self.assertEqual(got["pick.pickcardw"], 130)
        # One row of controls: a wrapped row would be ~2x a single button.
        self.assertLess(got["pick.pickctlvp"], 60)

    def test_a_stats_shown_toggle_removes_that_row(self):
        """§4.3: "Stats shown lets the player toggle which rows appear (also how
        new fields get added later)." """
        got = _render([_shot("pick", _choice_payload(), click="top 4")])
        self.assertNotIn("Top 4=", got["pick.pickrows"])
        self.assertIn("Avg place=3.20", got["pick.pickrows"])
        self.assertIn("top 4:off", got["pick.pickctl"])

    def test_no_option_without_data_invents_a_row(self):
        """§6.2/§5: an option the DBs have nothing for says so, and shows no
        rows — rather than a zero or a guess."""
        rep = _payload(choice={"kind": "hero", "source": "Choose One",
                               "ranked": [["Nobody", "BG31_999", 0.0, "", 0]],
                               "option_stats": {}, "guides": {}})
        got = _render([_shot("bare", rep)])
        self.assertIn("No data for this card on this patch yet.",
                      got["bare.alltext"])
        self.assertEqual(got["bare.pickrows"], "")
        self.assertEqual(got["bare.pickbars"], 0)


class TestTheCompsScreens(_Rendered):
    """§4.4 Browse, Detail and Compare, drawn and measured in the browser.

    What a source assertion cannot see is here: which tier columns exist, how
    many rows each holds before the cap, that the mini-card slots are the
    design's 34x46 (not the tile's 104px box), that the core row's cards are
    88x120 and the flex row's 76x100, and that a control actually re-orders or
    filters the list when it is clicked.
    """

    @classmethod
    def shots(cls):
        base = _comps_payload()
        return [_shot("browse", base, tab="comps"),
                _shot("overlap", base, tab="comps",
                      clicks=[[".lv-ctl .lv-chip", "Overlap"]]),
                _shot("more", base, tab="comps", clicks=[[".lv-more", "+ 1 more"]]),
                _shot("noavg", _comps_payload(corpus={}), tab="comps"),
                _shot("detecting", _comps_payload(tribes_detecting=True),
                      tab="comps"),
                _shot("detail", base, tab="comps",
                      clicks=[_open("Elementals")]),
                _shot("back", base, tab="comps",
                      clicks=[_open("Elementals"), [".lv-back", "◀ Comps"]]),
                _shot("compare", base, tab="comps",
                      clicks=[_compare("Elementals"), _compare("Beasts"),
                              _compare("Menagerie")]),
                _shot("four", base, tab="comps",
                      clicks=[_compare("Elementals"), _compare("Aardvark"),
                              _compare("Beasts"), _compare("Menagerie"),
                              _compare("Filler 1")])]

    def test_browse_is_one_column_per_source_tier_with_a_cap(self):
        got = self.got
        self.assertEqual(got["browse.comptiers"], "S tier · 2|A tier · 7")
        # The S column: both comps, the payload's tier-then-name order.
        self.assertTrue(got["browse.comprows"].startswith(
            "Elementals|3 of 3 owned|3.83 ; Menagerie|1 of 2 owned|—"),
            got["browse.comprows"])
        # ~6 rows per tier, then the count of what is left (round 3 item 3).
        self.assertEqual(got["browse.more"], "+ 1 more")
        self.assertEqual(got["browse.more"].count("+ "), 1)
        # The cap is per column, so the S column is not capped away too.
        self.assertIn("Elementals", got["browse.comprows"])

    def test_the_more_control_opens_the_rest_of_the_column(self):
        got = self.got
        self.assertIn("Filler 5", got["more.comprows"])
        self.assertEqual(got["more.more"], "",
                         "nothing left to expand once it is open")

    def test_the_comps_columns_are_never_three_wide(self):
        """Round 3 item 3: single column with sticky headers, two only when each
        holds 520px, never three. The cap is `max-width:calc(50% - 9px)` — a
        viewport media query cannot express it, because the main column is the
        window MINUS the rail above 1200px."""
        got = self.got
        widths = [int(w) for w in got["browse.colw"].split("|")]
        self.assertLessEqual(got["browse.cols"], 2,
                             f"{got['browse.cols']} comps columns on screen")
        for w in widths:
            self.assertGreaterEqual(w, 520, f"a column is only {w}px")
        self.assertEqual(got["browse.h4pos"], "sticky",
                         "the tier headers do not stick")
        # A window wide enough for two 520px columns puts them side by side, and
        # NEVER a third: eight columns would fit at this width if it were
        # allowed to.
        wide = _render([_shot("w", _comps_payload(), tab="comps")],
                       size=(2600, 1200))
        self.assertEqual(wide["w.cols"], 2,
                         "a 2600px window showed more or fewer than two columns")
        xs = [int(x) for x in wide["w.colx"].split("|")]
        self.assertEqual(len(set(xs)), 2, "the two columns are stacked")
        for w in [int(v) for v in wide["w.colw"].split("|")]:
            self.assertGreaterEqual(w, 520)

    def test_the_avg_column_is_hidden_until_the_corpus_has_data(self):
        """Round 3 item 5: a column of dashes is a column of nothing."""
        got = self.got
        self.assertGreater(got["browse.avgcells"], 0,
                           "the fixture has corpus data, so the column is there")
        self.assertEqual(got["browse.hasavg"], got["browse.cols"])
        self.assertEqual(got["noavg.avgcells"], 0,
                         "a dash per row is printed where the corpus is empty")
        self.assertEqual(got["noavg.hasavg"], 0)
        self.assertIn("Elementals|3 of 3 owned", got["noavg.comprows"])
        # Three tracks instead of four: the avg column is gone, not empty.
        self.assertEqual(len(got["noavg.cmptracks"].split()), 3,
                         got["noavg.cmptracks"])

    def test_the_comps_panel_has_no_second_tribe_chip_row(self):
        """Round 3 item 4: the page has ONE tribe row, above the tabs, and the
        comps panel had a copy of it. The not-confirmed state is said once, in
        the panel header, instead of on every row."""
        got = self.got
        self.assertEqual(got["browse.ctlchips"],
                         "Source tier|Overlap|Avg placement",
                         "the comps controls are not just the sort chips")
        self.assertNotIn("Lobby tribes", got["browse.paneltext"],
                         "the comps panel has its own tribe chip row again")
        self.assertEqual(got["browse.unconfirmed"], 0,
                         "a row still carries the unconfirmed note")
        # The harness strips values, so the leading space of the header note is
        # not part of what comes back.
        self.assertEqual(got["detecting.hnote"], "· tribes not confirmed yet")
        self.assertEqual(got["detecting.unconfirmed"], 0)
        # ...and one chip row for the tribes, on the page itself.
        self.assertIn("BEAST", got["detecting.chips"])

    def test_a_comp_row_is_a_grid_with_the_strip_and_the_name_in_it(self):
        """Round 3 item 2: `minmax(0,1fr) auto 64px 90px`, a nowrap 34x46 strip,
        a name clamped to two lines, and nothing positioned over the name."""
        got = self.got
        tracks = got["browse.cmptracks"].split()
        self.assertEqual(len(tracks), 4, got["browse.cmptracks"])
        self.assertIn("64px", tracks)
        self.assertIn("90px", tracks)
        self.assertEqual(got["browse.stripwrap"], "nowrap",
                         "the core strip still wraps")
        self.assertEqual(got["browse.slotflex"], "0 0 auto",
                         "a slot can still be squeezed by the strip")
        self.assertEqual(got["browse.nameclamp"], "2",
                         "the comp name is not clamped to two lines")
        self.assertEqual(got["browse.slotpx"], "34x46")
        # The compare box sits at the START of the row, in flow: the name is to
        # its right, so nothing is over anything.
        withbox = _render([_shot("wb", _comps_payload(), tab="comps",
                                 clicks=[[".lv-cmpbox", None, "Beasts"]])])
        self.assertEqual(withbox["wb.cmpchecked"], 1)
        self.assertEqual(withbox["wb.rowcols"], "grid")

    def test_the_compare_box_and_the_comp_name_are_themed(self):
        """Round 3 item 6: a themed checkbox, and names underlined on hover
        only — a column of permanent underlines read as a wall of links."""
        got = self.got
        self.assertIn("none", got["browse.cmpskin"],
                      "the checkbox is still the browser's default control")
        self.assertEqual(got["browse.nameunder"], "none",
                         "every comp name wears an underline")
        hovered = _render([_shot("h", _comps_payload(), tab="comps",
                                 clicks=[[".lv-ctl .lv-chip", "Overlap"]])])
        self.assertEqual(hovered["h.nameunder"], "none")

    def test_the_sort_control_reorders_within_a_tier(self):
        """The default is the source's own tier order; sorting by overlap or by
        average placement is opt-in, the same rule the pick screen follows."""
        self.assertTrue(self.got["browse.comprows"].split(" ; ")[2]
                        .startswith("Aardvark|0 of 1 owned"),
                        "default order is the source's, name after tier")
        self.assertTrue(self.got["overlap.comprows"].split(" ; ")[2]
                        .startswith("Beasts|2 of 2 owned"),
                        "by overlap, the comp whose core you hold most of leads")
        # Both orders keep the two S comps in the S column: sorting never
        # rearranges the columns, which are the source's labels.
        for name in ("browse", "overlap"):
            self.assertTrue(self.got[name + ".comptiers"].startswith("S tier"))

    def test_the_average_placement_sort_puts_the_best_average_first(self):
        """Opt-in, and stated as the player's choice — the screens never rank on
        their own. Aardvark averages 2.00, Beasts 4.00, and the comps nobody has
        played sort last rather than at zero."""
        got = _render([_shot("avg", _comps_payload(), tab="comps",
                             clicks=[[".lv-ctl .lv-chip", "Avg placement"]])])
        rows = got["avg.comprows"].split(" ; ")[2:]
        self.assertTrue(rows[0].startswith("Aardvark|0 of 1 owned|2.00"), rows[0])
        self.assertTrue(rows[1].startswith("Beasts|2 of 2 owned|4.00"), rows[1])
        self.assertTrue(rows[2].endswith("|—"), rows[2])

    def test_the_out_of_play_comp_is_hidden_and_that_is_stated(self):
        """§4.4: "Comps for out-of-play tribes are hidden." Naga is rotated this
        patch, so the Nagas comp cannot be built at all — and the screen says one
        is missing rather than silently shortening the list."""
        got = self.got
        self.assertNotIn("Nagas", got["browse.comprows"])
        self.assertIn("1 comp hidden: their tribe is out of play this patch.",
                      got["browse.notes"])

    def test_the_core_slots_are_the_designs_34_by_46(self):
        """§5 sizes the Browse slot at 34x46 and the Compare slot at 52x70. A
        tile is 88-130px wide, so a slot that inherits the card rule would be
        more than twice the specified size."""
        self.assertEqual(self.got["browse.slotpx"], "34x46")
        self.assertEqual(self.got["compare.cmpslotpx"], "52x70")
        # Owned, in-hand and missing are three states, and the missing one is
        # dashed rather than a smaller solid box.
        self.assertGreaterEqual(self.got["browse.compslots"], 10)
        self.assertGreaterEqual(self.got["browse.slotsmiss"], 1)

    def test_a_slot_carries_the_cards_art_and_a_legend_explains_the_colours(self):
        """Fix list round 1 item 6: a row of coloured rectangles said nothing
        about WHICH core cards a comp wants, so the slot shows the card's own art
        (dimmed when you do not own it) — and a legend says what the colours mean,
        drawn from the slot element itself."""
        got = self.got
        self.assertGreaterEqual(got["browse.slotart"], 10,
                                "the slots have no art in them")
        self.assertEqual(got["browse.legend"],
                         "on board|in hand|not owned|banned this game")
        self.assertEqual(got["browse.legendslots"], 4,
                         "the legend swatches are not the slot element")
        # The in-hand slot is still distinguishable, and a missing one is dimmed
        # rather than hidden.
        self.assertGreaterEqual(got["browse.slotshand"], 1)

    def test_compare_is_a_checkbox_and_the_rows_are_a_grid(self):
        """Fix list round 1 item 6: "compare as a checkbox", and rows that line up
        (a flex row with `margin-left:auto` could not promise the same x for the
        owned count down a column)."""
        got = self.got
        # Eight visible rows: two S + the six the A column shows before its cap.
        self.assertEqual(got["browse.cmpboxes"], 8,
                         "one compare box per visible row")
        self.assertEqual(got["browse.cmpchecked"], 0)
        self.assertEqual(got["compare.cmpchecked"], 3,
                         "the three ticked rows are not ticked")
        self.assertEqual(got["four.cmpchecked"], 3,
                         "a fourth tick was accepted")
        self.assertGreaterEqual(got["four.cmpdisabled"], 1,
                                "the remaining boxes are not disabled with a "
                                "reason")
        self.assertEqual(got["browse.rowcols"], "grid")

    def test_the_board_caption_reads_out_of_play_not_cant_grow(self):
        """Fix list round 1 item 7 / round 2 item 5, and the reason the payload
        carries the tribe: the value pass's own string ("banned tribe — can't
        grow") is what the CLASSIC Sell box shows and what its test pins, so the
        tavern caption is built from data instead."""
        got = _render([_shot("ban", _payload(
            board=[{"card": "BG31_815", "atk": 5, "health": 5,
                    "tribe": "BEAST"},
                   {"card": "BG31_820", "atk": 2, "health": 2,
                    "tribe": "ELEMENTAL"}],
            banned=["Beast"], bans_manual=True))])
        self.assertIn("Beast — out of play", got["ban.caps"])
        self.assertNotIn("can't grow", got["ban.alltext"])
        self.assertNotIn("banned tribe", got["ban.alltext"])

    def test_detail_draws_the_core_row_and_the_flex_row_at_their_sizes(self):
        """The design's WIDTHS are the contract (88 core, 76 flex). The HEIGHT
        stopped being a fixed number on 2026-10-09: one card component
        everywhere means the name and caption sit BELOW the art in flow, so
        the tile is the art's ratio plus its own text — taller than the art
        alone, and no longer a box with a strip printed over it."""
        got = self.got
        self.assertEqual(got["detail.detail"], "Elementals")
        self.assertEqual(got["detail.detailchips"], "S tier|ELEMENTAL|Easy")
        core_w, core_h = got["detail.corepx"].split("x")
        flex_w, flex_h = got["detail.flexpx"].split("x")
        self.assertEqual(core_w, "88", f"core row: {got['detail.corepx']}")
        self.assertEqual(flex_w, "76", f"flex row: {got['detail.flexpx']}")
        # The art alone would be 88x116 and 76x100 (the design's ratios). The
        # name row is what pushes the tile past it — if this ever reads equal,
        # the name is back ON the art.
        self.assertGreater(int(core_h), 116,
                           f"core card is art-only: {got['detail.corepx']}")
        self.assertGreater(int(flex_h), 100,
                           f"flex card is art-only: {got['detail.flexpx']}")
        # §8: nothing is communicated by colour alone — every core card carries
        # its own state as a caption.
        self.assertIn("on board", got["detail.caps"])
        self.assertIn("in hand", got["detail.caps"])
        self.assertIn("not owned", got["detail.caps"])

    def test_detail_shows_the_statistics_and_a_collapsed_guide(self):
        """§4.4 Detail: "headline stat, distribution, stat rows, and
        `Guide text ▸` collapsed by default." """
        got = self.got
        self.assertEqual(got["detail.stathead"], "3.83")
        self.assertIn("Games=12", got["detail.statrows"])
        self.assertIn("Top 4=67%", got["detail.statrows"])
        self.assertIn("1st place=17%", got["detail.statrows"])
        self.assertEqual(got["detail.guideopen"], 0, "the guide starts collapsed")
        self.assertEqual(got["detail.guidesum"], "Guide text")
        # §5: every stat block carries a source line — the dataset, and the
        # "observational, not causal" note. The patch is the one field the
        # corpus cannot state, and the block says so instead of guessing (§6.3).
        self.assertIn("observational, not causal", got["detail.notes"])
        self.assertIn("no per-game patch recorded", got["detail.notes"])

    def test_the_back_link_returns_to_browse(self):
        got = self.got
        self.assertEqual(got["back.detail"], "")
        self.assertEqual(got["back.comptiers"], "S tier · 2|A tier · 7")

    def test_compare_shows_the_same_statistics_in_the_same_order(self):
        """§4.4: "Up to three comps ... Same stats, same order, no ranking." The
        columns are in the order the player picked them."""
        got = self.got
        self.assertEqual(got["compare.cmpcols"],
                         "Elementals|Beasts|Menagerie")
        cols = got["compare.cmpstats"].split(" ~ ")
        self.assertEqual(len(cols), 3)
        labels = [c.split("#")[0] for c in cols]
        self.assertEqual(labels[0], labels[1],
                         "the same stat rows, in the same order, per column")
        self.assertEqual(cols[0].split("#")[1], "3.83")
        self.assertEqual(cols[1].split("#")[1], "4.00")
        self.assertEqual(cols[2].split("#")[1], "",
                         "a comp with no corpus record has no headline number")

    def test_compare_holds_three_and_says_so_at_the_fourth(self):
        got = self.got
        self.assertEqual(got["four.cmpcols"], "Elementals|Aardvark|Beasts",
                         "the fourth comp is refused, not silently swapped in")

    def test_the_comps_screens_get_the_main_column(self):
        """The design's §4.4 columns need the main column, not the 340px rail —
        and round 3 item 3 re-cut how many of them there are (see
        `test_the_comps_columns_are_never_three_wide`)."""
        got = self.got
        self.assertGreater(got["browse.panelw"], 600,
                           "the comps screens need the main column: a 340px rail "
                           "cannot hold one 520px column, let alone two")
        self.assertGreaterEqual(len(got["browse.colat"].split("|")), 2,
                                "no tier columns rendered")

    def test_a_low_sample_comp_is_flagged_by_games_count(self):
        """§5: "Low sample marker ... Define the threshold by games count, not a
        fixed percent." Beasts has 4 games, Elementals 12, and only one of them
        is flagged — with a chip, not only with the dimming."""
        got = self.got
        self.assertIn("Beasts|2 of 2 owned|4.00|low", got["browse.comprows"])
        self.assertNotIn("Elementals|3 of 3 owned|3.83|low",
                         got["browse.comprows"])
        self.assertEqual(got["browse.lowsamp"], "low sample")


class TestTheGameOverCard(_Rendered):
    """§6.5, and the reachability bug behind it.

    The end-of-game card arrives on a `welcome: true` payload with no board, and
    `render` returned at the welcome branch BEFORE the viewer was consulted — so
    the Tavern game-over card could not be reached in a real session at all, while
    a direct `renderLiveTavern` call in a test made it look alive. These shots go
    through `render`, so the route is part of what is measured.
    """

    @classmethod
    def shots(cls):
        return [_shot("over", _game_over_payload()),
                _shot("auto", _game_over_payload(enabled=True)),
                _shot("classic", _game_over_payload(), viewer="classic"),
                # A tavern render, then the game-over payload: the card, not the
                # last shop screen still standing behind it.
                _shot("after", _game_over_payload(), pre=_comps_payload(),
                      pretab="comps", preclicks=[_open("Elementals")]),
                _shot("firstrun", _welcome_payload(), viewer="tavern")]

    def test_the_card_is_the_placement_and_the_round(self):
        got = self.got
        self.assertEqual(got["over.tavern"], 1)
        self.assertEqual(got["over.overlabel"], "Game over",
                         "the big line has no label (fix list round 1 item 8)")
        self.assertEqual(got["over.overbig"], "3rd · Round 12")
        self.assertEqual(got["over.gobtn"], "Open in Settle Up")

    def test_the_sharing_counter_follows_the_game(self):
        """Fix list round 1 item 8: the summary says how many games have been
        shared, so it has to move with the game. A card that keeps the previous
        game's count is exactly the kind of stale number this project treats as a
        bug — and the count is real here: `share_status()` is what
        `welcome_payload` reads, replaced per payload as the machine's own
        answer would be."""
        first = _game_over_payload(sent=3)
        second = _game_over_payload(sent=4)
        self.assertIn("(3 shared so far)", first["privacy"])
        got = _render([_shot("g1", first), _shot("g2", second)])
        self.assertIn("3 shared so far", got["g1.fine"])
        self.assertIn("4 shared so far", got["g2.fine"],
                      "the card kept the previous game's count")

    def test_the_auto_save_answer_and_its_control_share_one_row(self):
        """§6.5: "Merge `Saved to the Settle Up tab automatically ✓` and the
        `Save every replay automatically` checkbox into one row." """
        got = self.got
        self.assertEqual(got["auto.saverows"], 1)
        self.assertEqual(got["auto.checkboxin"], 1,
                         "the checkbox is not inside the save row")
        self.assertIn("Save every replay automatically", got["auto.saverowtext"])
        self.assertEqual(got["auto.saved"],
                         "Saved to the Settle Up tab automatically ✓")
        # With the answer OFF the row offers the click instead, and still one row.
        self.assertEqual(got["over.saverows"], 1)
        self.assertIn("Save replay", got["over.saverowtext"])
        self.assertEqual(got["over.saved"], "")

    def test_the_card_keeps_the_coach_line_and_the_sharing_summary(self):
        """§6.5: "Keep the line that the coach is still running ... Keep the
        sharing summary as small secondary text." The summary's WORDING depends
        on this machine's sharing answer, so it is compared with the payload's
        own sentence rather than with a phrase from one branch."""
        rep = _game_over_payload()
        got = _render([_shot("over", rep)])
        self.assertIn("still running", got["over.notes"])
        self.assertIn(rep["privacy"], got["over.notes"],
                      "the sharing summary is not on the card")

    def test_the_render_route_reaches_the_tavern_card(self):
        """The bug this class exists for."""
        got = self.got
        self.assertEqual(got["after.tavern"], 1)
        self.assertEqual(got["after.overbig"], "3rd · Round 12")
        self.assertEqual(got["after.tavernon"], 1)
        self.assertEqual(got["after.decidehidden"], 1,
                         "the classic pane is not hidden behind the card")

    def test_classic_still_shows_the_classic_game_over_card(self):
        got = self.got
        self.assertEqual(got["classic.tavern"], 0,
                         "the tavern layout survived a Classic render")
        self.assertGreaterEqual(got["classic.decidekids"], 1,
                                "the classic game-over card did not draw")

    def test_a_first_run_card_is_classic_and_clears_the_tavern_layout(self):
        """The other half of the same bug: a first-run welcome has no Tavern
        design, so it draws the classic card — but the Tavern container kept its
        last frame and `tavern-on` kept the panes hidden, so the card appeared
        behind a stale Tavern screen."""
        got = self.got
        self.assertEqual(got["firstrun.tavern"], 0)
        self.assertEqual(got["firstrun.tavernon"], 0)
        self.assertEqual(got["firstrun.decidehidden"], 0)
        self.assertGreater(got["firstrun.classic"], 0,
                           "the classic welcome card is not on screen")


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
