#!/usr/bin/env python3
"""V1 coaching UI: a local overlay served over HTTP.

Runs a tiny stdlib HTTP server (no dependencies). `live.py` pushes the latest
situation analysis here each buy phase; the server exposes it as JSON at
`/analysis` and serves a static HTML/CSS/JS page at `/` that polls it and renders
the V1 widgets (board, sell ranking, comps, banned tribes, trigger counts,
gold/tier). Design: analysis/DESIGN_COACHING_UI.md.

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

_HTML = """<!doctype html>
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
  #app { display:grid; grid-template-columns:1fr 1fr 1fr; gap:8px;
         align-items:start; }
  @media (max-width:1250px) { #app { grid-template-columns:1fr 1fr; } }
  @media (max-width:840px)  { #app { grid-template-columns:1fr; } }
  .col { display:flex; flex-direction:column; gap:8px; min-width:0; }
  .box { background:var(--panel); border:1px solid #2c2f36; border-radius:6px;
         padding:7px 9px; }
  .box h3 { margin:0 0 4px; font-size:11px; letter-spacing:.06em;
            text-transform:uppercase; color:var(--dim); }
  /* Rows: thumb, then the name snug against it (flex:1 — the old
     space-between floated the middle child to the panel's center), score
     pinned right. */
  .row { display:flex; align-items:center; gap:7px; padding:1px 0; }
  .row .l { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis;
            white-space:nowrap; }
  .row .r { flex:none; }
  .gold { color:#ffd97a; }
  .golden::after { content:" ◆"; color:#ffd97a; }
  .safest { color:var(--good); } .valuable { color:var(--bad); }
  .thumb { width:44px; height:44px; border-radius:5px; object-fit:cover; flex:none;
           cursor:zoom-in; transition:transform .12s ease-out; }
  /* No art cached for this card: a same-size placeholder keeps every row
     aligned (missing art used to collapse the row and shift names). */
  .thumb.ph { display:inline-flex; align-items:center; justify-content:center;
              color:var(--dim); background:var(--panel2);
              border:1px solid #2c2f36; font-size:18px; cursor:default; }
  /* Hover zoom: art is 256x256, so scale(5) on a 44px thumb shows it near
     full size; origin left keeps the popup on-panel (thumbs sit at the
     row's left edge), z-index floats it above the other boxes. Scoped to
     real images — a placeholder has nothing to zoom. */
  img.thumb:hover { transform:scale(5); transform-origin:left center;
                    position:relative; z-index:5; }
  .thumb.golden { box-shadow:0 0 0 2px #ffd97a; }
  .thumbrow { display:flex; align-items:center; gap:7px; }
  /* The Buy box mirrors the top move's actual buy; its card is highlighted
     in the ranked shop list too. */
  .buynow .l { color:var(--gold); font-weight:700; }
  img.thumb.buynowart { box-shadow:0 0 0 2px var(--gold); }
  /* Target-comp shopping list: what you're hunting is fully opaque; pieces
     already on the board fade back. Rows stack under the group label. */
  .comprow { opacity:.45; }
  .comprow.missing { opacity:1; }
  .compgroup { display:flex; align-items:flex-start; gap:6px; margin-top:5px; }
  .compgroup .grouplabel { color:var(--dim); font-size:12px; width:44px; flex:none;
                           padding-top:16px; }
  .complist { display:flex; flex-direction:column; gap:1px; flex:1; min-width:0; }
  .chips { display:flex; flex-wrap:wrap; gap:4px; }
  .chip { background:var(--panel2); border-radius:10px; padding:1px 8px;
          font-size:13px; }
  .level { font-weight:600; }
  /* Top move: each numbered priority step on its own line */
  .step { font-size:16px; font-weight:700; line-height:1.4; padding:1px 0; }
  .stepnum { color:var(--gold); margin-right:7px; }
  .topmove { font-size:16px; font-weight:700; color:var(--text); line-height:1.4; }
  .topmove .act { color:var(--gold); }
  .target { font-size:14px; font-weight:600; color:var(--gold); }
  .target .pivot { color:var(--warn); }
  .chip.owned { border:1px solid var(--good); color:var(--good); }
  .chip.missing { border:1px dashed var(--dim); color:var(--dim); }
  .buythis { display:flex; align-items:center; gap:9px; font-size:16px;
             font-weight:700; color:var(--gold); }
  .buythis small { color:var(--dim); font-weight:400; }
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
function thumbRow(cid, name) {
  const r = el('div', 'row thumbrow');
  r.appendChild(thumb(cid, name));
  r.appendChild(el('span', 'l', name));
  return r;
}
function rankRow(name, score, isTop) {
  const r = el('div', 'row');
  r.appendChild(el('span', 'l ' + (isTop ? 'safest' : 'valuable'), name));
  r.appendChild(el('span', 'score', score.toFixed(0)));
  return r;
}
function render(a) {
  const app = document.getElementById('app');
  const statebar = document.getElementById('statebar');
  app.innerHTML = '';
  statebar.innerHTML = '';
  if (!a || !a.board) { statebar.textContent = 'No game yet.'; return; }

  // Three columns: DECIDE (what to do), BUILD (what you're making), MARKET
  // (what's on offer). State + banned tribes live in the strip above.
  const decide = el('div', 'col');
  const build = el('div', 'col');
  const market = el('div', 'col');

  // STATE STRIP — hero / gold / tier / turn / banned tribes
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
  if (a.banned && a.banned.length) {
    statebar.appendChild(el('span', 'lbl', 'Banned:'));
    a.banned.forEach(t => statebar.appendChild(el('span', 'banned', t)));
  }

  // DECIDE — the pending pick (hero / trinket / discover), top of the column
  if (a.choice && a.choice.ranked && a.choice.ranked.length) {
    const pickBody = el('div', 'pickbody');
    const [name, cid, score, why] = a.choice.ranked[0];
    const head = el('div', 'thumbrow');
    head.appendChild(thumb(cid, name));
    head.appendChild(el('div', 'topmove', 'PICK ' + name));
    pickBody.appendChild(head);
    if (why) pickBody.appendChild(el('div', 'none', why));
    if (a.choice.kind === 'hero' && a.choice.ranked.length > 1) {
      pickBody.appendChild(el('div', 'none', 'if locked, pick ' + a.choice.ranked[1][0]));
    }
    const rest = el('div', null);
    a.choice.ranked.forEach(([n, c, s, w]) => {
      rest.appendChild(thumbRow(c, n + (s != null ? '  (' + (w || s.toFixed(1)) + ')' : '')));
    });
    pickBody.appendChild(rest);
    decide.appendChild(box('Choose 1 (' + a.choice.kind + ')', pickBody));
  }

  // DECIDE — top move: each numbered priority step on its own line
  if (a.top_move) {
    const body = el('div', 'steps');
    a.top_move.split(' · ').forEach(step => {
      const m = step.match(/^(\d+)\. (.*)$/);
      const line = el('div', 'step');
      if (m) {
        line.appendChild(el('span', 'stepnum', m[1]));
        line.appendChild(el('span', null, m[2]));
      } else {
        line.textContent = step;
      }
      body.appendChild(line);
    });
    decide.appendChild(box('Top move', body));
  }

  // DECIDE — the Buy box mirrors the top move's actual buy. When the plan
  // says roll, the Top move already says exactly that — a Buy box repeating
  // it was dead real estate.
  const stepCard = (a.shop_rank && a.shop_rank.length)
    ? (a.buy_step_card || (a.buy_roll_text ? null : a.shop_rank[0].card))
    : null;
  if (stepCard) {
    const s = a.shop_rank.find(x => x.card === stepCard);
    const stepName = s ? s.name : stepCard;
    const buyBox = el('div', 'buythis');
    buyBox.appendChild(thumb(stepCard, stepName));
    buyBox.appendChild(el('span', null, stepName + '  '));
    if (s) buyBox.appendChild(el('small', null,
      'score ' + s.score + (s.price != null ? ' · ' + s.price + 'g' : '')));
    decide.appendChild(box(a.buy_label || 'Buy this', buyBox));
  }

  // DECIDE — refresh-vs-level call (the button's real price, not tier+1)
  if (a.tier && a.tier < 6) {
    const cost = (a.level_cost != null) ? a.level_cost : a.tier + 1;
    decide.appendChild(box('Level / Roll', el('div', 'level',
      a.gold !== null && a.gold >= cost
        ? 'Can afford to level (tier ' + a.tier + ' → ' + (a.tier + 1) + ', ' + cost + 'g)'
        : 'Level costs ' + cost + 'g — ' + Math.max(0, cost - (a.gold ?? 0)) + ' short; stabilize / roll')));
  }

  // MARKET — the full ranked tavern (the plan's buy is highlighted)
  if (a.shop_rank && a.shop_rank.length) {
    const shopBody = el('div');
    a.shop_rank.forEach(s => {
      const r = el('div', 'row thumbrow');
      if (s.card === stepCard) r.classList.add('buynow');
      const t = thumb(s.card, s.name);
      if (s.card === stepCard) t.classList.add('buynowart');
      r.appendChild(t);
      const tagCls = s.tag ? ' tag-' + s.tag : '';
      r.appendChild(el('span', 'l' + tagCls,
        s.name + (s.tag ? '  [' + s.tag + ']' : '')));
      const sc = el('span', 'score',
        (s.price != null ? s.price + 'g · ' : '') + s.score.toFixed(0));
      r.appendChild(sc);
      shopBody.appendChild(r);
    });
    market.appendChild(box('Tavern shop (minions + spells)', shopBody));
  } else {
    market.appendChild(box('Tavern', el('div', 'none', 'offer not parsed yet')));
  }

  // MARKET — sell ranking (safest to sell -> most valuable); duplicates
  // grouped with a ×N badge (score = the instance you'd sell first)
  const sellBody = el('div');
  if (a.sell_rank && a.sell_rank.length) {
    a.sell_rank.forEach((s, i) => {
      const r = el('div', 'row thumbrow');
      r.appendChild(thumb(s.card, s.name));
      const lbl = el('span', 'l ' + (i < 2 ? 'safest' : 'valuable'), s.name);
      if (s.n > 1) {
        lbl.appendChild(el('span', 'xcount', '  ×' + s.n));
      }
      r.appendChild(lbl);
      r.appendChild(el('span', 'score', s.score.toFixed(0)));
      sellBody.appendChild(r);
    });
  } else {
    sellBody.appendChild(el('div', 'none', '—'));
  }
  market.appendChild(box('Sell ranking (safe → keep)', sellBody));

  // MARKET — playable comps
  const compsBody = el('div');
  if (a.comps && a.comps.length) {
    const chips = el('div', 'chips');
    a.comps.forEach(c => chips.appendChild(el('span', 'chip', c)));
    compsBody.appendChild(chips);
  } else {
    compsBody.appendChild(el('div', 'none', '—'));
  }
  market.appendChild(box('Playable comps', compsBody));

  // BUILD — target comp: what you're hunting is fully opaque; pieces already
  // on the board fade back.
  if (a.target_comp) {
    const pivot = a.target_state === 'pivot';
    const body = el('div', 'target',
      (pivot ? 'pivot to ' : 'committing to ') + a.target_comp);
    const tc = a.target_cards || {};
    [['core', 'core'], ['addons', 'addons']].forEach(([label, key]) => {
      const cards = tc[key] || [];
      if (!cards.length) return;
      const g = el('div', 'compgroup');
      g.appendChild(el('span', 'grouplabel', label));
      const list = el('div', 'complist');
      cards.forEach(c => {
        const r = thumbRow(c.card, c.name + (c.owned ? '  [have]' : ''));
        r.classList.add('comprow', c.owned ? 'owned' : 'missing');
        list.appendChild(r);
      });
      g.appendChild(list);
      body.appendChild(g);
    });
    build.appendChild(box('Target comp', body));
  }

  // BUILD — board (golden thumbs get a gold ring)
  const boardBody = el('div');
  (a.board || []).forEach(m => {
    const r = thumbRow(m.card, (m.name || m.card) + ' ' + m.atk + '/' + m.health);
    if (m.golden) {
      r.querySelector('.l').classList.add('golden');
      const img = r.querySelector('img');
      if (img) img.classList.add('golden');
    }
    r.appendChild(el('span', null, m.tribe || ''));
    boardBody.appendChild(r);
  });
  build.appendChild(box('Board', boardBody));

  // BUILD — real per-turn triggers ("turns" is game state, in the strip)
  const triggers = (a.scenario || {});
  const active = Object.entries(triggers)
    .filter(([k, v]) => v && !k.endsWith('_total') && k !== 'turns');
  if (active.length) {
    const chips = el('div', 'chips');
    active.forEach(([k, v]) => chips.appendChild(el('span', 'chip', k.replace('play_','') + ' ' + v)));
    build.appendChild(box('Per-turn triggers', chips));
  }

  app.appendChild(decide);
  app.appendChild(build);
  app.appendChild(market);
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
            g = {"card": c, "name": names.get(c, c), "score": round(v), "n": 1}
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
