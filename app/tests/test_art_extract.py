"""Client-side card-art extraction: id matching and wanted-id collection."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from hearth_art_extract import ID_RE  # noqa: E402


class TestIdRegex(unittest.TestCase):
    def test_bg_card_ids_match(self):
        # the 2026-09-03 bug: BG\d+ alone never matched BG19_010 (full-string
        # match with no _suffix branch), so all BG ids reported "no carddef"
        for cid in ("BG19_010", "BG36_204", "BG30_MagicItem_434",
                    "BG26_HERO_104", "BG33_886", "BG28_897"):
            self.assertTrue(ID_RE.match(cid), cid)

    def test_other_sets_rejected(self):
        for cid in ("REV_244", "HS26_058", "CORE_EX1_007", "Story_123",
                    "LT24_456", "GVG_096"):
            self.assertIsNone(ID_RE.match(cid), cid)


if __name__ == "__main__":
    unittest.main()