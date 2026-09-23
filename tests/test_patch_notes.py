"""patch_notes.py contract tests.

Two halves:

1. Matching/apply must never silently edit the *last* homonymous entity.
   meta/dark_gifts.json has 4 duplicate names (one per tier). The old name-keyed
   dict silently aliased them; a "Battle Scars" change edited the +2/+2 entry
   whenever the +3/+3 entry was last. Dry-run behavior now: unique name ->
   applied; duplicate name -> ambiguous (unless the change carries a tier).

2. Fetch + section extraction regressions (2026-09-05 commit 6264486 dropped
   `import requests` while fetch_text/discover_latest still call it, and
   html_to_text collapsed h2 and h3 into the same "## " prefix so
   extract_bg_section truncated any Battlegrounds section at its first
   sub-heading — the 36.6 BG section extracted to 92 characters).
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests as requests_module

import patch_notes
from patch_notes import apply_changes, extract_bg_section, html_to_text


class TestDuplicateNames(unittest.TestCase):
    def test_duplicate_name_is_ambiguous_not_wrongly_applied(self):
        report = apply_changes(
            [{"entity_type": "dark_gift", "name": "Battle Scars",
              "field": "text", "new": "+4/+4"}],
            do_apply=False)
        self.assertEqual(report[0]["status"], "ambiguous", report)
        self.assertIn("2 entities", report[0]["reason"])

    def test_ambiguous_reports_distinguishing_descriptions(self):
        """Dark gifts have no tier field; the report must show the descriptions
        that distinguish the duplicates so a human can resolve manually."""
        report = apply_changes(
            [{"entity_type": "dark_gift", "name": "Battle Scars",
              "field": "text", "new": "+4/+4", "tier": 2}],
            do_apply=False)
        self.assertEqual(report[0]["status"], "ambiguous")
        self.assertIn("+3/+3", report[0]["reason"])
        self.assertIn("+2/+2", report[0]["reason"])

    def test_unique_name_still_applies(self):
        report = apply_changes(
            [{"entity_type": "dark_gift", "name": "Spectral Sight",
              "field": "text", "new": "Replaced text"}],
            do_apply=False)
        status = report[0]["status"]
        self.assertIn(status, ("applied", "unmatched"), report)


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class TestFetchUsesRequests(unittest.TestCase):
    """fetch_text/discover_latest call requests.get — it must be importable.

    Regression: commit 6264486 swapped `import requests` for `import coach_llm`
    and left both call sites, so every fetch died with
    `NameError: name 'requests' is not defined`.
    """

    def test_module_exposes_the_requests_module(self):
        self.assertTrue(
            hasattr(patch_notes, "requests"),
            "patch_notes must import requests: fetch_text/discover_latest call "
            "requests.get")
        self.assertIs(patch_notes.requests, requests_module)

    def test_fetch_text_gets_through_requests(self):
        calls = {}

        def fake_get(url, **kwargs):
            calls["url"] = url
            calls["kwargs"] = kwargs
            return _FakeResponse("<h2>Battlegrounds</h2><p>Body text</p>")

        with mock.patch.object(patch_notes.requests, "get", fake_get):
            text = patch_notes.fetch_text("https://example.test/patch")

        self.assertEqual(calls["url"], "https://example.test/patch")
        self.assertIn("timeout", calls["kwargs"])
        self.assertIn("Battlegrounds", text)
        self.assertIn("Body text", text)

    def test_discover_latest_gets_through_requests(self):
        body = (
            'var stickyBlogList = ['
            '{"id": 1, "title": "36.6 Patch Notes", "slug": "366-patch-notes"},'
            '{"id": 2, "title": "Some Other News", "slug": "other"}];'
        )
        seen = {}

        def fake_get(url, **kwargs):
            seen["url"] = url
            return _FakeResponse(body)

        with mock.patch.object(patch_notes.requests, "get", fake_get):
            url, article = patch_notes.discover_latest()

        self.assertIn("hearthstone.blizzard.com", seen["url"])
        self.assertEqual(article["title"], "36.6 Patch Notes")
        self.assertEqual(
            url,
            "https://hearthstone.blizzard.com/en-us/news/1/366-patch-notes")


# A Battlegrounds section shaped like the real 36.6 notes: an intro paragraph
# followed by h3 sub-headings, with an unrelated h2 after it.
_BG_HTML = """<h2>Battlegrounds Updates</h2>
<p>Intro paragraph about the new season.</p>
<h3>New Minion Type: Aberrations</h3>
<p>Deity minions appear in every lobby.</p>
<h3>Minion Updates</h3>
<ul><li>Some Minion has been removed from the pool.</li></ul>
<h2>Bug Fixes</h2>
<p>Unrelated bug fix text.</p>
"""


class TestBgSectionExtraction(unittest.TestCase):
    """The Battlegrounds section must survive its own sub-headings.

    Regression: html_to_text turned BOTH <h2> and <h3> into "## ", and
    extract_bg_section stopped at the next "## ", so a BG section with
    sub-headings collapsed to its intro paragraph.
    """

    def test_h2_and_h3_keep_distinct_levels(self):
        text = html_to_text(_BG_HTML)
        self.assertIn("## Battlegrounds Updates", text)
        self.assertIn("### New Minion Type: Aberrations", text)
        self.assertIn("### Minion Updates", text)

    def test_h3_subheadings_do_not_truncate_the_section(self):
        bg = extract_bg_section(html_to_text(_BG_HTML))
        self.assertIn("Intro paragraph about the new season.", bg)
        self.assertIn("New Minion Type: Aberrations", bg)
        self.assertIn("Deity minions appear in every lobby.", bg)
        self.assertIn("Minion Updates", bg)
        self.assertIn("Some Minion has been removed from the pool.", bg)

    def test_next_h2_still_ends_the_section(self):
        bg = extract_bg_section(html_to_text(_BG_HTML))
        self.assertNotIn("Unrelated bug fix text.", bg)

    def test_section_without_subheadings_still_works(self):
        text = html_to_text(
            "<h2>Battlegrounds Updates</h2><p>Only prose.</p>"
            "<h2>Bug Fixes</h2><p>Other.</p>")
        bg = extract_bg_section(text)
        self.assertIn("Only prose.", bg)
        self.assertNotIn("Other.", bg)

    def test_h3_battlegrounds_heading_is_used_when_no_h2_exists(self):
        bg = extract_bg_section(
            "### Battlegrounds\n\nonly content\n\n### Next Thing\n\nother")
        self.assertEqual(bg, "only content")

    def test_missing_section_returns_none(self):
        self.assertIsNone(
            extract_bg_section(html_to_text("<h2>Bug Fixes</h2><p>x</p>")))


if __name__ == "__main__":
    unittest.main()