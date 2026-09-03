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
from http.server import BaseHTTPRequestHandler, HTTPServer

from value import _load_bg_names, _load_spell_db

_HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_PORT = 8747

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
         font:15px/1.5 "Segoe UI", system-ui, sans-serif; padding:8px; }
  #app { max-width:520px; display:flex; flex-direction:column; gap:8px; }
  .box { background:var(--panel); border:1px solid #2c2f36; border-radius:6px; padding:9px 11px; }
  .box h3 { margin:0 0 6px; font-size:12px; letter-spacing:.06em; text-transform:uppercase;
            color:var(--dim); }
  .row { display:flex; justify-content:space-between; gap:8px; padding:2px 0; }
  .row .l { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .row .r { flex:none; }
  .gold { color:#ffd97a; }
  .golden::after { content:" ◆"; color:#ffd97a; }
  .safest { color:var(--good); } .valuable { color:var(--bad); }
  .thumb { width:64px; height:64px; border-radius:6px; object-fit:cover; flex:none;
           cursor:zoom-in; transition:transform .12s ease-out; }
  /* Hover zoom: cached renders are 256x256, so scale(4) shows them at full
     size; origin left keeps the popup on-panel (thumbs sit at the row's
     left edge), z-index floats it above the other boxes. */
  .thumb:hover { transform:scale(4); transform-origin:left center;
                 position:relative; z-index:5; }
  .thumbrow { display:flex; align-items:center; gap:8px; }
  .chips { display:flex; flex-wrap:wrap; gap:4px; }
  .chip { background:var(--panel2); border-radius:10px; padding:2px 9px; font-size:14px; }
  .level { font-weight:600; }
  /* Top move: each numbered priority step on its own line */
  .step { font-size:17px; font-weight:700; line-height:1.45; padding:1px 0; }
  .stepnum { color:var(--gold); margin-right:7px; }
  .topmove { font-size:17px; font-weight:700; color:var(--text); line-height:1.4; }
  .topmove .act { color:var(--gold); }
  .target { font-size:15px; font-weight:600; color:var(--gold); }
  .target .pivot { color:var(--warn); }
  .compgroup { display:flex; align-items:baseline; gap:6px; margin-top:5px; }
  .compgroup .grouplabel { color:var(--dim); font-size:13px; width:48px; flex:none; }
  .compgroup .chips { flex:1; }
  .chip.owned { border:1px solid var(--good); color:var(--good); }
  .chip.missing { border:1px dashed var(--dim); color:var(--dim); }
  .buythis { font-size:17px; font-weight:700; color:var(--gold); }
  .buythis small { color:var(--dim); font-weight:400; }
  .none { color:var(--dim); font-style:italic; }
  #wait { color:var(--dim); }
  .score { color:var(--dim); flex:none; }
</style>
</head>
<body>
<div id="app"><div id="wait">Waiting for live.py analysis…</div></div>
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
function thumb(cid) {
  const img = document.createElement('img');
  img.className = 'thumb';
  img.src = '/img/' + cid + '.png';
  img.alt = '';
  img.onerror = () => { img.remove(); };
  return img;
}
function thumbRow(cid, name) {
  const r = el('div', 'row thumbrow');
  r.appendChild(thumb(cid));
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
  app.innerHTML = '';
  if (!a || !a.board) { app.appendChild(el('div', null, 'No game yet.')); return; }

  // Pending pick (hero / trinket / discover) — a forced decision, top box
  if (a.choice && a.choice.ranked && a.choice.ranked.length) {
    const pickBody = el('div', 'pickbody');
    const [name, cid, score, why] = a.choice.ranked[0];
    const head = el('div', 'thumbrow');
    head.appendChild(thumb(cid));
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
    app.appendChild(box('Choose 1 (' + a.choice.kind + ')', pickBody));
  }

  // Top move — each numbered priority step on its own line
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
    app.appendChild(box('Top move', body));
  }

  // Target comp — what to build toward, with its shopping list
  if (a.target_comp) {
    const pivot = a.target_state === 'pivot';
    const body = el('div', 'target',
      (pivot ? 'pivot to ' : 'committing to ') + a.target_comp);
    const tc = a.target_cards || {};
    [['core  ', 'core'], ['addons', 'addons']].forEach(([label, key]) => {
      const cards = tc[key] || [];
      if (!cards.length) return;
      const g = el('div', 'compgroup');
      g.appendChild(el('span', 'grouplabel', label));
      const chips = el('div', 'chips');
      cards.forEach(c => chips.appendChild(
        el('span', 'chip ' + (c.owned ? 'owned' : 'missing'), c.name)));
      g.appendChild(chips);
      body.appendChild(g);
    });
    app.appendChild(box('Target comp', body));
  }

  // Header / state strip
  const header = box('State', (() => {
    const c = el('div'); c.style.display='flex'; c.style.gap='10px'; c.style.flexWrap='wrap';
    c.appendChild(el('span', null, 'Hero: ' + (a.hero || '?')));
    c.appendChild(el('span', 'gold', 'Gold: ' + (a.gold ?? '?')));
    c.appendChild(el('span', null, 'Tier: ' + (a.tier ?? '?')));
    return c;
  })());
  app.appendChild(header);

  // Refresh-vs-level call
  if (a.tier && a.tier < 6) {
    const cost = a.tier + 1;
    const lvl = box('Level / Roll', el('div', 'level',
      a.gold !== null && a.gold >= cost
        ? 'Can afford to level (tier ' + a.tier + ' → ' + (a.tier + 1) + ', ~' + cost + 'g)'
        : 'Low gold — stabilize / roll for your comp'));
    app.appendChild(lvl);
  }

  // Real per-turn triggers
  const triggers = (a.scenario || {});
  const active = Object.entries(triggers).filter(([k, v]) => v && !k.endsWith('_total'));
  if (active.length) {
    const chips = el('div', 'chips');
    active.forEach(([k, v]) => chips.appendChild(el('span', 'chip', k.replace('play_','') + ' ' + v)));
    app.appendChild(box('Per-turn triggers', chips));
  }

  // Board
  const boardBody = el('div');
  (a.board || []).forEach(m => {
    const r = thumbRow(m.card, (m.name || m.card) + ' ' + m.atk + '/' + m.health);
    if (m.golden) r.querySelector('.l').classList.add('golden');
    r.appendChild(el('span', null, m.tribe || ''));
    boardBody.appendChild(r);
  });
  app.appendChild(box('Board', boardBody));

  // Tavern — the shop's best card (minion or spell), labeled by priority
  if (a.shop_rank && a.shop_rank.length) {
    const top = a.shop_rank[0];
    const buyBox = el('div', 'buythis');
    buyBox.appendChild(thumb(top.card));
    const lbl = el('span', null, top.name + ' <small>score ' + top.score + '</small>');
    buyBox.appendChild(lbl);
    app.appendChild(box(a.buy_label || 'Buy this', buyBox));
    if (a.shop_rank.length > 1) {
      const shopBody = el('div');
      a.shop_rank.slice(1).forEach(s => {
        const r = el('div', 'row thumbrow');
        r.appendChild(thumb(s.card));
        r.appendChild(el('span', 'l', s.name + (s.tag ? ' [' + s.tag + ']' : '')));
        r.appendChild(el('span', 'score', s.score.toFixed(0)));
        shopBody.appendChild(r);
      });
      app.appendChild(box('Tavern shop (minions + spells)', shopBody));
    }
  } else {
    app.appendChild(box('Tavern', el('div', 'none', 'offer not parsed yet')));
  }

  // Sell ranking (safest to sell -> most valuable)
  const sellBody = el('div');
  if (a.sell_rank && a.sell_rank.length) {
    a.sell_rank.forEach((s, i) => {
      const r = el('div', 'row thumbrow');
      r.appendChild(thumb(s.card));
      r.appendChild(el('span', 'l ' + (i < 2 ? 'safest' : 'valuable'), s.name));
      r.appendChild(el('span', 'score', s.score.toFixed(0)));
      sellBody.appendChild(r);
    });
  } else {
    sellBody.appendChild(el('div', 'none', '—'));
  }
  app.appendChild(box('Sell ranking (safe → keep)', sellBody));

  // Playable comps
  const compsBody = el('div');
  if (a.comps && a.comps.length) {
    const chips = el('div', 'chips');
    a.comps.forEach(c => chips.appendChild(el('span', 'chip', c)));
    compsBody.appendChild(chips);
  } else {
    compsBody.appendChild(el('div', 'none', '—'));
  }
  app.appendChild(box('Playable comps', compsBody));

  // Banned tribes
  const bannedBody = el('div');
  if (a.banned && a.banned.length) {
    const chips = el('div', 'chips');
    a.banned.forEach(t => chips.appendChild(el('span', 'chip', t)));
    bannedBody.appendChild(chips);
  } else {
    bannedBody.appendChild(el('div', 'none', 'none'));
  }
  app.appendChild(box('Banned tribes', bannedBody));
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
    a["sell_rank"] = [{"card": c, "name": names.get(c, c), "score": round(v)}
                      for c, v in analysis["sell_rank"]]
    # Tag shop entries by comp membership (core/addon) or kind (spell), so the
    # shop list shows why each card matters without opening the comp DB.
    tc = analysis.get("target_cards") or {}
    core = {c["card"] for c in tc.get("core", [])}
    addons = {c["card"] for c in tc.get("addons", [])}
    spells = set(_load_spell_db())
    a["shop_rank"] = [dict(card=c, name=names.get(c, c), score=round(v),
                           tag=("core" if c in core else
                                "addon" if c in addons else
                                "spell" if c in spells else None))
                      for c, v in analysis.get("shop_rank", [])]
    a["target_cards"] = analysis.get("target_cards")
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
                path = os.path.join(_HERE, "img_cache", f"{m.group(1)}.png")
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
    """Start the overlay server in a background thread; returns the server."""
    server = HTTPServer(("127.0.0.1", port), _Handler)
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
