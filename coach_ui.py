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
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from value import _load_bg_names

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
         font:13px/1.45 "Segoe UI", system-ui, sans-serif; padding:8px; }
  #app { max-width:340px; display:flex; flex-direction:column; gap:8px; }
  .box { background:var(--panel); border:1px solid #2c2f36; border-radius:6px; padding:8px 10px; }
  .box h3 { margin:0 0 6px; font-size:11px; letter-spacing:.06em; text-transform:uppercase;
            color:var(--dim); }
  .row { display:flex; justify-content:space-between; gap:8px; padding:2px 0; }
  .row .l { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .gold { color:#ffd97a; }
  .golden::after { content:" ◆"; color:#ffd97a; }
  .safest { color:var(--good); } .valuable { color:var(--bad); }
  .chips { display:flex; flex-wrap:wrap; gap:4px; }
  .chip { background:var(--panel2); border-radius:10px; padding:1px 8px; font-size:12px; }
  .level { font-weight:600; }
  .none { color:var(--dim); font-style:italic; }
  #wait { color:var(--dim); }
  .score { color:var(--dim); }
</style>
</head>
<body>
<div id="app"><div id="wait">Waiting for live.py analysis…</div></div>
<script>
async function poll() {
  try {
    const r = await fetch('/analysis');
    const a = await r.json();
    render(a);
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
    const r = el('div', 'row');
    r.appendChild(el('span', 'l' + (m.golden ? ' golden' : ''), (m.name || m.card) + ' ' + m.atk + '/' + m.health));
    r.appendChild(el('span', null, m.tribe || ''));
    boardBody.appendChild(r);
  });
  app.appendChild(box('Board', boardBody));

  // Sell ranking (safest to sell -> most valuable)
  const sellBody = el('div');
  if (a.sell_rank && a.sell_rank.length) {
    a.sell_rank.forEach((s, i) => sellBody.appendChild(rankRow(s.name, s.score, i < 2)));
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
    a["comps"] = sorted(analysis.get("playable_comps", {}).keys())
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
