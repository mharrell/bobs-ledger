"""Comp guidance reaches the player.

Until 2026-10-02 the per-comp advice in `meta/comps.json` (`summary`,
`when_to_commit`, `common_enablers`, `how_to_play`) and all 20 mined guide
files in `meta/guides/` were read by NO runtime code: the overlay's comp
panel showed a name, a tier letter and card chips, so a player was told
which cards to hunt and never how the build works.

These tests hold the wiring in place, and hold the honesty of it: a comp
with no written guide must say so, not render an empty box, and the panel
must not label a comp "Unranked" when no tier was ever published for it.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import coach_ui  # noqa: E402


def _comps():
    return coach_ui._comps_by_slug()


def _analysis_for(slug):
    """A minimal analysis whose target comp is `slug`."""
    comp = _comps()[slug]
    return {"board": [], "sell_rank": [], "shop_rank": [], "hand": [],
            "target_comp": comp["name"],
            "target_cards": {"core": [], "addons": []},
            "playable_comps": {slug: comp},
            "comp_progress": [], "banned": [], "out_of_pool": []}


class TestCompGuide(unittest.TestCase):
    def setUp(self):
        self.comps = _comps()
        self.assertGreater(len(self.comps), 20, "comp DB did not load")

    def test_markup_is_stripped_for_display(self):
        """comps.json cites cards as `[[Name||id]]`; the player sees names."""
        slug = next(s for s, c in self.comps.items() if c.get("how_to_play"))
        guide = coach_ui.comp_guide(slug, self.comps[slug])
        self.assertNotIn("[[", guide["how_to_play"])
        self.assertNotIn("||", guide["how_to_play"])

    def test_slug_cannot_escape_the_guides_dir(self):
        for bad in ("../../etc/passwd", "..", "a/b", "UPPER", ""):
            guide = coach_ui.comp_guide(bad, {"name": "x"})
            self.assertIsNone(guide["markdown"], f"{bad!r} read a guide")

    def test_display_text_drops_markdown_syntax(self):
        md = "# Title\n\n> provenance line\n\n## Engine\n\nA **big** claim.\n"
        out = coach_ui._guide_display(md)
        self.assertNotIn("#", out)
        self.assertNotIn("**", out)
        self.assertNotIn("\n>", out)
        self.assertIn("provenance line", out)      # never drop the sourcing
        self.assertIn("A big claim.", out)

    def test_opening_skips_title_and_provenance(self):
        """The target box quotes this as plain text, so it must be a real
        paragraph — not the title, and not the `> ` attribution block."""
        md = "# Aberrations - Thing\n\n> Our advice for a build.\n\n## Engine\n\nThe real pitch.\n"
        opening = coach_ui._guide_opening(md)
        self.assertEqual(opening, "The real pitch.")

    def test_opening_is_bounded(self):
        opening = coach_ui._guide_opening("word " * 300)
        self.assertLessEqual(len(opening), 425)


class TestEveryCompHasAdvice(unittest.TestCase):
    """No comp may render an empty panel."""

    def test_every_comp_offers_something(self):
        empty = []
        for slug, comp in _comps().items():
            guide = coach_ui.comp_guide(slug, comp)
            if not (guide["how_to_play"] or guide["markdown"]
                    or guide["when_to_commit"]):
                empty.append(slug)
        self.assertEqual(empty, [], "comps with nothing to show")

    def test_comps_without_curated_prose_still_get_an_opening(self):
        """Three comps have no `how_to_play` line (including the one the plan
        commits to most). Their mined guide carries the explanation, so the
        panel quotes that rather than showing nothing."""
        missing = [s for s, c in _comps().items() if not c.get("how_to_play")]
        self.assertTrue(missing, "expected the DB to still have this gap to cover")
        for slug in missing:
            guide = coach_ui.comp_guide(slug, _comps()[slug])
            self.assertFalse(guide["curated"])
            if guide["markdown"]:
                self.assertTrue(guide["opening"],
                                f"{slug} has a guide but no opening paragraph")


class TestPayloadCarriesGuidance(unittest.TestCase):
    def test_comp_rows_carry_the_short_guidance(self):
        a = coach_ui.render_json(_analysis_for("elementals-unbound-tempest"))
        row = next(r for r in a["comps"] if r["slug"] == "elementals-unbound-tempest")
        self.assertEqual(row["difficulty"], "Easy")
        self.assertTrue(row["summary"])
        self.assertTrue(row["when_to_commit"])
        self.assertTrue(row["enablers"])
        self.assertTrue(row["has_guide"])

    def test_missing_tier_is_flagged_not_faked(self):
        """Aberrations - Deity Feed was promoted from our own mined corpus and
        has no published tier. The panel must be able to label that honestly
        instead of letting a null read as "Unranked"."""
        slug = "aberrations-deity-feed"
        a = coach_ui.render_json(_analysis_for(slug))
        row = next(r for r in a["comps"] if r["slug"] == slug)
        self.assertIsNone(row["meta_tier"])
        self.assertTrue(row["tier_missing"])
        self.assertFalse(row["provisional"])

    def test_target_comp_guide_rides_the_payload(self):
        a = coach_ui.render_json(_analysis_for("aberrations-deity-feed"))
        tg = a["target_comp_guide"]
        self.assertEqual(tg["slug"], "aberrations-deity-feed")
        self.assertTrue(tg["when_to_commit"])
        self.assertTrue(tg["how_to_play"], "no guidance for the committed comp")

    def test_no_target_comp_is_none_not_an_empty_box(self):
        analysis = _analysis_for("aberrations-deity-feed")
        analysis["target_comp"] = None
        a = coach_ui.render_json(analysis)
        self.assertIsNone(a["target_comp_guide"])

    def test_the_long_prose_is_not_in_the_polled_payload(self):
        """A guide is ~2 KB x 35 comps. It is fetched on expand, so the
        payload must stay lean: this fails if someone starts pushing prose."""
        a = coach_ui.render_json(_analysis_for("elementals-unbound-tempest"))
        blob = json.dumps(a)
        self.assertNotIn("## ", blob)
        for row in a["comps"]:
            self.assertNotIn("how_to_play", row)
            self.assertNotIn("markdown", row)
            self.assertLess(len(json.dumps(row)), 2000)


class TestTrinketPickGuides(unittest.TestCase):
    """The 110 curated trinket guides reach the pick panel.

    Same class of gap as the comp guides: the advice shipped in
    meta/trinkets.json and no code rendered it — on the one screen where a
    wrong pick costs the whole game, and where the panel already shows the
    pick% and average placement.
    """

    def _guide_names(self):
        return [t["name"] for t in coach_ui.meta.trinkets() if t.get("guide")]

    def test_offered_trinket_guides_ride_the_pick_payload(self):
        names = self._guide_names()[:2]
        self.assertEqual(len(names), 2, "expected curated trinket guides")
        ids = {t["name"]: t["id"] for t in coach_ui.meta.trinkets()}
        ranked = [[n, ids.get(n, "BG30_MagicItem_301"), 3.0, "pick 30%"]
                  for n in names]
        a = coach_ui.render_json({
            "board": [], "sell_rank": [], "shop_rank": [], "hand": [],
            "choice": {"kind": "trinket", "source": "Lesser Trinket",
                       "ranked": ranked}})
        guides = a["choice"]["guides"]
        self.assertEqual(set(guides), set(names))
        for n in names:
            self.assertTrue(guides[n])
            self.assertNotIn("[[", guides[n], "card markup not stripped")

    def test_a_hero_pick_carries_no_guide_block(self):
        a = coach_ui.render_json({
            "board": [], "sell_rank": [], "shop_rank": [], "hand": [],
            "choice": {"kind": "hero", "source": "Choose One",
                       "ranked": [["Reno Jackson", "BG20_HERO_201", 5.0, "pick 50%"]]}})
        self.assertNotIn("guides", a["choice"])

    def test_an_offered_trinket_without_a_guide_is_simply_absent(self):
        """Never a placeholder: a trinket with no guide shows no guide.

        Keyed by NAME (the DB is name-keyed, and variant rows can share a
        name), so "has no guide" means no row with that name has one.
        """
        guided = {t["name"] for t in coach_ui.meta.trinkets() if t.get("guide")}
        no_guide = [t["name"] for t in coach_ui.meta.trinkets()
                    if t.get("name") and t["name"] not in guided]
        self.assertTrue(no_guide, "expected some trinkets to have no guide")
        a = coach_ui.render_json({
            "board": [], "sell_rank": [], "shop_rank": [], "hand": [],
            "choice": {"kind": "trinket", "source": "Lesser Trinket",
                       "ranked": [[no_guide[0], "BG30_MagicItem_999", 1.0, ""]]}})
        self.assertNotIn("guides", a.get("choice", {}))


class TestStaleAdviceMarker(unittest.TestCase):
    """A frozen overlay must not look live.

    The page only re-renders when the payload CHANGES, and a wedged live.py
    leaves the server answering 304 forever — so the last advice stayed on
    screen indistinguishable from live advice, and the player acts on it
    (2026-10-02). The payload now carries when it was produced, and a
    separate ticker (not render()) ages it on screen.
    """

    def test_payload_carries_the_generation_time(self):
        import time
        a = coach_ui.render_json({"board": [], "sell_rank": [], "shop_rank": [],
                                  "hand": []})
        self.assertIsInstance(a["generated"], float)
        self.assertLess(abs(a["generated"] - time.time()), 60)

    def test_the_page_has_a_freshness_node_and_ticker(self):
        html = coach_ui._HTML
        self.assertIn('id="freshness"', html)
        # The ticker must be independent of render(): poll() stops calling
        # render() once the payload stops changing, which is exactly the
        # failure this reports.
        self.assertIn("setInterval(tickFreshness", html)
        self.assertIn("function tickFreshness", html)
        self.assertIn("STALE_AFTER", html)


if __name__ == "__main__":
    unittest.main()
