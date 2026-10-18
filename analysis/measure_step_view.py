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


def main():
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
