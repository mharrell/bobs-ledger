#!/usr/bin/env python3
"""Measure the Settle Up step-through's geometry in a real browser.

WHY THIS EXISTS. The step view's sizes are CSS variables multiplied by vw/vh
clamps, so "how tall is a board card" cannot be read off the stylesheet — it has
to be laid out. `tests/browser.py` already drives headless Chromium for the
suites; this reuses it at the viewports the layout plan names (1728x1000,
1512x860, 1440x780) and prints what it found.

  python3 analysis/measure_step_view.py                 # all three viewports
  python3 analysis/measure_step_view.py 1728 1000       # one of them
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "app"))
sys.path.insert(0, os.path.join(HERE, "app", "tests"))

import live_coach  # noqa: F401,E402  (preload: coach_ui <-> live_coach is circular)
import coach_ui     # noqa: E402
import browser      # noqa: E402

VIEWPORTS = ((1728, 1000), (1512, 860), (1440, 780))


def styles():
    html = coach_ui._HTML
    start = html.index("<style>") + len("<style>")
    return html[start:html.index("</style>", start)]


def doc(tiles=7):
    """The step view's real markup, laid out without the server.

    Art is not fetched (a headless file:// page has no /img), but the thumbnail's
    height comes from `aspect-ratio`, so the geometry is the app's.
    """
    cards = "".join(
        f'<div class="tile"><img class="thumb" alt="">'
        f'<div class="tname">Card {i}</div>'
        f'<div class="tsub"><span class="stat-atk">13</span>'
        f'<span class="stat-sep">/</span><span class="stat-hp">15</span></div></div>'
        for i in range(tiles))
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{styles()}</style></head><body>
<div class="tavern"><div class="tstep stepview">
  <div class="stepnav"><button class="snav">◀</button>
    <button class="snav splay">▶</button><button class="snav">▶</button></div>
  <div class="steptrack"></div>
  <div class="slegend">R roll · B buy</div>
  <div class="stepcap">Your board after step 1 of 4 — Buy a card</div>
  <div class="stepboard">{cards}</div>
</div></div>
<div id="out"></div>
<script>
const r = el => document.querySelector(el);
const box = el => {{ const b = el.getBoundingClientRect();
  return [Math.round(b.width), Math.round(b.height)]; }};
const cs = getComputedStyle(r('.stepboard'));
const tile = r('.stepboard .tile');
const thumb = r('.stepboard .thumb');
const parts = {{}};
// `#out` is parsed as space-separated key=value, so a value may not contain a
// space or the pairs after it stop being parseable (that is how `vh` went
// missing on the first run of this script).
const clean = v => v.trim().replace(/\s+/g, '_');
parts.tstepw = clean(cs.getPropertyValue('--tstepw'));
parts.tcardw = clean(cs.getPropertyValue('--tcardw'));
parts.over = Math.round(document.documentElement.scrollHeight - window.innerHeight);
parts.tile = box(tile).join('x');
parts.thumb = box(thumb).join('x');
parts.card = Math.round(tile.getBoundingClientRect().height);
parts.thumbH = Math.round(thumb.getBoundingClientRect().height);
parts.thumbW = Math.round(thumb.getBoundingClientRect().width);
// A custom property comes back as the TOKEN STREAM, not a used value, so it has
// to be applied to a real property before it can be measured.
const sv = getComputedStyle(r('.stepview'));
parts.r = sv.getPropertyValue('--r').trim();
const probe = document.createElement('div');
probe.style.cssText = 'position:absolute;visibility:hidden;';
r('.stepview').appendChild(probe);
probe.style.height = 'var(--b)';
parts.b = Math.round(probe.getBoundingClientRect().height);
probe.style.height = 'var(--s)';
parts.s = Math.round(probe.getBoundingClientRect().height);
parts.vh = window.innerHeight;
parts.vw = window.innerWidth;
document.getElementById('out').textContent = JSON.stringify(parts);
</script></body></html>"""


def read(doc_html, size):
    """The measurements the page printed, parsed as the JSON object it wrote."""
    import html as _html
    import re
    raw = browser.run(doc_html, size=size)
    m = re.search(r'id="out"[^>]*>([^<]*)<', raw)
    if not m:
        raise AssertionError("the page printed no #out")
    text = _html.unescape(m.group(1)).strip()
    return json.loads(text)


def measure(w, h):
    """Measure at a VIEWPORT of w x h.

    `--window-size` is the window, and headless Chromium spends ~143px of the
    height on chrome: asking for 1000 got a 857px viewport, which silently
    flips the `max-height: 880px` query and changes every number. So the first
    run measures the shortfall and the second asks for the extra.
    """
    got = read(doc(), (w, h))
    vh = got.get("vh")
    if vh is not None and 0 < h - vh < 400:
        got = read(doc(), (w, h + (h - vh)))
        got["viewport"] = f"{w}x{h}"
    return got


#: A synthetic saved game, so a screenshot shows the product and not a real one.
#: Card ids are the fixture's own (matching tests/test_settle_browser.py's style):
#: fake "Buy N" cards, never a real player's game.
def synthetic_rep():
    def m(cid, name, atk, hp, eid):
        return {"card": cid, "name": name, "atk": atk, "health": hp,
                "golden": False, "eid": eid}
    opened = [m("BG31_815", "Dune Dweller", 3, 3, 9),
              m("BG31_820", "Kooky Chemist", 2, 2, 11)]
    ended = [m("BG31_815", "Dune Dweller", 5, 5, 9),
             m("BG31_820", "Kooky Chemist", 2, 2, 11),
             m("BG31_831", "Annoy-o-Module", 4, 8, 14)]
    turn = {"turn": 1, "gold": 4, "winner": "us", "eff": 30,
            "buy_start": opened, "buy_end": ended,
            "battle_end": ended, "buy_end_text": "Dune Dweller 5/5",
            "stats": {"buy_end": 40, "growth": 5, "growth_atk": 3,
                      "growth_hp": 2},
            "spend": {"total": 14, "rolls": 3},
            "shop_events": {"played": 2, "tier_up": False, "hero_power": False,
                            "trinkets": []},
            "took": {"bought": [{"card": "BG31_815", "name": "Dune Dweller"}],
                     "sold": [], "plays": [], "spell_ids": []},
            "combat_start": {"ours": opened, "theirs": []},
            "steps": [{"k": "buy", "card": "BG31_815", "cardName": "Dune Dweller",
                       "board": opened, "hand": [{"card": "BG31_820",
                                                  "name": "Kooky Chemist",
                                                  "atk": 2, "health": 2}],
                       "tavern": ["BG31_815", "BG31_820", "BG31_831"]}],
            "notes": []}
    return {"schema": 1, "created": "2026-10-17T12:00:00",
            "session": "synthetic", "log": "Power.log", "game": 1,
            "hero": "Synthetic Hero", "placement": 1,
            "phases": [{"turn": 1, "kind": "taken", "plan": "1. Buy a card"}],
            "totals": {"phases": 1, "taken": 1, "ignored": 0},
            "caveat": "synthetic fixture, not a game",
            "timeline": {"turns": [turn]}, "timeline_error": None}


def serve(port):
    """Start the app's OWN server on a spare port, over a temp store holding the
    synthetic game. Returns a shutdown callable."""
    import tempfile
    import threading
    import time
    import replay_store
    tmp = tempfile.TemporaryDirectory()
    replay_store.store_dir = (lambda root=None: tmp.name)
    replay_store.save(synthetic_rep(), rid="2026-10-17_120000-Synthetic-Hero-1")
    # The page is JS-driven and a headless run cannot click, so the tab switch
    # (and, for the review, picking the game) is injected into the markup this
    # server hands out. `--virtual-time-budget` then fast-forwards the timers and
    # the settle-list fetch before the screenshot is taken.
    original = coach_ui._page_html
    driver = ("<script>setTimeout(function(){try{showTab('settle');"
              "}catch(e){}},120);</script></body>")
    coach_ui._page_html = lambda: original().replace("</body>", driver)
    srv = coach_ui.start_server(port=port)
    for _ in range(100):
        try:
            import urllib.request
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1).read()
            break
        except Exception:
            time.sleep(0.1)

    def stop():
        srv.shutdown()
        tmp.cleanup()
    return stop


def short_shot(url, path, w, h):
    """One screenshot at a VIEWPORT of w x h (the window carries ~143px of chrome)."""
    exe = browser.browser()
    if exe is None:
        raise browser.BrowserUnavailable("no Chromium browser on this machine")
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-sandbox",
                        "--hide-scrollbars", f"--window-size={w},{h + 143}",
                        f"--user-data-dir={os.path.join(tmp, 'p')}",
                        "--virtual-time-budget=4000",
                        f"--screenshot={path}", url],
                       capture_output=True, timeout=180)
    return os.path.exists(path)


def main():
    if "--shot" in sys.argv:
        import time
        i = sys.argv.index("--shot")
        out_dir = sys.argv[i + 1]
        os.makedirs(out_dir, exist_ok=True)
        port = 8799
        stop = serve(port)
        try:
            time.sleep(1.5)
            url = f"http://127.0.0.1:{port}/?token={coach_ui.server_token()}"
            for w, h in VIEWPORTS:
                path = os.path.join(out_dir, f"summary-{w}x{h}.png")
                ok = short_shot(url, path, w, h)
                print(("ok   " if ok else "FAIL ") + path)
        finally:
            stop()
        return
    want = [tuple(int(x) for x in sys.argv[1:3])] if len(sys.argv) > 2 else VIEWPORTS
    for size in want:
        try:
            got = measure(*size)
        except browser.BrowserUnavailable as e:
            print(f"{size[0]}x{size[1]}: NO BROWSER — {e}")
            continue
        print(json.dumps({"viewport": f"{size[0]}x{size[1]}", **got}, indent=None))


if __name__ == "__main__":
    main()
