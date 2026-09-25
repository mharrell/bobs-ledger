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


HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")


class TestTokenDiscipline(unittest.TestCase):
    def test_hex_literals_live_only_in_root(self):
        css = _css()
        root = _root_block(css)
        outside = css.replace(root, "")
        strays = sorted(set(HEX_RE.findall(outside)))
        self.assertEqual(
            strays, [],
            "raw colors outside the :root token block (use a var): "
            + ", ".join(strays))

    def test_gold_is_defined(self):
        """The 2026-09-24 audit found var(--gold) referenced 10x and defined
        nowhere — ten silent style failures. Any var the CSS references must
        exist in :root."""
        css = _css()
        root = _root_block(css)
        defined = set(re.findall(r"(--[a-z0-9-]+)\s*:", root))
        referenced = set(re.findall(r"var\((--[a-z0-9-]+)", css))
        missing = sorted(referenced - defined)
        self.assertEqual(missing, [],
                         "var() referenced but never defined: "
                         + ", ".join(missing))


class TestKindChips(unittest.TestCase):
    """The plan steps render a text chip per step kind. value._STEP_KINDS is
    the source of the kind set; when value grows a kind and the JS chip map
    doesn't, the step silently renders the NOTE chip — this keeps the two
    from diverging."""

    def test_every_step_kind_has_a_chip(self):
        from value import _STEP_KINDS
        m = re.search(r"const KIND_CHIP = \{(.*?)\};", _HTML, re.S)
        self.assertTrue(m, "KIND_CHIP map not found in the page JS")
        chips = set(re.findall(r"(\w+):\s*'", m.group(1)))
        kinds = {k for _prefix, k in _STEP_KINDS}
        self.assertEqual(kinds - chips, set(),
                         "step kinds with no chip in the JS map: "
                         + ", ".join(sorted(kinds - chips)))
        self.assertEqual(chips - kinds, set(),
                         "chips for kinds value.py no longer emits: "
                         + ", ".join(sorted(chips - kinds)))


if __name__ == "__main__":
    unittest.main()
