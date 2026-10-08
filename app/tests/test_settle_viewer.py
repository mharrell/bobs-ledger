"""The Settle Up viewer flag (2026-10-08): a styling toggle that keeps the
shipped Classic renderer as the default while the REPLAY_VIEWER_DESIGN.md
build grows behind the Tavern branch. The flag is the contract under test:
Classic must be the default and untouched, the choice must persist, and the
Tavern branch must reuse the real card renderer rather than fork it.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import coach_ui  # noqa: E402


def _function(name):
    m = re.search(rf"function {name}\(.*?\n\}}", coach_ui._HTML, re.S)
    return m.group(0) if m else None


class TestTheFlag(unittest.TestCase):

    def test_the_toggle_is_in_the_settle_header(self):
        self.assertIn('id="settle-viewer"', coach_ui._HTML)
        head = coach_ui._HTML[coach_ui._HTML.index('id="settle-viewer"'):]
        self.assertIn('data-v="classic"', head)
        self.assertIn('data-v="tavern"', head)
        # Classic is the shipped default, in the markup itself, so the page
        # reads right even before the script runs.
        self.assertRegex(head[:200], r'data-v="classic" class="on"')

    def test_the_choice_persists_under_its_own_key(self):
        self.assertIn("localStorage.getItem('bl-settle-viewer')",
                      coach_ui._HTML)
        self.assertIn("localStorage.setItem('bl-settle-viewer'",
                      coach_ui._HTML)

    def test_classic_is_the_default(self):
        self.assertIn("let _viewer = 'classic';", coach_ui._HTML)

    def test_render_settle_game_branches_and_remembers_the_rep(self):
        src = _function("renderSettleGame")
        self.assertIsNotNone(src)
        self.assertIn("if (_viewer === 'tavern') return renderTavernGame(rep);",
                      src, "the branch is the whole flag")
        self.assertLess(src.index("_settleRep = rep"),
                        src.index("if (_viewer"),
                        "the rep is remembered BEFORE the branch, or toggling "
                        "on a loaded game would blank it")

    def test_the_classic_renderer_is_unchanged(self):
        """The shipped path keeps its shape: one card per timeline turn, the
        sticky header, and the final-duel phases attached to the last card."""
        src = _function("renderSettleGame")
        self.assertIn("settleTurnCard(r, phases.filter(p => p.turn === r.turn))",
                      src)
        self.assertIn("className = 'turn s-sticky'", src)
        self.assertIn("for (const p of rest) lastCard.appendChild(phaseRow(p));",
                      src)

    def test_tavern_reuses_the_real_card_renderer(self):
        """The Tavern branch must not fork the card logic: one turn on screen
        is THE settleTurnCard, notes and honesty included."""
        src = _function("renderTavernGame")
        self.assertIsNotNone(src, "renderTavernGame is missing")
        self.assertIn("settleTurnCard(row, phases.filter(", src)
        self.assertIn("className = 'tavern'", src)
        self.assertIn("stripMark(r.winner, r.damage_taken)", src)

    def test_tavern_tokens_are_scoped_not_global(self):
        """The Tavern palette lives on .tavern; the classic viewer and the
        live overlay keep their own tokens."""
        self.assertRegex(coach_ui._HTML, r"\.tavern \{[^}]*--tbg:#17110d")
        for root_rule in re.findall(r":root \{[^}]*\}", coach_ui._HTML):
            self.assertNotIn("--tbg", root_rule,
                             "the Tavern palette leaked into :root")


class TestTheStripMarker(unittest.TestCase):
    """stripMark is the strip's result line, run under node (skipped without
    it). Result is never color-only, so the glyph and the HP text are the
    contract; unknown states are explicit, never a guess."""

    def setUp(self):
        if shutil.which("node") is None:
            self.skipTest("node is not installed, so the page's script cannot "
                          "be executed")
        source = _function("stripMark")
        self.assertIsNotNone(
            source, "stripMark() is no longer a function in the page")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cases = [["us", 10], ["them", 10], ["tie", None], [None, None],
                 [None, 5], ["us", -3], ["them", 0]]
        driver = os.path.join(self.tmp.name, "drive.js")
        with open(driver, "w", encoding="utf-8") as f:
            f.write(f"{source}\n"
                    f"const cases = {json.dumps(cases)};\n"
                    "console.log(JSON.stringify("
                    "cases.map(([w, d]) => stripMark(w, d))));\n")
        # Bytes in, UTF-8 decoded here: node writes UTF-8 to the pipe and
        # text=True would decode it with the Windows locale (cp1252), which
        # mojibakes every glyph this test exists to pin (▲/▼/− measured
        # scrambled on 2026-10-08).
        proc = subprocess.run(["node", driver], capture_output=True,
                              timeout=30)
        self.assertEqual(proc.returncode,
                         0, f"node could not run stripMark: "
                            f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
        self.out = json.loads(proc.stdout.decode("utf-8"))

    def test_win_loss_tie_glyphs(self):
        self.assertEqual(self.out[0]["ch"], "▲ −10")
        self.assertEqual(self.out[0]["cls"], "win")
        self.assertEqual(self.out[1]["ch"], "▼ −10")
        self.assertEqual(self.out[1]["cls"], "loss")
        self.assertEqual(self.out[2]["ch"], "=")
        self.assertEqual(self.out[2]["cls"], "tie")

    def test_unknown_states_are_explicit(self):
        self.assertEqual(self.out[3]["ch"], "?")
        self.assertEqual(self.out[3]["cls"], "")
        self.assertEqual(self.out[4]["ch"], "? −5")

    def test_hp_gain_and_zero(self):
        self.assertEqual(self.out[5]["ch"], "▲ +3")
        self.assertEqual(self.out[6]["ch"], "▼ ±0")


if __name__ == "__main__":
    unittest.main()
