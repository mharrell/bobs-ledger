"""The Settle Up turn card keeps ONE size when the player switches views.

Reported by the maintainer 2026-10-07: *"when you switch between the phase views,
the card changes size and makes it hard to track where you're at now."* It did,
and for a structural reason — the three view bodies were SIBLINGS appended
straight to the card, and switching set the inactive ones to `display:none`. A
card was therefore exactly as tall as the view on screen, so moving from Shop to
Battle to Result resized it, which moved the buttons and every turn below it.

The fix is two lines of structure: the bodies share one grid cell (`.tviews`),
and the inactive ones are hidden with `visibility` rather than `display` — so
they keep their LAYOUT space and the card is always as tall as its tallest view.

**This is measured, not asserted from the source.** `node` cannot lay anything
out and no DOM is available to the suite, so the test drives a real browser
(Chrome or Edge, headless) over a page built from the PAGE'S OWN `<style>`, and
reads back `offsetHeight` under each of the three switches. The numbers are the
control; the two structural assertions at the end are only the wiring, and they
exist because a layout measurement cannot see that the JS stopped putting the
bodies in the shared box.

**The measurement is rehearsed against the OLD structure in the same run.** A
layout check that cannot fail is worse than none — CSS that never loaded reports
every height as 0, which is "equal". So the second case rebuilds the pre-fix
markup (`display` toggling, sibling bodies) and the test requires the heights to
come out UNEQUAL there: measured 2026-10-07, `shop=100 battle=40 aftermath=60`
against `100/100/100` for the fix.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed

import coach_ui  # noqa: E402

#: Where a Chromium browser lives on this platform. Checked in order; the test
#: skips and says why when none of them is there, the same way the node-based
#: tests skip without node.
BROWSERS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)

_ROWS = "".join('<div class="brow"><span>row %d</span></div>' % i
                for i in range(1, 6))
_TWO = "".join('<div class="brow"><span>row %d</span></div>' % i
               for i in range(1, 3))
_THREE = "".join('<div class="brow"><span>row %d</span></div>' % i
                 for i in range(1, 4))

#: 5 rows / 2 rows / 3 rows, substituted here rather than left as placeholders.
#: A first version of this file forgot the `%` and shipped literal `%s` into the
#: page: every body rendered empty, all three heights came out 42, and the
#: "same height" assertion passed for the WRONG reason. The rehearsal below is
#: what caught it, which is the whole argument for having one.
_BODIES = """
  <div class="tbody" id="shop">%s</div>
  <div class="tbody" id="battle">%s</div>
  <div class="tbody" id="aftermath">%s</div>
""" % (_ROWS, _TWO, _THREE)


def _browser():
    for path in BROWSERS:
        if os.path.exists(path):
            return path
    return shutil.which("google-chrome") or shutil.which("chromium")


def _page_style():
    """The page's own <style> block, so the test cannot pass on its own CSS."""
    m = re.search(r"<style>(.*?)</style>", coach_ui._HTML, re.S)
    return m.group(1) if m else ""


def _measure(doc):
    """Render `doc` in a headless browser and return the numbers it wrote.

    The page prints its own measurements into #out and `--dump-dom` reads them
    back: a headless run gives no other channel, and the alternative — parsing a
    screenshot — would need the pixels to be read, which nothing here can do.
    """
    browser = _browser()
    with tempfile.TemporaryDirectory() as tmp:
        page = os.path.join(tmp, "layout.html")
        with open(page, "w", encoding="utf-8") as fh:
            fh.write(doc)
        proc = subprocess.run(
            [browser, "--headless=new", "--disable-gpu", "--no-sandbox",
             f"--user-data-dir={os.path.join(tmp, 'profile')}",
             "--dump-dom", "file:///" + page.replace(os.sep, "/")],
            capture_output=True, text=True, timeout=120)
    m = re.search(r'id="out">([^<]*)<', proc.stdout or "")
    if not m:
        raise AssertionError(
            f"the browser did not run the page: {(proc.stderr or '')[:300]}")
    # ints, not the strings the page printed: a string comparison would make
    # `assertGreater` raise and every equality check pass on the text.
    return {part.split("=")[0]: int(part.split("=")[1])
            for part in m.group(1).split()}


def _harness(container, prop, hidden, visible, style):
    """A card with three view bodies, measured at each of the three switches.

    `container` is the markup the bodies go inside, and `prop`/`hidden`/
    `visible` are what a switch sets — the page sets `style.visibility` to
    `hidden`, while the pre-fix code set `style.display` to `none`. One harness
    therefore measures the fix and rehearses the bug it fixed.
    """
    return f"""<!doctype html><html><head><style>{style}</style></head><body>
<pre id="out">pending</pre>
<div class="turn" id="card">{container.format(s=_BODIES)}</div>
<script>
  const bodies = {{shop: document.getElementById('shop'),
                   battle: document.getElementById('battle'),
                   aftermath: document.getElementById('aftermath')}};
  const card = document.getElementById('card');
  const out = [];
  for (const shown of ['shop', 'battle', 'aftermath']) {{
    for (const k of ['shop', 'battle', 'aftermath'])
      bodies[k].{prop} = k === shown ? {visible} : {hidden};
    out.push(shown + '=' + card.offsetHeight);
  }}
  document.getElementById('out').textContent = out.join(' ');
</script></body></html>"""


class TestTheTurnCardHoldsItsSize(unittest.TestCase):
    def setUp(self):
        if _browser() is None:
            self.skipTest("no Chromium browser on this machine, so a layout "
                          "cannot be measured")
        style = _page_style()
        self.assertIn(".tviews", style,
                      "the page no longer stacks the views — the card will "
                      "resize again when the player switches")

    def test_the_card_is_the_same_height_in_all_three_views(self):
        heights = _measure(_harness('<div class="tviews">{s}</div>',
                                    "style.visibility", "'hidden'", "''",
                                    _page_style()))
        self.assertEqual(len(set(heights.values())), 1,
                         f"the card changes size on a view switch: {heights}")
        self.assertGreater(max(heights.values()), 0,
                           "every view measured 0 — the CSS did not load, so "
                           "equality here would prove nothing")

    def test_the_measurement_would_catch_the_old_structure(self):
        """The rehearsal. Same page, pre-fix markup (`display` toggling, no
        shared grid cell): the heights MUST come out unequal, or this suite
        cannot tell the fix from the bug it fixed."""
        heights = _measure(_harness("{s}", "style.display", "'none'", "''",
                                    _page_style()))
        self.assertGreater(len(set(heights.values())), 1,
                           f"the old structure measured equal heights ({heights})"
                           " — this control is blind")


class TestTheWiring(unittest.TestCase):
    """A layout measurement cannot see the JS, and the JS is what puts the three
    bodies in the shared box and hides them the way the CSS expects."""

    def test_the_bodies_go_into_the_shared_container(self):
        page = coach_ui._HTML
        self.assertIn("views.appendChild(body)", page)
        self.assertIn("card.appendChild(views)", page)
        self.assertNotIn("card.appendChild(body)", page,
                         "a body appended straight to the card is the bug")

    def test_the_inactive_views_are_hidden_without_leaving_the_layout(self):
        page = coach_ui._HTML
        self.assertIn("bodies[k].style.visibility", page)
        self.assertNotIn("bodies[k].style.display", page,
                         "display:none takes the view out of the layout, which "
                         "collapses the card back to the visible view")


if __name__ == "__main__":
    unittest.main()
