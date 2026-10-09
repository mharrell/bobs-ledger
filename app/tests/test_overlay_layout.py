"""The Settle Up turn card fits the view it is showing, tabs on top.

The 2026-10-07 shape held the card at ONE height across all three views: the
bodies shared a single grid cell and the inactive ones kept their layout space
under `visibility`. The maintainer's 2026-10-09 fix list named the cost that
arrangement was paying all along — *"the tabs are pinned to the bottom of a
panel with about 400px of empty space"* — and reversed it: the tab row sits
ABOVE the views, and the panel is as tall as the view on screen
(`display:none`, in flow).

**This is measured, not asserted from the source.** `node` cannot lay anything
out and no DOM is available to the suite, so the test drives a real browser
(Chrome or Edge, headless) over a page built from the PAGE'S OWN `<style>`, and
reads back `offsetHeight` under each of the three switches. The numbers are the
control; the structural assertions at the end are only the wiring, and they
exist because a layout measurement cannot see that the JS stopped putting the
bodies in the shared box or moved the tab row above them.

**The measurement is rehearsed against the OLD structure in the same run.** A
layout check that cannot fail is worse than none — CSS that never loaded reports
every height as 0. So the second case rebuilds the 2026-10-07 markup (shared
grid cell, `visibility` toggling) and the test requires the heights to come out
EQUAL there: measured 2026-10-07, that structure read `100/100/100` where the
in-flow one reads its three contents apart. The rehearsal is the same control
it always was, pointed the other way.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed
sys.path.insert(0, os.path.join(HERE, "tests"))   # the shared test helpers

import browser  # noqa: E402  (the shared headless-browser harness)
import coach_ui  # noqa: E402

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


def _page_style():
    """The page's own <style> block, so the test cannot pass on its own CSS."""
    m = re.search(r"<style>(.*?)</style>", coach_ui._HTML, re.S)
    return m.group(1) if m else ""


def _measure(case, doc):
    """Render `doc` in a headless browser and return the numbers it wrote.

    The launch, the DOM read and the diagnosis live in `browser.py`, shared
    with `test_settle_browser`; a browser this session cannot START is a skip
    with the browser's own words in it, not a failure (2026-10-08 — see that
    module for the measurement behind the distinction).
    """
    try:
        return browser.numbers(doc)
    except browser.BrowserUnavailable as e:
        case.skipTest(str(e))


def _harness(container, prop, hidden, visible, style):
    """A card with three view bodies, measured at each of the three switches.

    `container` is the markup the bodies go inside, and `prop`/`hidden`/
    `visible` are what a switch sets — the page sets `style.display` to
    `none` (in flow), while the 2026-10-07 code set `style.visibility`. One
    harness therefore measures the fix and rehearses the structure it
    replaced.
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


class TestTheCardFitsItsView(unittest.TestCase):
    def setUp(self):
        browser.require_browser(self)
        style = _page_style()
        self.assertIn(".tviews", style,
                      "the page no longer marks the view container — the card "
                      "structure below cannot be the page's own")

    def test_each_view_is_as_tall_as_its_own_content(self):
        """Shop (5 rows) > Result (3) > Battle (2): the panel is the view's
        height, not the tallest view's. This is the deliberate reversal of
        the 2026-10-07 rule — the fix list traded the never-resize card for
        ~400px of dead space gone."""
        heights = _measure(self, _harness('<div class="tviews">{s}</div>',
                                          "style.display", "'none'", "''",
                                          _page_style()))
        self.assertEqual(len(set(heights.values())), 3,
                         f"the card does not fit its view: {heights}")
        self.assertGreater(heights["shop"], heights["aftermath"],
                           f"the tallest view is not the tallest: {heights}")
        self.assertGreater(heights["aftermath"], heights["battle"],
                           f"the shortest view is not the shortest: {heights}")
        self.assertGreater(max(heights.values()), 0,
                           "every view measured 0 — the CSS did not load, so "
                           "these assertions would prove nothing")

    def test_the_measurement_would_catch_the_old_structure(self):
        """The rehearsal. Same page, 2026-10-07 markup (one shared grid cell,
        `visibility` toggling): the heights MUST come out equal, or this
        suite cannot tell the fix from the structure it replaced."""
        heights = _measure(self, _harness(
            '<style>.tviews {{ display:grid; }}'
            '.tviews .tbody {{ grid-area:1 / 1; }}</style><div class="tviews">'
            '{s}</div>',
            "style.visibility", "'hidden'", "''", _page_style()))
        self.assertEqual(len(set(heights.values())), 1,
                         f"the old structure measured apart ({heights})"
                         " — this control is blind")
        self.assertGreater(max(heights.values()), 0,
                           "every view measured 0 — the control proved nothing")


class TestTheWiring(unittest.TestCase):
    """A layout measurement cannot see the JS, and the JS is what puts the tab
    row above the bodies and hides them the way the CSS expects."""

    def test_the_bodies_go_into_the_shared_container(self):
        page = coach_ui._HTML
        self.assertIn("views.appendChild(body)", page)
        self.assertIn("card.appendChild(views)", page)
        self.assertNotIn("card.appendChild(body)", page,
                         "a body appended straight to the card is the bug")

    def test_the_tab_row_sits_above_the_views(self):
        """The fix list: "Move the Shop / Battle / Result tabs above the
        boards." The buttons append FIRST, or the controls are back at the
        bottom of the panel."""
        page = coach_ui._HTML
        self.assertIn("card.appendChild(btns)", page)
        self.assertIn("card.appendChild(views)", page)
        self.assertLess(page.index("card.appendChild(btns)"),
                        page.index("card.appendChild(views)"),
                        "the tab row must be appended before the views")

    def test_the_inactive_views_leave_the_layout(self):
        page = coach_ui._HTML
        self.assertIn("bodies[k].style.display", page)
        self.assertNotIn("bodies[k].style.visibility", page,
                         "visibility keeps a hidden view in the layout — the "
                         "card would hold the tallest view's height again")


if __name__ == "__main__":
    unittest.main()
