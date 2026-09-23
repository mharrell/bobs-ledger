"""Provisional comps: a direction for a tribe the published source does not cover.

The measured problem (2026-09-23): 4 of the 12 games in the local corpus ended on
an Aberration-dominant board, the comp source has no Aberration comp at all, and
36-60% of the coach's lines in a typical game were the "no target comp"
placeholder. Adherence in those games is a structural zero — the player cannot
follow advice that does not exist — so the gap also poisoned the metric.

The fix is not to invent a comp. It is to mine one from our own boards, mark it
`provisional` with its evidence attached, and make EVERY ranking path treat it as
second class while every DISPLAY path says what it is.
"""
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import comp_miner  # noqa: E402
import meta  # noqa: E402
import scrape_comps  # noqa: E402
import value  # noqa: E402

AB = "Aberration"
CORE = ["BG36_318", "BG36_103"]          # Faceless Converter, N'raqi Sapper
BEAST = ["BG36_201", "BG36_202"]


AB_SIDE = ["BG36_115", "BG36_109", "BG36_320"]   # Aberration bodies


def board(ids, tribe=None):
    """A board whose ids are tribed: CORE/BEAST by lookup, `tribe` overrides."""
    out = []
    for cid in ids:
        t = tribe
        if t is None:
            t = AB if cid in CORE + AB_SIDE else ("Beast" if cid in BEAST else None)
        out.append({"card": cid, "name": cid, "atk": 5, "health": 5, "tribe": t})
    return out


PROVISIONAL = {
    "aberrations-deity-feed": {
        "name": "Aberrations - Deity Feed", "tribe": AB, "meta_tier": None,
        "difficulty": None, "core": CORE, "addons": [],
        "provisional": True, "source": "own replay corpus (comp_miner.py)",
        "evidence": {"games": 4, "top4": 2, "floor": 3, "built": "2026-09-23"},
    },
}
BEASTS = {
    "beasts-lobstah": {"name": "Beasts - Tasty Lobstah", "tribe": "Beast",
                       "meta_tier": "A", "core": [BEAST[0]], "addons": []},
}


class TestGapIgnoresProvisional(unittest.TestCase):
    """`comp_gap` is about the PUBLISHED source, and stays that way."""

    def test_a_provisional_comp_does_not_close_the_gap(self):
        b = board(CORE + ["BG36_115", "BG36_109", "BG36_320"])
        self.assertEqual(value.comp_gap(b, PROVISIONAL), AB,
                         "the published source still has nothing for this tribe")

    def test_a_published_comp_still_closes_the_gap(self):
        comps = dict(PROVISIONAL)
        comps["aberrations-published"] = {
            "name": "Aberrations - Published", "tribe": AB, "core": ["BG36_318"]}
        b = board(CORE + ["BG36_115", "BG36_109", "BG36_320"])
        self.assertIsNone(value.comp_gap(b, comps))


class TestProvisionalIsSecondClass(unittest.TestCase):
    def test_gap_fallback_coaches_the_mined_comp(self):
        b = board(CORE + ["BG36_115", "BG36_109", "BG36_320"])
        got = value.comp_target(b, PROVISIONAL)
        self.assertIsNotNone(got, "a mined comp is a real direction")
        self.assertTrue(got["provisional"])
        self.assertEqual(got["name"], "Aberrations - Deity Feed")

    def test_no_provisional_and_no_published_is_still_no_direction(self):
        b = board(CORE + ["BG36_115", "BG36_109", "BG36_320"])
        self.assertIsNone(value.comp_target(b, {}))

    def test_a_published_comp_wins_even_with_fewer_board_pieces(self):
        """2 published Beast hits beat a provisional comp the board is full of."""
        b = board([BEAST[0], BEAST[0], BEAST[1]]) + board(CORE[:1], tribe=AB)
        got = value.comp_target(b, dict(PROVISIONAL, **BEASTS))
        self.assertEqual(got["name"], "Beasts - Tasty Lobstah")
        self.assertFalse(got.get("provisional"))

    def test_provisional_never_sets_a_tribe_level_direction(self):
        """A Beast-dominant board is not pulled onto a mined comp.

        The published Beast comp has ONE matching board piece and the mined
        Aberration comp has two, so if provisional comps fed the tribe-level
        path this would answer "Aberrations - Deity Feed". It must not: a
        mined comp is reached only through the gap branch.
        """
        b = board([BEAST[0], BEAST[1], BEAST[1]]) + board(CORE, tribe=AB)
        comps = dict(PROVISIONAL)
        comps["beasts-1hit"] = {"name": "Beasts - One Hit", "tribe": "Beast",
                                "core": [BEAST[0]], "addons": []}
        got = value.comp_target(b, comps)
        self.assertIsNone(got, "the mined comp must not fill in as the tribe "
                               "signal on a board whose tribe HAS a comp")

    def test_recent_acquisitions_do_not_pivot_onto_a_provisional_comp(self):
        b = board(["BG36_115"], tribe=AB)
        got = value.comp_target(b, PROVISIONAL, recent_cards=CORE)
        self.assertNotEqual((got or {}).get("name"), "Aberrations - Deity Feed")

    def test_the_board_overlap_decides_between_two_mined_comps(self):
        other = {"aberrations-other": {
            "name": "Aberrations - Other", "tribe": AB, "core": ["BG36_115"],
            "provisional": True,
            "evidence": {"games": 9, "top4": 9, "floor": 3}}}
        b = board(CORE + ["BG36_115", "BG36_109", "BG36_320"])
        got = value.comp_target(b, dict(PROVISIONAL, **other))
        self.assertEqual(got["name"], "Aberrations - Deity Feed",
                         "board overlap beats a bigger sample for the same tribe")


class TestProvisionalIsLabelled(unittest.TestCase):
    def test_label_carries_the_marker_and_the_sample(self):
        comp = PROVISIONAL["aberrations-deity-feed"]
        self.assertEqual(value.comp_label(comp),
                         "Aberrations - Deity Feed (provisional — 4 of our games)")

    def test_a_published_comp_label_is_just_its_name(self):
        self.assertEqual(value.comp_label(BEASTS["beasts-lobstah"]),
                         "Beasts - Tasty Lobstah")

    def test_the_shopping_list_says_provisional(self):
        comp = PROVISIONAL["aberrations-deity-feed"]
        tc = value.comp_cards(comp, board(CORE))
        self.assertTrue(tc["provisional"])
        self.assertIn("provisional", tc["name"])
        self.assertEqual(tc["evidence"]["games"], 4)
        self.assertTrue(all(c["owned"] for c in tc["core"]))

    def test_progress_rows_carry_the_marker(self):
        b = board(CORE + ["BG36_115", "BG36_109", "BG36_320"])
        rows = value.comp_progress(b, PROVISIONAL)
        self.assertTrue(rows)
        self.assertTrue(rows[0]["provisional"])
        self.assertEqual(rows[0]["evidence"]["top4"], 2)


class TestMinerPromotion(unittest.TestCase):
    ROWS = [(AB, 1, CORE + ["GLUE"]), (AB, 2, CORE), (AB, 5, CORE[:1])]

    def mined(self, min_games=3):
        return comp_miner.mine(self.ROWS, AB, min_games)

    def test_entry_shape_never_invents_a_tier(self):
        entry = comp_miner.provisional_entry(self.mined(), name="Aberrations - X")
        self.assertTrue(entry["provisional"])
        self.assertIsNone(entry["meta_tier"],
                          "nobody published this comp — a tier would be a lie")
        self.assertIsNone(entry["difficulty"])
        self.assertEqual(entry["tribe"], AB)
        self.assertEqual(entry["core"], CORE)
        self.assertEqual(entry["source"], comp_miner.PROVISIONAL_SOURCE)
        self.assertEqual(entry["evidence"]["games"], 3)
        self.assertEqual(entry["evidence"]["floor"], 3)
        self.assertIn("built", entry["evidence"])
        self.assertEqual([c["card"] for c in entry["evidence"]["core"]], CORE)

    def test_promote_creates_a_provisional_entry(self):
        slug, entry, action, reason = comp_miner.promote(
            self.ROWS, {}, AB, name="Aberrations - X", min_games=3)
        self.assertEqual((slug, action, reason),
                         ("aberrations-x", "created", None))
        self.assertTrue(entry["provisional"])

    def test_promote_refuses_when_a_published_comp_covers_the_tribe(self):
        comps = {"a-published": {"name": "Aberrations - Pub", "tribe": AB,
                                 "core": CORE}}
        slug, entry, action, reason = comp_miner.promote(
            self.ROWS, comps, AB, min_games=3)
        self.assertIsNone(entry)
        self.assertEqual(action, "skipped")
        self.assertIn("published comp already covers", reason)

    def test_promote_refuses_below_the_floor(self):
        rows = self.ROWS[:2]
        slug, entry, action, reason = comp_miner.promote(
            rows, {}, AB, min_games=3)
        self.assertIsNone(entry)
        self.assertIn("insufficient evidence (n=2, need 3)", reason)

    def test_promote_refuses_to_overwrite_a_published_slug(self):
        comps = {"aberrations-x": {"name": "Published Thing", "tribe": "Beast"}}
        slug, entry, action, reason = comp_miner.promote(
            self.ROWS, comps, AB, name="Aberrations - X", min_games=3)
        self.assertIsNone(entry)
        self.assertIn("not provisional", reason)

    def test_rerunning_refreshes_evidence_and_keeps_the_human_name(self):
        _, first, _, _ = comp_miner.promote(self.ROWS, {}, AB,
                                            name="Aberrations - X", min_games=3)
        comps = {"aberrations-x": first}
        _, second, action, reason = comp_miner.promote(
            self.ROWS, comps, AB, min_games=3)
        self.assertEqual(action, "updated")
        self.assertIsNone(reason)
        self.assertEqual(second["name"], "Aberrations - X",
                         "a re-run must not rename what a human named")

    def test_tribes_without_comps_ignores_provisional(self):
        self.assertIn(AB, comp_miner.tribes_without_comps(PROVISIONAL))
        self.assertNotIn(AB, comp_miner.tribes_without_comps(
            {"p": {"name": "x", "tribe": AB}}))

    def test_shadowed_provisional_is_reported_not_deleted(self):
        comps = dict(PROVISIONAL)
        comps["aberrations-published"] = {"name": "Aberrations - Pub",
                                          "tribe": AB, "core": CORE}
        self.assertEqual(comp_miner.shadowed_provisional(comps),
                         ["aberrations-deity-feed"])


class TestPruneKeepsProvisional(unittest.TestCase):
    """`scrape_comps.py --prune` must not delete what the source never owned."""

    def test_prune_drops_source_comps_and_keeps_the_mined_one(self):
        comps = {"beasts-old": {"name": "old"}, "aberrations-deity-feed":
                 PROVISIONAL["aberrations-deity-feed"]}
        pruned, kept = scrape_comps.prune_unlisted(comps, keep_slugs=set())
        self.assertEqual(pruned, ["beasts-old"])
        self.assertEqual(kept, ["aberrations-deity-feed"])
        self.assertIn("aberrations-deity-feed", comps)

    def test_prune_still_keeps_what_the_source_lists(self):
        comps = {"beasts-live": {"name": "live"}}
        pruned, kept = scrape_comps.prune_unlisted(comps, {"beasts-live"})
        self.assertEqual((pruned, kept), ([], []))
        self.assertIn("beasts-live", comps)


class TestTheShippedEntry(unittest.TestCase):
    """The real meta/comps.json entry this feature exists for."""

    def test_the_aberration_entry_is_provisional_and_carries_evidence(self):
        comp = meta.comps().get("aberrations-deity-feed")
        self.assertIsNotNone(comp, "the mined Aberration comp is missing")
        self.assertTrue(comp["provisional"])
        self.assertEqual(comp["tribe"], AB)
        self.assertTrue(comp["core"])
        ev = comp["evidence"]
        self.assertGreaterEqual(ev["games"], comp_miner.PROVISIONAL_FLOOR)
        self.assertIsNone(comp["meta_tier"])

    def test_every_core_and_addon_card_exists_in_the_minion_db(self):
        known = {m["id"] for m in meta.minions()}
        comp = meta.comps()["aberrations-deity-feed"]
        missing = [c for c in comp["core"] + comp["addons"] if c not in known]
        self.assertFalse(missing, f"comp names cards the DB cannot resolve: {missing}")

    def test_the_published_comps_are_untouched(self):
        """Promotion must not have disturbed a single scraped entry."""
        comps = meta.comps()
        published = [k for k, c in comps.items() if not c.get("provisional")]
        self.assertEqual(len(published), len(comps) - 1)
        for k in published:
            self.assertIn("meta_tier", comps[k])


if __name__ == "__main__":
    unittest.main()
