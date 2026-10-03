"""Fetching session reports back out of the collector.

The collector stores each report with no client identifier — reports are not
linked to each other, to an install, or to a person — so this tool is the only
way to get at them, and it has to be safe to run repeatedly as sessions
arrive.
"""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # app/
sys.path.insert(0, HERE)          # the code dir, wherever this runs from

import fetch_sessions  # noqa: E402

KEYS = ["sessions/2026-10-03/aaaa1111.json.gz",
        "sessions/2026-10-03/bbbb2222.json.gz"]


def fake_urlopen(payloads, seen=None):
    """A urlopen that answers the listing and the two report bodies."""
    def _open(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if seen is not None:
            seen.append(url)
        if url.endswith("/sessions"):
            body = json.dumps({"keys": KEYS, "truncated": False}).encode()
        else:
            for k in KEYS:
                if url.endswith(k):
                    body = b"GZ-" + k.encode()
                    break
            else:
                raise AssertionError(f"unexpected url {url}")
        resp = io.BytesIO(body)
        resp.__enter__ = lambda *a: resp
        resp.__exit__ = lambda *a: False
        return resp
    return _open


class TestListing(unittest.TestCase):
    def test_it_lists_what_is_stored(self):
        with mock.patch.object(fetch_sessions.urllib.request, "urlopen",
                               fake_urlopen(KEYS)):
            self.assertEqual(fetch_sessions.list_keys("http://x", "k"), KEYS)

    def test_a_truncated_listing_says_so(self):
        def _open(req, timeout=None):
            resp = io.BytesIO(json.dumps({"keys": ["sessions/a/b.json.gz"],
                                          "truncated": True}).encode())
            resp.__enter__ = lambda *a: resp
            resp.__exit__ = lambda *a: False
            return resp
        with mock.patch.object(fetch_sessions.urllib.request, "urlopen", _open):
            with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                fetch_sessions.list_keys("http://x", "k")
        self.assertIn("1000-key page limit", out.getvalue())


class TestFetching(unittest.TestCase):
    def test_reports_land_under_their_date(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(fetch_sessions.urllib.request, "urlopen",
                                   fake_urlopen(KEYS)):
                got, skipped = fetch_sessions.fetch("http://x", "k", td)
            self.assertEqual((got, skipped), (2, 0))
            self.assertTrue(os.path.exists(
                os.path.join(td, "2026-10-03", "aaaa1111.json.gz")))
            with open(os.path.join(td, "2026-10-03", "bbbb2222.json.gz"),
                      "rb") as f:
                self.assertEqual(f.read(), b"GZ-sessions/2026-10-03/bbbb2222.json.gz")

    def test_running_it_again_downloads_nothing(self):
        """Sessions keep arriving, so this gets run over and over."""
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(fetch_sessions.urllib.request, "urlopen",
                                   fake_urlopen(KEYS)):
                fetch_sessions.fetch("http://x", "k", td)
            seen = []
            with mock.patch.object(fetch_sessions.urllib.request, "urlopen",
                                   fake_urlopen(KEYS, seen)):
                got, skipped = fetch_sessions.fetch("http://x", "k", td)
            self.assertEqual((got, skipped), (0, 2))
            self.assertEqual([u for u in seen if "json.gz" in u], [])

    def test_force_redownloads(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(fetch_sessions.urllib.request, "urlopen",
                                   fake_urlopen(KEYS)):
                fetch_sessions.fetch("http://x", "k", td)
                got, skipped = fetch_sessions.fetch("http://x", "k", td,
                                                    force=True)
            self.assertEqual((got, skipped), (2, 0))

    def test_the_key_is_sent(self):
        """Reading is keyed; a request without it gets a 403 and no data."""
        seen = {}

        def _open(req, timeout=None):
            seen["header"] = req.get_header("X-telemetry-key")
            resp = io.BytesIO(json.dumps({"keys": [], "truncated": False}).encode())
            resp.__enter__ = lambda *a: resp
            resp.__exit__ = lambda *a: False
            return resp

        with mock.patch.object(fetch_sessions.urllib.request, "urlopen", _open):
            fetch_sessions.list_keys("http://x", "sekrit")
        self.assertEqual(seen["header"], "sekrit")

    def test_a_failing_report_does_not_stop_the_rest(self):
        def _open(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if url.endswith("/sessions"):
                body = json.dumps({"keys": KEYS, "truncated": False}).encode()
            elif url.endswith(KEYS[0]):
                import urllib.error
                raise urllib.error.HTTPError(url, 500, "boom", None, None)
            else:
                body = b"GZ-second"
            resp = io.BytesIO(body)
            resp.__enter__ = lambda *a: resp
            resp.__exit__ = lambda *a: False
            return resp

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(fetch_sessions.urllib.request, "urlopen", _open):
                got, _skipped = fetch_sessions.fetch("http://x", "k", td)
            self.assertEqual(got, 1)
            self.assertTrue(os.path.exists(
                os.path.join(td, "2026-10-03", "bbbb2222.json.gz")))


class TestNoKey(unittest.TestCase):
    def test_it_refuses_without_a_key_and_says_why(self):
        with mock.patch("sys.argv", ["fetch_sessions.py"]):
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("sys.stdout", new_callable=io.StringIO) as out:
                    rc = fetch_sessions.main()
        self.assertEqual(rc, 1)
        self.assertIn("HEARTH_TELEMETRY_KEY", out.getvalue())


if __name__ == "__main__":
    unittest.main()
