"""Log sanitization: BattleTags are the log's only personal data; they must
be redacted to stable placeholders while the parse keeps working."""
import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from sanitize_log import BATTLETAG, sanitize_text  # noqa: E402
from config import HS_LOG_GLOB  # noqa: E402


class TestSanitizeText(unittest.TestCase):
    def test_battletags_replaced_with_stable_placeholders(self):
        text = ("TAG_CHANGE Entity=Player#1234 tag=RESOURCES value=3\n"
                "TAG_CHANGE Entity=Player#1234 tag=RESOURCES value=4\n"
                "TAG_CHANGE Entity=OtherGuy#54321 tag=PLAYSTATE value=WON")
        clean, mapping = sanitize_text(text)
        self.assertNotIn("Player", clean)
        self.assertNotIn("OtherGuy", clean)
        self.assertNotIn("#", clean.replace("tag=", ""))  # no raw tags left
        # same tag -> same placeholder across the file (parsers key on it)
        self.assertEqual(clean.count("P1"), 2)
        self.assertEqual(len(mapping), 2)

    def test_non_tag_hashes_untouched(self):
        """Card ids / game text with # don't exist, but a near-miss (short
        discriminator, leading digit) must not be mangled."""
        clean, _ = sanitize_text("cardId=BG36_204 player=1 #notATag2 x#12")
        self.assertEqual(clean, "cardId=BG36_204 player=1 #notATag2 x#12")

    def test_placeholder_parsing_survives(self):
        """The live coach must parse a sanitized log identically (names are
        just dict keys)."""
        import live_coach
        text = ("GameState.DebugPrintPower() - TAG_CHANGE "
                "Entity=SomeBody#1234 tag=RESOURCES value=5\n")
        clean, _ = sanitize_text(text)
        c = live_coach.LiveCoach()
        for line in clean.splitlines():
            c.feed(line)
        self.assertEqual(c.gs.gold.get("P1"), 5)

    def test_real_log_fully_redacted(self):
        """Integration (local logs): after sanitizing, zero BattleTag
        matches remain in the output."""
        logs = sorted(glob.glob(HS_LOG_GLOB),
                      key=os.path.getmtime, reverse=True)
        if not logs:
            self.skipTest("no Hearthstone session log found")
        with open(logs[0], encoding="utf-8", errors="replace") as f:
            text = f.read(5_000_000)
        if not BATTLETAG.search(text):
            self.skipTest("no BattleTags in this segment")
        clean, _ = sanitize_text(text)
        self.assertIsNone(BATTLETAG.search(clean))


if __name__ == "__main__":
    unittest.main()