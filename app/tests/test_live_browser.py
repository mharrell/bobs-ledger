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
        # The tribe state, in the DIRECTION 2026-10-13 fixed: the five the
        # player taps ARE the tribes in the tavern, `tribes_available` is what
        # the row marks amber, and `banned` is the derived complement within
        # this patch's pool (Naga is out of play, so it is in neither list).
        # The fixture's own casing (uppercase, as the log tags tribes) is kept:
        # the point here is the marking, not the canon.
        "tribe_roster": ["BEAST", "DEMON", "ELEMENTAL", "MECH", "UNDEAD",
                         "PIRATE", "NAGA"],
        "out_of_pool": ["NAGA"],
        "tribes_available": ["BEAST", "ELEMENTAL", "MECH", "PIRATE", "UNDEAD"],
        "banned": ["DEMON"], "bans_manual": True, "tribes_seen": 5,
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


#: The lobby's five for the item-B fixtures. Deliberately NOT the fixture's own
#: `tribes_available`: the point of these shots is what happens to a comp whose
#: tribe the lobby has CONFIRMED and does not offer (Mech, here), which needs a
#: five that leaves one of the fixture's tribes out.
_FIVE_TRIBES = ["BEAST", "ELEMENTAL", "PIRATE", "UNDEAD", "DRAGON"]


def _comps_marked(available=None, **over):
    """The comps payload with `_tribe_available` set the way the PRODUCER sets it.

    `live_coach.comps_marked` marks every row with
    `LiveCoach.tribe_available(comp, available_tribes())`, and item B.1's main
    list is exactly the rows that mark keeps. The static method is CALLED here
    rather than re-implemented: a second copy of the rule would go stale the
    moment the producer's changed, and this fixture would then be testing the
    copy instead of the page.
    """
    import live_coach
    names = available if available is not None else _analysis()["tribes_available"]
    avail = {live_coach.normalize(t) for t in names}
    if "game_comps" not in over:
        over["game_comps"] = {
            k: dict(v, _tribe_available=live_coach.LiveCoach.tribe_available(
                v, avail))
            for k, v in _comps_analysis()["game_comps"].items()}
    return _comps_payload(**over)


def _comps_after_bans(**over):
    """THE DONE-WHEN CASE for item B.1: five tribes confirmed.

    The fixture's comps then split three ways — Elemental and Beast are in this
    lobby, Mech is BANNED this game, Naga is out of play this patch — and Mixed
    (Menagerie) is always buildable. So the main list must be the confirmed
    tribes plus Mixed, the Naga comp must be in the collapsed block, and the
    note must count the rows that are in neither.
    """
    over.setdefault("tribes_available", list(_FIVE_TRIBES))
    over.setdefault("tribes_seen", 5)
    return _comps_marked(available=_FIVE_TRIBES, **over)


def _comps_without_beast(**over):
    """Five tribes confirmed, BEAST NOT among them.

    The mirror of `_comps_after_bans`: the Beasts comp has to leave the main list,
    which is the change the view-state re-cut exists for — a compare box ticked on
    it would otherwise keep a Compare column alive for a comp the player can no
    longer see.
    """
    five = [t for t in _FIVE_TRIBES if t != "BEAST"] + ["MECH"]
    over.setdefault("tribes_available", list(five))
    over.setdefault("tribes_seen", 5)
    return _comps_marked(available=five, **over)


def _comps_with_long_names(**over):
    """The comps fixture with the real DB's long names in it.

    Item B.2's row has to survive a name that does not fit one line: it clamps to
    two, the tribe moves down with it, and the strip and the owned count stay in
    their own tracks. The names are the shipped ones (`meta/comps.json`), so the
    length is the length the page will really meet.
    """
    import meta
    long_names = [c["name"] for c in meta.comps().values()
                  if isinstance(c, dict) and len(c.get("name") or "") >= 22][:2]
    comps = {k: dict(v) for k, v in _comps_analysis()["game_comps"].items()}
    for i, name in enumerate(long_names):
        comps["long%d" % i] = {"name": name, "meta_tier": "S", "tribe": "BEAST",
                               "core": ["BG31_815", "BG31_820"],
                               "addons": []}
    return _comps_payload(game_comps=comps, **over)


#: A FOUR-option hero pick: the shape the wide mock draws (one row of four), and#: the only kind whose options carry a SUBLINE — `choices.option_stats` reads the
#: hero power by name. The options come from the SHIPPED hero DB, so the subline
#: is real text rather than a fixture's idea of one, and the fourth has no data
#: at all: that is the design's "No data" card (§6.2) with a card of its own.
def _hero_pick_payload():
    import meta
    names = [h["name"] for h in meta.heroes()
             if h.get("pick_rate") is not None and h.get("hero_power")]
    ranked = [[n, "HERO%d" % i, 0.0, "", i] for i, n in enumerate(names[:3])]
    ranked.append(["Nobody At All", "HERO_NONE", 0.0, "", 3])
    return _payload(choice={"kind": "hero", "source": "Choose One",
                            "ranked": ranked})


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
    """A FIRST-RUN welcome: no game over, so the shell card."""
    import json
    import replay_store
    saved = replay_store.auto_save_enabled
    replay_store.auto_save_enabled = lambda: False
    try:
        body = coach_ui.welcome_payload()
    finally:
        replay_store.auto_save_enabled = saved
    return json.loads(body)


#: The driver: run the REAL render(), report what is on screen. It is defensive
#: the same way the Settle Up driver is — a renderer that throws has to SAY so,
#: or a passing case proves nothing.
#:
#: It used to set the viewer first (`_liveViewer = s.viewer || 'tavern'`) because
#: two renderers existed behind that flag. There is one live page now, and each
#: shot's `viewer=` argument is GONE rather than left as a dead parameter.
_DRIVER = r"""
<pre id="out">pending</pre>
<script>
(function () {
  const recs = [];
  const rec = (k, v) => recs.push(k + '=' + String(v));
  const SHOTS = __SHOTS__;
  const txt = el => el ? el.textContent : '';
  // WHICH ARRANGEMENT IS ON SCREEN (fix list round 4 item 5): both are built,
  // because the width that decides is a CONTAINER query and JS cannot read its
  // answer — so this ASKS THE LAYOUT instead. The sheet leaves exactly one of the
  // two displayed, and a displayed grid has a width while a `display:none` one
  // measures 0, so the wider box is the one on screen. Nothing anywhere in this
  // driver forces a display: the widths measured have to be the ones the real
  // page produces, and an inline override would measure a layout the player never
  // sees. `shot()` needs the same answer as `facts()` — a page-wide search for a
  // section called "Comps" finds the HIDDEN one first — so it is one function.
  function shownArrangement() {
    const boxes = [...document.querySelectorAll('.tavern.live .lv-main')];
    let best = null;
    boxes.forEach(b => {
      if (!best
          || b.getBoundingClientRect().width > best.getBoundingClientRect().width) {
        best = b;
      }
    });
    return best;
  }
  //: A panel by the TITLE in its heading (the text node — the one-line summary
  //: lives in a span beside it), inside the arrangement on screen. The
  //: end-of-game card has no arrangements, so a page-wide fallback covers it.
  //:
  //: THE FALLBACK IS FOR THE PICK STRIP (2026-10-14): `lvBody` puts the pick
  //: screen ABOVE both arrangements, so it is in neither and a scope-only search
  //: finds nothing. The order matters — the shown arrangement FIRST, then the
  //: document — because a page-wide search would find the hidden arrangement's
  //: "Comps" before the visible one.
  function sectionPanel(want) {
    const inRoot = root => {
      if (!root) return null;
      return [...root.querySelectorAll('.lv-pn')].find(x => {
        const hd = x.querySelector('h3');
        if (!hd) return false;
        let t = '';
        hd.childNodes.forEach(n => {
          if (n.nodeType === 3) t += n.textContent;
        });
        return t.trim() === want;
      });
    };
    const scope = shownArrangement();
    return inRoot(scope) || (scope ? inRoot(document) : null);
  }
  //: THE PICK STRIP, by name, from the ROOT (2026-10-14): it is a sibling of
  //: both arrangements rather than a section of one, so every pick read has to
  //: come from outside `scope`. It is built ONCE — `lvBody` appends it above
  //: both — so there is no hidden copy to double-count, unlike the sections.
  function pickStrip() {
    const root = document.querySelector('.tavern.live');
    return root ? root.querySelector('.lv-pickstrip') : null;
  }
  function facts(name) {
    const root = document.querySelector('.tavern.live');
    const body = root ? root.querySelector('.lv-body') : null;
    // The end-of-game CARD has no arrangements at all — one centred panel and its
    // own entry point (`renderTavernGameOver`) — so there the root IS the scope.
    const scope = shownArrangement() || root;
    const arr = !body ? (root ? 'card' : '')
              : (scope && scope.classList.contains('lv-layout-cols') ? 'cols'
                 : 'acc');
    const q = s => scope ? scope.querySelectorAll(s) : [];
    const one = s => scope ? scope.querySelector(s) : null;
    // The page chrome ABOVE the arrangements — the status bar and the tribe row
    // — is on the root, not inside either arrangement (round 4 item 5).
    const rq = s => root ? root.querySelectorAll(s) : [];
    const rone = s => root ? root.querySelector(s) : null;
    // A root-wide read that skips the HIDDEN arrangement: the chrome above the
    // arrangements has to be read from the root, and a page-wide `.lv-chip`
    // would count the comps panel's controls twice (both arrangements build
    // them). `offsetParent` is null for the arrangement the container query has
    // turned off.
    const live = n => !!n.offsetParent;
    const all = s => [...rq(s)].filter(live);
    const o = {};
    o.tavern = root ? 1 : 0;
    o.arr = arr;
    o.bodyw = body ? Math.round(body.getBoundingClientRect().width) : 0;
    // THE VIEWPORT, which is what the layout's window rule actually reads. A
    // harness `size` is the browser WINDOW, and the viewport is ~16px narrower
    // (measured: a 1920x1080 window here gives 1904). A test that pinned the
    // arrangement at an exact window size would be asserting which side of a
    // breakpoint the window chrome falls on; a test that reads this cannot be.
    o.vw = window.innerWidth;
    // THE LAYOUT VIEWPORT: the width the page's boxes can actually occupy, with
    // the scrollbar already excluded. `vw` above does NOT exclude it, and the
    // distance between the two is the HOST's, not the page's — measured
    // 2026-10-15, it is 31px on Windows (a 16px window-chrome inset plus a
    // classic 15px scrollbar) and 0 on macOS, whose overlay scrollbars are free.
    // A box width read against `vw` was therefore partly a measurement of the
    // machine the suite happened to run on; read against this it is the page.
    o.docw = document.documentElement.clientWidth;
    o.hero = txt(rone('.lv-hero'));
    o.stats = all('.lv-st')
      .map(d => txt(d.querySelector('small')) + ':' + txt(d.querySelector('b')))
      .join('|');
    o.chips = all('.lv-chip').map(c => c.textContent).join('|');
    o.outchips = all('.lv-chip.out').map(c => c.textContent).join('|');
    // The tab row is GONE (round 4 item 5) and `lv-tabs` has no element to
    // count — so these two read what replaced it. `tabh` stays a measurement of
    // a real control: the accordion header, which is the tab row's successor.
    o.tabs = q('.lv-tabs button').length;
    o.tabon = txt(one('.lv-tabs button.on'));
    o.tabh = (function () {
      const h = one('.lv-acc > h3');
      return h ? Math.round(h.getBoundingClientRect().height) : 0;
    })();
    // The panel names, from the h3's own TITLE only: the header carries the
    // one-line summary in a span beside it (`lv-sum`), and reading the whole h3
    // would fold the summary into the panel name every test here pins.
    const title = h => {
      let s = '';
      h.childNodes.forEach(n => {
        if (n.nodeType === 3) s += n.textContent;
      });
      return s.trim();
    };
    const secs = [...q('.lv-pn')];
    const head = p => p.querySelector('h3');
    o.panels = secs.filter(head).map(p => title(head(p))).join('|');
    o.panelcount = secs.length;
    o.sums = secs.map(p => txt(p.querySelector('.lv-sum'))).join('|');
    o.shut = secs.filter(p => p.classList.contains('shut'))
      .map(p => title(head(p))).join('|');
    o.accs = q('.lv-acc').length;
    // Whether the Facts panel is the pinned strip, and where it sits.
    o.factspin = (function () {
      const p = one('.lv-pin');
      return p ? getComputedStyle(p).position : '';
    })();
    o.factsat = (function () {
      const p = one('.lv-pin');
      if (!p) return '';
      const r = p.getBoundingClientRect();
      return Math.round(r.left) + ',' + Math.round(r.top);
    })();
    // THE PIN, MEASURED (item 5): scroll the page and see which offsets move.
    // `window.scrollTo` needs a document taller than the window, which is why
    // the two ends of this are compared rather than any one of them asserted.
    o.scroll = (function () {
      const p = one('.lv-pin');
      const first = one('.lv-pn');
      if (!p || !first) return '';
      const before = [Math.round(first.getBoundingClientRect().top),
                      Math.round(p.getBoundingClientRect().top)];
      window.scrollTo(0, 300);
      const after = [Math.round(first.getBoundingClientRect().top),
                     Math.round(p.getBoundingClientRect().top)];
      window.scrollTo(0, 0);
      // A COMMA, not an arrow: the harness reads these back as `key=value`
      // pairs, and every value has to be one token.
      return before.join('/') + ',' + after.join('/');
    })();
    // The three columns of the three-column arrangement, in order.
    o.colw = (function () {
      if (arr !== 'cols') return '';
      return [...scope.querySelectorAll('.lv-col')]
        .map(c => Math.round(c.getBoundingClientRect().width)).join('|');
    })();
    o.colx = (function () {
      if (arr !== 'cols') return '';
      return [...scope.querySelectorAll('.lv-col')]
        .map(c => Math.round(c.getBoundingClientRect().left)).join('|');
    })();
    // The panel names per column, so "column 2 is Comps" is measured.
    o.colpanels = (function () {
      if (arr !== 'cols') return '';
      return [...scope.querySelectorAll('.lv-col')].map(c =>
        [...c.querySelectorAll('.lv-pn > h3')].map(title).join('+')).join('|');
    })();
    // The COMPS panel's own text, for claims about ONE panel rather than the
    // page: "Lobby tribes" belongs to the page's tribe row, and the comps panel
    // must not have a second copy of it (round 3 item 4). BY NAME since
    // 2026-10-13: it read the first panel on the page, which stopped being the
    // comps panel the moment the accordion put the pinned Facts strip first.
    // `textContent` reads a SHUT section too (its children are display:none, not
    // gone), which is what this claim needs — it is about what the panel holds.
    o.compspaneltext = (function () {
      const p = sectionPanel('Comps');
      return p ? p.textContent.replace(/\s+/g, ' ').trim() : '';
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
    // confused with the board and hand rows, which are cards too. BY NAME since
    // 2026-10-13 (round 4 item 5): `panes[0]` was the Tavern panel only while the
    // shop was the FIRST panel on the page, and in the accordion the pinned Facts
    // strip comes first — measured, "the first panel" became the facts table and
    // two shop tests read 0 cards with the shop plainly rendered on screen (the
    // same shape of stale read commit 62fb33d fixed in this file's comps driver).
    const tavpanel = sectionPanel('Tavern');
    o.taverncards = tavpanel
      ? tavpanel.querySelectorAll('.lv-card').length : 0;
    o.skel = q('.lv-skel').length;
    o.empty = [...q('.lv-empty')].map(d => d.textContent).join('|');
    o.notes = [...q('.lv-note')].map(d => d.textContent).join('|');
    // --- THE PICK STRIP (item A, 2026-10-14): compact HORIZONTAL option
    // cards, art on the left, name/subline/headline/rows on the right. Every
    // read comes from the strip itself, which is outside `scope` (see
    // `pickStrip`).
    const pk = pickStrip();
    const pq = s => pk ? pk.querySelectorAll(s) : [];
    const pone = s => pk ? pk.querySelector(s) : null;
    const pbox = s => {
      const n = pone(s);
      if (!n) return '';
      const r = n.getBoundingClientRect();
      return Math.round(r.width) + 'x' + Math.round(r.height);
    };
    o.pick = pq('.lv-optcard').length;
    o.picknames = [...pq('.lv-pname')].map(txt).join('|');
    o.picknameh = (function () {
      const n = pone('.lv-pname');
      return n ? Math.round(n.getBoundingClientRect().height) : 0;
    })();
    // The ONE line under the name: the hero power, or a discover's tier/tribe.
    o.picksub = [...pq('.lv-psub')].map(txt).join('|');
    o.picksubwrap = (function () {
      const n = pone('.lv-psub');
      return n ? getComputedStyle(n).whiteSpace : '';
    })();
    o.pickhead = [...pq('.lv-phead b')].map(txt).join('|');
    o.picklbl = [...pq('.lv-phead small')].map(txt).join('|');
    o.pickvs = [...pq('.lv-vs')].map(txt).join('|');
    o.pickrows = [...pq('.lv-optcard .lv-kv')]
      .map(d => txt(d.children[0]) + '=' + txt(d.children[d.children.length - 1]))
      .join('|');
    o.pickmore = [...pq('.lv-pmore')].map(txt).join('|');
    o.picknodata = [...pq('.lv-pnodata')].map(txt).join('|');
    o.picknodatatitle = (function () {
      const n = pone('.lv-pnodata');
      return n ? n.title : '';
    })();
    o.pickart = pbox('.lv-pickart');
    o.pickartratio = (function () {
      const n = pone('.lv-pickart');
      if (!n) return '';
      const r = n.getBoundingClientRect();
      return r.width ? (r.height / r.width).toFixed(3) : '';
    })();
    o.pickcard = pbox('.lv-optcard');
    // EVERY card the same height, and the row's own measure — the design's
    // "fixed min-height so the grid does not jump".
    o.pickcards = [...pq('.lv-optcard')]
      .map(c => Math.round(c.getBoundingClientRect().height)).join('|');
    o.pickcols = (function () {
      const n = pone('.lv-pickgrid');
      return n ? getComputedStyle(n).gridTemplateColumns : '';
    })();
    o.pickcolw = (function () {
      const n = pone('.lv-optcard');
      return n ? Math.round(n.getBoundingClientRect().width) : 0;
    })();
    o.pickcolx = [...pq('.lv-optcard')]
      .map(c => Math.round(c.getBoundingClientRect().left)).join('|');
    o.pickcoly = [...pq('.lv-optcard')]
      .map(c => Math.round(c.getBoundingClientRect().top)).join('|');
    // HOW MANY TIMES each option's name appears inside its own card: "the name
    // appears once" is the item's own wording, and a `textContent` count is what
    // it means. 1 for every card, or the name is on the screen twice.
    o.picknamecount = [...pq('.lv-optcard')].map(c => {
      const n = c.querySelector('.lv-pname');
      const want = n ? n.textContent : '';
      return want ? String(c.textContent.split(want).length - 1) : '0';
    }).join('|');
    o.pickartno = pq('.lv-pickart .tname').length;
    o.picksrc = (function () {
      const n = pone('.lv-source');
      if (!n) return '';
      const s = getComputedStyle(n);
      return s.whiteSpace + ',' + s.overflow + ',' + s.textOverflow
           + ',' + (n.title === n.textContent ? 'title' : 'no-title');
    })();
    o.picksrcgap = (function () {
      const n = pone('.lv-source');
      return n ? getComputedStyle(n).marginBottom : '';
    })();
    o.pickctl = [...pq('.lv-pickctl .lv-chip')]
      .map(c => c.textContent + (c.classList.contains('on') ? ':on' : ':off'))
      .join('|');
    o.pickctlvp = (function () {
      const n = pone('.lv-pickctl');
      return n ? Math.round(n.getBoundingClientRect().height) : 0;
    })();
    // The source line under the pick controls. Guarded: the comps Compare block
    // reuses `.lv-opts` for its columns and has no `.lv-pickctl` at all, so an
    // unguarded read threw on that screen and took the whole shot with it.
    const pickctl = pone('.lv-pickctl');
    o.picknote = pickctl ? txt(pickctl.parentNode.querySelector('.lv-note')) : '';
    // WHERE THE STRIP SITS, against the dashboard it must not evict: above it,
    // and (for the "fits without scrolling" claim) entirely inside the window.
    o.pickabove = (function () {
      const arr = shownArrangement();
      if (!pk || !arr) return 0;
      return pk.getBoundingClientRect().top < arr.getBoundingClientRect().top
        ? 1 : 0;
    })();
    o.pickbottom = pk ? Math.round(pk.getBoundingClientRect().bottom) : 0;
    o.vh = window.innerHeight;
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
    // THE CARD SLOT, and the two fields this replaces (`decidekids` and
    // `classic`, which both read this same count). They measured "the classic
    // page drew": the classic renderer wrote the pane headers and the card into
    // `#col-decide`, so a non-zero count was the classic page being on screen.
    // Live frames no longer write there at all — only the welcome/game-over card
    // does — so the honest read is that count, with the opposite meaning.
    o.cardslotkids = document.getElementById('col-decide').children.length;
    // The classic tribe picker's row, which no longer exists: the Tavern row
    // (`.lv-tribes`) is the only picker, so a hit here is a removed control back
    // on the page. Page-wide on purpose — it would be OUTSIDE the view's root.
    o.inplaychips = document.querySelectorAll('.inplaychips').length;
    o.label = txt(one('.lv-lbl'));
    // The TRIBE ROW's own label: `.lv-lbl` first is the tavern mix or the comps
    // Sort chip now that every section renders at once (round 4 item 5).
    o.tribelbl = txt(rone('.lv-tribes .lv-lbl'));
    o.opplabel = txt(one('.lv-opp'));
    // --- the fix lists' own facts (rounds 1 and 2, 2026-10-09) ------------
    // 1. Live fills the window: the tavern container against the viewport, and
    //    where the sections actually sit. Measured on the ROOT:
    //    `root.querySelector('.tavern.live')` looks for a DESCENDANT of it and
    //    finds nothing, which read as a 0px-wide view.
    o.tavernw = root ? Math.round(root.getBoundingClientRect().width) : 0;
    o.vpw = window.innerWidth;
    // Where the panel sections sit relative to each other, whatever the mode:
    // stacked (different tops) or side by side (one top, different lefts).
    o.sectat = [...q('.lv-pn')].map(p => {
      const r = p.getBoundingClientRect();
      return Math.round(r.left) + ',' + Math.round(r.top);
    }).join('|');
    // 2. The waiting state. (`statebarhidden` read the classic strip's `hidden`
    // flag here; the strip and its element are gone, so a read of it would throw
    // — which is why the field went rather than being left to return 0.)
    o.herocls = rone('.lv-hero') ? rone('.lv-hero').className : '';
    o.missvals = all('.lv-st b.miss').length;
    o.inline = [...q('.lv-inline')].map(d => d.textContent).join('|');
    o.bhlabels = [...q('.lv-bh .lv-lbl')].map(d => d.textContent).join('|');
    o.bhhalf = q('.lv-bh > div').length;
    // Where the board and the hand sit vertically, so "stacked under 700px" is
    // measured rather than inferred from the grid rule that does it.
    o.tops = [...q('.lv-bh > div')]
      .map(d => Math.round(d.getBoundingClientRect().top)).join('|');
    // 3. One art treatment, spell tags, names.
    o.kinds = [...q('.tile .tag-kind')].map(d => d.textContent).join('|');
    // The pick screen's own art is NOT a `.tile` any more (2026-10-14): it is
    // `.lv-pickart`, which is what makes "one name and no caption" structural
    // rather than a flag. `pickartno` above is the read that matters.
    o.renameless = pq('.lv-optcard .tname').length;
    o.tiletitles = q('.tile[title]').length;
    o.tnamewrap = (function () {
      const n = one('.tavern .tile .tname') || one('.tile .tname');
      return n ? getComputedStyle(n).whiteSpace : '';
    })();
    o.noart = q('.tile .thumb').length;
    // 4. The tribe row: one chip per tribe, amber when set, dimmed when not.
    o.chipcls = all('.lv-tribes .lv-chip')
      .map(c => c.textContent + ':' + (c.classList.contains('active') ? 'active'
             : c.classList.contains('dim') ? 'dim'
             : c.classList.contains('out') ? 'out' : '?')).join('|');
    o.nagacount = all('.lv-tribes .lv-chip')
      .filter(c => c.textContent === 'NAGA' || c.textContent === 'Naga').length;
    // (The pick screen's own numbers and layout — `picklbl`, `pickcolw`,
    // `pickctlvp`, `pickctlw`, `pickctlbox`, `picknameh`, `pickcardw` — were
    // read HERE, from the arrangement scope, until 2026-10-14. The pick strip is
    // above both arrangements now, so all of them moved up to the `pk` block
    // near `picknames`: one scope for one panel, and `pickctlw`/`pickctlbox`
    // went with them as unreferenced — the "one row" claim they served is
    // `pickctlvp`'s.)
    // (The Classic | Tavern toggle's three colour reads — `vsegbg`, `vsegon`,
    // `vsegpad` — were here and were already unreferenced; the control is gone,
    // so the reads would answer for a null and the fields went with them. The one
    // segment control left, `#settle-mode`, is themed by the same `.vseg` rules
    // that `test_live_tavern.test_the_segment_control_is_themed` pins.
    // 7. Game over: the label, and the sharing counter in its sentence.
    o.overlabel = txt(one('.lv-overlabel'));
    o.fine = [...q('.lv-fine')].map(d => d.textContent).join('|');
    // §4.4: the comp rows, their tier columns, the mini-card slots with the
    // size actually laid out, the controls, and the Detail/Compare shapes.
    // SCOPED TO THE MAIN LIST since 2026-10-14 (item B.1): the out-of-play
    // block's rows are `.lv-crow` too, and a page-wide read would fold them into
    // "the list" the tier columns count — which is the whole distinction the
    // item is about. `ooprows` below reads the other list by name.
    o.comprows = [...q('.lv-cols .lv-crow')].map(r => {
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
    // "card name on hover" (item B.2): the slot's own title names the card and
    // its state, so the thumbnail is never a picture with no way to read it.
    o.slottitles = q('.lv-slot[title]').length;
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
    // The comps TIER columns. Named apart from `colw`/`colx` above, which are
    // the three columns of the LAYOUT (round 4 item 5) — two different meanings
    // of "column" in one view, and one driver key cannot be both.
    o.ctierw = [...q('.lv-ctier')].map(c => Math.round(c.getBoundingClientRect().width)).join('|');
    o.ctierx = [...q('.lv-ctier')].map(c => Math.round(c.getBoundingClientRect().left)).join('|');
    o.cols = [...q('.lv-ctier')].length;
    // The COMP panel's own box, by its heading: with three columns, "how wide is
    // the comps screen" is what decides how many tier columns fit in it, and
    // `.lv-pn` first would be the Tavern panel.
    o.compsw = (function () {
      const p = [...q('.lv-pn')].find(x => {
        const h = x.querySelector('h3');
        if (!h) return false;
        let t = '';
        h.childNodes.forEach(n => {
          if (n.nodeType === 3) t += n.textContent;
        });
        return t.trim() === 'Comps';
      });
      return p ? Math.round(p.getBoundingClientRect().width) : 0;
    })();
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
    o.avgcells = q('.lv-cols .lv-ap').length;
    o.hasavg = q('.lv-ctier.has-avg').length;
    o.hnote = [...q('.lv-hnote')].map(n => n.textContent).join('|');
    // --- item B (2026-10-14): the TWO lists, and the row's own parts. --------
    // The out-of-play block: a collapsed `<details>`, dimmed, grouped by tribe,
    // and with NO compare box on any of its rows.
    o.ooprows = q('.lv-oop .lv-crow').length;
    o.oopsum = txt(one('.lv-oopsum'));
    o.oopopen = q('.lv-oop[open]').length;
    o.ooptribes = [...q('.lv-oopgroup')].map(txt).join('|');
    o.oopboxes = q('.lv-oop .lv-cmpbox').length;
    o.oopnames = [...q('.lv-oop .lv-copen')].map(txt).join('|');
    o.oopdim = (function () {
      const r = one('.lv-oop .lv-crow');
      return r ? getComputedStyle(r).opacity : '';
    })();    // The row's own parts: the tribe under the name, in the row's text colour;
    // the compare box with NO visible word; the tier chip only under an opt-in
    // sort; an EMPTY avg cell rather than a dash.
    o.tribetext = [...q('.lv-cols .lv-crowtribe')].map(txt).join('|');
    o.tribecolor = (function () {
      const t = one('.lv-crowtribe');
      return t ? getComputedStyle(t).color : '';
    })();
    o.uncf = q('.lv-uncf').length;
    o.tierchips = q('.lv-cols .lv-crow .lv-tier').length;
    o.cmplbl = q('.lv-cmplbl').length;
    o.cnametitles = q('.lv-cname[title]').length;
    o.nametitle = (function () {
      const n = one('.lv-cname');
      return n ? n.title : '';
    })();
    // The accessible name the visible "compare" word used to carry (item B.2).
    o.cboxlabel = (function () {
      const b = one('.lv-cmpbox');
      return b ? (b.getAttribute('aria-label') || '') : '';
    })();
    // The OWNED cell's colour, as the control for the tribe's: green is the
    // owned colour on this screen and nothing else may wear it.
    o.ownedcolor = (function () {
      const b = one('.lv-owned');
      return b ? getComputedStyle(b).color : '';
    })();
    o.apvals = [...q('.lv-cols .lv-ap')].map(txt).join('|');
    o.apempty = [...q('.lv-cols .lv-ap')].filter(b => !b.textContent).length;
    o.crowgap = (function () {
      const r = one('.lv-crow');
      return r ? getComputedStyle(r).gap : '';
    })();
    // THE ROW BOXES, in order: "comp rows don't overlap" is the item's own
    // wording, and only a rectangle can answer it. `rowbox` is read back as text
    // (left,top,right,bottom per row) because the harness's numeric fields are
    // single ints.
    o.crowboxes = [...q('.lv-cols .lv-crow')].map(r => {
      const b = r.getBoundingClientRect();
      return [Math.round(b.left), Math.round(b.top), Math.round(b.right),
              Math.round(b.bottom)].join(',');
    }).join(' ');
    // How tall the NAME cell is, so "a long name wraps to two lines and the
    // tribe moves down with it" is measured rather than assumed.
    o.cnameh = (function () {
      const n = one('.lv-cname');
      return n ? Math.round(n.getBoundingClientRect().height) : 0;
    })();
    // The comp distribution bars still exist on the DETAIL screen — the pick
    // card stopped drawing any (item A), so this is the control that the `lvBars`
    // renderer is still reached at all.
    o.compdistbars = q('.lv-cstat .lv-bar').length;
    // A COMP ROW IS DIMMED ONLY WHEN IT IS IN THE OUT-OF-PLAY BLOCK. This read
    // used to count the per-row "· tribe unconfirmed" note — and round 4 item 1
    // RENAMED that note to "· not available", so the filter matched nothing and
    // the assertions passed on a count that could only ever be 0. That is the
    // failure mode this harness exists to avoid, so the read is the computed
    // OPACITY the dimming actually is, and `oopdim` is its control: a renamed
    // class would zero `maindim` again, and a zero that CANNOT be non-zero is
    // not a measurement.
    o.crowrows = q('.lv-cols .lv-crow').length;
    o.maindim = [...q('.lv-cols .lv-crow')]
      .filter(r => parseFloat(getComputedStyle(r).opacity) < 1).length;
    o.ctlchips = [...q('.lv-ctl .lv-chip')].map(c => c.textContent).join('|');
    o.ctlrows = q('.lv-ctl').length;
    // The compare control's own theming, and where the toggle lives.
    o.cmpskin = (function () {
      const b = one('.lv-cmpbox');
      if (!b) return '';
      const s = getComputedStyle(b);
      return s.appearance + ',' + s.backgroundColor;
    })();
    // (The flag's geometry — `toggleinnav`, `toggleright`, `togglehidden` — was
    // read here to pin where the Classic | Tavern control sat and that Settle Up
    // hid it. There is no control and no row: `navviewer` is the absence read
    // that replaces all three.)
    o.navviewer = document.querySelectorAll(
      '#tabs #live-viewer, #live-viewer-row, #settle-viewer').length;
    // One row per OFFER / per board minion (round 3 item 1), scoped to the
    // TAVERN section BY NAME (see `tavpanel` above), because the board and hand
    // rows are cards too and the pinned Facts strip is the first panel in the
    // accordion.
    o.shopcards = tavpanel
      ? tavpanel.querySelectorAll('.lv-card').length : 0;
    o.shopkeys = tavpanel
      ? [...tavpanel.querySelectorAll('.tname')].map(n => n.textContent).join('|')
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
    // The section HEADER's own box. It is the control that replaced the tab row
    // (round 4 item 5), so its target size is measured rather than declared —
    // and it is a `.lv-pn > h3`, which exists in BOTH arrangements, unlike the
    // accordion-specific `.lv-acc`.
    o.h3h = (function () {
      const h = one('.lv-pn > h3');
      return h ? Math.round(h.getBoundingClientRect().height) : 0;
    })();
    // EVERY word the view puts on screen, for the §1 scan. The panel headers
    // and the status labels are in here too — a verdict can hide in a label.
    o.alltext = root ? root.textContent.replace(/\s+/g, ' ').trim() : '';
    // --- fix list round 4 items 3 and 4 -----------------------------------
    // A panel BY ITS HEADING, so "the next opponent's rows" cannot be answered
    // by some other panel's rows (the fixtures carry several .lv-kv tables).
    // The heading's TITLE is the text node, not `textContent`: every header
    // carries the round 4 item 5 one-line summary in a span beside the name, so
    // `textContent` would read "Next opponentReno" and match nothing.
    const pn = want => [...q('.lv-pn')].find(p => {
      const h = p.querySelector('h3');
      return h ? title(h) === want : false;
    });
    // The offers that LEFT the shop this turn: one card per OFFER ENTITY.
    o.passedlbl = txt(one('.lv-passed .lv-lbl'));
    o.passedcards = q('.lv-passed .lv-card').length;
    o.passednames = [...q('.lv-passed .tname')].map(n => n.textContent)
      .join('|');
    o.passedcaps = [...q('.lv-passed .lv-cap')].map(c => c.textContent)
      .join('|');
    o.passednote = txt(one('.lv-passed .lv-note'));
    // How long ago the panel was read, ON the panel (item 3(b)). A class, not
    // the id it used to be: the Tavern panel exists in both arrangements (item
    // 5), so an id would have been duplicated.
    o.readage = txt(one('.lv-read'));
    // The tribe composition of the shop, and of the opponent's board.
    o.mixlbl = [...q('.lv-mix .lv-lbl')].map(d => d.textContent).join('|');
    o.mixchips = [...q('.lv-mixchip')].map(d => d.textContent).join('|');
    o.opprows = (function () {
      const p = pn('Next opponent');
      if (!p) return '';
      return [...p.querySelectorAll('.lv-kv')]
        .map(d => txt(d.children[0]) + '='
                  + txt(d.children[d.children.length - 1])).join('|');
    })();
    o.opptext = (function () {
      const p = pn('Next opponent');
      return p ? p.textContent.replace(/\s+/g, ' ').trim() : '';
    })();
    o.oppcards = (function () {
      const p = pn('Next opponent');
      return p ? p.querySelectorAll('.lv-card').length : 0;
    })();
    o.oppempty = (function () {
      const p = pn('Next opponent');
      return p ? txt(p.querySelector('.lv-empty')) : '';
    })();
    for (const k of Object.keys(o))
      rec(name + '.' + k, ['tavern', 'cards', 'skel', 'pick',
                           'taverncards', 'compslots', 'slotsmiss',
                           'slotshand', 'guideopen', 'panelw', 'saverows',
                           'checkboxin', 'tavernon', 'decidehidden',
                           'cardslotkids', 'tabh', 'tavernw', 'vpw', 'slotart',
                           'legendslots', 'cmpboxes', 'cmpchecked', 'cmpdisabled',
                           'missvals', 'bhhalf', 'renameless', 'tiletitles',
                           'noart', 'nagacount', 'pickcolw', 'pickctlvp',
                           'picknameh', 'cols', 'vw', 'vh',
                           'avgcells', 'hasavg', 'crowrows', 'maindim', 'ctlrows',
                           'navviewer', 'inplaychips', 'shopcards',
                           'boardcards', 'passedcards', 'oppcards',
                           'tabs', 'panelcount', 'accs', 'bodyw',
                           'pickabove', 'pickbottom', 'pickartno',
                           'ooprows', 'oopopen', 'oopboxes', 'uncf',
                           'tierchips', 'cmplbl', 'cnametitles', 'apempty',
                           'compdistbars', 'cnameh', 'slottitles']
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
    const hits = [...scope.querySelectorAll(sel)]
      .filter(c => label === null || c.textContent === label);
    // A VISIBLE MATCH IS PREFERRED (2026-10-14). Both arrangements build the
    // comps panel, so a page-wide search finds the HIDDEN arrangement's copy
    // first — and clicking a summary inside a `display:none` subtree opened a
    // block nobody could see, which read as "the control does not work". The
    // fallback keeps every shot whose control is legitimately off-screen (the
    // end-of-game card, a shut section's own header) working as before.
    const node = hits.find(c => c.offsetParent) || hits[0];
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
    // THE OPEN/CLOSED SECTIONS ARE LOCALSTORAGE, NOT A MODULE VARIABLE (round 4
    // item 5), so the reset above cannot reach them: a shot that shut a section
    // would hand that to every shot after it, and the leak would be between
    // SHOTS rather than inside one. Cleared first, then written when this shot
    // asks for a state — so "nothing stored" is the default every shot starts
    // from, and nothing else in this driver touches the key.
    try { localStorage.removeItem('bl-lv-open'); }
    catch (e) { /* private mode */ }
    if (s.open != null) {
      try { localStorage.setItem('bl-lv-open', s.open); }
      catch (e) { /* private mode */ }
    }
    // `pre` is the screen the player was looking at before this payload arrived
    // (a live payload, then the end-of-game one) — the only way to test that the
    // new card replaces it rather than leaving it behind.
    if (s.pre) {
      render(s.pre);
      (s.preclicks || []).forEach(c => clickCtl(c[0], c[1], c[2]));
    }
    render(s.rep);
    // `reveal` OPENS THE SECTION FIRST, THEN the shot's clicks land (2026-10-14).
    // It used to run last, which was fine while every control a shot clicked was
    // a div the renderer had already built — but a shut section is
    // `display:none`, and both arrangements build a Comps panel, so a click on a
    // control inside one had no way to tell the visible copy from the hidden one:
    // the out-of-play summary that was clicked belonged to the hidden
    // arrangement, the visible block stayed shut, and the shot read 0 (measured).
    // Clicking what is on screen is also what a player does.
    if (s.reveal) {
      const p = sectionPanel(s.reveal);
      if (!p) throw new Error('no section titled ' + s.reveal);
      const h = p.querySelector('h3');
      if (h && h.getAttribute('role') === 'button'
          && p.classList.contains('shut')) h.click();
      window.scrollTo(0, Math.max(0, p.getBoundingClientRect().top
                                     + window.scrollY - 8));
    }
    if (s.click) clickCtl('.lv-pickctl .lv-chip', s.click);
    (s.clicks || []).forEach(c => clickCtl(c[0], c[1], c[2]));
    // `toggle`: click a section's header, then RE-RENDER the same payload — which
    // is what the 5-second shop re-read does (`live.SHOP_REREAD_SECONDS`). The
    // section's state is persisted, so a render that did not re-apply it from
    // storage would pop the section back to its default right there, in front of
    // the player.
    if (s.toggle) {
      const p = sectionPanel(s.toggle);
      if (!p) throw new Error('no section titled ' + s.toggle);
      const h = p.querySelector('h3');
      if (!h || h.getAttribute('role') !== 'button') {
        throw new Error(s.toggle + ' is not a foldable section');
      }
      h.click();
      render(s.rep);
    }
    // `settle`: the payload renders on the live tab and the SETTLE tab is then
    // opened — the shot that used to measure "the live viewer flag is out of the
    // way over there", kept because the ABSENCE has to hold on both tabs.
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


def _render_source():
    """The page's source with its comments removed — for ABSENCE assertions.

    The page's own comments NAME what was removed, on purpose ("`#statebar` was
    the classic live page's stat tile row ... the element, its CSS rules and
    every line that touched it are gone"), so an absence check on the raw string
    fails on the explanation rather than on a regression. Only `/* */`, `<!-- -->`
    and `//` comments are removed, so live code is never removed with them.
    """
    import re
    body = re.sub(r"/\*.*?\*/", "", coach_ui._HTML, flags=re.S)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    return re.sub(r"//[^\n]*", "", body)


def _page(shots):
    driver = _DRIVER.replace("__SHOTS__", __import__("json").dumps(shots))
    return coach_ui._page_html().replace("</body>", driver + "</body>")


def _shot(name, rep, reveal=None, click=None, clicks=None,
          pre=None, preclicks=None, settle=False, open=None, toggle=None):
    """One shot.

    `reveal` is the SECTION the player is looking at (the successor of the old
    `tab`: every section is on the page now, so "the Comps screen" means "Comps
    is the part of the page being read"). `open` is this shot's stored
    open/closed state for the accordion — the `bl-lv-open` value written before
    the render, e.g. `'-Comps'` for a shut Comps. `toggle` names a section whose
    header is CLICKED after the render and then RE-RENDERS the same payload,
    which is the 5-second re-read in miniature (fix list round 4 item 5: the
    state has to survive it).

    NO `viewer` ARGUMENT (2026-10-13). Every shot used to pass one (default
    "tavern") so the driver could set `_liveViewer` before rendering; with the
    choice gone the parameter would set nothing, and a dead parameter is how a
    shot silently stops testing what its name says.
    """
    return {"name": name, "rep": rep, "reveal": reveal,
            "click": click, "clicks": clicks or [], "pre": pre,
            "preclicks": preclicks or [], "settle": settle, "open": open,
            "toggle": toggle}


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


#: What the shop ROLLED PAST (fix list round 4 item 3(c)): a tavern spell, then
#: TWO copies of one minion — two OFFER ENTITIES with two entity ids, which is
#: the item's whole premise and the one thing a card-keyed record cannot hold.
#: The ids are taken from the shipped DBs rather than written down, so a tier
#: refresh cannot silently turn a tribe assertion into a tautology (an unknown
#: id resolves to no tribe, and "0 Elemental" would pass where "2 Elemental"
#: was meant — the same trap the pool-chip test documents).
def _real_minion(tribe):
    import meta
    return next(m["id"] for m in meta.minions() if m.get("tribe") == tribe)


def _real_tavern_spell():
    import value
    return next(iter(value._load_spell_db()))


_SPELL = _real_tavern_spell()
_ELEM = _real_minion("Elemental")
ROLL_FIRST = {"eid": 101, "card": _SPELL, "turn": 9}
ROLL_SECOND = {"eid": 102, "card": _ELEM, "turn": 9}
ROLL_THIRD = {"eid": 103, "card": _ELEM, "turn": 9}

#: One turn's shop after a roll: the two copies of the Elemental and the spell
#: are what is on offer now, and all three of them are ALSO what left during
#: this turn (a rolled-away generation and the current one are the same shape to
#: this panel).
ROLLED = dict(turn=9,
              shop_passed=[ROLL_FIRST, ROLL_SECOND, ROLL_THIRD],
              shop_entities=[{"eid": ROLL_FIRST["eid"], "card": _SPELL},
                             {"eid": ROLL_SECOND["eid"], "card": _ELEM},
                             {"eid": ROLL_THIRD["eid"], "card": _ELEM}],
              shop_offers=[_SPELL, _ELEM, _ELEM])

#: Two rows in the analysis, one per turn: the panel takes THIS turn's only, so
#: the count in its own label is one and not two.
ROLLED_LAST_TURN = dict(ROLLED, shop_passed=[{"eid": 73, "card": _ELEM,
                                              "turn": 8},
                                             {"eid": 74, "card": _ELEM,
                                              "turn": 9}])


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
    def size(cls):
        """The window this class's shots are laid out in.

        It is a class property rather than a constant because the LAYOUT is what
        fix list round 4 item 5 makes width-dependent: a class whose claim is
        about the accordion has to say so, or it would be measuring whatever the
        default window happens to be (`browser.WIDE`), which is the whole failure
        this harness exists to prevent — "a claim about the window is not a claim
        about the container".
        """
        return browser.WIDE

    @classmethod
    def shots(cls):
        raise NotImplementedError

    def setUp(self):
        cls = type(self)
        # `cls.__dict__`, not `cls._outcome`: the cache must be PER SUBCLASS. It
        # was not, and the classes below that ask for a different window inherited
        # whichever class ran first — so a class whose shots are about the
        # accordion was reading the three-column layout rendered at 1400x900 and
        # every one of its assertions failed on a page it never asked for
        # (measured 2026-10-13, while adding the round 4 item 5 layout classes).
        if "_outcome" not in cls.__dict__:
            try:
                cls._outcome = _render(cls.shots(), size=cls.size())
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
                _shot("comps", _comps_payload(), reveal="Comps"),
                _shot("nocomps", _comps_payload(game_comps={}, tribe_pressure=[]),
                      reveal="Comps"),
                _shot("lobby", _payload(), reveal="Lobby"),
                _shot("notread", _payload(fragility=None, level_cost=None,
                                          board_stats=None, opp_stats=None,
                                          opp_lobby=None)),
                _shot("noshop", _payload(shop_rank=[])),
                # A game number, so the tribe row's own state is a real one
                # (the row marks the five the server says are in play, so the
                # payload has to carry a game's worth of them).
                _shot("g7", _payload(game_no=7))]

    def test_the_status_bar_is_the_hero_and_six_numbers(self):
        self.assertEqual(self.got["t.tavern"], 1)
        self.assertEqual(self.got["t.hero"], "Chenvaala")
        # The labels are uppercase through CSS (text-transform), which is the
        # design's spec — the text itself stays as written.
        self.assertEqual(self.got["t.stats"],
                         "Gold:7|Tier:3|HP:26+4|Turn:9|Place:3rd")

    def test_the_tavern_row_is_the_only_picker_left(self):
        """REVERSED 2026-10-13 from
        `test_the_classic_picker_asks_for_the_five_in_the_tavern`, which read the
        CLASSIC picker's chip row (`.inplaychips`) and the sentence above it: the
        line used to read "tap the 5 banned tribes to set them now", so a player
        who followed it produced the complement on purpose.

        That row went with the classic renderer, and the claim it carried is not
        dropped with it — it MOVES to the Tavern row, which is now the page that
        asks for the set: `tribelbl` is the "tap to correct" line, and the marks
        are the five `tribes_available`
        (`test_a_tribe_out_of_play_appears_once_and_the_chips_are_marked`
        measures those, and this asserts the ask is still on screen at all and
        that no second picker came back).
        """
        got = self.got
        self.assertEqual(got["g7.inplaychips"], 0,
                         "the classic picker's chip row is back — two pickers "
                         "writing the same set from two places")
        self.assertEqual(got["t.inplaychips"], 0)
        self.assertIn("tap to correct", got["g7.tribelbl"])
        self.assertNotIn("ban", got["g7.tribelbl"].lower(),
                         "the row asks for the banned five again — a player "
                         "following it produces the complement")

    def test_the_tribe_row_is_one_row_and_out_of_play_is_struck_not_banned(self):
        """The row's label and the fact that an out-of-play tribe is its own
        state rather than a ban the player could undo. The row is one row of
        every in-pool tribe, with the five in the tavern marked (see
        `test_a_tribe_out_of_play_appears_once_and_the_chips_are_marked`)."""
        self.assertIn("BEAST", self.got["t.chips"])
        self.assertIn("PIRATE", self.got["t.chips"])
        self.assertEqual(self.got["t.outchips"], "NAGA",
                         "out-of-play tribes are their own state, never a ban "
                         "the player could undo")
        # The row's own label, not the first `.lv-lbl` on the page: the tavern
        # mix and the comps Sort label come first now that every section is
        # rendered at once (round 4 item 5), and `.lv-lbl` first would read one
        # of those.
        self.assertIn("tap to correct", self.got["t.tribelbl"])

    def test_a_tribe_out_of_play_appears_once_and_the_chips_are_marked(self):
        """Fix list round 1 item 3. The roster is every tribe the game has, so
        Naga is in it AND in `out_of_pool`: iterating both printed it twice.

        REVERSED 2026-10-13. This pinned "amber outline when the tribe is
        banned, dimmed when it is in play" — the direction the payoff session
        (2026-10-13_12_01_10) proved wrong: the five the player taps are the
        tribes in the tavern, so the set the page seeds from is
        `tribes_available` and `banned` is its complement. The read is the same
        three states with the meanings swapped: the tapped five are `active`
        (BEAST, PIRATE among them), the tribe this game cannot offer — and that
        the player did not tap — is `dim` (DEMON), and the rotated one is `out`.
        """
        got = self.got
        self.assertEqual(got["t.nagacount"], 1,
                         "the out-of-play tribe is listed twice")
        self.assertIn("BEAST:active", got["t.chipcls"],
                      "a tribe the player set as in the tavern is not marked")
        self.assertIn("PIRATE:active", got["t.chipcls"],
                      "a tribe the player set as in the tavern is not marked")
        self.assertIn("DEMON:dim", got["t.chipcls"],
                      "the tribe this game cannot offer is not dimmed")
        self.assertIn("NAGA:out", got["t.chipcls"])
        self.assertEqual(got["t.chipcls"].count(":?"), 0,
                         "a chip with no state class at all")

    def test_the_sections_are_the_whole_page_and_the_tabs_are_gone(self):
        """REVERSED 2026-10-13 (fix list round 4 item 5). This pinned §4.1's tab
        row — `Shop | Comps | Lobby`, in DOM order, with the Facts table beside
        every screen — because the screens were exclusive and the row is what
        selected one. Both arrangements show every section at once, so there is
        nothing left for a tab row to select: a control that hides what is
        already visible is not a fact, it is a way to hide one. The `lv-tabs`
        class and its CSS went with it (see `test_live_tavern`).

        What replaces it: the six sections, in the ARRANGEMENT's own DOM order,
        each with a heading — and the tab row really gone, measured as an absence
        WITH a control, since a count that can only ever be zero is not a
        measurement (the mistake commit 62fb33d fixed in this very suite). The
        control is `panelcount`: the selector that used to find the tabs still
        finds the panels.

        The order is asserted in BOTH arrangements because they differ on
        purpose: the accordion pins Facts to the top of the stack (it is the
        strip the rest scrolls under), while the three-column one puts it in
        column 3. The harness's own 1400x900 window is an ACCORDION window since
        the threshold became the maintainer's window rule (see
        `TestTheLayoutByWidth`), so `t.panels` is the accordion's order and the
        1920x1080 render below is the columns'.
        """
        for shot in ("t", "comps", "lobby"):
            self.assertEqual(self.got[shot + ".tabs"], 0,
                             f"{shot} still carries a tab row")
            self.assertGreaterEqual(self.got[shot + ".panelcount"], 5,
                                    f"{shot} rendered almost no sections, so the "
                                    f"zero above is a selector that matches "
                                    f"nothing rather than a removed tab row")
        self.assertEqual(self.got["t.panels"],
                         "Facts|Tavern|Board and hand|Comps|Next opponent|Lobby")
        # The comps and lobby shots are the SAME page (round 4 item 5): every
        # section is rendered, and `reveal` only scrolled to one of them.
        self.assertEqual(self.got["comps.panels"], self.got["t.panels"])
        self.assertEqual(self.got["lobby.panels"], self.got["t.panels"])
        # The same six in the three-column arrangement: Tavern+board | Comps |
        # Facts+opponent+lobby, so the pinned strip is last in DOM order there.
        wide = _render([_shot("t", _payload())], size=(1920, 1080))
        self.assertEqual(wide["t.arr"], "cols")
        self.assertEqual(wide["t.panels"],
                         "Tavern|Board and hand|Comps|Facts|Next opponent|Lobby")
        # §8: 44px minimum targets. The accordion header is the control that
        # replaced the tabs; it is measured in `TestTheAccordionLayout`, at the
        # width where the accordion is the arrangement on screen. What can be
        # asserted HERE is that a section header is a real box rather than a
        # 0-height artefact of a collapsed one.
        self.assertGreaterEqual(int(self.got["t.h3h"]), 14,
                                "a section header has no height")

    def test_the_page_fills_the_window(self):
        """Fix list round 1 item 1: the tavern container was a flex rule inside a
        two-column GRID — and inside the flex COLUMN the page falls back to below
        1200x900, `flex-basis` is a height, so it did not stretch either.
        Measured before the fix: 815px of a 1384px window.

        The rail half of this test moved to the layout tests (fix list round 4
        item 5, 2026-10-13): the view is no longer two columns of panels, it is
        three columns at a big window and an accordion everywhere else, so what
        "beside it" means is measured in `TestTheLayoutByWidth` and
        `TestTheAccordionLayout`. What stays here is the claim that still holds
        in EVERY mode: the tavern container is the window."""
        # BOTH branches of `#app`'s layout: the grid (a tall window) and the flex
        # column (a short one).
        for size in ((1400, 1000), (1400, 900)):
            got = _render([_shot("f", _payload())], size=size)
            self.assertGreater(got["f.tavernw"], got["f.vpw"] * 0.9,
                               f"the tavern view is {got['f.tavernw']}px wide in "
                               f"a {got['f.vpw']}px window at {size}")
        # ...and below 700 the pick grid is a single column, with the board and
        # hand stacked rather than squeezed.
        narrow = _render([_shot("n", _choice_payload())], size=(600, 900))
        self.assertGreater(narrow["n.pickcolw"], 400,
                           "the pick grid is not a single column under 700px")
        self.assertEqual(narrow["n.arr"], "acc",
                         "600px is inside the accordion's range")
        bhn = _render([_shot("b", _payload())], size=(600, 900))
        self.assertEqual(bhn["b.bhhalf"], 2)
        # The board and hand are STACKED at that width, not side by side: their
        # tops differ, which is what the old rail comparison was really asking
        # (`colat2` read the rail's own position).
        bh = bhn["b.tops"].split("|")
        self.assertEqual(len(bh), 2)
        self.assertNotEqual(bh[0], bh[1],
                            "the board and the hand should stack under 700px")

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

    def test_there_is_no_state_strip_at_all(self):
        """REVERSED 2026-10-13 from `test_the_empty_strip_at_the_top_is_hidden`
        (fix list round 2 item 7: `#statebar` has a background and a radius, so
        blanking it left a rounded empty bar above the card).

        The strip was the classic live view's; the Tavern view draws its own
        status bar inside `#live-tavern`. That page is deleted, so nothing wrote
        to the strip and hiding what nothing writes to is a workaround rather
        than a fix — the element, its CSS and its writers are gone. The read that
        replaces the hidden-flag check is the CARD SLOT: on a live frame it is
        empty, which is the half of this a bare absence could not say.
        """
        got = self.got
        self.assertEqual(got["t.tavern"], 1)
        self.assertEqual(got["t.cardslotkids"], 0,
                         "a card is sitting in the slot under a live frame")
        welcome = _render([_shot("wel", _welcome_payload())])
        self.assertGreater(welcome["wel.cardslotkids"], 0,
                           "the first-run card did not draw in the slot")
        # And the strip is not merely hidden: the element is not in the page.
        self.assertNotIn("statebar", _render_source())

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

    def test_the_lobby_section_is_sightings_and_the_last_seen_board(self):
        """REVERSED 2026-10-13 (fix list round 4 item 5) from `…_tab_is_…`: the
        Lobby is not a screen a tab selects any more, it is a section of the
        page (column 3 in the three-column layout, a foldable section in the
        accordion). Its content is what this test is about, and that is
        unchanged — including the seat's own handle, which `lvOpponent` leaves
        out on purpose and this panel has always carried."""
        got = self.got
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

    def test_no_viewer_control_is_on_either_tab(self):
        """REVERSED 2026-10-13 from
        `test_the_classic_tavern_toggle_sits_on_the_nav_row` (round 3 item 7:
        right-aligned on the nav row, hidden while Settle Up was open). All three
        reads it used — where the flag sat, that it was visible on the live tab
        and that the Settle Up tab hid it — were reads of the control.

        What replaces them is the absence, on BOTH tabs (the same discipline the
        tab-row reversal in this suite uses: a count that can only ever be zero
        is not a measurement, so the read spans the three ids the two flags and
        their row could come back under, and the tavern view is asserted present
        in the same shot).
        """
        got = self.got
        self.assertEqual(got["t.tavern"], 1,
                         "the live view is not the page, so the zero below "
                         "proves nothing")
        self.assertEqual(got["t.navviewer"], 0,
                         "a Classic | Tavern control is on the nav row")
        settle = _render([_shot("s", _payload(), settle=True)])
        self.assertEqual(settle["s.navviewer"], 0,
                         "a viewer control is on screen over Settle Up")

    def test_a_second_live_frame_still_draws_the_live_view(self):
        """REVERSED 2026-10-13 from `test_classic_still_renders_after_a_tavern_render`,
        which pinned the way BACK from the Tavern view to Classic — the bug being
        that the first version cleared `#app` and destroyed the panes.

        There is no way back and nothing to go back to; what still has to hold is
        that a frame drawn after another frame re-draws the view rather than
        leaving the page blank, and that the card slot stays empty. These shots
        run in order, so `g7` has already drawn over `noshop` by the time it is
        read.
        """
        self.assertEqual(self.got["g7.tavern"], 1)
        self.assertEqual(self.got["g7.panelcount"], self.got["t.panelcount"],
                         "the second frame drew a different page")
        self.assertEqual(self.got["g7.cardslotkids"], 0)


class TestTheLayoutByWidth(_Rendered):
    """Fix list round 4 item 5: three columns at a big window, NO tabs anywhere.

    The threshold is the WINDOW's since 2026-10-13, on the maintainer's own call
    ("if the window is ~1920 wide, then three columns. Otherwise collapse it").
    This class first pinned a CONTAINER threshold of 1180px of box, which is a
    ~1250px window, and it was wrong for a reason worth keeping: `#wrap` caps the
    PAGE at 1600px, so past ~1640px of window the box stops growing and the box
    cannot tell a 1920px window from a 1700px one. The box is still MEASURED here,
    because it is what has to fit the three columns.

    Each claim names the window it is about and measures what the real sheet
    produced in it. The class's own shot is the harness's 1400x900 window, whose
    box is 1325px on the Windows box this was written on and 1356px on macOS —
    an ACCORDION window at both, which is the maintainer's rule. The 31px is
    chrome, not the page: see `test_the_default_window_is_an_accordion`.
    """

    @classmethod
    def shots(cls):
        return [_shot("w", _comps_payload())]

    def test_the_default_window_is_an_accordion(self):
        """REVERSED 2026-10-13: this asserted three columns at the harness's own
        1400x900 window, which is what a 1180px-of-box threshold gave it. The
        maintainer's rule is a window one and 1400 is not a big desktop window, so
        the same window is now the accordion — and the box it produces (1325px) is
        still measured here, because that number is exactly what used to decide
        and no longer does.

        The box is asserted as `docw - 44` rather than as `1325`, because 1325 was
        the HOST's number and this suite runs on more than one host since
        2026-10-15. Measured on the first macOS checkout: the same window gives
        1356px of box, and the 31px is entirely platform chrome —
        `documentElement.clientWidth` (what the page's boxes can occupy) is
        `window - 16 - 15` on Windows, a 16px window-chrome inset plus a classic
        15px scrollbar, and `window - 0` on macOS, whose overlay scrollbars cost
        nothing. The SHELL's own gutter, which is what this test is about, is 44px
        on both: 1384-44 = 1325 there and 1400-44 = 1356 here, and the same holds
        at 1100 (1069-44 = 1025 there, 1100-44 = 1056 here). Reading the box
        against `vw` would still have been a claim about the host; `docw` cancels
        the chrome and leaves the page."""
        got = self.got
        self.assertEqual(int(got["w.bodyw"]), int(got["w.docw"]) - 44)
        self.assertEqual(got["w.arr"], "acc",
                         f"a 1400x900 window is not in the accordion "
                         f"(box {got['w.bodyw']}px of {got['w.docw']}px)")
        self.assertEqual(got["w.panels"],
                         "Facts|Tavern|Board and hand|Comps|Next opponent|Lobby")

    def test_three_columns_at_a_1920_window(self):
        """MEASURED 2026-10-13 at 1920x1080: three columns at 622/622/300 inside
        a 1572px box. The box is 1572 and not 1592 because `#wrap` caps the PAGE
        at 1600px (a pre-existing rule of the shell), so this is as wide as the
        tavern view ever gets — which is why the numbers here and at a 3200px
        window are the same, and why "wider window" is not a layout this view has
        to answer for. A 1920x1080 window measures 1904px of VIEWPORT in this
        harness, which is why the threshold is 1800 and not 1920 itself."""
        got = _render([_shot("w", _comps_payload())], size=(1920, 1080))
        self.assertEqual(got["w.arr"], "cols",
                         f"a 1920x1080 window is not in the three-column layout "
                         f"(box {got['w.bodyw']}px)")
        widths = [int(v) for v in got["w.colw"].split("|")]
        self.assertEqual(len(widths), 3, f"columns: {got['w.colw']}")
        self.assertEqual(widths, [622, 622, 300])
        xs = [int(x) for x in got["w.colx"].split("|")]
        self.assertEqual(len(set(xs)), 3, "the three columns are not side by side")
        self.assertEqual(xs, sorted(xs), "the columns are out of order")
        # WHAT IS IN EACH ONE, in order: the two screens the player reads the
        # game through | Comps | the reference material.
        self.assertEqual(got["w.colpanels"],
                         "Tavern+Board and hand|Comps|Facts+Next opponent+Lobby")

    def test_the_tab_row_is_gone_at_that_width(self):
        """§4.1's `Shop | Comps | Lobby` row selected between exclusive screens;
        with every section on screen it has nothing left to select. Gone is
        measured with a POSITIVE CONTROL, because a selector that matches nothing
        would make this assertion pass on a page with no layout at all (the
        mistake commit 62fb33d fixed in this same file)."""
        got = _render([_shot("w", _comps_payload())], size=(1920, 1080))
        self.assertEqual(got["w.tabs"], 0, "the tab row is still rendered")
        self.assertEqual(got["w.panelcount"], 6,
                         "the selector that counted the tabs found no SECTIONS "
                         "either, so the zero above is not a measurement")
        self.assertEqual(got["w.panels"],
                         "Tavern|Board and hand|Comps|Facts|Next opponent|Lobby")

    def test_a_shorter_window_still_gets_three_columns(self):
        """The rule reads the WINDOW, so the shell's branch does not move it:
        measured, a 1920x900 window and a 1920x1080 one both give the box 1572px,
        because the 1600px `#wrap` cap is reached before the shell's 1200x900 grid
        branch can matter — and a 3200px window is capped the same. So every one
        of these is three columns, which is the claim: the layout does not flip
        when the window gets shorter or wider."""
        for size in ((1920, 900), (1920, 1080), (3200, 1200)):
            got = _render([_shot("s", _comps_payload())], size=size)
            self.assertEqual(got["s.arr"], "cols", f"not three columns at {size}")
            self.assertEqual(len(got["s.colw"].split("|")), 3, f"at {size}")
            self.assertEqual(got["s.colpanels"].count("|"), 2, f"at {size}")

    def test_the_width_that_switches_the_layout_is_the_windows(self):
        """REVERSED 2026-10-13: this test measured the threshold as the BOX's,
        which is what the first version of item 5 implemented. It is the window's
        now ("if the window is ~1920 wide, then three columns. Otherwise collapse
        it"), and the box is kept in the test as the thing that NO LONGER decides —
        which is the whole argument for the change.

        WHAT THE RULE READS is the VIEWPORT, and a harness `size` is the browser
        WINDOW, which is ~16px wider (measured: 1920x1080 here gives 1904px of
        viewport). So the test reads `vw` and asserts the arrangement against THAT
        number, rather than pinning which side of the breakpoint the window chrome
        happens to fall on — which is exactly how this test failed its first run,
        asserting a 1800px window was three columns when its viewport was 1784.

        The proof that the box stopped deciding is a PAIR: 1700x1080 gives the box
        ~1572px (the `#wrap` cap, the widest this page ever gets) and is an
        accordion, while 1900x800 — the shell's short branch, where the 340px rail
        still takes a track — gives it ~1532px and is three columns. A WIDER box in
        the accordion than in the columns is not a contradiction under this rule;
        under the box rule it was impossible.
        """
        for size in ((1799, 900), ((1800, 900)), (1850, 900), (1920, 1080)):
            got = _render([_shot("m", _comps_payload())], size=size)
            self.assertEqual(got["m.arr"],
                             "cols" if int(got["m.vw"]) >= 1800 else "acc",
                             f"at a {size} window (viewport {got['m.vw']}px) the "
                             f"layout did not follow the viewport")
        # THE MEASUREMENT THAT SAYS THE THRESHOLD CANNOT BE THE BOX: two windows
        # far apart in size give this view the SAME box — 1572px, the `#wrap` cap,
        # which any window past ~1640px reaches — and the rule still puts them in
        # DIFFERENT arrangements. A container query answers "same box" with the
        # same layout, so the first version of item 5 could not have implemented
        # the maintainer's call at all; that is why this is a window rule now.
        acc = _render([_shot("a", _comps_payload())], size=(1700, 1080))
        cols = _render([_shot("c", _comps_payload())], size=(1920, 1080))
        self.assertEqual(acc["a.arr"], "acc",
                         f"a 1700x1080 window is not an accordion "
                         f"(viewport {acc['a.vw']})")
        self.assertLess(int(acc["a.vw"]), 1800)
        self.assertEqual(cols["c.arr"], "cols",
                         f"a 1920x1080 window is not three columns "
                         f"(viewport {cols['c.vw']})")
        self.assertEqual(int(acc["a.bodyw"]), int(cols["c.bodyw"]),
                         f"these two windows do not share a box "
                         f"({acc['a.bodyw']}px vs {cols['c.bodyw']}px), so this "
                         f"pair does not show the box losing its say")
        self.assertEqual(int(cols["c.bodyw"]), 1572)
        # ...and every window that gets the columns is past the cap, so the three
        # columns measure the same wherever they appear — including at the
        # narrowest window a viewport rule can give them (1850 is the first
        # harness size whose VIEWPORT clears 1800).
        narrowest = _render([_shot("n", _comps_payload())], size=(1850, 800))
        self.assertEqual(narrowest["n.arr"], "cols",
                         f"a 1850x800 window (viewport {narrowest['n.vw']}) is not "
                         f"three columns, so this is not the narrowest one")
        self.assertEqual([int(v) for v in narrowest["n.colw"].split("|")],
                         [622, 622, 300],
                         f"the columns are not the full width at 1850x800: "
                         f"{narrowest['n.colw']}")


class TestTheAccordionLayout(_Rendered):
    """Fix list round 4 item 5: every window under 1800px is the accordion.

    One column of foldable sections, a one-line summary in every header, and the
    Facts table PINNED above them. The pin is measured by scrolling: a strip whose
    offset does not move while the section above it does is pinned, and one
    number on its own cannot tell the two apart.

    The same arrangement is what a 1400px window gets (`TestTheLayoutByWidth`),
    which the maintainer's rule made explicit: the columns are for a ~1920px
    desktop window and everything else collapses.
    """

    @classmethod
    def size(cls):
        # 1100x900: the box measures 1025px — a small desktop window, and the
        # width the pin and the summaries were measured at.
        return (1100, 900)

    @classmethod
    def shots(cls):
        # A board that wraps: the accordion has to be TALLER than the window for
        # the scroll measurement to have anything to scroll, and the stock
        # fixture fits 900px.
        big = _payload(board=[{"card": "BG31_815", "atk": 5, "health": 5,
                               "tribe": "Beast", "eid": i}
                              for i in range(20)])
        return [_shot("a", big),
                _shot("flat", _payload()),
                _shot("shut", _payload(), open="-Comps,-Lobby")]

    def test_one_column_with_a_summary_line_in_every_header(self):
        got = self.got
        self.assertEqual(got["flat.arr"], "acc")
        self.assertEqual(got["flat.panels"],
                         "Facts|Tavern|Board and hand|Comps|Next opponent|Lobby")
        # One line per section, and every one is a COUNT and a noun — the same
        # kind of fact the panels below already carry. §1 is about words on the
        # screen, and a header summary is exactly where a verdict would sneak in,
        # which is why `lvSectionLine` is in the source scan in `test_live_tavern`
        # as well.
        # "N in this lobby" since 2026-10-14 (item B.1): the comps list is the
        # comps this game can build, so the header counts THAT list. This fixture
        # carries one comp, and it is the lobby's — the old wording was
        # "1 of 1 available", which counted a list that no longer exists.
        self.assertEqual(
            got["flat.sums"],
            "|3 offers|2 on board · 1 in hand|1 in this lobby|Reno"
            "|2 of 3 seen seats")
        # The strip carries no line of its own: it IS the facts, and its rows are
        # the summary.
        self.assertEqual(got["flat.sums"].split("|")[0], "")

    def test_the_facts_strip_is_pinned_while_the_rest_scrolls(self):
        """Measured at 1100x900 with a board of 20 cards: the box is 1025px, so
        the accordion is the layout, the strip sits 164px down the page (the
        status bar and the tribe row are above it) and the sections run to 2900px
        below that. One scroll of 300px takes the strip's viewport top from 164 to
        0 — stuck at `top:0` — while the first section under it moves to 0 as
        well, i.e. by the whole scroll distance. Both numbers are read from the
        two ends of one scroll, because one screenshot cannot tell a pinned strip
        from a strip that happens to be at the top."""
        got = self.got
        self.assertEqual(got["a.factspin"], "sticky",
                         "the facts strip is not a sticky element")
        before, after = got["a.scroll"].split(",")
        f0, s0 = [int(v) for v in before.split("/")]
        f1, s1 = [int(v) for v in after.split("/")]
        self.assertGreater(s0, 0, "the strip is not below the fold to start with")
        self.assertEqual(s1, 0, "the strip did not come to rest at the top")
        self.assertEqual(got["a.factsat"].split(",")[1], str(s0),
                         "the strip is not where the scroll measurement put it")
        # The strip and the section below it both end at the top, which is what
        # "the page scrolled under the strip" means — and the strip STARTED below
        # the section's line, so it was carried to the top rather than being
        # there all along.
        self.assertEqual(f1, 0)
        self.assertGreater(f0, s0 - 1)
        self.assertGreater(s0 - s1, 40,
                           f"the scroll was too small to measure anything "
                           f"({s0} -> {s1})")

    def test_the_accordion_headers_are_the_designs_target_size(self):
        """§8's 44px minimum click target, measured on the control that replaced
        the tab row rather than declared in the sheet."""
        got = self.got
        self.assertGreaterEqual(got["flat.tabh"], 44,
                                "the accordion header is under the 44px target")

    def test_the_sections_are_shut_by_default_and_say_so(self):
        """The three the player CONSULTS are shut — five open sections is a stack
        five screens tall — and the two they read the game through are open."""
        got = self.got
        self.assertEqual(got["flat.shut"], "Comps|Next opponent|Lobby")
        self.assertNotIn("Tavern", got["flat.shut"])
        self.assertNotIn("Board and hand", got["flat.shut"])

    def test_a_narrow_window_collapses_to_one_column(self):
        """The third width: 640x900 gives the box 565px — the same accordion, one
        column of it. Every section shares an x and each top is above the next, so
        the sections are stacked rather than squeezed side by side."""
        got = _render([_shot("n", _comps_payload())], size=(640, 900))
        self.assertLess(int(got["n.bodyw"]), 700)
        self.assertEqual(got["n.arr"], "acc")
        self.assertEqual(got["n.panels"],
                         "Facts|Tavern|Board and hand|Comps|Next opponent|Lobby")
        self.assertEqual(got["n.colw"], "",
                         "a 640px window rendered the three-column layout")
        lefts = {v.split(",")[0] for v in got["n.sectat"].split("|")}
        tops = [int(v.split(",")[1]) for v in got["n.sectat"].split("|")]
        self.assertEqual(len(lefts), 1, f"the sections are not one column: {lefts}")
        self.assertEqual(tops, sorted(tops), f"the sections are out of order: {tops}")
        # ...and it still says what each one holds, which is what the summary line
        # is for: at this width a section can be off screen entirely.
        self.assertIn("3 offers", got["n.sums"])


class TestTheAccordionStateSurvivesARerender(_Rendered):
    """The way this item ships broken (fix list round 4 item 5).

    The shop is re-read every 5 seconds (`live.SHOP_REREAD_SECONDS`) and the page
    re-renders the WHOLE tavern view whenever the payload string changes, so a
    section whose state lived in the DOM only would pop open or shut under the
    player's hands every 5 seconds. The state is re-applied from localStorage on
    every render, and `toggle` in the driver is the real thing: it clicks the
    header and renders AGAIN.
    """

    @classmethod
    def size(cls):
        # The state lives in the ACCORDION, so this class runs where the
        # accordion is the arrangement (the same 1100x900 window as
        # `TestTheAccordionLayout`).
        return (1100, 900)

    @classmethod
    def shots(cls):
        return [_shot("persist", _payload(), toggle="Comps"),
                _shot("stored", _payload(), open="-Comps,-Lobby"),
                # The key is read in a try/catch and PARSED defensively: private
                # mode, a half-written value and a value from an older version all
                # have to render the page.
                _shot("garbage", _payload(), open="junk,,nonsense,,"),
                _shot("nothing", _payload())]

    def test_a_toggled_section_survives_the_next_render(self):
        got = self.got
        # The click landed: Comps is shut by default, so the header's click opens
        # it, and the driver reports the state AFTER re-rendering the same
        # payload (what the 5s poll does, and the only thing that can pop a
        # section open).
        self.assertEqual(got["persist.shut"], "Next opponent|Lobby",
                         "clicking the Comps header did not stick across a "
                         "re-render — the open/closed state is not re-applied "
                         "from storage")
        self.assertEqual(got["persist.panelcount"], 6,
                         "the zero-ish shut list above is a page that rendered "
                         "nothing")

    def test_a_stored_state_is_what_renders(self):
        """The other direction, and the one that makes the test above mean
        something: a stored `-Comps` has to come back SHUT, or "survives a
        re-render" would also be satisfied by a page that ignores storage."""
        got = self.got
        self.assertEqual(got["stored.shut"], "Comps|Next opponent|Lobby",
                         "a stored shut section rendered open (Next opponent is "
                         "shut by default, so it is the control)")
        self.assertNotIn("Tavern", got["stored.shut"],
                         "a section with nothing stored lost its default")

    def test_a_garbage_stored_value_cannot_break_the_render(self):
        """A value the page cannot parse costs the player their open/closed state
        and NOTHING else: every section renders, with its default."""
        got = self.got
        self.assertEqual(got["garbage.panels"], got["nothing.panels"],
                         "a garbage value changed which sections render")
        self.assertEqual(got["garbage.shut"], got["nothing.shut"],
                         f"a garbage value was partly believed: "
                         f"{got['garbage.shut']}")
        self.assertEqual(got["nothing.shut"], "Comps|Next opponent|Lobby",
                         "the defaults are not the two-open three-shut set")

    def test_the_summaries_carry_no_verdict(self):
        """The header summaries are the newest place a verdict could appear, so
        they are scanned here as well as in `TestTheViewCarriesNoVerdict` (which
        has the whole vocabulary)."""
        got = self.got
        text = got["nothing.sums"].lower()
        self.assertTrue(text.strip(), "no summaries rendered, so nothing was "
                                      "scanned")
        for word in ("best", "should", "worth ", "rank", "hunt", "you want",
                     "priorit"):
            self.assertNotIn(word, text)


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
                _shot("lobby", _payload(), reveal="Lobby"),
                _shot("comps", _comps_payload(), reveal="Comps"),
                # §4.4's Detail and Compare are screens too, and the guide block
                # is prose from the meta DB: if a verdict can reach this view,
                # these are the two places it would.
                _shot("detail", _comps_payload(), reveal="Comps",
                      clicks=[_open("Elementals")]),
                _shot("compare", _comps_payload(), reveal="Comps",
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
        # ONE DECIMAL EVERYWHERE (item A, 2026-10-14): the rows too.
        self.assertIn("Avg place=3.2", got["pick.pickrows"])
        self.assertIn("Top 4=62.0%", got["pick.pickrows"])
        # Game order again: Ann was offered first, so her 30.0% leads even though
        # Zed's 60.0% would win any ranking.
        self.assertEqual(got["pick.pickhead"], "30.0%|60.0%",
                         "the headline figures follow the option order, and carry "
                         "one decimal (fix list round 1 item 2)")
        self.assertEqual(got["pick.picklbl"], "Picked|Picked",
                         "the headline figure says what it is")
        self.assertIn("+15.0 vs offered avg", got["pick.pickvs"],
                      "the distance from the offered average, stated")
        # The offered average itself is on the source line: the ± figure has to
        # be relative to something the player can see.
        self.assertIn("Offered average: 45.0% picked", got["pick.picknote"])

    def test_the_compact_card_is_art_left_and_content_right(self):
        """Item A (2026-10-14): the option is a HORIZONTAL card — art on the
        left at a 3/4 ratio, everything else stacked to its right — and its
        min-height is what stops the grid jumping between payloads.

        The art's HEIGHT is the clamped number; the width follows from the
        ratio, so the assertion is the ratio rather than a pixel width (the
        design's 72x96 is what the nominal window gives, and 14vh is what a
        real one gives).
        """
        got = self.got
        self.assertEqual(got["pick.pick"], 2, "both options are cards")
        self.assertEqual(got["pick.pickartratio"], "1.333",
                         f"the art is not 3/4: {got['pick.pickart']}")
        # Art LEFT of the name: the art's box ends before the name's begins.
        self.assertEqual(got["pick.pickabove"], 1,
                         "the pick screen is not above the dashboard")
        art_w, art_h = (int(v) for v in got["pick.pickart"].split("x"))
        self.assertGreaterEqual(art_h, 64)
        self.assertLessEqual(art_h, 128)
        self.assertGreater(art_w, 0)
        # The card is at least the design's floor, and every card is that tall
        # or taller: a card with less data must not shrink its row.
        self.assertGreaterEqual(int(got["pick.pickcard"].split("x")[1]), 144)
        heights = [int(h) for h in got["pick.pickcards"].split("|")]
        self.assertEqual(len(heights), 2)
        self.assertTrue(all(h >= 144 for h in heights), got["pick.pickcards"])
        # The name is one or two lines — bold 15px.
        self.assertLessEqual(got["pick.picknameh"], 40)
        # ONE line of headline: a wrapped one would be ~2x a single line.
        self.assertEqual(got["pick.pickhead"].count("|"), 1,
                         "the headline did not render once per option")

    def test_the_option_grid_is_four_wide_then_two_then_one(self):
        """Item A's layout by WIDTH: one row of four at >=1500px, two by two from
        700 to 1500, one column under 700. Four options, so the counts are the
        assertion at every size — and at >=1500 each column is at least 200px.
        """
        shots = [_shot("pick", _hero_pick_payload())]
        wide = _render(shots, size=(1600, 900))
        self.assertEqual(len(wide["pick.pickcolx"].split("|")), 4)
        self.assertEqual(len(set(wide["pick.pickcolx"].split("|"))), 4,
                         "the four options are not in four columns")
        self.assertEqual(len(set(wide["pick.pickcoly"].split("|"))), 1,
                         "the four options are not on ONE row")
        for w in (int(v) for v in wide["pick.pickcolx"].split("|")):
            self.assertGreaterEqual(w, 0)
        self.assertGreaterEqual(wide["pick.pickcolw"], 200,
                                "a wide column is under the design's 200px")
        mid = _render(shots, size=(1100, 700))
        self.assertEqual(len(set(mid["pick.pickcolx"].split("|"))), 2,
                         "1100px is not a 2x2 grid")
        self.assertEqual(len(set(mid["pick.pickcoly"].split("|"))), 2,
                         "1100px is not a 2x2 grid")
        narrow = _render(shots, size=(640, 700))
        self.assertEqual(len(set(narrow["pick.pickcolx"].split("|"))), 1,
                         "under 700px is not a single column")
        # The design's own art size at that width.
        self.assertEqual(narrow["pick.pickart"], "57x76",
                         f"the narrow art is not 56x76-ish: "
                         f"{narrow['pick.pickart']}")

    def test_a_four_option_hero_pick_fits_a_1100x700_window(self):
        """The done-when: a four-option HERO pick fits a 1100x700 window with no
        scroll, each name appears once, and a card with no data says "No data"
        on ONE line.

        "No scroll" is measured, not inferred: the pick panel's own bottom is
        inside the viewport, so all four options are on screen without scrolling
        for them. The panel is above the dashboard, so what fits is the whole
        pick screen, and the tavern/comps/facts stay below it.
        """
        got = _render([_shot("pick", _hero_pick_payload())], size=(1100, 700))
        self.assertEqual(got["pick.pick"], 4, "the fixture is not four options")
        self.assertEqual(got["pick.pickabove"], 1,
                         "the pick screen is not above the dashboard panels")
        self.assertLessEqual(got["pick.pickbottom"], got["pick.vh"],
                             f"the pick panel runs past the fold: "
                             f"{got['pick.pickbottom']} > {got['pick.vh']}")
        # Every option's name appears exactly once inside its own card.
        self.assertEqual(got["pick.picknamecount"], "1|1|1|1",
                         f"a name is on screen twice: {got['pick.picknamecount']}")
        self.assertEqual(got["pick.pickartno"], 0,
                         "the art carries its own name caption again")
        # The hero's subline is the hero POWER, on ONE line with the whole text
        # on the hover (a trinket has no subline at all, which is why this is
        # measured here and not on the trinket shot).
        self.assertTrue(got["pick.picksub"], "no option rendered a subline")
        self.assertEqual(got["pick.picksubwrap"], "nowrap")
        self.assertEqual(got["pick.picknodata"], "No data")
        self.assertIn("No data for this card on this patch yet.",
                      got["pick.picknodatatitle"],
                      "the patch detail is not on the hover")
        self.assertIn("No data", got["pick.picknodata"])

    def test_the_source_line_is_one_line_with_the_whole_text_on_hover(self):
        """Item A: "Source line on one line with ellipsis (full text on hover),
        12px gap before the cards"."""
        got = self.got
        self.assertIn("nowrap", got["pick.picksrc"])
        self.assertIn("hidden", got["pick.picksrc"])
        self.assertIn("ellipsis", got["pick.picksrc"])
        self.assertIn("title", got["pick.picksrc"],
                      "the truncated source line has no full-text hover")
        self.assertEqual(got["pick.picksrcgap"], "12px")

    def test_the_pick_screen_names_each_option_once(self):
        """Fix list round 1 item 2 / round 2 item 1, tightened by item A: the
        art carries no caption at all now, so the name beside it is the only one
        — and the card's own name is what the count is taken from."""
        got = self.got
        self.assertEqual(got["pick.renameless"], 0,
                         "the option's art still carries its own name caption")
        self.assertEqual(got["pick.picknames"], "Ann|Zed")
        self.assertNotIn("Picked in", got["pick.pickrows"],
                         "the pick rate is still repeated as a stat row")
        self.assertEqual(got["pick.picknamecount"], "1|1")
        # The full name is on the card's own title, however the name clamps.
        self.assertIn("Ann", got["pick.picknames"])

    def test_the_pick_controls_are_one_row_and_the_card_is_wide_enough(self):
        """Item A's controls: Hero | Trinket | Discover, Stats shown and Order
        on ONE row, and each option column at least 200px at >=1500."""
        got = self.got
        self.assertGreaterEqual(got["pick.pickcolw"], 200,
                                "an option column is narrower than 200px")
        # One row of controls: a wrapped row would be ~2x a single button.
        self.assertLess(got["pick.pickctlvp"], 60)
        # ...and all three groups are in it, so nothing was dropped: the three
        # kinds, the Stats-shown set, and the Order set.
        for label in ("Hero:", "Trinket:", "Discover:", "avg place:", "top 4:",
                      "As offered:", "By picked %:"):
            self.assertIn(label, got["pick.pickctl"],
                          f"the pick row lost {label!r}")

    def test_a_stats_shown_toggle_removes_that_row(self):
        """§4.3: "Stats shown lets the player toggle which rows appear (also how
        new fields get added later)." """
        got = _render([_shot("pick", _choice_payload(), click="top 4")])
        self.assertNotIn("Top 4=", got["pick.pickrows"])
        self.assertIn("Avg place=3.2", got["pick.pickrows"])
        self.assertIn("top 4:off", got["pick.pickctl"])

    def test_no_option_without_data_invents_a_row(self):
        """§6.2/§5: an option the DBs have nothing for says so, and shows no
        rows — rather than a zero or a guess. Item A shortens the sentence to
        "No data" and moves the patch detail to the hover, so the card keeps the
        same height as every other one."""
        rep = _payload(choice={"kind": "hero", "source": "Choose One",
                               "ranked": [["Nobody", "BG31_999", 0.0, "", 0]],
                               "option_stats": {}, "guides": {}})
        got = _render([_shot("bare", rep)])
        self.assertEqual(got["bare.picknodata"], "No data")
        self.assertIn("No data for this card on this patch yet.",
                      got["bare.picknodatatitle"])
        self.assertEqual(got["bare.pickrows"], "")
        # The old sentence is NOT on the card: it was the line that wrapped.
        self.assertNotIn("No data for this card on this patch yet.",
                         got["bare.alltext"])
        # Same height as a card with data — the design's "same card height".
        self.assertGreaterEqual(int(got["bare.pickcard"].split("x")[1]), 144)


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
        return [_shot("browse", base, reveal="Comps"),
                _shot("overlap", base, reveal="Comps",
                      clicks=[[".lv-ctl .lv-chip", "Overlap"]]),
                _shot("more", base, reveal="Comps", clicks=[[".lv-more", "+ 1 more"]]),
                _shot("noavg", _comps_payload(corpus={}), reveal="Comps"),
                # The detection window, marked by the PRODUCER's own rule so the
                # "unconfirmed" reads below are about the page and not the
                # fixture (item B.1).
                _shot("detecting", _comps_marked(tribes_detecting=True),
                      reveal="Comps"),
                # Five tribes confirmed, and this fixture's comps split three
                # ways by them: Mech is banned this game, Naga is out of play,
                # Beast/Elemental/Mixed are in. THE DONE-WHEN SHOT.
                _shot("banned", _comps_after_bans(), reveal="Comps"),
                # The out-of-play block, shut and then opened for real.
                _shot("oopsum", base, reveal="Comps"),
                # Names the shipped DB really carries, at the width the comps
                # column really gets: the row has to hold a two-line name.
                _shot("longname", _comps_with_long_names(), reveal="Comps"),
                _shot("oopopen", base, reveal="Comps",
                      clicks=[[".lv-oopsum", "Out of play · 1"]]),
                # THE RECOMPUTE: a tick on a comp that the NEXT payload takes out
                # of the lobby. A stale tick would keep a Compare column alive for
                # a row nobody can see (item B.1's "recompute on every tribe
                # change").
                _shot("recut", _comps_without_beast(), reveal="Comps",
                      pre=base, preclicks=[_compare("Beasts")]),
                _shot("detail", base, reveal="Comps",
                      clicks=[_open("Elementals")]),
                _shot("back", base, reveal="Comps",
                      clicks=[_open("Elementals"), [".lv-back", "◀ Comps"]]),
                _shot("compare", base, reveal="Comps",
                      clicks=[_compare("Elementals"), _compare("Beasts"),
                              _compare("Menagerie")]),
                _shot("four", base, reveal="Comps",
                      clicks=[_compare("Elementals"), _compare("Aardvark"),
                              _compare("Beasts"), _compare("Menagerie"),
                              _compare("Filler 1")])]

    def test_browse_is_one_column_per_source_tier_with_a_cap(self):
        got = self.got
        self.assertEqual(got["browse.comptiers"], "S tier · 2|A tier · 7")
        # The S column: both comps, the payload's tier-then-name order. The avg
        # cell is EMPTY for a comp the corpus has never seen (item B.2: "no '—'
        # on each row") — the column still exists, its value does not.
        self.assertTrue(got["browse.comprows"].startswith(
            "Elementals|3 of 3 owned|3.83 ; Menagerie|1 of 2 owned|"),
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
        holds 520px, never three — the cap is `max-width:calc(50% - 9px)`, which a
        viewport media query cannot express.

        NARROWED 2026-10-13 (fix list round 4 item 5). While the comps screen was
        the page's whole main column, a 2600px window made two 520px columns fit
        and this test measured exactly that. The three-column layout gives the
        comps panel ONE of three: MEASURED, its box is 499px at 1400x900 and 622px
        at 1920x1080 and at a 3200px window — the tavern container maxes out at
        1572px — and two 520px columns need 1058. So the side-by-side pair is not
        reachable in this arrangement at ANY window size. What holds in both is
        the column count and the fit: never three, and never wider than the box
        (the flat `min-width:520px` inside a 499px panel laid both columns out at
        the same x, 520px each, on top of one another — measured 2026-10-13).
        """
        got = self.got
        self.assertLessEqual(got["browse.cols"], 2,
                             f"{got['browse.cols']} comps columns on screen")
        self.assertEqual(got["browse.h4pos"], "sticky",
                         "the tier headers do not stick")
        box = int(got["browse.compsw"])
        for w in [int(v) for v in got["browse.ctierw"].split("|")]:
            self.assertLessEqual(w, box + 1,
                                 "a tier column is wider than the screen it is "
                                 "in — the flex floor is not capped at the box")
        # Wider than any of it: the same is true at a 3200px window, where the
        # comps panel is at its widest (622px) and still one column short of a
        # pair — the control proving the stack above is not a narrow-window
        # accident.
        wide = _render([_shot("w", _comps_payload(), reveal="Comps")],
                       size=(3200, 1200))
        self.assertGreater(int(wide["w.compsw"]), 600,
                           "the fixture is not measuring a wide comps panel")
        self.assertEqual(wide["w.cols"], 2,
                         "the payload carries two tiers, so two columns render")
        xs = [int(x) for x in wide["w.ctierx"].split("|")]
        self.assertEqual(len(set(xs)), 1,
                         "two 520px columns cannot fit a 622px panel, so they "
                         "stack — a second x here would mean they overlap")
    def test_the_avg_column_is_hidden_until_the_corpus_has_data(self):
        """Round 3 item 5, tightened by round 4 item 6: a column of dashes is a
        column of nothing, and the decision is the WHOLE list's rather than one
        tier group's — per group, the tracks changed as you scrolled."""
        got = self.got
        self.assertGreater(got["browse.avgcells"], 0,
                           "the fixture has corpus data, so the column is there")
        self.assertEqual(got["browse.hasavg"], got["browse.cols"])
        # Six tracks with the avg column: checkbox | name | tier·tribe | strip |
        # owned | avg (round 4 item 6 — the checkbox and the tier/tribe used to
        # be inside the name cell, so nothing lined up down the column).
        self.assertEqual(len(got["browse.cmptracks"].split()), 6,
                         got["browse.cmptracks"])
        self.assertEqual(got["noavg.avgcells"], 0,
                         "a column of dashes is printed where the corpus is "
                         "empty")
        self.assertEqual(got["noavg.hasavg"], 0)
        self.assertIn("Elementals|3 of 3 owned", got["noavg.comprows"])
        # Five tracks instead of six: the avg column is gone, not empty.
        self.assertEqual(len(got["noavg.cmptracks"].split()), 5,
                         got["noavg.cmptracks"])
        # ...and where the column DOES exist, a row the corpus has never seen
        # leaves its cell empty rather than printing a dash (item B.2).
        self.assertGreaterEqual(got["browse.apempty"], 1,
                                f"no row left its avg cell empty: "
                                f"{got['browse.apvals']}")
        self.assertNotIn("—", got["browse.apvals"])

    def test_the_comps_panel_has_no_second_tribe_chip_row(self):
        """Round 3 item 4: the page has ONE tribe row, above the tabs, and the
        comps panel had a copy of it.

        Round 4 item 1 reworded the per-row note to "· not available" (available
        comps are marked, not dropped), which killed the /unconfirmed/ read this
        test used: it matched nothing and both assertions passed vacuously. Item
        B.1 (2026-10-14) then changed WHAT is listed — the main list is the
        comps this lobby offers, and the out-of-play ones moved to their own
        collapsed block — so the `unavail` read moves with it: the MAIN list has
        no dimmed row at all, and the block is where the dimmed rows live. The
        block's read (`ooprows`) is the positive control: it proves the class is
        still on the page for the count of zeros above to mean anything.
        """
        got = self.got
        self.assertEqual(got["browse.ctlchips"],
                         "Source tier|Overlap|Avg placement",
                         "the comps controls are not just the sort chips")
        self.assertNotIn("Lobby tribes", got["browse.compspaneltext"],
                         "the comps panel has its own tribe chip row again")
        self.assertGreater(got["browse.crowrows"], 0,
                           "the comps list rendered no rows at all, so the "
                           "dimmed-row read below proves nothing")
        self.assertEqual(got["browse.maindim"], 0,
                         "a comp row in the main list is dimmed although every "
                         "tribe in it is available")
        # The harness strips values, so the leading space of the header note is
        # not part of what comes back.
        self.assertEqual(got["detecting.hnote"], "· tribes not confirmed yet")
        self.assertGreater(got["detecting.crowrows"], 0)
        self.assertEqual(got["detecting.maindim"], 0,
                         "an unconfirmed tribe with fewer than five confirmed is "
                         "AVAILABLE (item B.1), so no row dims here")
        # The POSITIVE control: the out-of-play block's rows ARE dimmed, so the
        # zero above is a measurement rather than a read that cannot rise.
        self.assertGreaterEqual(got["browse.ooprows"], 1,
                                "the out-of-play block rendered no rows, so the "
                                "dimmed-row read proves nothing")
        self.assertEqual(got["browse.oopdim"], "0.55")
        # ...and one chip row for the tribes, on the page itself.
        self.assertIn("BEAST", got["detecting.chips"])

    def test_a_comp_row_is_a_grid_with_the_strip_and_the_name_in_it(self):
        """Round 3 item 2 gave the row its tracks; round 4 item 6 fixed what is
        IN them: `22px | name | tier·tribe | strip | 64px | 90px`, one cell per
        column in the same order on every row. The checkbox and the tier/tribe
        used to live inside the name cell, so nothing lined up down the list."""
        got = self.got
        tracks = got["browse.cmptracks"].split()
        self.assertEqual(len(tracks), 6, got["browse.cmptracks"])
        self.assertEqual(tracks[0], "22px", "the checkbox column is first")
        self.assertIn("64px", tracks)
        self.assertIn("90px", tracks)
        self.assertEqual(got["browse.stripwrap"], "nowrap",
                         "the core strip still wraps")
        # The slots SHRINK since 2026-10-14 (item B.2 measured it): six 40px
        # slots plus the avg track do not fit a 499px comps panel, and
        # `flex:none` pushes the row out of its own box instead of letting the
        # strip give up width.
        self.assertEqual(got["browse.slotflex"], "0 1 auto",
                         "a slot cannot give up width when the row is full")
        self.assertEqual(got["browse.nameclamp"], "2",
                         "the comp name is not clamped to two lines")
        self.assertEqual(got["browse.slotpx"], "40x54")
        # The compare box sits at the START of the row, in flow: the name is to
        # its right, so nothing is over anything.
        withbox = _render([_shot("wb", _comps_payload(), reveal="Comps",
                                 clicks=[[".lv-cmpbox", None, "Beasts"]])])
        self.assertEqual(withbox["wb.cmpchecked"], 1)
        self.assertEqual(withbox["wb.rowcols"], "grid")

    def test_a_comp_row_is_the_designs_four_parts(self):
        """Item B.2: `[checkbox] [name, up to 2 lines, tribe on the second line]
        [card strip] [N of M owned]`, the same on every row.

        The compare control is a checkbox with a TOOLTIP and no visible word —
        the word "compare" sat in the row and collided with the name — so this
        reads the absence of the label element, the presence of the tooltip, and
        the accessible name that replaced the label.
        """
        got = self.got
        self.assertEqual(got["browse.cmplbl"], 0,
                         "the word 'compare' is still in the row")
        self.assertEqual(got["browse.cmpboxes"], got["browse.crowrows"],
                         "a main-list row has no compare box")
        self.assertEqual(got["browse.cboxlabel"], "Compare Elementals",
                         "the checkbox has no accessible name")
        # The tribe is on the line UNDER the name, in the row's own text colour.
        self.assertIn("BEAST", got["browse.tribetext"])
        self.assertEqual(got["browse.tribecolor"], got["browse.ownedcolor"],
                         "the tribe is not in the row's normal text colour")
        # The name column takes the space that is left, and the whole name is
        # reachable however it clamps — the first row's, which is Elementals.
        self.assertEqual(got["browse.nametitle"], "Elementals")
        self.assertGreater(got["browse.cnametitles"], 0)
        # NO per-row tier in the default sort: the tier column's own header says
        # it. It comes back under the two opt-in sorts, where the header is no
        # longer what you are reading.
        self.assertEqual(got["browse.tierchips"], 0,
                         "a row repeats the tier its column header states")
        self.assertGreater(got["overlap.tierchips"], 0,
                           "the opt-in sorts do not show the tier on the row")

    def test_the_out_of_play_block_is_collapsed_grouped_and_uncomparable(self):
        """Item B.1: comps for tribes KNOWN to be out of play move to a collapsed
        "Out of play · N" block at the bottom — dimmed, grouped by tribe, and
        with no compare checkbox.

        Naga is rotated this patch, so the Nagas comp is the block's only row in
        this fixture. The block is SHUT until it is asked for, and opening it
        really does put the rows on screen (the click is what proves that).
        """
        got = self.got
        self.assertEqual(got["oopsum.oopsum"], "Out of play · 1")
        self.assertEqual(got["oopsum.oopopen"], 0, "the block starts open")
        self.assertEqual(got["oopsum.ooprows"], 1)
        self.assertNotIn("Nagas", got["oopsum.comprows"],
                         "an out-of-play comp is in the main list")
        self.assertEqual(got["oopsum.oopnames"], "Nagas")
        # GROUPED BY TRIBE, and the group header is the tribe.
        self.assertEqual(got["oopsum.ooptribes"], "NAGA")
        # DIMMED, and with no compare box on any of its rows.
        self.assertEqual(got["oopsum.oopdim"], "0.55")
        self.assertEqual(got["oopsum.oopboxes"], 0,
                         "an out-of-play comp offers a compare box")
        # THE POSITIVE CONTROL for the "collapsed" half: the same payload with
        # the summary clicked does show the row, so the count above is not a
        # block that simply rendered nothing.
        self.assertEqual(got["oopopen.oopopen"], 1)
        self.assertEqual(got["oopopen.ooprows"], 1)

    def test_five_confirmed_tribes_leave_only_those_tribes_in_the_list(self):
        """THE DONE-WHEN for item B.1: with five tribes confirmed, the main list
        shows only those tribes (plus Mixed), and the out-of-play comps are in
        the collapsed block.

        The fixture's comps split three ways under `<five>`: Elemental and Beast
        are in this lobby, Mech is BANNED this game, Naga is out of play. So the
        main list is Elementals + Menagerie (Mixed) + Beasts — three rows — and
        the six Mech comps are in NEITHER list, which the note says out loud
        rather than shortening the list in silence.
        """
        got = self.got
        names = [r.split("|")[0] for r in got["banned.comprows"].split(" ; ")]
        self.assertEqual(names, ["Elementals", "Menagerie", "Beasts"],
                         f"the main list is not the confirmed tribes: {names}")
        self.assertTrue(got["banned.comptiers"].startswith("S tier · 2"),
                        got["banned.comptiers"])
        # The main list header is the count of that list.
        self.assertIn("3 in this lobby", got["banned.sums"])
        # The out-of-play comp is in the block, not the list...
        self.assertEqual(got["banned.ooprows"], 1)
        self.assertEqual(got["banned.oopnames"], "Nagas")
        # ...and the six that are in neither are counted in the note.
        self.assertIn("6 comps for tribes this lobby does not offer are not "
                      "listed.", got["banned.notes"])
        self.assertNotIn("Aardvark", got["banned.comprows"])

    def test_comp_rows_do_not_overlap_and_a_long_name_wraps(self):
        """THE DONE-WHEN: "Comp rows don't overlap, and a long name wraps to two
        lines."

        Overlap is measured from the row RECTANGLES — two rows in one list must
        not share a pixel of vertical space, and no row may reach past the right
        edge of the panel it is in (the strip's slots shrank from 34px to 40px in
        item B.2, and the six-card cores plus the avg track are what that width
        has to fit). The long-name half uses the names the shipped DB carries,
        because a fixture's short names would never wrap.
        """
        boxes = [[int(v) for v in b.split(",")]
                 for b in self.got["browse.crowboxes"].split()]
        self.assertGreater(len(boxes), 2, "the list rendered almost no rows")
        for i in range(1, len(boxes)):
            self.assertGreaterEqual(
                boxes[i][1], boxes[i - 1][3],
                f"row {i} starts ({boxes[i][1]}) inside row {i - 1} "
                f"(ends {boxes[i - 1][3]})")
        panel = int(self.got["browse.compsw"])
        self.assertGreater(panel, 0)
        for b in boxes:
            self.assertLessEqual(b[2] - b[0], panel,
                                 f"a row is wider than the panel: "
                                 f"{b[2] - b[0]} > {panel}")
        # A LONG NAME, in the shipped DB's own words.
        long_rows = self.got["longname.comprows"].split(" ; ")
        self.assertTrue(any(" - " in r for r in long_rows),
                        f"the fixture has no long comp name: {long_rows[:3]}")
        # Two lines of name, tribe under it: taller than one line (18px) and
        # shorter than three (54px). The clamp is what keeps a third line out.
        self.assertGreater(self.got["longname.cnameh"], 18)
        self.assertLessEqual(self.got["longname.cnameh"], 40)
        self.assertEqual(self.got["longname.nameclamp"], "2")
        # ...and those rows still fit their panel, which is the pair of facts the
        # done-when asks for together.
        for b in ([int(v) for v in x.split(",")]
                  for x in self.got["longname.crowboxes"].split()):
            self.assertLessEqual(b[2] - b[0],
                                 int(self.got["longname.compsw"]))

    def test_a_tribe_change_recuts_the_view_state(self):
        """Item B.1: "Recompute the list on every tribe change."

        The rows are derived from the payload on every render, so that half is
        automatic; the VIEW state that points into the list is not. The `recut`
        shot ticks the Beasts row while BEAST is one of the five, then renders a
        payload where it is not — and the tick has to be gone, because a slug that
        has left the list would keep a Compare column alive for a comp nobody can
        see.
        """
        got = self.got
        self.assertNotIn("Beasts", got["recut.comprows"],
                         "the fixture did not take Beasts out of the lobby")
        self.assertGreater(got["recut.crowrows"], 0,
                           "the recut payload rendered no rows at all")
        self.assertEqual(got["recut.cmpchecked"], 0,
                         "a compare box is still ticked for a comp that has left "
                         "the list")

    def test_an_unconfirmed_tribe_stays_in_the_list_marked(self):
        """Item B.1: "Tribes that are unconfirmed (fewer than 5 confirmed) stay
        in the main list with a small 'unconfirmed' marker."

        The payload publishes the COUNT of confirmed tribes and the window flag,
        not which ones — so while the window is open every tribe-bearing row is
        marked, and the moment the five land the markers are gone. Both halves
        are measured, because only the pair says the marker tracks the window
        rather than being a permanent decoration.
        """
        got = self.got
        # While the window is open every main-list row that HAS a tribe is
        # marked; Mixed has no tribe to confirm, so it carries no marker. The
        # tier cap means the fixture shows 8 of the 9 rows — the count comes from
        # the rows that RENDERED, not from the payload.
        tribes = got["detecting.tribetext"].split("|")
        self.assertEqual(len(tribes), got["detecting.crowrows"])
        with_tribe = [t for t in tribes if t != "Mixed"]
        self.assertGreater(len(with_tribe), 0)
        self.assertEqual(got["detecting.uncf"], len(with_tribe),
                         f"the markers do not cover the tribe rows: {tribes}")
        self.assertEqual(got["detecting.tribetext"].count("unconfirmed"),
                         len(with_tribe))
        # With five confirmed, the list is exact and nothing is marked.
        self.assertEqual(got["banned.uncf"], 0)
        self.assertNotIn("unconfirmed", got["banned.tribetext"])

    def test_the_compare_box_and_the_comp_name_are_themed(self):
        """Round 3 item 6: a themed checkbox, and names underlined on hover
        only — a column of permanent underlines read as a wall of links."""
        got = self.got
        self.assertIn("none", got["browse.cmpskin"],
                      "the checkbox is still the browser's default control")
        self.assertEqual(got["browse.nameunder"], "none",
                         "every comp name wears an underline")
        hovered = _render([_shot("h", _comps_payload(), reveal="Comps",
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
        played sort last rather than at zero (with an EMPTY avg cell, since item
        B.2 dropped the per-row dash)."""
        got = _render([_shot("avg", _comps_payload(), reveal="Comps",
                             clicks=[[".lv-ctl .lv-chip", "Avg placement"]])])
        rows = got["avg.comprows"].split(" ; ")[2:]
        self.assertTrue(rows[0].startswith("Aardvark|0 of 1 owned|2.00"), rows[0])
        self.assertTrue(rows[1].startswith("Beasts|2 of 2 owned|4.00"), rows[1])
        self.assertTrue(rows[2].endswith("|"), rows[2])
        self.assertEqual(rows[2].split("|")[2], "",
                         f"a dash is back in the avg cell: {rows[2]}")

    def test_an_out_of_play_comp_is_not_in_the_main_list_at_all(self):
        """Item B.1: an out-of-play tribe's comps leave the main list for their
        own block, and the main list's count no longer claims them.

        This replaces round 4 item 1's "marked, not dropped" pin for THIS case:
        the row is still on the page — one block down, dimmed, under its tribe —
        but it is not one of the comps the panel header counts as in the lobby.
        """
        got = self.got
        self.assertNotIn("Nagas", got["browse.comprows"])
        self.assertEqual(got["browse.oopnames"], "Nagas")
        # Ten comps in the fixture, one of them Naga's, so nine are this
        # lobby's — and the tier headers count the same nine (2 + 7).
        self.assertIn("9 in this lobby", got["browse.sums"],
                      "the main list header does not count the main list")

    def test_the_core_slots_are_the_designs_40_by_54(self):
        """Item B.2: "strip thumbnails ~40x54 at 75% opacity". The Compare slot
        stays 52x70 (§5), and a tile is 88-130px wide, so a slot that inherited
        the card rule would be more than twice the specified size."""
        self.assertEqual(self.got["browse.slotpx"], "40x54")
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
        # EVERY slot names its card on the hover (item B.2) — the legend's four
        # included, since the legend is the slot element itself.
        self.assertEqual(got["browse.slottitles"], got["browse.compslots"],
                         "a slot has no title, so its art cannot be read")

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
        `Guide text ▸` collapsed by default."

        The DISTRIBUTION is the only thing left reading `lvBars` (item A took
        the eight bars off the pick card, which has no room for them), so this
        asserts they render here — a renderer nothing reaches is a renderer that
        quietly stops working.
        """
        got = self.got
        self.assertEqual(got["detail.stathead"], "3.83")
        self.assertIn("Games=12", got["detail.statrows"])
        self.assertIn("Top 4=67%", got["detail.statrows"])
        self.assertIn("1st place=17%", got["detail.statrows"])
        self.assertEqual(got["detail.compdistbars"], 8,
                         "the comp detail's distribution is not eight bars")
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
        """The design's §4.4 columns need real width, not a 340px rail, and round
        3 item 3 re-cut how many of them there are (see
        `test_the_comps_columns_are_never_three_wide`).

        REVERSED 2026-10-13 (fix list round 4 item 5). This pinned
        `panelw > 600` — "the comps screens have the main column, not the rail" —
        which was the contract while the comps screen was the MAIN COLUMN and the
        facts table was a 340px rail beside it. The three-column layout gives the
        comps screen a COLUMN of its own by design, and at 1400x900 that column
        is 499px: narrower than the old threshold, and correct. What the design
        still needs from this test is that the comps panel gets a column of its
        own rather than the rail's width, and that the tier columns it renders
        inside it are never squeezed below 520 — which is measured here and one
        test up.
        """
        got = self.got
        self.assertGreater(int(got["browse.compsw"]), 400,
                           "the comps screens are down to the facts rail's width "
                           "again (the 4.4 columns need a column of their own)")
        self.assertGreaterEqual(len(got["browse.colat"].split("|")), 1,
                                "no tier columns rendered")
        # ...and the column is a real page column, not a rail: at 1400x900 the
        # page's three columns measure 499/499/300 (round 4 item 5).
        self.assertLessEqual(len(got["browse.colw"].split("|")), 3)

    def test_a_low_sample_comp_is_flagged_by_games_count(self):
        """§5: "Low sample marker ... Define the threshold by games count, not a
        fixed percent." Beasts has 4 games, Elementals 12, and only one of them
        is flagged — with a chip, not only with the dimming."""
        got = self.got
        self.assertIn("Beasts|2 of 2 owned|4.00|low", got["browse.comprows"])
        self.assertNotIn("Elementals|3 of 3 owned|3.83|low",
                         got["browse.comprows"])
        self.assertEqual(got["browse.lowsamp"], "low sample")


class TestWhatTheShopKeepsSaying(_Rendered):
    """Fix list round 4 items 3 and 4, on the rendered page.

    3(c) the offers that were ROLLED PAST, per turn, keyed by OFFER ENTITY — so
    two copies of one minion are two cards, which is the item's whole point.
    3(b) "read Ns ago" ON the tavern panel, and the tavern mix of what is on
    offer. 4 the announced next opponent, facts only.
    """

    @classmethod
    def shots(cls):
        return [_shot("t", _payload()),
                _shot("dup", _payload(**ROLLED)),
                _shot("last", _payload(**ROLLED_LAST_TURN)),
                _shot("none", _payload(shop_passed=[])),
                _shot("noopp", _payload(opp_comp=None, opp_stats=None,
                                        opp_age=None)),
                _shot("noshop", _payload(shop_rank=[], shop_passed=[]))]

    def test_a_minion_two_copies_were_rolled_past_render_as_two_cards(self):
        """The payload keeps both ENTITY ids and the page draws both cards.

        A card-keyed record can only ever hold one of them: this is the duplicate
        collapse the item exists to undo, one panel over from where round 3
        undid it for the tavern row itself. The row is drawn NEWEST FIRST (the
        generation the player just rolled away from is the one they are looking
        for, and a heavy roll turn leaves 40 cards behind it), which is why the
        spell that left first renders last.
        """
        rep = _payload(**ROLLED)
        self.assertEqual([r["eid"] for r in rep["shop_passed"]],
                         [ROLL_FIRST["eid"], ROLL_SECOND["eid"],
                          ROLL_THIRD["eid"]],
                         "the payload lost an offer entity")
        got = self.got
        self.assertEqual(got["dup.passedcards"], 3,
                         "two copies of one minion did not draw two cards")
        names = got["dup.passednames"].split("|")
        self.assertEqual(len(names), 3)
        self.assertEqual(names[0], names[1],
                         "the two copies are not the same card")
        self.assertNotEqual(names[1], names[2],
                            "the spell is not the minion")
        # ...and the count in the section's own label is the count of CARDS.
        self.assertIn("3", got["dup.passedlbl"])

    def test_the_rolled_past_row_is_a_caption_per_card_and_not_a_price_list(self):
        """The pool chip is a property of the CARD and stays; the PRICE goes,
        because this card can no longer be bought and a price on it invites
        reading the row as an offer."""
        caps = self.got["dup.passedcaps"].split("|")
        self.assertEqual(len(caps), 3)
        self.assertIn("pool left", caps[0])
        self.assertEqual(caps[1], caps[0],
                         "the two copies of one card disagree about the pool")
        self.assertEqual(caps[2], "—",
                         "a tavern spell has no pool figure, and a guess would "
                         "be worse than a dash")
        for cap in caps:
            self.assertIsNone(re.match(r"^\d+\s*g\b", cap),
                              f"the rolled-past row carries a price: {cap!r}")

    def test_only_this_turns_rolls_are_on_the_panel(self):
        """The analysis keeps the WHOLE game (`shop_passed` is per-game state
        with a turn stamp); the panel is per turn, and last turn's roll must not
        be counted in this one's label.

        The fixture carries one row per turn on purpose: a payload that kept
        everything would draw TWO cards here and say 2.
        """
        rep = _payload(**ROLLED_LAST_TURN)
        self.assertEqual([r["eid"] for r in rep["shop_passed"]], [74],
                         "the turn filter is gone from render_json")
        got = self.got
        self.assertEqual(got["last.passedcards"], 1,
                         "last turn's roll is on this turn's panel")
        self.assertIn("1", got["last.passedlbl"])

    def test_a_shop_with_nothing_rolled_past_says_so_rather_than_going_blank(self):
        """Fix list round 4 item 3: a panel that is empty without a state reads
        as a panel that is broken, which is exactly what the maintainer asked to
        stop happening."""
        got = self.got
        self.assertEqual(got["none.passedcards"], 0)
        self.assertEqual(got["none.passednote"], "Nothing rolled past yet this turn.")

    def test_the_panel_says_how_long_ago_it_was_read(self):
        """Item 3(b): the fact belongs on the panel the player is reading, not
        only in the strip above the card — and the same line exists on the empty
        shop, which is the panel where a player most needs it.

        The SHAPE is what a browser can honestly assert. The page counts from
        the payload's own `generated` stamp against the browser's clock, so a
        shot that takes more than a second to render and read says "read 1s
        ago": this test pinned the literal "read just now" and adding a sixth
        shot to this class broke it exactly that way (measured 2026-10-13 — the
        assertion was a race, not a contract). The vocabulary itself ("just
        now", the minute rollover, the ticker that keeps it moving) is pinned at
        the source in `test_live_tavern`'s
        `test_the_panel_carries_its_own_read_age`.
        """
        for panel in ("t", "noshop"):
            self.assertRegex(self.got[panel + ".readage"],
                             r"^read (just now|\d+s ago|\d+ min ago)$",
                             panel + " has no read-age line on its panel")

    def test_the_tavern_mix_counts_the_offers_one_by_one(self):
        """Item 3(b): the tribe composition of the shop, counted per OFFER — two
        copies of one Elemental are two Elementals — with a tavern spell counted
        as a Spell rather than dropped, so the counts add up to the cards drawn
        in the row above."""
        got = self.got
        self.assertIn("Tavern mix", got["t.mixlbl"])
        self.assertIn("1 Elemental", got["t.mixchips"])
        self.assertIn("1 Spell", got["t.mixchips"])
        self.assertIn("2 Elemental", got["dup.mixchips"],
                      "the duplicate offer is not counted as two")
        self.assertIn("Their mix", got["t.mixlbl"])
        self.assertIn("1 Elemental", got["t.mixchips"])

    def test_the_next_opponent_panel_is_their_board_and_its_age(self):
        """Item 4: hero, the board they staged, what it is worth with how long
        ago that was read (`opp_age`), the round the board is from, and its mix.

        NOT the seat's handle: `opp_comp.name` is the opponent's BattleTag and
        it already rides the Lobby tab. This panel is the one that ends up in a
        screenshot, and the rule for those is to keep the handle out.
        """
        got = self.got
        self.assertEqual(
            got["t.opprows"],
            "Hero=Reno|Their board stats=19 (seen 1 round ago)|Last seen=round 8")
        self.assertEqual(got["t.oppcards"], 1)
        self.assertNotIn("SomeHandle", got["t.opptext"],
                         "the opponent's handle reached the panel that gets "
                         "screenshotted")
        self.assertIn("1 Elemental", got["t.mixchips"])

    def test_the_lobby_figure_is_labelled_as_one_on_the_opponent_panel_too(self):
        """A stale exact figure is not shown as exact: with no fresh
        `opp_stats` the panel falls back to the lobby median and SAYS so, the
        same rule the facts rail follows for its own row.

        `lobby_opp`, not `opp_lobby`: `render_json` DERIVES the latter from the
        former, so setting `opp_lobby` in the fixture would prove nothing (the
        same trap `test_the_lobby_figure_is_named_as_an_average` documents).
        """
        got = _render([_shot("lb", _payload(opp_stats=None, opp_age=None,
                                            lobby_opp=59))])
        self.assertIn("Their board stats=~59 lobby avg", got["lb.opprows"])

    def test_a_game_whose_opponent_was_never_seen_says_so(self):
        got = self.got
        self.assertEqual(got["noopp.opprows"], "")
        self.assertEqual(got["noopp.oppempty"], "No opponent board seen yet.")

    def test_the_empty_shop_keeps_the_reason_it_is_empty(self):
        """Item 3: never an empty panel without a state. `lvWaiting` says what
        the page is waiting for AND how old the read is."""
        got = self.got
        self.assertIn("Reading the shop", got["noshop.notes"])
        self.assertEqual(got["noshop.passedlbl"], "")


class TestTheGameOverCard(_Rendered):
    """§6.5, and the reachability bug behind it.

    The end-of-game card arrives on a `welcome: true` payload with no board, and
    `render` used to return at the welcome branch BEFORE the viewer was consulted
    — so the Tavern game-over card could not be reached in a real session at all
    while a direct `renderLiveTavern` call in a test made it look alive. These
    shots go through `render`, so the route is part of what is measured, and
    since 2026-10-13 there is one card: the route no longer consults a viewer and
    the shot that rendered the CLASSIC game-over card is gone with that card.
    """

    @classmethod
    def shots(cls):
        return [_shot("over", _game_over_payload()),
                _shot("auto", _game_over_payload(enabled=True)),
                # A live render, then the game-over payload: the card, not the
                # last shop screen still standing behind it.
                _shot("after", _game_over_payload(), pre=_comps_payload(),
                      preclicks=[_open("Elementals")]),
                _shot("firstrun", _welcome_payload())]

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

    def test_the_render_route_reaches_the_card(self):
        """The bug this class exists for."""
        got = self.got
        self.assertEqual(got["after.tavern"], 1)
        self.assertEqual(got["after.overbig"], "3rd · Round 12")
        self.assertEqual(got["after.tavernon"], 1)
        self.assertEqual(got["after.decidehidden"], 1,
                         "the card slot is not hidden behind the card")

    def test_the_game_over_payload_always_draws_this_card(self):
        """REVERSED 2026-10-13 from
        `test_classic_still_shows_the_classic_game_over_card`, which rendered the
        same payload with the viewer set to classic and asserted the OTHER card
        drew (a card in `#col-decide` and no tavern layout). There is one card
        now, so the honest pin is that the payload reaches it and leaves the slot
        empty — which is what makes the card in the shot not a leftover.
        """
        got = self.got
        self.assertEqual(got["over.tavern"], 1)
        self.assertEqual(got["over.cardslotkids"], 0,
                         "something is still drawing in the card slot")
        self.assertEqual(got["over.decidehidden"], 1)

    def test_a_first_run_card_clears_the_live_view(self):
        """The other half of the same bug: a first-run welcome has no live-view
        design, so it draws the shell card — but the view's container kept its
        last frame and `tavern-on` kept the card slot hidden, so the card
        appeared behind a stale screen. (The card itself is no longer "the
        classic card": it is the only one there is.)"""
        got = self.got
        self.assertEqual(got["firstrun.tavern"], 0)
        self.assertEqual(got["firstrun.tavernon"], 0)
        self.assertEqual(got["firstrun.decidehidden"], 0)
        self.assertGreater(got["firstrun.cardslotkids"], 0,
                           "the welcome card is not on screen")


class TestTheHarnessItself(unittest.TestCase):
    def test_a_broken_payload_is_reported_rather_than_swallowed(self):
        """The rehearsal, and it has to break something THIS view reads: a shop
        the renderer iterates. (Breaking `board` would prove nothing — the view
        reads `board_cards`, and a payload with no `board` at all is a shape
        `live.py` never sends.)"""
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
