#!/usr/bin/env python3
"""V1 coaching UI: a local overlay served over HTTP.

Runs a tiny stdlib HTTP server (no dependencies). `live.py` pushes the latest
situation analysis here each buy phase; the server exposes it as JSON at
`/analysis` (ETag/304 — the page polls at 300ms and unchanged pushes cost a
header) and serves a static HTML/CSS/JS page at `/`.
Layout (2026-09-24 rework): two panes on a wide window — DECIDE (the state
strip, the "Do this now" plan with its kind-chipped hero step, Your hand,
Hand engine) sticky and never scrolled away; REFERENCE (Next opponent, Sell,
Looking for, Comp direction meters, Lobby pressure, ranked Tavern, Playable
comps) scrolls. Below ~1200px the original single priority column returns,
decide first. Colors come from the token block at the top of the stylesheet
(a test fails on hex drift); severity uses the status palette with a mark
and a word, never color alone.
Design: analysis/DESIGN_COACHING_UI.md. Tile names carry a '*N' tavern-tier
badge (2026-09-09); hovering a tile shows the full card render — framed
layout WITH text (img_cache/card/, fetched on demand) — or, when upstream
has no render, the card text from the meta DBs. The "Playable comps" panel
groups the playable comps by meta tier; clicking a comp expands its required
cards (owned faded, banned struck out), clicking again collapses it
(expansion state survives the rebuilds).

Usage:
    python coach_ui.py [--port=N]     # run the server standalone (empty state)
"""
import hashlib
import json
import os
import re
import threading
import time
import urllib.request
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from value import (_load_bg_names, _load_card_db, _load_spell_db,
                   DYING_HEALTH, SELL_FILLER_SCORE,
                   HAND_DEPLOY_KITS, hand_engine, sell_reason)
import pool
import meta

_HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_PORT = 8747

# On-demand card art. HearthstoneJSON's render build lags the current patch:
# returning cards (old ids), heroes and trinkets render, but brand-new
# minions and the newest heroes 404 upstream (and the wiki is
# Cloudflare-blocked), so those stay as UI placeholders / text tooltips.
RENDER_URL = "https://art.hearthstonejson.com/v1/render/latest/enUS/256x/{}.png"
MISS_TTL = 3600.0  # seconds before re-attempting a card id that 404'd
# A bare "Mozilla/5.0" now gets 403 from the art CDN (2026-09-09 probe) —
# the on-demand fetches need a plausible full browser User-Agent.
RENDER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

# Full-card renders (framed layout WITH name/text, unlike img_cache root's
# raw portraits) for the hover tooltip, kept in their own subdir so the two
# art kinds don't get confused. Same upstream URL as the /img fetch, so the
# two endpoints share one miss list — a card that 404s upstream misses both.
CARD_DIR = os.path.join(_HERE, "img_cache", "card")

_art_lock = threading.Lock()
_art_miss_path = os.path.join(_HERE, ".art_miss.json")
os.makedirs(os.path.join(_HERE, "img_cache"), exist_ok=True)
os.makedirs(CARD_DIR, exist_ok=True)
try:
    with open(_art_miss_path, encoding="utf-8") as _f:
        _art_miss = json.load(_f)
except (OSError, ValueError):
    _art_miss = {}


_miss_last_write = [0.0]  # last on-disk flush of the miss list (rate-limit)


def _remember_miss(cid):
    with _art_lock:
        _art_miss[cid] = time.time()
        # Prune entries already dead to _can_retry — the file used to grow
        # without bound (502 ids and counting). The in-memory dict is the
        # gate; the disk write is only crash recovery, so it is rate-limited
        # (it used to rewrite the whole file on every miss).
        now = time.time()
        for c in [c for c, t in _art_miss.items() if now - t > MISS_TTL]:
            del _art_miss[c]
        if now - _miss_last_write[0] >= 30.0:
            _miss_last_write[0] = now
            try:
                with open(_art_miss_path, "w", encoding="utf-8") as f:
                    json.dump(_art_miss, f)
            except OSError:
                pass


def _active_misses():
    """Card ids that would 404 RIGHT NOW — fresh on the miss list AND with
    no art file on disk. Served once at GET /artmiss so the page renders
    placeholder tiles with no 404 round-trip per tile per rebuild.

    The file-exists check is not optional: the miss list goes stale when art
    arrives by another door (patch-day hearth_art_extract rewrites img_cache
    without touching this file — 434 of its 504 entries had files on disk on
    2026-09-24). The /img endpoint itself is immune (it stats the file
    first); only this list can lie, and the client trusts it."""
    with _art_lock:
        now = time.time()
        return sorted(
            c for c, t in _art_miss.items()
            if now - t <= MISS_TTL
            and not os.path.exists(
                os.path.join(_HERE, "img_cache", f"{c}.png")))


def _can_retry(cid):
    return time.time() - _art_miss.get(cid, 0) > MISS_TTL


def _fetch_render(cid, dest_dir=None):
    """Download the HearthstoneJSON render for cid into dest_dir (img_cache
    root by default). True on success. The browser re-requests images on
    every DOM rebuild, so a miss is remembered for MISS_TTL — repeated polls
    must not re-hammer upstream.
    """
    if dest_dir is None:
        dest_dir = os.path.join(_HERE, "img_cache")
    try:
        req = urllib.request.Request(RENDER_URL.format(cid),
                                     headers={"User-Agent": RENDER_UA})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = r.read()
        with open(os.path.join(dest_dir, f"{cid}.png"), "wb") as f:
            f.write(data)
        return True
    except Exception:
        _remember_miss(cid)
        return False

_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Coach</title>
<style>
  /* Design tokens — the ONLY place a raw hex may appear (a test parses this
     block and fails on hex drift anywhere else). Values from the validated
     dark-mode reference palette; status colors are for STATE, never
     decoration, and always ride a word or mark, never color alone. */
  :root {
    /* surfaces + ink */
    --bg:#0d0d0d;        /* page plane */
    --panel:#1a1a19;     /* box surface */
    --panel2:#242422;    /* raised surface: chips, placeholder thumbs, hover */
    --text:#ffffff;      /* primary ink: values, names, actions */
    --text-2:#c3c2b7;    /* secondary ink: why-lines, subs, body */
    --dim:#898781;       /* muted: labels, headers, de-emphasis */
    --border:rgba(255,255,255,.10);  --gridline:#2c2c2a;
    /* status */
    --good:#0ca30c;      /* favored / safe */
    --warn:#fab219;      /* fragile / out-of-play */
    --bad:#ec835a;       /* serious: behind, do-not-sell, banned */
    --critical:#d03b3b;  /* DYING only — 3.6:1, large marks never small text */
    /* coach identity: currency / commit */
    --gold:#ffd97a;
    /* step-kind accents (categorical, not status) */
    --k-level:#8fb8ff; --k-cast:#cbb2ff; --k-sell:#e0a06a; --k-spell:#7ab8f0;
    /* severity band tints; --crit-ink carries the dying band's body text */
    --warn-bg:rgba(250,178,25,.13);  --warn-border:rgba(250,178,25,.38);
    --crit-bg:rgba(208,59,59,.16);   --crit-border:rgba(208,59,59,.45);
    --crit-ink:#ffd7d7;
    --shadow:0 8px 24px rgba(0,0,0,.65);
    --radius:6px;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:14px/1.45 "Segoe UI", system-ui, sans-serif; padding:8px; }
  #wrap { max-width:1600px; margin:0 auto; }
  /* State strip: stat tiles (muted label over a semibold value), then the
     chip row (triggers, bans, out-of-play, forecast). */
  #statebar { display:flex; align-items:center; gap:16px; flex-wrap:wrap;
              background:var(--panel); border:1px solid var(--border);
              border-radius:var(--radius); padding:6px 12px; margin-bottom:8px;
              font-size:14px; }
  #statebar .tile { display:inline-flex; flex-direction:column;
                    align-items:flex-start; line-height:1.25; }
  #statebar .lbl { color:var(--dim); font-weight:400; font-size:11px; }
  #statebar .val { font-weight:600; font-size:15px;
                   font-variant-numeric:tabular-nums; }
  #statebar .val.gold { color:var(--gold); }
  #statebar .val.warn { color:var(--warn); }
  /* DYING HP: --crit-ink, not --critical — critical is 3.6:1 on this
     surface, below large-text size at 15px. */
  #statebar .val.bad { color:var(--crit-ink); font-weight:700; }
  #statebar .good { color:var(--good); font-weight:600; font-size:12px; }
  #statebar .bad { color:var(--bad); font-weight:600; font-size:12px; }
  #statebar .banned { color:var(--text-2); font-weight:400; font-size:12px; }
  /* Out-of-play tribes (rotated by a patch: Naga since 36.6.1) are a THIRD
     state, not a ban — struck through and warn-colored so "Naga — out of
     play" never reads as "Naga was banned this game". */
  #statebar .oop { color:var(--warn); font-weight:400; font-size:12px;
                   text-decoration:line-through; }
  /* Ban picker (2026-09-19): tap the 5 banned tribes from the reveal
     screen — the log never carries the ban list, the inference takes
     minutes, a manual set is exact from turn 1. */
  .banchips { display:flex; gap:6px; flex-wrap:wrap; margin-top:4px; }
  .banchips .chip { border:1px solid var(--border); border-radius:12px;
                    padding:2px 10px; font-size:12px; cursor:pointer;
                    color:var(--dim); user-select:none; }
  .banchips .chip.picked { border-color:var(--bad); color:var(--bad);
                           text-decoration:line-through; }
  /* Two panes on a wide window: DECIDE (the turn's decision — never
     needs scrolling, sticky) and REFERENCE (scout intel + shopping
     lists, scrolls). Under 1200px — or a very short window, where a
     sticky column taller than the viewport would trap its bottom —
     they stack into the original single priority column, decide first.
     NEVER set overflow on a pane: it clips the 4.5x hover zoom. */
  #app { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr);
         gap:8px; align-items:start; }
  #app > section { display:flex; flex-direction:column; gap:8px;
                   min-width:0; }
  #col-decide { position:sticky; top:8px; }
  @media (max-width:1199.98px), (max-height:899px) {
    #app { display:flex; flex-direction:column; }
    #col-decide { position:static; }
  }
  .box { background:var(--panel); border:1px solid var(--border); border-radius:var(--radius);
         padding:7px 9px; }
  .box h3 { margin:0 0 4px; font-size:11px; letter-spacing:.06em;
            text-transform:uppercase; color:var(--dim); }
  /* The instruction panel is THE element: gold border, big numbered steps. */
  .instructions { border:2px solid var(--gold); padding:10px 12px; }
  .instructions h3 { color:var(--gold); font-size:12px; }
  .instructions .step { font-size:19px; padding:3px 0; }
  .instructions .footline { margin-top:6px; padding-top:5px;
                            border-top:1px solid var(--border);
                            color:var(--dim); font-size:13px; }
  .instructions .pickline { font-size:19px; font-weight:700;
                            color:var(--good); padding:3px 0; }
  /* The situation read: the plan's one-line thread. */
  .instructions .situation { font-size:14px; font-weight:600;
                             color:var(--warn); padding:2px 0 3px; }
  /* DANGER: the fragility band as its own line. The 2026-09-18 loss was a
     misread of a legal-looking plan at 14 HP, so this must not be buried in
     the row above it. */
  .instructions .danger { font-size:15px; font-weight:700; padding:4px 6px;
                          margin:2px 0 4px; border-radius:3px; }
  /* Status never rides color alone: the mark (▲/■) + the word FRAGILE/DYING
     carry the state; the tint band just makes it un-missable. Body text is
     ink (--crit-ink for dying), never the status color itself — critical is
     3.6:1 on this surface, too low for small text. */
  .instructions .danger.fragile { color:var(--text); background:var(--warn-bg);
                                  border:1px solid var(--warn-border); }
  .instructions .danger.fragile .dmark { color:var(--warn); }
  .instructions .danger.dying { color:var(--crit-ink); background:var(--crit-bg);
                                border:1px solid var(--crit-border); }
  .instructions .danger.dying .dmark { color:var(--critical); }
  #statebar .warn { color:var(--warn); font-weight:700; }
  /* Plan steps render from structured data: kind chip, then the action (ink —
     identity is the chip's text + border accent, never the text color), the
     tag and the ONE reason under it, the remaining clauses behind hover. */
  .instructions .step .stepbody { display:inline-block; }
  .instructions .step .act { font-weight:700; }
  .instructions .step .chip { font-size:10px; font-weight:700;
                              letter-spacing:.05em; color:var(--text-2);
                              border:1px solid var(--border); border-radius:3px;
                              padding:0 4px; margin-right:6px;
                              vertical-align:2px; }
  .instructions .step .chip.k-level { border-color:var(--k-level); }
  .instructions .step .chip.k-buy   { border-color:var(--good); }
  .instructions .step .chip.k-pick  { border-color:var(--gold); }
  .instructions .step .chip.k-sell  { border-color:var(--k-sell); }
  .instructions .step .chip.k-cast  { border-color:var(--k-cast); }
  .instructions .step .chip.k-play  { border-color:var(--k-cast); }
  .instructions .step .chip.k-swap  { border-color:var(--warn); }
  .instructions .step .tag { color:var(--dim); font-size:12px; font-weight:600;
                             margin-left:6px; border:1px solid var(--border);
                             border-radius:3px; padding:0 4px; }
  .instructions .step .why { color:var(--text-2); font-size:13px;
                             font-weight:400; line-height:1.3; }
  .instructions .step .more { cursor:help; color:var(--dim); opacity:.6; }
  /* Step 1 is the view's ONE hero: the biggest text on the page, anchored by
     a gold bar. (A pending pick gates the turn — the pick line above already
     reads first, so the hero rule stays honest.) */
  .instructions .step.hero { font-size:22px; padding:2px 0 4px;
                             border-left:3px solid var(--gold);
                             padding-left:8px; }
  /* Horizontal game-like card tiles: thumb on top, name below. */
  .tiles { display:flex; flex-wrap:wrap; gap:10px 12px; align-items:flex-start; }
  .tile { display:flex; flex-direction:column; align-items:center; gap:2px;
          width:104px; min-width:0; text-align:center; }
  .tile .thumb { width:56px; height:56px; }
  .tile .tname { font-size:12px; line-height:1.25; width:104px; overflow:hidden;
                 text-overflow:ellipsis; white-space:nowrap; }
  .tile .tsub { font-size:11px; color:var(--text-2); }
  .tile .xcount { color:var(--dim); font-size:11px; }
  .tile.buynow .tname { color:var(--gold); font-weight:700; }
  /* Sell groups: safe | divider | keep, all on one horizontal line. */
  .sellrow { display:flex; align-items:flex-start; gap:10px; flex-wrap:wrap; }
  .sellgroup { display:flex; flex-direction:column; gap:4px; min-width:0; }
  .sellgroup .grouplabel { font-size:12px; font-weight:700;
                           letter-spacing:.05em; text-transform:uppercase; }
  .sellgroup.safe .grouplabel { color:var(--good); }
  .sellgroup.keep .grouplabel { color:var(--bad); }
  .sellgroup.safe .tname { color:var(--good); }
  .sellgroup.keep .tname { color:var(--bad); }
  .gdivider { width:2px; align-self:stretch; flex:none;
              background:var(--border); border-radius:1px; }
  /* Hand-charge engine row: deployer on board? slot free? charging? */
  .engrow { display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  .engbit { font-size:12px; color:var(--text-2); }
  .engbit.ok { color:var(--good); }
  .engbit.bad { color:var(--bad); font-weight:700; }
  /* Target-comp tiles: what you're hunting fully opaque, owned faded. */
  .tile.comprow { opacity:.4; }
  .tile.comprow.missing { opacity:1; }
  /* A banned-tribe piece of a hybrid comp: struck out, dim. */
  .tile.comprow.bannedrow .tname { text-decoration:line-through; }
  .tile.comprow.bannedrow .tsub { color:var(--bad); }
  .gold { color:var(--gold); }
  .thumb { width:56px; height:56px; border-radius:5px; object-fit:cover; flex:none;
           cursor:zoom-in; transition:transform .12s ease-out; }
  /* No art cached for this card: a same-size placeholder keeps every row
     aligned (missing art used to collapse the row and shift names). */
  .thumb.ph { display:inline-flex; align-items:center; justify-content:center;
              color:var(--dim); background:var(--panel2);
              border:1px solid var(--border); font-size:18px; cursor:default; }
  /* Hover zoom (the fallback when no tooltip appears): art is 256x256, so
     scale(4.5) on a 56px tile thumb shows it near full size; origin center
     bottom grows the popup up and outward from the tile, z-index floats it
     above the other boxes. Scoped to real images with no tooltip content —
     canzoom is dropped the moment a render/text tooltip shows. */
  img.thumb.canzoom:hover { transform:scale(4.5); transform-origin:center bottom;
                    position:relative; z-index:5; }
  .thumb.golden { box-shadow:0 0 0 2px var(--gold); }
  /* The plan's buy glows in the tavern tiles. */
  img.thumb.buynowart { box-shadow:0 0 0 2px var(--gold); }
  /* Hover card: the full framed render (with text) near the tile, or — when
     upstream has no render for the card — a text box fed from the meta DB. */
  #tip { position:fixed; z-index:50; max-width:300px; }
  .tiprender { display:block; width:256px; border-radius:8px;
               box-shadow:0 8px 24px var(--shadow); }
  .tipbox { background:var(--panel2); border:1px solid var(--border);
            border-radius:var(--radius); padding:6px 9px; max-width:280px;
            box-shadow:0 8px 24px var(--shadow); }
  .tipname { font-weight:700; font-size:13px; }
  .tiptext { font-size:12px; color:var(--text-2); margin-top:2px; }
  .chips { display:flex; flex-wrap:wrap; gap:4px; }
  .chip { background:var(--panel2); border-radius:10px; padding:1px 8px;
          font-size:13px; }
  /* Comps panel (bottom): tier headers + click-to-expand comp rows. The
     expanded shopping list reuses the target-comp tile language (owned
     faded, banned struck out, missing opaque). */
  .cptier { font-size:11px; font-weight:700; letter-spacing:.06em;
            text-transform:uppercase; color:var(--dim); margin:6px 0 2px; }
  .cptier:first-child { margin-top:0; }
  .crowhead { display:flex; align-items:baseline; gap:7px; padding:2px 6px;
              cursor:pointer; border-radius:4px; }
  .crowhead:hover { background:var(--panel2); }
  /* Detection-window rows: tribe not yet confirmed in this lobby — still
     listed (it's the game-level view) but visibly uncertain. */
  .crow.unconf { opacity:.5; }
  .carrow { color:var(--dim); font-size:11px; flex:none; width:10px; }
  .cname { font-weight:600; }
  .cstat { color:var(--text-2); font-size:12px; flex:none; }
  .cbody { padding:0 0 4px 17px; }
  /* Top move: each numbered priority step on its own line */
  .step { font-size:16px; font-weight:700; line-height:1.4; padding:1px 0; }
  .stepnum { color:var(--gold); margin-right:7px; }
  .target { font-size:14px; font-weight:600; color:var(--gold); }
  .target .pivot { color:var(--warn); }
  .tag-core { color:var(--gold); }
  .tag-spell { color:var(--k-spell); }
  .tag-addon { color:var(--warn); }
  /* Comp direction meter: track (light step of the same ramp) + severity
     fill + candidate name + the text state that carries the meaning. */
  .mrow { display:flex; align-items:center; gap:8px; padding:2px 0;
          font-size:14px; min-width:0; }
  .mrow .meter { width:44px; height:8px; border-radius:4px; flex:none;
                 background:rgba(255,217,122,.16); overflow:hidden;
                 position:relative; }
  .mrow .meter.near { background:rgba(250,178,25,.14); }
  .mrow .meter:not(.met):not(.near) { background:var(--gridline); }
  .mrow .meter .fill { position:absolute; inset:0 auto 0 0; display:block;
                       height:100%; border-radius:4px; min-width:4px;
                       background:var(--dim); }
  .mrow .meter.near .fill { background:var(--warn); }
  .mrow .meter.met .fill { background:var(--gold); }
  .mrow .mname { font-weight:600; overflow:hidden; text-overflow:ellipsis;
                 white-space:nowrap; }
  .mrow .mstat { color:var(--text-2); font-size:12px; flex:none; }
  .mrow.locked .mname { color:var(--gold); font-weight:700; }
  /* Pane headers: the two-pane grouping (Decide | Reference). */
  .pane-h { margin:0; font-size:11px; font-weight:700; letter-spacing:.14em;
            text-transform:uppercase; color:var(--dim); }
  .none { color:var(--dim); font-style:italic; }
  .score { color:var(--dim); flex:none; }
  .xcount { color:var(--dim); font-weight:400; }
</style>
</head>
<body>
<div id="wrap">
<div id="statebar">Waiting for live.py analysis…</div>
<div id="app">
<section id="col-decide"></section>
<section id="col-ref"></section>
</div>
</div>
<script>
let _lastPayload = null;
let _etag = null;
let _pollBusy = false;
async function poll() {
  if (_pollBusy) return;  // a slow response must not pile up ticks
  _pollBusy = true;
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 2500);
    const r = await fetch('/analysis', {
      signal: ctrl.signal,
      headers: _etag ? {'If-None-Match': _etag} : undefined,
    });
    clearTimeout(timer);
    if (r.status !== 304) {          // 304 = unchanged: header only, no body,
      const raw = await r.text();    // no JSON.parse, no DOM work
      _etag = r.headers.get('ETag');
      if (raw !== _lastPayload) {    // unchanged payloads never rebuild the
        _lastPayload = raw;          // DOM (rebuilding every second made
        render(JSON.parse(raw));     // thumbnails flicker)
      }
    }
  } catch (e) { /* keep last frame */ }
  finally { _pollBusy = false; }
}
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}
// Per-card display metadata from the payload ({tier, text}) — golden ids
// resolve to their base id like the server's own cache does.
let CARDS = {};
const _warmed = new Set();
function cardMeta(cid) {
  return CARDS[String(cid || '').replace(/_G$/, '')] || {};
}
// The tier badge in every name: "*1 Suspicious Prisoner guard". Cards the
// meta DBs carry no tier for (heroes, trinkets) show bare names.
function badgeName(cid, name) {
  const meta = cardMeta(cid);
  return (meta.tier ? '*' + meta.tier + ' ' : '') + (name || '');
}
// Hover tooltip: the full HearthstoneJSON render (framed card with text) when
// upstream has it, else the card text from the meta DB, else nothing (and
// the old portrait zoom stays active). The page pre-warms /card fetches for
// every card in the payload, so the first hover of a phase may still be
// loading but every later hover is instant.
const tip = document.createElement('div');
tip.id = 'tip';
tip.hidden = true;
document.body.appendChild(tip);
let tipCid = null;
function hoverCard(elm, cid, name) {
  const meta = cardMeta(cid);
  const id = String(cid || '').replace(/_G$/, '');
  tipCid = id;
  let shown = false;
  const show = node => {
    if (tipCid !== id) return;  // a later hover superseded this one
    tip.innerHTML = '';
    tip.appendChild(node);
    const r = elm.getBoundingClientRect();
    tip.style.left =
      Math.max(4, Math.min(r.left - 100, window.innerWidth - 300)) + 'px';
    tip.style.top =
      Math.max(4, Math.min(r.bottom + 2, window.innerHeight - 400)) + 'px';
    tip.hidden = false;
    shown = true;
    elm.classList.remove('canzoom');  // tooltip replaces the portrait zoom
  };
  // Text box first (instant, from the meta DB) when we have text.
  if (meta.text) {
    const box = el('div', 'tipbox');
    box.appendChild(el('div', 'tipname', badgeName(cid, name)));
    box.appendChild(el('div', 'tiptext', meta.text));
    show(box);
  }
  // The full render upgrades the tooltip when upstream has it; a 404 keeps
  // the text box — or, with no text either, the old portrait zoom.
  const big = new Image();
  big.className = 'tiprender';
  big.onload = () => show(big);
  big.onerror = () => { if (tipCid === id && !shown) tipCid = null; };
  big.src = '/card/' + id + '.png';
}
function leaveCard() { tipCid = null; tip.hidden = true; }
function box(title, body) {
  const b = el('div', 'box');
  b.appendChild(el('h3', null, title));
  if (body) b.appendChild(body);
  return b;
}
// Card ids with no art upstream (the render build lags the patch; trinkets
// have none at all), fetched once from GET /artmiss: thumb() renders the
// placeholder directly, so ~500 known misses stop paying a 404 round-trip
// per tile per rebuild. Keyed by the EXACT id requested — /img does not
// strip the golden _G suffix.
const MISSES = new Set();
fetch('/artmiss').then(r => r.json()).then(j => {
  (j.misses || []).forEach(cid => MISSES.add(cid));
}).catch(() => {});
// Card art thumbnail (img_cache/ via /img/<id>.png, fetched by fetch_art.py).
// Hides itself gracefully when no art is cached (current-set BG-only cards).
// Hover shows the full card render (framed layout WITH text) via /card/,
// falling back to a text box from the meta DB, then to the old portrait zoom.
function thumbPh(cid, name) {
  const ph = document.createElement('span');
  ph.className = 'thumb ph';
  ph.textContent = (name || '?').trim().charAt(0).toUpperCase();
  ph.onmouseenter = () => hoverCard(ph, cid, name);
  ph.onmouseleave = leaveCard;
  return ph;
}
function thumb(cid, name) {
  if (MISSES.has(cid)) return thumbPh(cid, name);
  const img = document.createElement('img');
  img.className = 'thumb canzoom';
  img.src = '/img/' + cid + '.png';
  img.alt = '';
  img.onmouseenter = () => hoverCard(img, cid, name);
  img.onmouseleave = leaveCard;
  img.onerror = () => {
    // No art available (render build lags the patch; trinkets have none
    // upstream): a same-size placeholder keeps every row aligned. The id
    // joins MISSES so sibling tiles of the same card skip the 404 too.
    MISSES.add(cid);
    img.replaceWith(thumbPh(cid, name));
  };
  return img;
}
// A horizontal game-like card tile: thumb on top, name below, sub-line
// (price / score / count) under that.
function tile(cid, name, sub, opts) {
  opts = opts || {};
  const t = el('div', 'tile' + (opts.cls ? ' ' + opts.cls : ''));
  const img = thumb(cid, name);
  if (opts.golden) img.classList.add('golden');
  if (opts.cls === 'buynow') img.classList.add('buynowart');
  t.appendChild(img);
  const nm = el('div', 'tname', badgeName(cid, name));
  if (opts.n > 1) nm.appendChild(el('span', 'xcount', '  ×' + opts.n));
  t.appendChild(nm);
  if (sub) t.appendChild(el('div', 'tsub', sub));
  return t;
}
// Comps panel: one playable comp as a clickable row. Clicking expands its
// required cards (core, then addons) — owned faded, banned-this-game struck
// out, missing fully opaque, same language as the Looking-for box; clicking
// again collapses. The open set survives the rebuilds (a rebuild
// drops the DOM but re-opens whatever was open). The collapsed row already
// says how much of the core you own, so expanding is only for the detail.
const _openComps = new Set();
// Expanded bodies are cached keyed by slug + the exact rows (core/addons
// with their owned/banned flags — those are compTiles' only inputs, and
// keying on them is what keeps a just-bought card from still reading
// "have"/"missing"). appendChild re-parents, so the <img>s persist across
// the full-DOM rebuilds instead of being re-requested every tick.
const _compBodyCache = new Map();
function compBody(c) {
  const key = c.slug + '|' + JSON.stringify([c.core, c.addons]);
  let node = _compBodyCache.get(key);
  if (!node) {
    node = compTiles(c);
    if (_compBodyCache.size > 300) _compBodyCache.clear();
    _compBodyCache.set(key, node);
  }
  return node;
}
function compTiles(c) {
  const tiles = el('div', 'tiles');
  [['core', 'core'], ['addons', 'addons']].forEach(([_label, key]) => {
    (c[key] || []).forEach(x => {
      const sub = x.banned ? 'banned' : (x.owned ? 'have' : null);
      const cls = 'comprow ' + (x.banned ? 'bannedrow'
                   : x.owned ? 'owned' : 'missing');
      tiles.appendChild(tile(x.card, x.name, sub, {cls: cls}));
    });
  });
  return tiles.children.length
    ? tiles : el('div', 'none', 'no card list in the meta DB');
}
function compRow(c) {
  const open = _openComps.has(c.slug);
  // Inside the ban-detection window the panel lists EVERY comp; a row whose
  // tribe the pool hasn't confirmed yet is dimmed and labeled — it could
  // still be banned, and it stays until the 5/5 set lands.
  const unconf = c.tribe_confirmed === false;
  const head = el('div', 'crowhead');
  const arrow = el('span', 'carrow', open ? '▾' : '▸');
  head.appendChild(arrow);
  const core = c.core || [];
  head.appendChild(el('span', 'cname', c.name));
  head.appendChild(el('span', 'cstat',
    core.length + ' core · '
    + core.filter(x => x.owned).length + ' owned'
    + (unconf ? ' · tribe unconfirmed' : '')));
  const body = el('div', 'cbody');
  // Collapsed rows build their tiles lazily (on first expand) so a 21-comp
  // panel doesn't queue 100+ card fetches up front; an open row reuses the
  // cached body (see _compBodyCache).
  body.hidden = !open;
  if (open) body.appendChild(compBody(c));
  head.onclick = () => {
    const nowOpen = !_openComps.has(c.slug);
    if (nowOpen) _openComps.add(c.slug); else _openComps.delete(c.slug);
    head.classList.toggle('open', nowOpen);
    arrow.textContent = nowOpen ? '▾' : '▸';
    body.hidden = !nowOpen;
    if (nowOpen && !body.children.length) body.appendChild(compBody(c));
  };
  const wrap = el('div', 'crow' + (unconf ? ' unconf' : ''));
  wrap.appendChild(head);
  wrap.appendChild(body);
  return wrap;
}
// Step-kind chips: 2-4 characters of text — font-independent (no glyphs)
// and never the only carrier (the action word is ink; the chip's border
// adds the kind accent). value._STEP_KINDS is the source of the kind set;
// a drift-guard test fails when the two diverge.
const KIND_CHIP = {
  level: 'LV', pick: 'PICK', buy: 'BUY', sell: 'SELL', roll: 'ROLL',
  cast: 'CAST', play: 'PLAY', hold: 'HOLD', swap: 'SWAP', discard: 'DISC',
  note: 'NOTE',
};
function render(a) {
  const app = document.getElementById('app');
  const statebar = document.getElementById('statebar');
  // A rebuild discards the hovered element without a mouseleave — drop the
  // tooltip with the old frame so it can't outlive its card.
  leaveCard();
  CARDS = a.cards || {};
  // value.py's constants, mirrored to the client (the JS used to hard-code
  // its own copies — two definitions that could drift).
  const TH = a.thresholds || {};
  const decide = document.getElementById('col-decide');
  const ref = document.getElementById('col-ref');
  decide.innerHTML = '';
  ref.innerHTML = '';
  statebar.innerHTML = '';
  if (!a || !a.board) { statebar.textContent = 'No game yet.'; return; }
  // Pane grouping: DECIDE = the turn's decision (never scrolled away),
  // REFERENCE = scout intel and shopping lists. The headers re-render with
  // the panes (render() clears each section wholesale).
  decide.appendChild(el('h2', 'pane-h', 'Decide'));
  ref.appendChild(el('h2', 'pane-h', 'Reference'));
  // Ban-picker sync (see the state block near the bottom): a new game
  // reseeds from the server; a settled manual set overwrites stale local
  // taps (unless we tapped in the last 3s — the POST may still be in
  // flight); while the player is mid-tapping during detection, local wins.
  const gameNo = a.game_no ?? null;
  if (gameNo !== _banPickGame) {
    _banPickGame = gameNo;
    _banPick = new Set(a.bans_manual ? (a.banned || []) : []);
    _banPickAt = 0;
    _compBodyCache.clear();  // a new game invalidates every owned/banned flag
  } else if (a.bans_manual && Date.now() - _banPickAt > 3000) {
    const srv = new Set(a.banned || []);
    if (srv.size !== _banPick.size || [...srv].some(t => !_banPick.has(t))) {
      _banPick = srv;
    }
  }
  // Pre-warm the /card renders for everything on screen so hovers are
  // instant (one-time per card: the server caches downloads in
  // img_cache/card/, and misses are remembered server-side).
  Object.keys(CARDS).forEach(cid => {
    if (!_warmed.has(cid)) {
      _warmed.add(cid);
      new Image().src = '/card/' + cid + '.png';
    }
  });

  // STATE STRIP — stat tiles (label over value), then the chip row.
  // Hero name leads as the trust anchor; the numbers use tabular figures so
  // they don't shift width as they tick.
  function statTile(label, value, valCls) {
    const t = el('span', 'tile');
    t.appendChild(el('span', 'lbl', label));
    t.appendChild(el('span', 'val' + (valCls ? ' ' + valCls : ''),
                     String(value)));
    return t;
  }
  statebar.appendChild(el('span', 'tile', a.hero || '?'));
  statebar.appendChild(statTile('Gold', a.gold ?? '?', 'gold'));
  statebar.appendChild(statTile('Tier', a.tier ?? '?'));
  if (a.health != null) {
    const fr = a.fragility || {};
    const dying = (a.health + (a.armor || 0)) <= (TH.dying_hp || 12);
    statebar.appendChild(statTile('HP',
      a.health + (a.armor ? '+' + a.armor : ''),
      dying ? 'bad' : (fr.band === 'fragile' ? 'warn' : null)));
  }
  const turns = (a.scenario || {}).turns;
  if (turns) statebar.appendChild(statTile('Turn', turns));
  if (a.current_place) {
    // Live leaderboard standing (Plan 5 lever 1). Ordinal only — no lobby
    // size exists in any payload, and inventing "of 8" would be wrong in
    // Duos and after late-game deaths.
    const p = a.current_place;
    const suf = ([11, 12, 13].includes(p % 100))
      ? 'th' : ({1: 'st', 2: 'nd', 3: 'rd'}[p % 10] || 'th');
    // Same rule value.situation_line uses: from t8, 5th-or-worse is the
    // "spike, not greed" zone.
    statebar.appendChild(statTile('Place', p + suf,
      (p >= 5 && turns >= 8) ? 'warn' : null));
  }
  if (a.scout) {
    statebar.appendChild(el('span', 'lbl', a.scout));
  }
  if (a.forecast) {
    // The next-fight verdict: the mark + the verdict word carry the state;
    // the color reinforces (never the reverse).
    const fav = a.forecast.startsWith('favored');
    const behind = a.forecast.startsWith('behind');
    const mark = fav ? '✓ ' : (behind ? '✕ ' : '');
    const cls = fav ? 'good' : (behind ? 'bad' : null);
    statebar.appendChild(el('span', cls, mark + a.forecast));
  }
  const triggers = (a.scenario || {});
  const active = Object.entries(triggers)
    .filter(([k, v]) => v && !k.endsWith('_total') && k !== 'turns');
  active.forEach(([k, v]) => {
    statebar.appendChild(el('span', 'lbl',
      k.replace('play_', '') + ' ' + v));
  });
  if (a.banned && a.banned.length) {
    statebar.appendChild(el('span', 'lbl', 'Banned:'));
    a.banned.forEach(t => statebar.appendChild(el('span', 'banned', t)));
  }
  // Out of play (rotated by a patch): NOT banned this game — the pool cannot
  // offer it in any lobby (Naga since 36.6.1). Its own labeled, struck-through
  // state, so a rotated tribe never reads as a ban the player could undo.
  if (a.out_of_pool && a.out_of_pool.length) {
    statebar.appendChild(el('span', 'lbl', 'Out of play:'));
    a.out_of_pool.forEach(t => statebar.appendChild(el('span', 'oop', t)));
  }

  // INSTRUCTIONS — the explicit, do-this-now panel. A pending pick gates
  // everything, so it reads first; then the numbered plan steps; then the
  // level/roll reference line.
  const instr = el('div', 'box instructions');
  instr.appendChild(el('h3', null, 'Do this now'));
  // The situation read: the plan's thread (direction, strength, danger) in
  // one line, so the numbered steps read as a story instead of a list.
  if (a.situation) instr.appendChild(el('div', 'situation', a.situation));
  // DANGER — its own line, not clause three of a long row. The 2026-09-18 loss
  // is the reason it exists: 14 HP, bled 10 in two of three fights, every level
  // gate legal by construction, and the plan read as "the build is about to
  // take off" — 8th place with 10 gold unspent. The number that decides the turn
  // is not the HP but the NEXT HIT, so that is what this says.
  if (a.fragility && a.fragility.band !== 'steady') {
    const fr = a.fragility;
    const dying = fr.band === 'dying';
    const danger = el('div', 'danger ' + fr.band);
    // Mark + word carry the state; color only reinforces it.
    danger.appendChild(el('span', 'dmark', dying ? '■ ' : '▲ '));
    danger.appendChild(el('span', null,
      (dying ? 'DYING — ' : 'FRAGILE — ')
      + fr.eff_health + ' effective HP'
      + (fr.last_hit ? ', took ' + fr.last_hit + ' last fight' : '')
      + ' — a ' + fr.eff_health + '-hit ends it'
      + (fr.recent3 ? ' · bled ' + fr.recent3 + ' over the last 3 fights' : '')
      + (fr.cap ? ' · damage cap ' + fr.cap : '')));
    instr.appendChild(danger);
  }
  // The empty-shop gap (after a buy/roll the offers vanish from the log for
  // a second or two before the game re-prints them) holds the old plan —
  // saying so makes the lag legible instead of looking like a freeze
  // (2026-09-07 'the coach has seized up' report).
  if ((!a.shop_rank || !a.shop_rank.length) && (a.board || []).length) {
    instr.appendChild(el('div', 'none',
      'reading the new shop… (the plan above is from your last action)'));
  }
  if (a.choice && a.choice.ranked && a.choice.ranked.length) {
    const [name, cid, score, why] = a.choice.ranked[0];
    // An unranked pick (no data — score null) is never blessed as "PICK X":
    // the first listed option read as advice (2026-09-08 Trip Vouchers
    // discover). Say the options carry no ranking instead.
    const line = score == null
      ? el('div', 'pickline', 'no data on these options — your call')
      : el('div', 'pickline', 'PICK ' + badgeName(cid, name)
                             + (why ? ' — ' + why : ''));
    instr.appendChild(line);
    if (a.choice.kind === 'hero' && a.choice.ranked.length > 1) {
      instr.appendChild(el('div', 'none',
        'if locked, pick ' + a.choice.ranked[1][0]));
    }
    const alts = el('div', 'tiles');
    a.choice.ranked.forEach(([n, c, s, w]) => {
      alts.appendChild(tile(c, n, w != null ? w : (s != null ? s.toFixed(1) : null)));
    });
    instr.appendChild(alts);
  }
  if (a.top_move) {
    // Render from the STRUCTURED steps (value.top_move side-writes
    // top_move_steps: {action, tag, reason, details, kind, card}) — the
    // string is never re-parsed here. That was the audit's "formatting used
    // as data" finding: rewording a message could silently break the page.
    // Identity rides the kind chip (text, not color); the action word is
    // ink. Step 1 is the view's ONE hero — unless a pending pick gates the
    // turn, in which case the pick line above already leads.
    const steps = a.top_move_steps || [];
    if (steps.length) {
      steps.forEach((s, i) => {
        const kind = s.kind || 'note';
        const line = el('div', 'step k-' + kind + (i === 0 ? ' hero' : ''));
        line.appendChild(el('span', 'stepnum', i + 1));
        const body = el('span', 'stepbody');
        body.appendChild(el('span', 'chip k-' + kind,
                           KIND_CHIP[kind] || 'NOTE'));
        body.appendChild(el('span', 'act', s.action || s.text || ''));
        if (s.tag) body.appendChild(el('span', 'tag', s.tag));
        if (s.reason) body.appendChild(el('div', 'why', s.reason));
        if ((s.details || []).length) {
          // Hover rather than on-screen: the reasons are real, they are just
          // not all worth a row while you have 30 seconds to spend gold.
          const more = el('div', 'why more', '…');
          more.title = s.details.join(' · ');
          body.appendChild(more);
        }
        line.appendChild(body);
        instr.appendChild(line);
      });
    } else {
      // Minimal payload (the Choose-1 push carries only the string).
      a.top_move.split(' · ').forEach(step => {
        instr.appendChild(el('div', 'step', step));
      });
    }
  }
  // Level/roll reference: the button's real price. An analysis without a
  // level_cost (never the live loop's case) shows no level line at all —
  // tier+1 was the old wrong model, never a fallback price.
  if (a.tier && a.tier < 6 && a.level_cost != null) {
    const cost = a.level_cost;
    instr.appendChild(el('div', 'footline',
      a.gold !== null && a.gold >= cost
        ? 'Level available: tier ' + a.tier + ' → ' + (a.tier + 1)
          + ' for ' + cost + 'g'
        : 'Level costs ' + cost + 'g — '
          + Math.max(0, cost - (a.gold ?? 0)) + ' short'));
  }
  // Opponents' trinkets — read from the log (2026-09-08 ground truth): free
  // scout intel the player cannot see in game.
  // The Dark gifts line that used to sit here was REMOVED (2026-09-23, player
  // call: "remove that list of Dark gifts on the coaching page. That is
  // accomplishing nothing."). It listed gifts the player already owns, which the
  // game itself shows on the board — real estate in the Decide column spent
  // restating known state. The analysis still carries `dark_gifts` for telemetry
  // and the corpus; only the overlay stopped rendering it.
  if (a.opp_trinkets && a.opp_trinkets.length) {
    instr.appendChild(el('div', 'footline',
      'Their trinkets: ' + a.opp_trinkets.join(', ')));
  }
  decide.appendChild(instr);

  // NEXT OPPONENT — the announced seat's last-known composition (phase 2,
  // lobby.py): exact when their board staged, aged since. The subtitle
  // names the round so a 3-round-old preview never reads current. Hand and
  // shop are invisible to the log, so this is their BOARD, not everything
  // they hold.
  if (a.opp_comp && a.opp_comp.cards && a.opp_comp.cards.length) {
    const oc = a.opp_comp;
    const body = el('div');
    body.appendChild(el('div', 'footline',
      (oc.hero_name || oc.hero || 'unknown hero')
      + (oc.name ? ' · ' + oc.name : '')
      + ' — as of round ' + oc.turn));
    const tiles = el('div', 'tiles');
    oc.cards.forEach(c => {
      tiles.appendChild(tile(c.card, c.name,
                             c.n > 1 ? '×' + c.n : null,
                             {golden: c.golden}));
    });
    body.appendChild(tiles);
    ref.appendChild(box('Next opponent', body));
  }

  // The plan's actual buy (highlighted in the shop tiles below too).
  const stepCard = a.buy_step_card || null;

  // HAND — casts from hand are free, stuck minions play free; the ranked
  // order here is the plan's hand steps (they're numbered in the panel too).
  // A `discard` verb (2026-09-23): the plan is feeding this card to a board
  // outlet that discards it, because the card's own text says discarding beats
  // casting it — it must not render as "play".
  if (a.hand && a.hand.length) {
    const tiles = el('div', 'tiles');
    a.hand.forEach(s => {
      // The plan's chosen discard fodder is named on the tile ("the plan's
      // discard") — discard_target rode the payload unrendered until now.
      const fodder = a.discard_target && a.discard_target === s.card;
      const sub = (s.verb === 'cast' ? 'cast' : s.verb === 'hold' ? 'hold'
                   : s.verb === 'discard' ? 'discard' : 'play')
        + (s.score != null ? ' · ' + s.score.toFixed(0) : '')
        + (fodder ? ' · the plan\'s discard' : '');
      tiles.appendChild(tile(s.card, s.name, sub, {golden: s.golden}));
    });
    decide.appendChild(box('Your hand', tiles));
  }

  // HAND ENGINE — a hand-charge kit (Bream Counter + Diremuck Forager is
  // the known one): the charger grows IN HAND and the deployer summons it
  // at start of combat. Each fact is a live check; the 2026-09-10 game
  // died with both broken and nothing on screen said so.
  if (a.engine) {
    const e = a.engine;
    const body = el('div', 'engrow');
    const bit = (text, cls) => body.appendChild(el('span', 'engbit' + (cls ? ' ' + cls : ''), text));
    if (e.on_board) bit('✓ ' + e.deployer_name + ' on board', 'ok');
    else bit('✗ ' + e.deployer_name + ' NOT on board — play your chargers', 'bad');
    if (e.space) bit('✓ slot free', 'ok');
    else bit('✗ board full — the summon needs a free slot', 'bad');
    bit(e.charging + ' charging');
    decide.appendChild(box('Hand engine', body));
  }

  // SELL — one horizontal line: safe to sell | divider | do not sell.
  // The split is the value function's own filler threshold (SELL_FILLER_SCORE,
  // shipped as thresholds.sell_safe_below — what top_move calls "a clear filler").
  const sellSafe = el('div', 'tiles');
  const sellKeep = el('div', 'tiles');
  (a.sell_rank || []).forEach(s => {
    // Board minions only — a hand card can't be sold until it's played
    // (player rule 2026-09-09), so render_json keeps hand entries out.
    // A Butchering-fuel undead reads "cast it instead of selling".
    const sub = s.score.toFixed(0)
      + (s.why ? ' · ' + s.why : '')
      + (s.fuel ? ' · cast, not sell' : '');
    const safe = s.score < (TH.sell_safe_below || 15);
    const t = tile(s.card, s.name, sub,
                   {golden: s.golden, n: s.n, cls: safe ? 'safe' : 'keep'});
    (safe ? sellSafe : sellKeep).appendChild(t);
  });
  const sellBody = el('div', 'sellrow');
  const safeG = el('div', 'sellgroup safe');
  safeG.appendChild(el('span', 'grouplabel', 'Safe to sell'));
  safeG.appendChild(sellSafe.children.length ? sellSafe : el('div', 'none', '—'));
  sellBody.appendChild(safeG);
  if (sellKeep.children.length) {
    sellBody.appendChild(el('div', 'gdivider'));
    const keepG = el('div', 'sellgroup keep');
    keepG.appendChild(el('span', 'grouplabel', 'Do not sell'));
    keepG.appendChild(sellKeep);
    sellBody.appendChild(keepG);
  }
  ref.appendChild(box('Sell', sellBody));

  // TARGET COMP — what you're hunting: horizontal tiles, missing pieces
  // fully opaque, owned pieces faded. A PROVISIONAL target (mined from our own
  // games, no published comp exists for the tribe) is labelled here and in the
  // comp-direction rows: the plan coaches it, but the player must be able to
  // tell it apart from a published comp at a glance.
  if (a.target_comp) {
    const pivot = a.target_state === 'pivot';
    const ev = a.target_comp_evidence || {};
    const body = el('div', 'target',
      (pivot ? 'pivot to ' : 'committing to ') + a.target_comp
      + (a.target_comp_provisional
         ? '  [provisional' + (ev.games ? ' — ' + ev.games + ' of our games' : '')
           + (ev.top4 != null ? ', top4 ' + ev.top4 : '') + ']'
         : ''));
    const tc = a.target_cards || {};
    const list = el('div', 'tiles');
    [['core', 'core'], ['addons', 'addons']].forEach(([_label, key]) => {
      (tc[key] || []).forEach(c => {
        // Banned-tribe piece of a hybrid comp (e.g. the Dragon in a naga
        // comp): shown struck-out, never as a hunt target.
        const sub = c.banned ? 'banned' : (c.owned ? 'have' : null);
        const cls = 'comprow ' + (c.banned ? 'bannedrow'
                     : c.owned ? 'owned' : 'missing');
        list.appendChild(tile(c.card, c.name, sub, {cls: cls}));
      });
    });
    body.appendChild(list);
    ref.appendChild(box('Looking for (' + (pivot ? 'pivot' : 'comp') + ')', body));
  }

  // COMP DIRECTION — commit-readiness meter: how close each candidate comp
  // is to the 2-core-hit commit threshold, BEFORE comp_target declares a
  // target. The committed comp glows gold; pre-commit, the top candidate's
  // missing core is shown as tiles (the cards that move the meter).
  if (a.comp_progress && a.comp_progress.length) {
    const body = el('div');
    a.comp_progress.forEach(r => {
      const row = el('div', 'mrow' + (r.name === a.target_comp ? ' locked' : ''));
      // A real meter, not pips: the track is a light step of the same ramp
      // so the state reads across the whole bar, and the fill's color is
      // severity (gold = committed/ready, warn = one away). The text state
      // beside it always carries the meaning — the meter never acts alone.
      const n = Math.min(r.hits, 2);
      const meter = el('span', 'meter'
        + (r.name === a.target_comp || r.ready ? ' met'
           : (r.tribe_hits || 0) >= 2 ? ' near' : ''));
      const fill = el('span', 'fill');
      fill.style.width = (n / 2 * 100) + '%';
      meter.appendChild(fill);
      row.appendChild(meter);
      row.appendChild(el('span', 'mname',
        r.name + (r.provisional ? ' [prov]' : '')));
      row.appendChild(el('span', 'mstat',
        (r.name === a.target_comp
          ? (a.target_state === 'pivot' ? 'pivoting — committed' : 'committed')
          : r.ready ? 'ready to commit'
          : (r.tribe_hits || 0) >= 2
            ? 'one core card away · tribe signal'
            : 'one core card away')
        + (r.hits > 2 ? ' (' + r.hits + ' hits)' : '')));
      body.appendChild(row);
    });
    if (!a.target_comp && (a.comp_progress[0].needs || []).length) {
      const t = el('div', 'tiles');
      a.comp_progress[0].needs.forEach(c => t.appendChild(tile(c.card, c.name)));
      body.appendChild(t);
    }
    ref.appendChild(box('Comp direction', body));
  }

  // LOBBY PRESSURE — tribe commitment across SEEN seats (phase 2): who is
  // contesting what, for pivot/deny context. "of" counts only seats we've
  // sighted; unseen seats are unknown, not empty — the label says "seen".
  if (a.tribe_pressure && a.tribe_pressure.length) {
    const body = el('div');
    a.tribe_pressure.forEach(r => {
      body.appendChild(el('div', 'footline',
        r.tribe + ' — ' + r.seats + ' of ' + r.of + ' seen seats (2+ copies)'));
    });
    ref.appendChild(box('Lobby pressure', body));
  }

  // TAVERN — the ranked shop as a horizontal card row (game-like); the
  // plan's buy glows gold. Score + price under each card. Pool chips
  // (phase 1): copies left in the shared pool beyond OUR holdings —
  // opponent holdings aren't subtracted yet, so this is a floor, not a
  // lobby total (analysis/pool_availability.md).
  if (a.shop_rank && a.shop_rank.length) {
    const body = el('div');
    // A buy the slot arbiter vetoed: the shop tile must not keep glowing gold
    // for a card the plan just argued against (board_swap.md).
    const vetoed = a.buy_step_swap_veto || null;
    if (vetoed) {
      body.appendChild(el('div', 'none',
        'not worth a board slot this turn: ' + vetoed
        + ' — see the swap line in Do this now'));
    }
    const tiles = el('div', 'tiles');
    a.shop_rank.forEach(s => {
      const sub = (s.price != null ? s.price + 'g · ' : '') + s.score.toFixed(0)
        + (s.tag ? ' · ' + s.tag : '')
        + (s.pool ? ' · ' + s.pool : '');
      tiles.appendChild(tile(s.card, s.name, sub,
                             {cls: (s.card === stepCard && !vetoed) ? 'buynow' : null,
                              golden: s.golden}));
    });
    body.appendChild(tiles);
    ref.appendChild(box('Tavern (ranked)', body));
  } else {
    ref.appendChild(box('Tavern', el('div', 'none', 'offer not parsed yet')));
  }

  // PLAYABLE COMPS — the bottom panel: grouped by meta tier (S/A/B, the
  // server pre-sorts), each comp a clickable row that expands into its
  // required cards with owned/banned flags. Click again to collapse.
  // This is the game-level list — what the tribe bans still allow — meant
  // to be readable on turn 1. While the 5/5 ban set streams in (~turn 3-5)
  // the panel lists EVERY comp (what this game might allow), dimming rows
  // of not-yet-confirmed tribes; the header says so the full list doesn't
  // read as "all tribes confirmed".
  const compsBody = el('div');
  if (a.tribes_detecting || a.bans_manual) {
    // Ban picker: the reveal screen shows the 5 banned tribes at t0 and
    // the pool inference only converges minutes later — tapping them here
    // makes every downstream comp filter exact for the whole game
    // (2026-09-19; the ban list is provably not in any log).
    const line = el('div', 'none', a.bans_manual
      ? 'bans set by you — tap to correct'
      : 'bans still resolving — ' + (a.tribes_seen || 0)
        + '/5 tribes confirmed · dimmed comps could still be banned · '
        + 'tap the 5 banned tribes to set them now:');
    compsBody.appendChild(line);
    const chips = el('div', 'banchips');
    // The reveal screen lists the CURRENT pool's tribes, so an out-of-play
    // tribe (Naga since 36.6.1) is not on it and is not tappable here either.
    const oopSet = new Set(a.out_of_pool || []);
    (a.tribe_roster || []).filter(t => !oopSet.has(t)).forEach(t => {
      const c = el('span', 'chip' + (_banPick.has(t) ? ' picked' : ''), t);
      c.onclick = () => {
        if (_banPick.has(t)) _banPick.delete(t); else _banPick.add(t);
        _banPickAt = Date.now();
        c.classList.toggle('picked');
        postBans([..._banPick]);
      };
      chips.appendChild(c);
    });
    compsBody.appendChild(chips);
  }
  if (a.comps && a.comps.length) {
    let lastTier = null;
    a.comps.forEach(c => {
      // A provisional (mined) comp has no published tier by definition: label
      // the group "Provisional" instead of letting a null read as "Unranked",
      // which would look like a real comp whose tier is merely unknown.
      const tier = c.provisional ? 'prov' : (c.meta_tier || '?');
      if (tier !== lastTier) {
        lastTier = tier;
        compsBody.appendChild(el('div', 'cptier',
          tier === '?' ? 'Unranked'
            : tier === 'prov' ? 'Provisional (mined from our own games)'
            : tier + ' tier'));
      }
      compsBody.appendChild(compRow(c));
    });
  } else if (!a.tribes_detecting) {
    compsBody.appendChild(el('div', 'none', '—'));
  }
  ref.appendChild(box('Playable comps', compsBody));
}
// Ban-picker state, deliberately OUTSIDE render(): the app rebuilds every
// poll second and would wipe in-progress taps. Per game: when the payload's
// game_no changes, seed from the server (a fresh game clears manual bans).
// Once tapping, local state wins for 3s so a poll can't flicker the chip
// back before the POST lands; after that the server (via bans_manual) is
// authoritative and self-heals any missed POST.
let _banPick = new Set(), _banPickGame = null, _banPickAt = 0;
function postBans(list) {
  fetch('/bans', {method: 'POST',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({banned: list})});
}
// 300ms: the live loop pushes up to ~3/s and the advice itself costs ~5ms —
// the 1s browser poll was the perceived lag. Between pushes the server
// answers a header-only 304, so the faster tick is nearly free.
setInterval(poll, 300);
poll();
</script>
</body>
</html>
"""


class _State:
    def __init__(self):
        self.lock = threading.Lock()
        self.analysis = None
        # The serialized /analysis body and its ETag, built once per push
        # (update_analysis) instead of once per request — the page polls at
        # 300ms and a 304 between pushes is a header, not ~40KB of JSON.
        self.payload = b"{}"
        self.etag = None
        # The player-set banned tribes (POST /bans), or None when not set.
        # The ban reveal is on screen at t0 and the pool inference needs
        # minutes to converge, so a 5-tap override at hero pick is the
        # precise path (2026-09-19; the list itself is not in any log).
        self.manual_bans = None


_state = _State()


def store_manual_bans(tribes):
    """Set the manual banned-tribe list; an empty list clears it.

    Only canonical display names (tribes.DISPLAY_TRIBES) are accepted;
    everything else is dropped. Returns the list that stuck (sorted).
    """
    from tribes import DISPLAY_TRIBES
    roster = set(DISPLAY_TRIBES)
    clean = sorted({t for t in (tribes or [])
                    if isinstance(t, str) and t in roster})
    with _state.lock:
        _state.manual_bans = clean if clean else None
    return clean


def latest_manual_bans():
    """The manual banned tribes, or None when the player hasn't set any."""
    with _state.lock:
        return list(_state.manual_bans) if _state.manual_bans is not None \
            else None


@lru_cache(maxsize=1)
def _meta_rows():
    """(minions, spells, trinkets) as id→record maps. The meta DB reads are
    already lru_cached, but rebuilding these three dicts on every analysis
    push (up to ~3/s) was pure waste — they change only on a meta refresh
    (i.e. on process restart, which is the documented live.py contract)."""
    return ({m.get("id"): m for m in meta.minions()},
            {s.get("id"): s for s in meta.spells()},
            {t.get("id"): t for t in meta.trinkets()})


def render_json(analysis):
    """Enrich coach.analyze output with card names for frontend display."""
    names = _load_bg_names()
    a = dict(analysis)
    a["board"] = [dict(m, name=names.get(m["card"], m["card"])) for m in analysis["board"]]
    # Group duplicate board minions (Fauna Whisperer ×2 with different stats
    # used to show as two confusing rows); score = the instance you'd sell
    # first, so the safe→keep order still reads right.
    grouped = {}
    sell = []
    for c, v in analysis["sell_rank"]:
        g = grouped.get(c)
        if g is None:
            g = {"card": c, "name": names.get(c, c), "score": round(v), "n": 1,
                 "golden": any(m["card"] == c and m.get("golden")
                               for m in analysis["board"])}
            grouped[c] = g
            sell.append(g)
        else:
            g["n"] += 1
            g["score"] = min(g["score"], round(v))
    sell.sort(key=lambda g: g["score"])
    # Hand minions are NOT in the Sell row: a hand minion can't be sold —
    # it has to be played first (player-corrected 2026-09-09, superseding
    # the 2026-09-05 "hand minions are sellable too" note that put hand
    # cards under "Safe to sell"). The hand box carries the play advice;
    # the plan's full-board play step already names the board filler to
    # sell for room, and that's the card that's actually sellable.
    # Butchering fuel (2026-09-08, the comp page): with a destroy-cost spell
    # in hand, a safe-to-sell UNDEAD is worth more dead-by-cast than sold —
    # the cast gives permanent +5 Attack to ALL Undead and frees the same
    # slot, where selling gives 1 gold. Annotated so the Sell row and the
    # hand's cast steps point the same direction.
    spell_db = _load_spell_db()
    card_db = _load_card_db()
    holding_destroy = any("destroy a friendly"
                          in ((spell_db.get(s["card"]) or {}).get("text")
                              or "").lower()
                          for s in analysis.get("hand", []))
    if holding_destroy:
        for g in sell:
            race = ((card_db.get(g["card"]) or {}).get("race") or "")
            if g["score"] < SELL_FILLER_SCORE and "Undead" in (race or ""):
                g["fuel"] = True
    # WHY each Sell row sits there (2026-09-10 ask): the score alone can't
    # tell "comp core" (a keep!) from "stats only" (a safe sell) — the
    # reason rides each row from the same inputs the scoring used, so the
    # two can't disagree.
    board_by_card = {}
    for m in analysis["board"]:
        board_by_card.setdefault(m["card"], m)
    tc = analysis.get("target_cards") or {}
    core_ids = {c["card"] for c in (tc.get("core") or [])
                if isinstance(c, dict) and c.get("card")}
    addon_ids = {c["card"] for c in (tc.get("addons") or [])
                 if isinstance(c, dict) and c.get("card")}
    target_comp = next((c for c in (analysis.get("playable_comps") or {}).values()
                        if isinstance(c, dict)
                        and c.get("name") == analysis.get("target_comp")), None)
    banned_tribes = set(analysis.get("banned") or [])
    for g in sell:
        g["why"] = sell_reason(board_by_card.get(g["card"], {}),
                               card_db.get(g["card"]), comp=target_comp,
                               core=core_ids, addons=addon_ids,
                               banned_tribes=banned_tribes)
    a["sell_rank"] = sell
    # Hand-charge engine status (2026-09-10: the Forager/Counter kit died
    # silently — the overlay now shows deployer on board? space? charging).
    a["engine"] = hand_engine(analysis.get("hand") or [], analysis["board"])
    # The hand: casts/plays ranked for the "Your hand" tiles (free actions —
    # the plan's numbered steps carry them too; this row is the reference).
    a["hand"] = [dict(s, name=names.get(s["card"], s["card"]))
                 for s in analysis.get("hand", [])]
    # Tag shop entries by comp membership (core/addon) or kind (spell), so the
    # shop list shows why each card matters without opening the comp DB.
    # Each row also carries its tavern price: minions a FLAT 3 (the patch's
    # default for ALL tiers — the log's tag=479 minion costs are stale legacy
    # tier costs; 2026-09-06 log charged 3 for tags saying 1, player-confirmed),
    # spells their own per-spell price. A wrong price ("thinks minions cost 1
    # gold") is otherwise instantly misleading.
    tc = analysis.get("target_cards") or {}
    core = {c["card"] for c in tc.get("core", [])}
    addons = {c["card"] for c in tc.get("addons", [])}
    spell_db = _load_spell_db()
    spells = set(spell_db)
    # A hand-charge kit's deployer (2026-09-10): the tag names WHY the shop
    # row matters when the comp sets don't — "deploys hand" = the engine
    # piece that summons the chargers back onto the board.
    deployers = {k["deployer"] for r in (analysis.get("hand") or [])
                 for k in [HAND_DEPLOY_KITS.get(r.get("card"))] if k}
    from value import _buy_prices
    prices = _buy_prices(analysis)
    # Pool availability chips (phases 1-2, analysis/pool_availability.md):
    # the shared pool minus what WE hold, minus what FRESH seats hold
    # (sightings <= 2 rounds old — lobby.py). Stale seats are excluded, not
    # guessed at; the wording stays "pool left", never a lobby total.
    held = dict(analysis.get("own_pool") or {})
    for c, n in (analysis.get("opp_pool") or {}).items():
        held[c] = held.get(c, 0) + n
    a["shop_rank"] = [dict(card=c, name=names.get(c, c), score=round(v),
                           price=prices.get(c),
                           pool=(pool.chip(c, held)
                                 if held is not None else None),
                           tag=("core" if c in core else
                                "addon" if c in addons else
                                "spell" if c in spells else
                                "deploys hand" if c.rstrip("_G") in deployers
                                else None))
                      for c, v in analysis.get("shop_rank", [])]
    # Next-opponent composition (phase 2): the seat's last-known board as
    # named tiles, golden-flagged, biggest first. Age rides along — the box
    # says "as of round N" so a stale preview never reads current.
    oc = analysis.get("opp_comp")
    if oc:
        cards = [{"card": c, "name": names.get(c, c), "n": n,
                  "golden": c in (oc.get("goldens") or [])}
                 for c, n in sorted(oc["cards"].items(),
                                    key=lambda kv: (-kv[1], kv[0]))]
        a["opp_comp"] = dict(oc, cards=cards)
    # Pre-commit "leads" tagging (comp meter): with no target committed yet,
    # shop cards that are unowned core of the leading candidate get a "leads
    # <tribe>" tag — that's the card the meter is waiting on. Once a target
    # exists the core/addon tags above take over.
    progress = analysis.get("comp_progress") or []
    if not analysis.get("target_comp") and progress:
        lead = progress[0]
        leads_set = set(lead.get("needs") or [])
        if leads_set:
            label = "leads " + (lead.get("tribe") or lead.get("name") or "")
            a["shop_rank"] = [dict(row, tag=label if row["card"] in leads_set
                                   else row["tag"])
                              for row in a["shop_rank"]]
    a["target_cards"] = analysis.get("target_cards")
    # Commit-readiness meter (per-candidate core hits) — pre-commit the
    # player is otherwise blind to direction until comp_target fires. The
    # missing-core ids are named here so the UI can show them as tiles
    # ("these lead to <comp>") without a client-side id->name map.
    a["comp_progress"] = [
        dict(r, needs=[{"card": cid, "name": names.get(cid, cid)}
                       for cid in (r.get("needs") or [])])
        for r in progress
    ]
    # Playable comps, rich rows for the bottom comps panel (2026-09-09): the
    # analysis carries a slug->comp dict; the UI groups them by meta tier and
    # each row expands into its required cards, so it needs the full shopping
    # list with owned/banned flags — not just names. owned = on the board
    # (same rule as the target-comp box: the board is what fights), banned =
    # a banned-tribe core piece of a hybrid comp (_blocked_core — can't be
    # bought this game). Sorted meta-tier first so the panel can group.
    # game_comps (2026-09-11) is the live coach's game-level list for this
    # panel — during the ban-detection window it's ALL comps, each with
    # _tribe_confirmed so unconfirmed rows can dim; playable_comps remains
    # the evidence-only advisory filter and is the fallback for analyses
    # without game_comps (coach.py, tests).
    pc = analysis.get("game_comps") or analysis.get("playable_comps") or {}
    if isinstance(pc, dict):
        comp_items = list(pc.items())
    else:
        comp_items = [(c.get("name"), c) for c in (pc or [])
                      if isinstance(c, dict)]
    board_ids = {m["card"] for m in analysis["board"]}
    tier_rank = {"S": 0, "A": 1, "B": 2}
    comp_rows = []
    for slug, comp in comp_items:
        if not isinstance(comp, dict) or not comp.get("name"):
            continue
        blocked = set(comp.get("_blocked_core") or [])

        def rows(ids_, _blocked=blocked):
            return [{"card": cid, "name": names.get(cid, cid),
                     "owned": cid in board_ids, "banned": cid in _blocked}
                    for cid in (ids_ or [])]

        comp_rows.append({
            "slug": slug,
            "name": comp["name"],
            "meta_tier": comp.get("meta_tier"),
            # Mined from our own corpus rather than published (value.
            # _is_provisional): the panel groups these under "Provisional"
            # instead of a tier, and they sort LAST — a comp with no published
            # tier must never appear above a real S/A/B comp.
            "provisional": bool(comp.get("provisional")),
            "evidence": comp.get("evidence"),
            # Tribe confirmed in this lobby? Absent (True) once the bans
            # resolve; False only inside the detection window, where the
            # panel dims the could-still-be-banned rows.
            "tribe_confirmed": comp.get("_tribe_confirmed", True),
            "core": rows(comp.get("core")),
            "addons": rows(comp.get("addons")),
        })
    comp_rows.sort(key=lambda c: (1 if c["provisional"] else 0,
                                  tier_rank.get(c["meta_tier"], 3),
                                  c["name"] or ""))
    a["comps"] = comp_rows
    # The Buy box mirrors the top move's actual buy/roll step (buy_step_card /
    # buy_step_roll are written by value.top_move), so the two can't disagree.
    a["buy_step_card"] = analysis.get("buy_step_card")
    a["buy_roll_text"] = analysis.get("buy_step_roll")
    # A buy the SLOT arbiter talked the plan out of (analysis/board_swap.md):
    # value.top_move rewrites its step and records the card here, so the Buy box
    # cannot keep blessing a card the numbers just argued against.
    a["buy_step_swap_veto"] = analysis.get("buy_step_swap_veto")
    # Which card the plan is feeding to a discard outlet, and why (analysis/
    # discard_mechanic.md): the hand box and the plan must name the same card.
    a["discard_target"] = analysis.get("discard_target")
    # Structured steps from value.top_move — [{text, kind, card}]. The JS
    # renders from these (2026-09-24 flip, the audit's render-at-the-edge
    # rework); the string is the fallback for the minimal Choose-1 payload.
    a["top_move_steps"] = analysis.get("top_move_steps") or []
    # Scout strip (gates 3+4): our stat total vs the next opponent's
    # last-known board (exact — we fought them), else the lobby median /
    # corpus baseline (~ estimate).
    bs = analysis.get("board_stats")
    their = analysis.get("opp_stats")
    approx = their is None
    if their is None:
        their = analysis.get("lobby_opp")
    if their is None:
        their = analysis.get("baseline_opp")
    a["scout"] = (f"you {bs} stats · "
                  f"{'~' if approx else ''}{int(their)} theirs"
                  if bs is not None and their else None)
    # The next-fight verdict (stat ratio + our keyword edges) rides the
    # scout strip so "will the next fight kill me" is on screen.
    a["forecast"] = analysis.get("forecast")
    # Opponents' trinkets (visible in the log, 2026-09-08 ground truth) — free
    # intel the player cannot see in game. `dark_gifts` is DROPPED from the
    # payload since 2026-09-23 (the overlay no longer renders it: it listed gifts
    # the player already owns and the game already shows). render_json copies the
    # whole analysis, so the drop has to be explicit — leaving the key would keep
    # shipping state the page has no use for.
    a.pop("dark_gifts", None)
    a["opp_trinkets"] = analysis.get("opp_trinkets") or []
    # Thresholds the JS would otherwise hard-code (dying HP, the sell
    # safe/keep split) — value.py's constants are the single source; the
    # page reads them with fallbacks so an old payload still renders.
    a["thresholds"] = {"dying_hp": DYING_HEALTH,
                       "sell_safe_below": SELL_FILLER_SCORE}
    # Per-card display metadata for the overlay (2026-09-09): the tavern tier
    # for the '*N' name badge and the card text for the hover tooltip — so
    # cards whose full render isn't upstream (new sets, trinkets) still get
    # their text. Golden ids resolve to their base card; heroes carry no
    # tier/text in the DBs, so pick-panel names badge nothing.
    ids = set()
    ids.update(g["card"] for g in sell)
    ids.update(s["card"] for s in analysis.get("hand", []))
    ids.update(r["card"] for r in a["shop_rank"])
    ids.update(c["card"] for key in ("core", "addons")
               for c in (tc.get(key) or []))
    # The comps panel's shopping lists ride the same tooltip metadata.
    for comp in a["comps"]:
        for key in ("core", "addons"):
            ids.update(r["card"] for r in comp[key])
    # comp meter needs: the RENDERED rows (a["comp_progress"]) carry needs as
    # {card, name} dicts; the raw analysis rows carry needs as bare card-id
    # strings (value.comp_progress), and c["card"] on those raised
    # "string indices must be integers" — crashing every analysis push once
    # the meter had a candidate with unowned core (i.e. most of the game).
    ids.update(c["card"] for r in a["comp_progress"]
               for c in (r.get("needs") or []))
    choice = analysis.get("choice") or {}
    ids.update(row[1] for row in (choice.get("ranked") or [])
               if len(row) > 1 and row[1])
    mrows, srows, trows = _meta_rows()
    cards = {}
    for cid in sorted(ids):
        base = cid[:-2] if cid.endswith("_G") else cid
        rec = mrows.get(base) or srows.get(base) or {}
        entry = {}
        if rec.get("tier"):
            entry["tier"] = rec["tier"]
        text = rec.get("text") or (trows.get(base) or {}).get("description")
        if text:
            entry["text"] = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", text))
        if entry:
            cards[base] = entry
    a["cards"] = cards
    return a


def update_analysis(analysis):
    """Store the latest rendered analysis for the overlay to serve."""
    data = json.dumps(render_json(analysis)).encode()
    etag = hashlib.sha1(data).hexdigest()
    with _state.lock:
        _state.analysis = json.loads(data)
        _state.payload = data
        _state.etag = etag


def latest_analysis():
    with _state.lock:
        return _state.analysis


def _analysis_response(if_none_match=None):
    """(code, headers, body) for GET /analysis. Pure, so the 304 path is
    testable without a socket. ETag/304 rather than SSE: the transport is
    BaseHTTPRequestHandler (HTTP/1.0, no keep-alive) and the client is
    loopback — a 304 costs microseconds and reuses the request path that
    already exists."""
    with _state.lock:
        payload, etag = _state.payload, _state.etag
    headers = {"Cache-Control": "no-cache"}
    if etag:
        headers["ETag"] = f'"{etag}"'
    if if_none_match and etag and etag in if_none_match:
        return 304, headers, b""
    return 200, headers, payload


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.rstrip("/") == "/analysis":
            code, headers, body = _analysis_response(
                self.headers.get("If-None-Match"))
            self._send(code, "application/json", body, headers=headers)
            return
        if self.path.rstrip("/") == "/artmiss":
            # Served BEFORE the /img regex (the pattern would otherwise not
            # match this path, but the ordering keeps the routes obvious).
            self._send(200, "application/json",
                       json.dumps({"misses": _active_misses()}).encode())
            return
        m = re.match(r"^/img/([A-Za-z0-9_]+)\.png$", self.path)
        if m:
            cid = m.group(1)
            path = os.path.join(_HERE, "img_cache", f"{cid}.png")
            if not os.path.exists(path) and _can_retry(cid):
                # On-demand: fetch the render now so the hero/trinket/
                # minion art appears on the next UI poll instead of never.
                _fetch_render(cid)
            if os.path.exists(path):
                with open(path, "rb") as f:
                    # Art is content-addressed by card id — cacheable hard.
                    self._send(200, "image/png", f.read(),
                               headers={"Cache-Control":
                                        "public, max-age=604800"})
                return
            self._send(404, "text/plain", b"no art cached",
                       headers={"Cache-Control": "no-store"})
            return
        m = re.match(r"^/card/([A-Za-z0-9_]+)\.png$", self.path)
        if m:
            # The hover tooltip's full render (framed card WITH text),
            # cached in img_cache/card/. Golden ids resolve to the base
            # card; misses share the /img miss list (same upstream URL).
            cid = m.group(1)
            if cid.endswith("_G"):
                cid = cid[:-2]
            path = os.path.join(CARD_DIR, f"{cid}.png")
            if not os.path.exists(path) and _can_retry(cid):
                _fetch_render(cid, dest_dir=CARD_DIR)
            if os.path.exists(path):
                with open(path, "rb") as f:
                    self._send(200, "image/png", f.read(),
                               headers={"Cache-Control":
                                        "public, max-age=604800"})
                return
            self._send(404, "text/plain", b"no card render cached",
                       headers={"Cache-Control": "no-store"})
            return
        # The page itself: no-cache so a Phase-2 CSS edit is picked up on
        # refresh (it previously had no validator at all, and Chrome's
        # heuristic caching served stale markup).
        self._send(200, "text/html; charset=utf-8", _HTML.encode(),
                   headers={"Cache-Control": "no-cache"})

    def do_POST(self):
        if self.path.rstrip("/") == "/bans":
            n = int(self.headers.get("Content-Length") or 0)
            try:
                payload = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                self._send(400, "application/json", b'{"error":"bad json"}')
                return
            banned = store_manual_bans(payload.get("banned"))
            self._send(200, "application/json",
                       json.dumps({"ok": True, "banned": banned}).encode())
            return
        self._send(404, "text/plain", b"no such endpoint")

    def _send(self, code, ctype, body, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # silence request logging
        pass


def start_server(port=DEFAULT_PORT):
    """Start the overlay server in a background thread; returns the server.

    Threading: an on-demand art fetch blocks that request for up to ~5s —
    on the single-threaded server it would stall /analysis polling.
    """
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    import sys
    port = DEFAULT_PORT
    for a in sys.argv[1:]:
        if a.startswith("--port"):
            port = int(a.split("=")[1])
    start_server(port)
    print(f"Coach UI serving at http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
