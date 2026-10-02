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


class TestWelcomeAndClear(unittest.TestCase):
    """The deliberate empty state: fresh boot, a new game's CREATE_GAME,
    and the page's Clear button all serve the welcome — never the previous
    game's panel dressed up as live advice."""

    def setUp(self):
        self._saved = (coach_ui._state.payload, coach_ui._state.etag,
                       coach_ui._state.analysis,
                       coach_ui._state.manual_bans)

    def tearDown(self):
        (coach_ui._state.payload, coach_ui._state.etag,
         coach_ui._state.analysis,
         coach_ui._state.manual_bans) = self._saved

    def test_clear_serves_the_welcome(self):
        import json
        coach_ui.clear_analysis()
        code, _h, body = coach_ui._analysis_response(None)
        self.assertEqual(code, 200)
        a = json.loads(body)
        self.assertTrue(a["welcome"])
        self.assertEqual(a["product"], "Bob's Ledger")

    def test_clear_button_keeps_manual_bans(self):
        coach_ui.store_manual_bans(["Beast"])
        coach_ui.clear_analysis(keep_bans=True)
        self.assertEqual(coach_ui.latest_manual_bans(), ["Beast"])

    def test_new_game_clear_wipes_manual_bans(self):
        coach_ui.store_manual_bans(["Beast"])
        coach_ui.clear_analysis()
        self.assertIsNone(coach_ui.latest_manual_bans())


class TestServerPortConflict(unittest.TestCase):
    """A port another overlay already answers on must not be hijacked.

    On Windows a second socket CAN bind a port a first process is listening
    on, so start_server() used to return a healthy-looking server that
    received no traffic at all — every request went to the older process and
    the new overlay stayed frozen with no error (2026-10-02: an audit's
    leftover live.py held 8747 and a fresh test server silently served
    nothing).
    """

    def test_port_in_use_detects_a_listener(self):
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            port = s.getsockname()[1]
            self.assertTrue(coach_ui._port_in_use(port))
        self.assertFalse(coach_ui._port_in_use(port))

    def test_start_server_steps_over_a_busy_port(self):
        import socket
        import urllib.request
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            busy = s.getsockname()[1]
            srv = coach_ui.start_server(busy)
            try:
                self.assertNotEqual(srv.server_address[1], busy,
                                    "bound the port another socket holds")
                # and it really serves, which the hijacked bind did not
                url = f"http://127.0.0.1:{srv.server_address[1]}/artmiss"
                with urllib.request.urlopen(url, timeout=10) as r:
                    self.assertEqual(r.status, 200)
                    self.assertIn(b"misses", r.read())
            finally:
                srv.shutdown()
                srv.server_close()

    def test_ephemeral_port_is_left_alone(self):
        srv = coach_ui.start_server(0)
        try:
            self.assertGreater(srv.server_address[1], 0)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
