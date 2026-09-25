"""scrape_comps.diff_comp — the --diff change report must surface tier moves,
core/addon swaps and text edits, and print nothing when a comp is unchanged."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from scrape_comps import diff_comp, load_card_names  # noqa: E402

NAMES = {"BG36_511": "Ferocious Felbat", "BG31_835": "Undead minion"}


def base_comp(**overrides):
    comp = {
        "name": "Test Comp",
        "meta_tier": "A",
        "difficulty": "Medium",
        "core": ["BG36_511"],
        "addons": [],
        "representative_card": "BG36_511",
        "how_to_play": "do the thing",
        "summary": "a comp",
        "when_to_commit": "when strong",
        "common_enablers": "enabler",
    }
    comp.update(overrides)
    return comp


class TestDiffComp(unittest.TestCase):
    def test_no_changes_reports_empty(self):
        self.assertEqual(diff_comp(base_comp(), base_comp(), NAMES), [])

    def test_tier_move(self):
        new = base_comp(meta_tier="S")
        self.assertEqual(diff_comp(base_comp(), new, NAMES),
                         ["tier: A -> S"])

    def test_core_swap_uses_card_names(self):
        new = base_comp(core=["BG31_835"])
        self.assertEqual(diff_comp(base_comp(), new, NAMES),
                         ["core: - Ferocious Felbat  + Undead minion"])

    def test_unknown_ids_fall_back_to_raw_id(self):
        new = base_comp(core=["BG36_511", "BG99_999"])
        self.assertEqual(diff_comp(base_comp(), new, NAMES),
                         ["core: + BG99_999"])

    def test_text_fields_report_length_only(self):
        new = base_comp(summary="a comp, ranked")
        self.assertEqual(diff_comp(base_comp(), new, NAMES),
                         ["summary: edited (6 -> 14 chars)"])

    def test_how_to_play_is_ours_and_never_diffed(self):
        """Since the 2026-09-24 takedown-hygiene pass, how_to_play is written
        in our own words and preserved across re-scrapes (HAND_ADDED_FIELDS) —
        the scraped prose is never imported, so the field can never change
        from a re-scrape and has nothing to diff."""
        new = base_comp(how_to_play="do the thing much better now ok")
        self.assertEqual(diff_comp(base_comp(), new, NAMES), [])

    def test_representative_change(self):
        new = base_comp(representative_card="BG31_835")
        self.assertEqual(diff_comp(base_comp(), new, NAMES),
                         ["representative: Ferocious Felbat -> Undead minion"])


class TestLoadCardNames(unittest.TestCase):
    def test_loads_real_minions_meta(self):
        names = load_card_names()
        self.assertGreater(len(names), 100)

    def test_missing_file_returns_empty_map(self):
        self.assertEqual(load_card_names(os.path.join(HERE, "no", "such.json")), {})


if __name__ == "__main__":
    unittest.main()