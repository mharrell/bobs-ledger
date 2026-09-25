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


if __name__ == "__main__":
    unittest.main()
