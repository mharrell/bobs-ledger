"""`scrape_comps.tier_changes` / `format_tier_changes` — asking the SITE what moved.

Why this exists: the comps tier list moves between patches and nothing here
recorded WHEN. `--diff` can only report a move by comparing the live page with
our own copy, which cannot tell "the tier list changed" apart from "we never
took the change" — and says nothing at all when our copy is the thing in
doubt. hsreplay publishes its own account of the change on the index record
(`comp_tier_last_updated`, `comp_previous_tier`, `comp_tier_recently_updated`,
`comp_guide_recently_updated`), and these tests hold the reading of it.

The 2026-10-04 refresh is the worked example: four comps moved in two days
(mechs-apm-magnetic A->S, murlocs-keyword S->A, mechs-magnetics-spells B->A,
aberrations-deathrattle-spells A->B) and our copy was behind on exactly those
four — which is what the site's own metadata says, with no diff needed.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from scrape_comps import format_tier_changes, tier_changes  # noqa: E402


def record(slug, tier, previous=None, updated="", recently=None,
           guide_updated=None):
    """One index record, in the shape the site actually serves."""
    rec = {"comp_slug": slug, "comp_name": slug.replace("-", " ").title(),
           "comp_tier": tier, "comp_tier_last_updated": updated}
    if previous is not None:
        rec["comp_previous_tier"] = previous
    if recently is not None:
        rec["comp_tier_recently_updated"] = recently
    if guide_updated is not None:
        rec["comp_guide_recently_updated"] = guide_updated
    return rec


RECORDS = [
    record("mechs-apm-magnetic", 1, previous=2, recently=True,
           updated="2026-10-04T05:54:15.193Z"),
    record("murlocs-keyword", 2, previous=1, recently=True,
           updated="2026-10-03T05:39:18.136Z"),
    record("beasts-summons", 3, previous=2, recently=False,
           updated="2026-10-01T14:38:23.428Z"),
]
DB = {"mechs-apm-magnetic": {"meta_tier": "A"},
      "murlocs-keyword": {"meta_tier": "S"},
      "beasts-summons": {"meta_tier": "B"}}


class TestTierChanges(unittest.TestCase):
    def test_rows_are_newest_first(self):
        rows = tier_changes(RECORDS, DB)
        self.assertEqual([r["slug"] for r in rows],
                         ["mechs-apm-magnetic", "murlocs-keyword", "beasts-summons"])

    def test_tier_numbers_become_the_letters_the_db_uses(self):
        row = tier_changes(RECORDS, DB)[0]
        self.assertEqual((row["previous_tier"], row["tier"]), ("A", "S"))

    def test_the_sites_own_flag_is_carried(self):
        rows = {r["slug"]: r for r in tier_changes(RECORDS, DB)}
        self.assertTrue(rows["mechs-apm-magnetic"]["recently_updated"])
        self.assertFalse(rows["beasts-summons"]["recently_updated"])
        self.assertEqual(rows["mechs-apm-magnetic"]["tier_last_updated"],
                         "2026-10-04T05:54:15.193Z")

    def test_our_stored_tier_is_attached_for_comparison(self):
        rows = {r["slug"]: r for r in tier_changes(RECORDS, DB)}
        self.assertEqual(rows["murlocs-keyword"]["db_tier"], "S")

    def test_it_works_with_no_local_copy_at_all(self):
        """The whole point: the answer is the site's, so a missing or
        unreadable comps.json must not stop the question being asked."""
        rows = tier_changes(RECORDS, None)
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["db_tier"] is None for r in rows))

    def test_records_without_a_slug_are_skipped(self):
        rows = tier_changes([{"comp_name": "no slug"}, None, "junk"] + RECORDS)
        self.assertEqual(len(rows), 3)

    def test_empty_input_is_not_an_error(self):
        self.assertEqual(tier_changes([], DB), [])


class TestFormatTierChanges(unittest.TestCase):
    def test_it_names_the_moves_and_what_we_are_behind_on(self):
        text = "\n".join(format_tier_changes(tier_changes(RECORDS, DB)))
        self.assertIn("3 comps ranked", text)
        self.assertIn("2026-10-04T05:54:15.193Z", text)   # the newest change
        self.assertIn("A ->", text)                        # previous -> now
        self.assertIn("our DB still says A", text)         # behind on the move
        # beasts-summons (B) is already in step AND not flagged, so the report
        # names 2 of 3 — an unmoved comp in step is not news, not noise.
        self.assertIn("behind on 2 of 3", text)
        self.assertNotIn("beasts-summons", text)

    def test_a_copy_in_step_says_so_instead_of_listing_nothing(self):
        # what comps.json looks like AFTER the 2026-10-04 refresh lands
        in_step = {"mechs-apm-magnetic": {"meta_tier": "S"},
                   "murlocs-keyword": {"meta_tier": "A"},
                   "beasts-summons": {"meta_tier": "B"}}
        text = "\n".join(format_tier_changes(tier_changes(RECORDS, in_step)))
        self.assertIn("matches the live tier list on all 3", text)
        self.assertNotIn("our DB still says", text)

    def test_no_records_says_so(self):
        self.assertIn("nothing to report", format_tier_changes([])[0])

    def test_a_comp_we_do_not_hold_is_missing_not_matching(self):
        """2026-10-08: three comps entered the tier list and read as
        "matching" — a missing comp's None tier passed the staleness filter.
        Missing is its own report, and the matches line must not claim a
        completeness the copy does not have."""
        rows = tier_changes(RECORDS + [record("undead-eternal-knight", 3,
                                              recently=True,
                                              updated="2026-10-08T04:41:"
                                                      "28.657Z")], DB)
        text = "\n".join(format_tier_changes(rows))
        self.assertIn("MISSING 1 comp(s)", text)
        self.assertIn("undead-eternal-knight", text)
        self.assertNotIn("matches the live tier list", text)

    def test_a_held_comp_with_no_tier_is_still_held(self):
        """A provisional entry in our copy (meta_tier None) is HELD — it must
        not be reported missing just because the tier is unset."""
        db = dict(DB)
        db["beasts-summons"] = {"meta_tier": None}
        rows = tier_changes(RECORDS, db)
        self.assertTrue([r for r in rows if r["slug"] == "beasts-summons"]
                        [0]["in_db"])
        text = "\n".join(format_tier_changes(rows))
        self.assertNotIn("MISSING", text)
        # tier None vs live B: behind, the honest reading
        self.assertIn("ours None -> live B", text)


class TestTheChangesFlagNeedsNothingLocal(unittest.TestCase):
    """`--changes` is a question about the SITE, so it must be answerable when
    the local copy is exactly what is in doubt: it returns before opening
    comps.json and before the ~10MB card-list download."""

    def test_it_returns_before_the_card_list_and_the_db_are_touched(self):
        import scrape_comps
        seen = []
        real_report = scrape_comps.report_changes
        real_load = scrape_comps.load_dbfid_map

        def fake_report(as_json=False):
            seen.append(as_json)
            return 0

        def boom(*_a, **_k):
            raise AssertionError("--changes downloaded the card list")

        scrape_comps.report_changes = fake_report
        scrape_comps.load_dbfid_map = boom
        argv = sys.argv
        sys.argv = ["scrape_comps.py", "--changes", "--json"]
        try:
            rc = scrape_comps.main()
        finally:
            sys.argv = argv
            scrape_comps.report_changes = real_report
            scrape_comps.load_dbfid_map = real_load
        self.assertEqual(rc, 0)
        self.assertEqual(seen, [True], "--changes did not reach the reporter")

    def test_changes_alone_is_a_complete_command(self):
        """Without --changes this argv is an argparse error, so the flag has to
        be accepted as a work list of its own."""
        import scrape_comps
        real_report = scrape_comps.report_changes
        scrape_comps.report_changes = lambda as_json=False: 0
        argv = sys.argv
        sys.argv = ["scrape_comps.py", "--changes"]
        try:
            self.assertEqual(scrape_comps.main(), 0)
        finally:
            sys.argv = argv
            scrape_comps.report_changes = real_report


if __name__ == "__main__":
    unittest.main()
