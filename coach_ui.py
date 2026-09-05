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
Design: analysis/DESIGN_COACHING_UI.md.

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

_HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_PORT = 8747

# On-demand card art. HearthstoneJSON's render build lags the current patch —
# returning minions (old ids) and most heroes render, but brand-new minions,
# the newest heroes, and ALL trinkets 404 upstream (and the wiki is
# Cloudflare-blocked), so those stay as UI placeholders.
RENDER_URL = "https://art.hearthstonejson.com/v1/render/latest/enUS/256x/{}.png"
MISS_TTL = 3600.0  # seconds before re-attempting a card id that 404'd

_art_lock = threading.Lock()
_art_miss_path = os.path.join(_HERE, ".art_miss.json")
os.makedirs(os.path.join(_HERE, "img_cache"), exist_ok=True)
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


def _fetch_render(cid):
    """Download the HearthstoneJSON render for cid into img_cache. True on
    success. The browser re-requests images on every DOM rebuild, so a miss
    is remembered for MISS_TTL — repeated polls must not re-hammer upstream.
    """
    try:
        req = urllib.request.Request(RENDER_URL.format(cid),
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = r.read()
        with open(os.path.join(_HERE, "img_cache", f"{cid}.png"), "wb") as f:
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
  .gold { color:#ffd97a; }
  .thumb { width:56px; height:56px; border-radius:5px; object-fit:cover; flex:none;
           cursor:zoom-in; transition:transform .12s ease-out; }
  /* No art cached for this card: a same-size placeholder keeps every row
     aligned (missing art used to collapse the row and shift names). */
  .thumb.ph { display:inline-flex; align-items:center; justify-content:center;
              color:var(--dim); background:var(--panel2);
              border:1px solid #2c2f36; font-size:18px; cursor:default; }
  /* Hover zoom: art is 256x256, so scale(4.5) on a 56px tile thumb shows it
     near full size; origin center bottom grows the popup up and outward
     from the tile, z-index floats it above the other boxes. Scoped to real
     images — a placeholder has nothing to zoom. */
  img.thumb:hover { transform:scale(4.5); transform-origin:center bottom;
                    position:relative; z-index:5; }
  .thumb.golden { box-shadow:0 0 0 2px #ffd97a; }
  /* The plan's buy glows in the tavern tiles. */
  img.thumb.buynowart { box-shadow:0 0 0 2px var(--gold); }
  .chips { display:flex; flex-wrap:wrap; gap:4px; }
  .chip { background:var(--panel2); border-radius:10px; padding:1px 8px;
          font-size:13px; }
  /* Top move: each numbered priority step on its own line */
  .step { font-size:16px; font-weight:700; line-height:1.4; padding:1px 0; }
  .stepnum { color:var(--gold); margin-right:7px; }
  .target { font-size:14px; font-weight:600; color:var(--gold); }
  .target .pivot { color:var(--warn); }
  .tag-core { color:var(--gold); }
  .tag-spell { color:#7ab8f0; }
  .tag-addon { color:var(--warn); }
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
function box(title, body) {
  const b = el('div', 'box');
  b.appendChild(el('h3', null, title));
  if (body) b.appendChild(body);
  return b;
}
// Card art thumbnail (img_cache/ via /img/<id>.png, fetched by fetch_art.py).
// Hides itself gracefully when no art is cached (current-set BG-only cards).
function thumb(cid, name) {
  const img = document.createElement('img');
  img.className = 'thumb';
  img.src = '/img/' + cid + '.png';
  img.alt = '';
  img.onerror = () => {
    // No art available (render build lags the patch; trinkets have none
    // upstream): a same-size placeholder keeps every row aligned.
    const ph = document.createElement('span');
    ph.className = 'thumb ph';
    ph.textContent = (name || '?').trim().charAt(0).toUpperCase();
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
  const nm = el('div', 'tname', name);
  if (opts.n > 1) nm.appendChild(el('span', 'xcount', '  ×' + opts.n));
  t.appendChild(nm);
  if (sub) t.appendChild(el('div', 'tsub', sub));
  return t;
}
function render(a) {
  const app = document.getElementById('app');
  const statebar = document.getElementById('statebar');
  app.innerHTML = '';
  statebar.innerHTML = '';
  if (!a || !a.board) { statebar.textContent = 'No game yet.'; return; }

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
  if (a.choice && a.choice.ranked && a.choice.ranked.length) {
    const [name, cid, score, why] = a.choice.ranked[0];
    const line = el('div', 'pickline', 'PICK ' + name + (why ? ' — ' + why : ''));
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
  // Level/roll reference: the button's real price (not tier+1).
  if (a.tier && a.tier < 6) {
    const cost = (a.level_cost != null) ? a.level_cost : a.tier + 1;
    instr.appendChild(el('div', 'footline',
      a.gold !== null && a.gold >= cost
        ? 'Level available: tier ' + a.tier + ' → ' + (a.tier + 1)
          + ' for ' + cost + 'g'
        : 'Level costs ' + cost + 'g — '
          + Math.max(0, cost - (a.gold ?? 0)) + ' short'));
  }
  app.appendChild(instr);

  // The plan's actual buy (highlighted in the shop tiles below too).
  const stepCard = a.buy_step_card || null;

  // SELL — one horizontal line: safe to sell | divider | do not sell.
  // The split is the value function's own filler threshold (score < 15 is
  // what top_move calls "a clear filler").
  const sellSafe = el('div', 'tiles');
  const sellKeep = el('div', 'tiles');
  (a.sell_rank || []).forEach(s => {
    const t = tile(s.card, s.name, s.score.toFixed(0),
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
        list.appendChild(tile(c.card, c.name, c.owned ? 'have' : null,
                              {cls: 'comprow ' + (c.owned ? 'owned' : 'missing')}));
      });
    });
    body.appendChild(list);
    app.appendChild(box('Looking for (' + (pivot ? 'pivot' : 'comp') + ')', body));
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

  // Playable comps — reference chips.
  const compsBody = el('div');
  if (a.comps && a.comps.length) {
    const chips = el('div', 'chips');
    a.comps.forEach(c => chips.appendChild(el('span', 'chip', c)));
    compsBody.appendChild(chips);
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
    a["sell_rank"] = sell
    # Tag shop entries by comp membership (core/addon) or kind (spell), so the
    # shop list shows why each card matters without opening the comp DB.
    # Each row also carries its tavern price (minion = tier, spell = cost) —
    # the price model is otherwise invisible, and a wrong one ("thinks
    # minions cost 1 gold") becomes instantly diagnosable.
    tc = analysis.get("target_cards") or {}
    core = {c["card"] for c in tc.get("core", [])}
    addons = {c["card"] for c in tc.get("addons", [])}
    spell_db = _load_spell_db()
    spells = set(spell_db)
    prices = {c: (v or {}).get("tier") for c, v in _load_card_db().items()}
    prices.update({c: (v or {}).get("cost") for c, v in spell_db.items()})
    a["shop_rank"] = [dict(card=c, name=names.get(c, c), score=round(v),
                           price=prices.get(c),
                           tag=("core" if c in core else
                                "addon" if c in addons else
                                "spell" if c in spells else None))
                      for c, v in analysis.get("shop_rank", [])]
    a["target_cards"] = analysis.get("target_cards")
    # Playable comps: the analysis carries a slug->comp dict, the UI wants a
    # name list (meta-tier order). (The box read a["comps"], which the
    # analysis never provided — it sat on "—" forever.)
    pc = analysis.get("playable_comps") or {}
    comps = list(pc.values()) if isinstance(pc, dict) else list(pc or [])
    comps = [c for c in comps if isinstance(c, dict) and c.get("name")]
    tier_rank = {"S": 0, "A": 1, "B": 2}
    comps.sort(key=lambda c: (tier_rank.get(c.get("meta_tier"), 3),
                              c.get("name") or ""))
    a["comps"] = [c["name"] for c in comps]
    # The Buy box mirrors the top move's actual buy/roll step (buy_step_card /
    # buy_step_roll are written by value.top_move), so the two can't disagree.
    a["buy_step_card"] = analysis.get("buy_step_card")
    a["buy_roll_text"] = analysis.get("buy_step_roll")
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
    # When leveling leads the top move, the buy is what you do with the
    # leftover — label it that way so the priorities read in order.
    a["buy_label"] = ("Then buy (after leveling)"
                      if (analysis.get("top_move") or "").startswith("1. LEVEL")
                      else "Buy this")
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
