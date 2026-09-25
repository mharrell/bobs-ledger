"""The /analysis 304 contract and the art cache headers (Phase 1).

The page polls every 300ms; between pushes the answer must be a
header-only 304 keyed on the ETag update_analysis computed, and card art
(content-addressed by card id) must be cacheable hard while its 404s must
poison nothing."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import coach_ui  # noqa: E402


class TestAnalysisResponse(unittest.TestCase):
    def setUp(self):
        self._saved = (coach_ui._state.payload, coach_ui._state.etag)

    def tearDown(self):
        coach_ui._state.payload, coach_ui._state.etag = self._saved

    def _set(self, obj):
        import json as _json
        import hashlib as _hashlib
        data = _json.dumps(obj).encode()
        coach_ui._state.payload = data
        coach_ui._state.etag = _hashlib.sha1(data).hexdigest()

    def test_first_request_is_200_with_etag(self):
        self._set({"hero": "Reno Jackson"})
        code, headers, body = coach_ui._analysis_response(None)
        self.assertEqual(code, 200)
        self.assertIn("ETag", headers)
        self.assertIn(b"Reno Jackson", body)
        self.assertEqual(headers["Cache-Control"], "no-cache")

    def test_matching_etag_is_a_304(self):
        self._set({"hero": "Reno Jackson"})
        etag = coach_ui._state.etag
        code, headers, body = coach_ui._analysis_response(f'"{etag}"')
        self.assertEqual(code, 304)
        self.assertEqual(body, b"")
        self.assertIn("ETag", headers)

    def test_different_etag_is_a_200(self):
        self._set({"hero": "Reno Jackson"})
        code, _, body = coach_ui._analysis_response('"stale-etag"')
        self.assertEqual(code, 200)
        self.assertTrue(body)

    def test_304_never_served_without_a_push(self):
        coach_ui._state.payload, coach_ui._state.etag = b"{}", None
        code, _, _ = coach_ui._analysis_response('"whatever"')
        self.assertEqual(code, 200)


class TestArtHeaders(unittest.TestCase):
    """The /img 404 must send no-store: art that appears after a patch-day
    retry must not stay poisoned in the browser cache."""

    def test_missing_art_404_is_no_store(self):
        import io
        import time as _time

        cid = "ZZZ_TEST_NOART"
        # Seed the miss list so _can_retry is False and do_GET never
        # attempts the upstream fetch; also stop the 30s rate-limiter from
        # touching the real .art_miss.json during the test.
        with coach_ui._art_lock:
            coach_ui._art_miss[cid] = _time.time()
        saved_writer = coach_ui._miss_last_write[0]
        coach_ui._miss_last_write[0] = _time.time()
        try:
            h = object.__new__(coach_ui._Handler)
            h.path = f"/img/{cid}.png"
            h.command = "GET"
            h.request_version = "HTTP/1.1"
            h.requestline = f"GET {h.path} HTTP/1.1"
            h.client_address = ("127.0.0.1", 0)
            h.headers = {}
            out = io.BytesIO()
            h.wfile = out
            h.do_GET()
            sent = out.getvalue().decode("latin-1")
            self.assertTrue(sent.startswith("HTTP/1.0 404")
                            or sent.startswith("HTTP/1.1 404"))
            self.assertIn("Cache-Control: no-store", sent)
        finally:
            with coach_ui._art_lock:
                coach_ui._art_miss.pop(cid, None)
            coach_ui._miss_last_write[0] = saved_writer


if __name__ == "__main__":
    unittest.main()
