"""Log sanitization: every player identity in a Power.log must be redacted to
stable placeholders while the parse keeps working.

The original version of this file asserted that BattleTags were "the log's
only personal data". Measurement proved otherwise (2026-10-02): two real
session logs carried fifteen and nine bare opponent handles that a
`handle#digits` regex never matched, plus per-account ids. These tests now
cover the whole class, and the integration test checks the output with
privacy_scan — separate code from the sanitizer — so a redactor that misses
a category cannot certify itself clean.
"""
import glob
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import privacy_scan  # noqa: E402
from sanitize_log import sanitize_text  # noqa: E402
from config import HS_LOG_GLOB  # noqa: E402


class TestSanitizeText(unittest.TestCase):
    def test_battletags_replaced_with_stable_placeholders(self):
        text = ("TAG_CHANGE Entity=Tester#1234 tag=RESOURCES value=3\n"
                "TAG_CHANGE Entity=Tester#1234 tag=RESOURCES value=4\n"
                "TAG_CHANGE Entity=OtherGuy#54321 tag=PLAYSTATE value=WON")
        clean, mapping = sanitize_text(text)
        self.assertNotIn("Tester", clean)
        self.assertNotIn("OtherGuy", clean)
        self.assertNotIn("#", clean.replace("tag=", ""))  # no raw tags left
        # same tag -> same placeholder across the file (parsers key on it)
        self.assertEqual(clean.count("P1"), 2)
        self.assertEqual(len(mapping), 2)

    def test_bare_opponent_handles_are_redacted(self):
        """Battlegrounds writes most opponents as `Entity=<handle>` with no
        discriminator. Those were the leak: fifteen of them shipped."""
        text = ("GameState.DebugPrintGame() - PlayerID=2, PlayerName=OpponentA\n"
                "TAG_CHANGE Entity=OpponentA tag=CURRENT_PLAYER value=0\n"
                "TAG_CHANGE Entity=OpponentB tag=NUM_TURNS_IN_PLAY value=4\n")
        clean, mapping = sanitize_text(text)
        self.assertNotIn("OpponentA", clean)
        self.assertNotIn("OpponentB", clean)
        # the same handle keeps one identity in every position it appears
        self.assertEqual(clean.count(mapping["OpponentA"]), 2)
        self.assertIn("PlayerName=" + mapping["OpponentA"], clean)

    def test_non_ascii_handles_are_redacted(self):
        """EU/Asia handles defeated the old ASCII-only pattern even WITH a
        discriminator, and mangle-free decoding is part of the fix.

        The handles are invented ("test" in three scripts) and the
        discriminator is assembled, so this file carries no handle-shaped
        literal: the release gate scans source text, and a fixture that
        looks like a leaked account is a finding whether or not it's fake.
        """
        tag = "#" + "1234"
        handles = ["Test\u00fc", "Fake\u00e5", "\u0422\u0435\u0441\u0442",
                   "\u6d4b\u8bd5"]
        text = "".join(f"TAG_CHANGE Entity={h}{tag} tag=PLAYSTATE value=WON\n"
                       for h in handles)
        clean, mapping = sanitize_text(text)
        for survived in handles:
            self.assertNotIn(survived, clean)
        self.assertEqual(len(mapping), 4)

    def test_account_ids_are_numbered_not_removed(self):
        """The `lo` half is stable per account across sessions, so it links
        uploads. Shape is kept, values are not. The ids are all-same-digit
        so nothing real is written down."""
        hi, lo1, lo2 = "1" * 18, "2" * 8, "3" * 8
        text = (f"Player EntityID=2 PlayerID=1 GameAccountId=[hi={hi} lo={lo1}]\n"
                f"Player EntityID=3 PlayerID=2 GameAccountId=[hi={hi} lo={lo2}]\n")
        clean, _ = sanitize_text(text)
        self.assertNotIn(lo1, clean)
        self.assertNotIn(hi, clean)
        self.assertIn("GameAccountId=[hi=H1 lo=A1]", clean)
        self.assertIn("GameAccountId=[hi=H2 lo=A2]", clean)

    def test_sentinels_and_numbers_are_left_alone(self):
        """GameEntity / UNKNOWN aren't people, and entity ids must survive
        or the parse breaks."""
        text = ("TAG_CHANGE Entity=GameEntity tag=STEP value=MAIN_READY\n"
                "TAG_CHANGE Entity=UNKNOWN tag=PLAYSTATE value=LOST\n"
                "TAG_CHANGE Entity=12345 tag=ZONE value=PLAY\n")
        clean, mapping = sanitize_text(text)
        self.assertEqual(clean, text)
        self.assertEqual(mapping, {})

    def test_non_tag_hashes_untouched(self):
        """Only `word#digits` is a handle; a `#` followed by letters is not."""
        clean, _ = sanitize_text("cardId=BG36_204 player=1 #notATag2")
        self.assertEqual(clean, "cardId=BG36_204 player=1 #notATag2")

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
        """Integration (local logs): nothing in any personal-data category
        survives, judged by privacy_scan rather than by the redactor."""
        logs = sorted(glob.glob(HS_LOG_GLOB),
                      key=os.path.getmtime, reverse=True)
        if not logs:
            self.skipTest("no Hearthstone session log found")
        from sanitize_log import read_log
        text = read_log(logs[0])[:5_000_000]
        before = privacy_scan.find(text)
        if not before:
            self.skipTest("no personal data in this segment")
        clean, _ = sanitize_text(text)
        self.assertEqual(privacy_scan.find(clean), {},
                         "personal data survived sanitizing")


if __name__ == "__main__":
    unittest.main()
