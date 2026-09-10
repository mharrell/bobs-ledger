#!/usr/bin/env python3
"""V1 coaching UI: a local overlay served over HTTP.

Runs a tiny stdlib HTTP server (no dependencies). `live.py` pushes the latest
situation analysis here each buy phase; the server exposes it as JSON at
`/analysis` and serves a static HTML/CSS/JS page at `/` that polls it. Layout
(2026-09-04 rework, player-directed): one priority column — a big "Do this
now" instruction panel (pending pick, then the numbered plan steps, then the
level/roll reference line), then horizontal game-like card tiles: the Sell
row split into "safe to sell | do not sell" groups (the value function's own
filler threshold, score < 15), the target-comp shopping list, and the ranked
tavern with the plan's buy glowing gold. The board list is gone (the sell
row covers what matters); triggers/turn live in the state strip.
Design: analysis/DESIGN_COACHING_UI.md. Tile names carry a '*N' tavern-tier
badge (2026-09-09); hovering a tile shows the full card render — framed
layout WITH text (img_cache/card/, fetched on demand) — or, when upstream
has no render, the card text from the meta DBs. The bottom "Playable comps"
panel (2026-09-09) groups the playable comps by meta tier; clicking a comp
expands its required cards (owned faded, banned struck out), clicking again
collapses it (expansion state survives the 1s poll rebuilds).

Usage:
    python coach_ui.py [--port N]     # run the server standalone (empty state)
"""
import json
import os
import re
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from value import _load_bg_names, _load_card_db, _load_spell_db

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


def _remember_miss(cid):
    with _art_lock:
        _art_miss[cid] = time.time()
        try:
            with open(_art_miss_path, "w", encoding="utf-8") as f:
                json.dump(_art_miss, f)
        except OSError:
            pass


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
  :root { --bg:#14161a; --panel:#1e2126; --panel2:#262a31; --text:#e8e8e8;
          --dim:#9aa0a8; --good:#5fd97a; --warn:#f0b04a; --bad:#e86a5a; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font:14px/1.45 "Segoe UI", system-ui, sans-serif; padding:8px; }
  #wrap { max-width:1600px; margin:0 auto; }
  /* State strip spans the whole width; the boxes flow in three columns on a
     wide window (the old 780px panel left two-thirds of the screen empty). */
  #statebar { display:flex; align-items:center; gap:12px; flex-wrap:wrap;
              background:var(--panel); border:1px solid #2c2f36;
              border-radius:6px; padding:6px 12px; margin-bottom:8px;
              font-size:15px; font-weight:600; }
  #statebar .lbl { color:var(--dim); font-weight:400; font-size:12px; }
  #statebar .good { color:var(--good); font-weight:400; font-size:12px; }
  #statebar .bad { color:var(--bad); font-weight:400; font-size:12px; }
  #statebar .banned { color:var(--dim); font-weight:400; font-size:12px; }
  /* One priority column: explicit instructions first, then the horizontal
     card rows (game-like), then reference chips. */
  #app { display:flex; flex-direction:column; gap:8px; min-width:0; }
  .box { background:var(--panel); border:1px solid #2c2f36; border-radius:6px;
         padding:7px 9px; }
  .box h3 { margin:0 0 4px; font-size:11px; letter-spacing:.06em;
            text-transform:uppercase; color:var(--dim); }
  /* The instruction panel is THE element: gold border, big numbered steps. */
  .instructions { border:2px solid var(--gold); padding:10px 12px; }
  .instructions h3 { color:var(--gold); font-size:12px; }
  .instructions .step { font-size:19px; padding:3px 0; }
  .instructions .footline { margin-top:6px; padding-top:5px;
                            border-top:1px solid #2c2f36;
                            color:var(--dim); font-size:13px; }
  .instructions .pickline { font-size:19px; font-weight:700;
                            color:var(--good); padding:3px 0; }
  /* The situation read: the plan's one-line thread. */
  .instructions .situation { font-size:14px; font-weight:600;
                             color:var(--warn); padding:2px 0 3px; }
  /* Horizontal game-like card tiles: thumb on top, name below. */
  .tiles { display:flex; flex-wrap:wrap; gap:10px 12px; align-items:flex-start; }
  .tile { display:flex; flex-direction:column; align-items:center; gap:2px;
          width:104px; min-width:0; text-align:center; }
  .tile .thumb { width:56px; height:56px; }
  .tile .tname { font-size:12px; line-height:1.25; width:104px; overflow:hidden;
                 text-overflow:ellipsis; white-space:nowrap; }
  .tile .tsub { font-size:11px; color:var(--dim); }
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
              background:#2c2f36; border-radius:1px; }
  /* Target-comp tiles: what you're hunting fully opaque, owned faded. */
  .tile.comprow { opacity:.4; }
  .tile.comprow.missing { opacity:1; }
  /* A banned-tribe piece of a hybrid comp: struck out, dim. */
  .tile.comprow.bannedrow .tname { text-decoration:line-through; }
  .tile.comprow.bannedrow .tsub { color:var(--bad); }
  .gold { color:#ffd97a; }
  .thumb { width:56px; height:56px; border-radius:5px; object-fit:cover; flex:none;
           cursor:zoom-in; transition:transform .12s ease-out; }
  /* No art cached for this card: a same-size placeholder keeps every row
     aligned (missing art used to collapse the row and shift names). */
  .thumb.ph { display:inline-flex; align-items:center; justify-content:center;
              color:var(--dim); background:var(--panel2);
              border:1px solid #2c2f36; font-size:18px; cursor:default; }
  /* Hover zoom (the fallback when no tooltip appears): art is 256x256, so
     scale(4.5) on a 56px tile thumb shows it near full size; origin center
     bottom grows the popup up and outward from the tile, z-index floats it
     above the other boxes. Scoped to real images with no tooltip content —
     canzoom is dropped the moment a render/text tooltip shows. */
  img.thumb.canzoom:hover { transform:scale(4.5); transform-origin:center bottom;
                    position:relative; z-index:5; }
  .thumb.golden { box-shadow:0 0 0 2px #ffd97a; }
  /* The plan's buy glows in the tavern tiles. */
  img.thumb.buynowart { box-shadow:0 0 0 2px var(--gold); }
  /* Hover card: the full framed render (with text) near the tile, or — when
     upstream has no render for the card — a text box fed from the meta DB. */
  #tip { position:fixed; z-index:50; max-width:300px; }
  .tiprender { display:block; width:256px; border-radius:8px;
               box-shadow:0 8px 24px rgba(0,0,0,.65); }
  .tipbox { background:var(--panel2); border:1px solid #2c2f36;
            border-radius:6px; padding:6px 9px; max-width:280px;
            box-shadow:0 8px 24px rgba(0,0,0,.65); }
  .tipname { font-weight:700; font-size:13px; }
  .tiptext { font-size:12px; color:var(--dim); margin-top:2px; }
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
  .carrow { color:var(--dim); font-size:11px; flex:none; width:10px; }
  .cname { font-weight:600; }
  .cstat { color:var(--dim); font-size:12px; flex:none; }
  .cbody { padding:0 0 4px 17px; }
  /* Top move: each numbered priority step on its own line */
  .step { font-size:16px; font-weight:700; line-height:1.4; padding:1px 0; }
  .stepnum { color:var(--gold); margin-right:7px; }
  .target { font-size:14px; font-weight:600; color:var(--gold); }
  .target .pivot { color:var(--warn); }
  .tag-core { color:var(--gold); }
  .tag-spell { color:#7ab8f0; }
  .tag-addon { color:var(--warn); }
  /* Comp direction meter: pip row + candidate name + distance-to-commit. */
  .mrow { display:flex; align-items:baseline; gap:8px; padding:2px 0;
          font-size:14px; min-width:0; }
  .mrow .pips { font-size:13px; letter-spacing:2px; color:var(--dim);
                flex:none; }
  .mrow .pips .full { color:var(--gold); }
  .mrow .mname { font-weight:600; overflow:hidden; text-overflow:ellipsis;
                 white-space:nowrap; }
  .mrow .mstat { color:var(--dim); font-size:12px; flex:none; }
  .mrow.locked .mname { color:var(--gold); font-weight:700; }
  .none { color:var(--dim); font-style:italic; }
  .score { color:var(--dim); flex:none; }
  .xcount { color:var(--dim); font-weight:400; }
</style>
</head>
<body>
<div id="wrap">
<div id="statebar">Waiting for live.py analysis…</div>
<div id="app"></div>
</div>
<script>
let _lastPayload = null;
async function poll() {
  try {
    const r = await fetch('/analysis');
    const raw = await r.text();
    if (raw === _lastPayload) return;  // nothing changed — don't rebuild the
    _lastPayload = raw;                // DOM (rebuilding every second made
    render(JSON.parse(raw));           // thumbnails flicker)
  } catch (e) { /* keep last frame */ }
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
// Card art thumbnail (img_cache/ via /img/<id>.png, fetched by fetch_art.py).
// Hides itself gracefully when no art is cached (current-set BG-only cards).
// Hover shows the full card render (framed layout WITH text) via /card/,
// falling back to a text box from the meta DB, then to the old portrait zoom.
function thumb(cid, name) {
  const img = document.createElement('img');
  img.className = 'thumb canzoom';
  img.src = '/img/' + cid + '.png';
  img.alt = '';
  img.onmouseenter = () => hoverCard(img, cid, name);
  img.onmouseleave = leaveCard;
  img.onerror = () => {
    // No art available (render build lags the patch; trinkets have none
    // upstream): a same-size placeholder keeps every row aligned.
    const ph = document.createElement('span');
    ph.className = 'thumb ph';
    ph.textContent = (name || '?').trim().charAt(0).toUpperCase();
    ph.onmouseenter = () => hoverCard(ph, cid, name);
    ph.onmouseleave = leaveCard;
    img.replaceWith(ph);
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
// again collapses. The open set survives the 1s poll rebuilds (a rebuild
// drops the DOM but re-opens whatever was open). The collapsed row already
// says how much of the core you own, so expanding is only for the detail.
const _openComps = new Set();
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
  const head = el('div', 'crowhead');
  const arrow = el('span', 'carrow', open ? '▾' : '▸');
  head.appendChild(arrow);
  const core = c.core || [];
  head.appendChild(el('span', 'cname', c.name));
  head.appendChild(el('span', 'cstat',
    core.length + ' core · '
    + core.filter(x => x.owned).length + ' owned'));
  const body = el('div', 'cbody');
  // Collapsed rows build their tiles lazily (on first expand) so a 21-comp
  // panel doesn't queue 100+ card fetches up front; an open row builds now.
  body.hidden = !open;
  if (open) body.appendChild(compTiles(c));
  head.onclick = () => {
    const nowOpen = !_openComps.has(c.slug);
    if (nowOpen) _openComps.add(c.slug); else _openComps.delete(c.slug);
    head.classList.toggle('open', nowOpen);
    arrow.textContent = nowOpen ? '▾' : '▸';
    body.hidden = !nowOpen;
    if (nowOpen && !body.children.length) body.appendChild(compTiles(c));
  };
  const wrap = el('div', 'crow');
  wrap.appendChild(head);
  wrap.appendChild(body);
  return wrap;
}
function render(a) {
  const app = document.getElementById('app');
  const statebar = document.getElementById('statebar');
  // A rebuild discards the hovered element without a mouseleave — drop the
  // tooltip with the old frame so it can't outlive its card.
  leaveCard();
  CARDS = a.cards || {};
  app.innerHTML = '';
  statebar.innerHTML = '';
  if (!a || !a.board) { statebar.textContent = 'No game yet.'; return; }
  // Pre-warm the /card renders for everything on screen so hovers are
  // instant (one-time per card: the server caches downloads in
  // img_cache/card/, and misses are remembered server-side).
  Object.keys(CARDS).forEach(cid => {
    if (!_warmed.has(cid)) {
      _warmed.add(cid);
      new Image().src = '/card/' + cid + '.png';
    }
  });

  // STATE STRIP — hero / gold / tier / turn / scout / banned / triggers
  statebar.appendChild(el('span', null, a.hero || '?'));
  const gold = el('span', null); gold.appendChild(el('span', 'lbl', 'Gold '));
  gold.appendChild(el('span', 'gold', String(a.gold ?? '?')));
  statebar.appendChild(gold);
  const tier = el('span', null); tier.appendChild(el('span', 'lbl', 'Tier '));
  tier.appendChild(el('span', null, String(a.tier ?? '?')));
  statebar.appendChild(tier);
  if (a.health != null) {
    const dying = a.health + (a.armor || 0) <= 12;
    const hp = el('span', null); hp.appendChild(el('span', 'lbl', 'HP '));
    hp.appendChild(el('span', dying ? 'bad' : null,
      a.health + (a.armor ? '+' + a.armor : '')));
    statebar.appendChild(hp);
  }
  const turns = (a.scenario || {}).turns;
  if (turns) {
    const t = el('span', null); t.appendChild(el('span', 'lbl', 'Turn '));
    t.appendChild(el('span', null, String(turns)));
    statebar.appendChild(t);
  }
  if (a.scout) {
    statebar.appendChild(el('span', 'lbl', a.scout));
  }
  if (a.forecast) {
    // The next-fight verdict: colored by its verdict word.
    const good = a.forecast.startsWith('favored');
    const cls = good ? 'good' : (a.forecast.startsWith('behind') ? 'bad' : null);
    statebar.appendChild(el('span', cls, a.forecast));
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

  // INSTRUCTIONS — the explicit, do-this-now panel. A pending pick gates
  // everything, so it reads first; then the numbered plan steps; then the
  // level/roll reference line.
  const instr = el('div', 'box instructions');
  instr.appendChild(el('h3', null, 'Do this now'));
  // The situation read: the plan's thread (direction, strength, danger) in
  // one line, so the numbered steps read as a story instead of a list.
  if (a.situation) instr.appendChild(el('div', 'situation', a.situation));
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
    a.top_move.split(' · ').forEach(step => {
      const m = step.match(/^(\d+)\. (.*)$/);
      const line = el('div', 'step');
      if (m) {
        line.appendChild(el('span', 'stepnum', m[1]));
        line.appendChild(el('span', null, m[2]));
      } else {
        line.textContent = step;
      }
      instr.appendChild(line);
    });
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
  // Dark gifts (what Dark Discovery granted) and the opponents' trinkets —
  // both read from the log (2026-09-08 ground truth).
  (a.dark_gifts || []).forEach(g => {
    instr.appendChild(el('div', 'footline',
      'Dark gift: ' + g.name + ' — ' + (g.description || '')));
  });
  if (a.opp_trinkets && a.opp_trinkets.length) {
    instr.appendChild(el('div', 'footline',
      'Their trinkets: ' + a.opp_trinkets.join(', ')));
  }
  app.appendChild(instr);

  // The plan's actual buy (highlighted in the shop tiles below too).
  const stepCard = a.buy_step_card || null;

  // HAND — casts from hand are free, stuck minions play free; the ranked
  // order here is the plan's hand steps (they're numbered in the panel too).
  if (a.hand && a.hand.length) {
    const tiles = el('div', 'tiles');
    a.hand.forEach(s => {
      const sub = (s.verb === 'cast' ? 'cast' : s.verb === 'hold' ? 'hold' : 'play')
        + (s.score != null ? ' · ' + s.score.toFixed(0) : '');
      tiles.appendChild(tile(s.card, s.name, sub, {golden: s.golden}));
    });
    app.appendChild(box('Your hand', tiles));
  }

  // SELL — one horizontal line: safe to sell | divider | do not sell.
  // The split is the value function's own filler threshold (score < 15 is
  // what top_move calls "a clear filler").
  const sellSafe = el('div', 'tiles');
  const sellKeep = el('div', 'tiles');
  (a.sell_rank || []).forEach(s => {
    // Board minions only — a hand card can't be sold until it's played
    // (player rule 2026-09-09), so render_json keeps hand entries out.
    // A Butchering-fuel undead reads "cast it instead of selling".
    const sub = s.score.toFixed(0)
      + (s.fuel ? ' · cast, not sell' : '');
    const t = tile(s.card, s.name, sub,
                   {golden: s.golden, n: s.n, cls: s.score < 15 ? 'safe' : 'keep'});
    (s.score < 15 ? sellSafe : sellKeep).appendChild(t);
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
  app.appendChild(box('Sell', sellBody));

  // TARGET COMP — what you're hunting: horizontal tiles, missing pieces
  // fully opaque, owned pieces faded.
  if (a.target_comp) {
    const pivot = a.target_state === 'pivot';
    const body = el('div', 'target',
      (pivot ? 'pivot to ' : 'committing to ') + a.target_comp);
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
    app.appendChild(box('Looking for (' + (pivot ? 'pivot' : 'comp') + ')', body));
  }

  // COMP DIRECTION — commit-readiness meter: how close each candidate comp
  // is to the 2-core-hit commit threshold, BEFORE comp_target declares a
  // target. The committed comp glows gold; pre-commit, the top candidate's
  // missing core is shown as tiles (the cards that move the meter).
  if (a.comp_progress && a.comp_progress.length) {
    const body = el('div');
    a.comp_progress.forEach(r => {
      const row = el('div', 'mrow' + (r.name === a.target_comp ? ' locked' : ''));
      const pips = el('span', 'pips');
      const n = Math.min(r.hits, 2);
      for (let i = 0; i < 2; i++) {
        pips.appendChild(el('span', i < n ? 'full' : null, i < n ? '●' : '○'));
      }
      if (r.hits > 2) pips.appendChild(el('span', 'full', '×' + r.hits));
      row.appendChild(pips);
      row.appendChild(el('span', 'mname', r.name));
      row.appendChild(el('span', 'mstat',
        r.name === a.target_comp
          ? (a.target_state === 'pivot' ? 'pivoting — committed' : 'committed')
          : r.ready ? 'ready to commit'
          : (r.tribe_hits || 0) >= 2
            ? 'one core card away · tribe signal'
            : 'one core card away'));
      body.appendChild(row);
    });
    if (!a.target_comp && (a.comp_progress[0].needs || []).length) {
      const t = el('div', 'tiles');
      a.comp_progress[0].needs.forEach(c => t.appendChild(tile(c.card, c.name)));
      body.appendChild(t);
    }
    app.appendChild(box('Comp direction', body));
  }

  // TAVERN — the ranked shop as a horizontal card row (game-like); the
  // plan's buy glows gold. Score + price under each card.
  if (a.shop_rank && a.shop_rank.length) {
    const tiles = el('div', 'tiles');
    a.shop_rank.forEach(s => {
      const sub = (s.price != null ? s.price + 'g · ' : '') + s.score.toFixed(0)
        + (s.tag ? ' · ' + s.tag : '');
      tiles.appendChild(tile(s.card, s.name, sub,
                             {cls: s.card === stepCard ? 'buynow' : null,
                              golden: s.golden}));
    });
    app.appendChild(box('Tavern (ranked)', tiles));
  } else {
    app.appendChild(box('Tavern', el('div', 'none', 'offer not parsed yet')));
  }

  // PLAYABLE COMPS — the bottom panel: grouped by meta tier (S/A/B, the
  // server pre-sorts), each comp a clickable row that expands into its
  // required cards with owned/banned flags. Click again to collapse.
  const compsBody = el('div');
  if (a.comps && a.comps.length) {
    let lastTier = null;
    a.comps.forEach(c => {
      const tier = c.meta_tier || '?';
      if (tier !== lastTier) {
        lastTier = tier;
        compsBody.appendChild(el('div', 'cptier',
          tier === '?' ? 'Unranked' : tier + ' tier'));
      }
      compsBody.appendChild(compRow(c));
    });
  } else {
    compsBody.appendChild(el('div', 'none', '—'));
  }
  app.appendChild(box('Playable comps', compsBody));
}
setInterval(poll, 1000);
poll();
</script>
</body>
</html>
"""


class _State:
    def __init__(self):
        self.lock = threading.Lock()
        self.analysis = None


_state = _State()


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
    holding_destroy = any("destroy a friendly"
                          in ((spell_db.get(s["card"]) or {}).get("text")
                              or "").lower()
                          for s in analysis.get("hand", []))
    if holding_destroy:
        card_db = _load_card_db()
        for g in sell:
            race = ((card_db.get(g["card"]) or {}).get("race") or "")
            if g["score"] < 15 and "Undead" in (race or ""):
                g["fuel"] = True
    a["sell_rank"] = sell
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
    from value import _buy_prices
    prices = _buy_prices(analysis)
    a["shop_rank"] = [dict(card=c, name=names.get(c, c), score=round(v),
                           price=prices.get(c),
                           tag=("core" if c in core else
                                "addon" if c in addons else
                                "spell" if c in spells else None))
                      for c, v in analysis.get("shop_rank", [])]
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
    pc = analysis.get("playable_comps") or {}
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
            "core": rows(comp.get("core")),
            "addons": rows(comp.get("addons")),
        })
    comp_rows.sort(key=lambda c: (tier_rank.get(c["meta_tier"], 3),
                                  c["name"] or ""))
    a["comps"] = comp_rows
    # The Buy box mirrors the top move's actual buy/roll step (buy_step_card /
    # buy_step_roll are written by value.top_move), so the two can't disagree.
    a["buy_step_card"] = analysis.get("buy_step_card")
    a["buy_roll_text"] = analysis.get("buy_step_roll")
    # Structured steps from value.top_move — [{text, kind, card}]. The JS
    # still renders from the top_move string today; migrating it onto these
    # (one entry per step, kind-tagged, buy card attached) is the planned
    # render-at-the-edge rework.
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
    # Dark gifts (what Dark Discovery granted) and the opponents' trinkets
    # (visible in the log, 2026-09-08 ground truth) — free intel lines.
    a["dark_gifts"] = analysis.get("dark_gifts") or []
    a["opp_trinkets"] = analysis.get("opp_trinkets") or []
    # When leveling leads the top move, the buy is what you do with the
    # leftover — label it that way so the priorities read in order.
    a["buy_label"] = ("Then buy (after leveling)"
                      if (analysis.get("top_move") or "").startswith("1. LEVEL")
                      else "Buy this")
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
    mrows = {m.get("id"): m for m in meta.minions()}
    srows = {s.get("id"): s for s in meta.spells()}
    trows = {t.get("id"): t for t in meta.trinkets()}
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
    with _state.lock:
        _state.analysis = render_json(analysis)


def latest_analysis():
    with _state.lock:
        return _state.analysis


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.rstrip("/") == "/analysis":
            with _state.lock:
                data = json.dumps(_state.analysis) if _state.analysis else "{}"
            self._send(200, "application/json", data.encode())
        else:
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
                        self._send(200, "image/png", f.read())
                    return
                self._send(404, "text/plain", b"no art cached")
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
                        self._send(200, "image/png", f.read())
                    return
                self._send(404, "text/plain", b"no card render cached")
                return
            self._send(200, "text/html; charset=utf-8", _HTML.encode())

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
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
