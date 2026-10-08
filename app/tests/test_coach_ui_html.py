"""The overlay stylesheet's design-token discipline.

Phase 2 (2026-09-24) gave the page a real token block after months of
ad-hoc hex — including var(--gold) referenced ten times and defined
nowhere, so every gold accent silently failed. These tests keep it that
way: a raw color may appear ONLY inside :root, and the tokens the
stylesheet leans on must actually exist.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import coach_ui  # noqa: E402

_HTML = coach_ui._HTML


def _css():
    start = _HTML.index("<style>") + len("<style>")
    return _HTML[start:_HTML.index("</style>", start)]


def _root_block(css):
    start = css.index(":root")
    end = css.index("}", start)
    return css[start:end]


def _tavern_token_blocks(css):
    """The Tavern palette's token rules (REPLAY_VIEWER_DESIGN.md §6, scoped
    on purpose so the classic viewer keeps its own tokens): rules whose
    SELECTOR is exactly `.tavern` — not the `.tavern .turn` rules that
    consume the tokens."""
    out = []
    for m in re.finditer(r"(?:^|[}\n])([^{}\n]*\.tavern)\s*\{([^{}]*)\}", css):
        if m.group(1).strip().endswith(".tavern"):
            out.append(m.group(2))
    return out


HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")


class TestTokenDiscipline(unittest.TestCase):
    def test_hex_literals_live_only_in_root(self):
        css = _css()
        outside = css.replace(_root_block(css), "")
        for block in _tavern_token_blocks(css):
            outside = outside.replace(block, "")
        strays = sorted(set(HEX_RE.findall(outside)))
        self.assertEqual(
            strays, [],
            "raw colors outside the token blocks (use a var): "
            + ", ".join(strays))

    def test_gold_is_defined(self):
        """The 2026-09-24 audit found var(--gold) referenced 10x and defined
        nowhere — ten silent style failures. Any var the CSS references must
        exist in :root or a scoped palette block."""
        css = _css()
        defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", _root_block(css)))
        for block in _tavern_token_blocks(css):
            defined |= set(re.findall(r"(--[a-z0-9-]+)\s*:", block))
        referenced = set(re.findall(r"var\((--[a-z0-9-]+)", css))
        missing = sorted(referenced - defined)
        self.assertEqual(missing, [],
                         "var() referenced but never defined: "
                         + ", ".join(missing))


class TestKindChipsAreGone(unittest.TestCase):
    """This class used to assert that every kind in value._STEP_KINDS had a
    chip in the page's KIND_CHIP map, both directions — a genuine drift guard,
    because a kind with no chip rendered as NOTE.

    The map and the plan it labelled left the live page on 2026-10-06
    (PIVOT.md): the chips were instruction labels ("BUY", "LEVEL", "SELL") on
    the numbered plan, and the live path ships state, not instructions. The
    guard is inverted rather than deleted, so this still fails if a step chip
    comes back — and it asserts the OTHER half too, that value.py kept the
    kinds the review and the corpus read."""

    def test_the_page_has_no_chip_map(self):
        self.assertNotIn("KIND_CHIP", _HTML)

    def test_value_still_defines_the_step_kinds(self):
        from value import _STEP_KINDS
        kinds = {k for _prefix, k in _STEP_KINDS}
        self.assertIn("buy", kinds)
        self.assertIn("level", kinds)


if __name__ == "__main__":
    unittest.main()
