"""The /analysis 304 contract and the art cache headers (Phase 1).

The page polls every 300ms; between pushes the answer must be a
header-only 304 keyed on the ETag update_analysis computed, and card art
(content-addressed by card id) must be cacheable hard while its 404s must
poison nothing."""
import hashlib
import os
import sys
import tempfile
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


class TestArtEndpointSources(unittest.TestCase):
    """Each endpoint must fetch its OWN kind of art, from its OWN source.

    This wiring WAS the distributed bug (2026-10-04): both routes shared one
    URL and one cache kind, and that URL 404s every current-patch Battlegrounds
    card, so a fresh install drew placeholders across most of the board while
    the maintainer's checkout (filled from the game client) looked fine. The
    fetch is patched out, so these assert what each route ASKS FOR.
    """

    def _drive(self, path):
        import io
        from unittest import mock
        h = object.__new__(coach_ui._Handler)
        h.path = path
        h.command = "GET"
        h.request_version = "HTTP/1.1"
        h.requestline = f"GET {path} HTTP/1.1"
        h.client_address = ("127.0.0.1", 0)
        h.headers = {}
        h.wfile = io.BytesIO()
        with mock.patch.object(coach_ui, "_fetch_render",
                               return_value=False) as fetch:
            h.do_GET()
        self.assertEqual(fetch.call_count, 1, f"{path} did not try to fetch")
        return fetch.call_args

    def test_the_tile_route_fetches_a_portrait(self):
        args, kwargs = self._drive("/img/ZZZ_TEST_WIRE.png")
        self.assertEqual(args, ("ZZZ_TEST_WIRE",))
        self.assertFalse(kwargs.get("card"),
                         "the 56x56 tile must get the square portrait source")
        self.assertIsNone(kwargs.get("dest_dir"),
                          "portraits live in img_cache root")

    def test_the_tooltip_route_fetches_a_card_render(self):
        args, kwargs = self._drive("/card/ZZZ_TEST_WIRE.png")
        self.assertEqual(args, ("ZZZ_TEST_WIRE",))
        self.assertTrue(kwargs.get("card"))
        self.assertEqual(kwargs.get("dest_dir"), coach_ui.CARD_DIR)
        self.assertEqual(kwargs.get("urls"), coach_ui.CARD_URLS)

    def test_the_tooltip_route_strips_the_golden_suffix(self):
        args, _ = self._drive("/card/ZZZ_TEST_WIRE_G.png")
        self.assertEqual(args, ("ZZZ_TEST_WIRE",),
                         "golden ids resolve to the base render")


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


class TestWelcomeCard(unittest.TestCase):
    """The first-run fix has to be ON the welcome card.

    live.py's console message has always told the player "the Coach UI
    welcome card shows the same steps" — the card pointed at the README on
    disk instead, which is the wrong place when the reason the player opened
    the overlay is that nothing was happening (2026-10-02).
    """

    def test_the_card_carries_the_log_config_block(self):
        import json as _json
        payload = _json.loads(coach_ui.welcome_payload())
        self.assertIn("log.config", payload["hint"])
        for line in ("[Power]", "LogLevel=1", "FilePrinting=true"):
            self.assertIn(line, payload["steps"])

    def test_the_page_renders_that_block(self):
        # Both the element and its rule have to exist, or the multi-line
        # block collapses into one unreadable line.
        self.assertIn("'w-steps'", coach_ui._HTML)
        self.assertIn(".welcome .w-steps", coach_ui._HTML)
        self.assertIn("white-space:pre-wrap", coach_ui._HTML)


class TestConsentOnTheWelcomeCard(unittest.TestCase):
    """The card used to promise "Nothing leaves your machine unless you share
    a session" while offering no way to share one and sending nothing. The
    sentence is now built from the consent state, the question is on the card,
    and the answer is one click either way."""

    def setUp(self):
        import share
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_paths = (share.CONSENT_PATH, share.REPORTS_DIR,
                             share.SENT_PATH)
        share.CONSENT_PATH = os.path.join(self._tmp.name, ".share_consent.json")
        share.REPORTS_DIR = os.path.join(self._tmp.name, "session_reports")
        share.SENT_PATH = os.path.join(share.REPORTS_DIR, ".sent.json")
        self._saved_state = (coach_ui._state.payload, coach_ui._state.etag)

    def tearDown(self):
        import share
        (share.CONSENT_PATH, share.REPORTS_DIR,
         share.SENT_PATH) = self._saved_paths
        (coach_ui._state.payload, coach_ui._state.etag) = self._saved_state
        self._tmp.cleanup()

    def _payload(self):
        import json as _json
        return _json.loads(coach_ui.welcome_payload())

    def _post(self, body, raw=False):
        import json as _json
        import urllib.error
        import urllib.request
        srv = coach_ui.start_server(0)
        try:
            url = f"http://127.0.0.1:{srv.server_address[1]}/share"
            data = body if raw else _json.dumps(body).encode()
            req = urllib.request.Request(
                url, data=data, method="POST",
                headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as e:
                return e.code, e.read()
        finally:
            srv.shutdown()
            srv.server_close()

    def test_an_unasked_player_is_asked_and_nothing_has_been_sent(self):
        p = self._payload()
        self.assertTrue(p["share"]["ask"])
        self.assertEqual(p["share"]["status"], "undecided")
        self.assertIn("Nothing has been sent", p["privacy"])
        self.assertIn(p["share"]["question"], p["share"]["question"])

    def test_the_old_unconditional_promise_is_gone(self):
        """It was false the moment reports could be sent."""
        self.assertNotIn("unless you share a session", self._payload()["privacy"])

    def test_no_sends_nothing_and_is_remembered(self):
        status, body = self._post({"share": False})
        self.assertEqual(status, 200)
        self.assertIn(b'"status": "off"', body.replace(b" ", b" "))
        p = self._payload()
        self.assertFalse(p["share"]["ask"])
        self.assertIn("Not sharing", p["privacy"])

    def test_yes_flips_the_card_to_the_sharing_sentence(self):
        status, _body = self._post({"share": True})
        self.assertEqual(status, 200)
        p = self._payload()
        self.assertEqual(p["share"]["status"], "on")
        self.assertIn("Sharing one small summary per game", p["privacy"])
        self.assertIn("no names", p["privacy"])

    def test_the_card_is_not_served_stale_after_the_answer(self):
        """The page polls with If-None-Match at 300ms: if the payload and its
        ETag were not rebuilt, the player would click and watch a 304 leave
        the old sentence on screen."""
        coach_ui._state.payload = coach_ui.welcome_payload()
        coach_ui._state.etag = hashlib.sha1(coach_ui._state.payload).hexdigest()
        before = coach_ui._state.etag
        self._post({"share": True})
        code, _headers, _body = coach_ui._analysis_response(f'"{before}"')
        self.assertEqual(code, 200, "old ETag still matched -> stale card")

    def test_a_non_boolean_is_refused(self):
        status, body = self._post({"share": "yes"})
        self.assertEqual(status, 400)
        self.assertIn(b"true or false", body)

    def test_bad_json_is_refused(self):
        status, _body = self._post(b"{not json", raw=True)
        self.assertEqual(status, 400)

    def test_the_page_draws_the_row(self):
        for needle in ("shareRow", "'w-share'", ".welcome .w-share-btn",
                       "/share"):
            self.assertIn(needle, coach_ui._HTML)


class TestForeignCallers(unittest.TestCase):
    """Binding loopback keeps other MACHINES out; it does not keep other PAGES
    out, and neither Host nor Origin used to be checked.

    Measured before this guard existed: a POST carrying
    `Origin: https://evil.example` and `Content-Type: text/plain` flipped the
    sharing consent from undecided to ON, and `GET /analysis` with
    `Host: evil.example` returned the live analysis. A page the player merely
    visited could therefore opt them into uploading their games, and read the
    overlay — which during play carries the opponent's handle (2026-10-03).
    """

    def setUp(self):
        import share
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = (share.CONSENT_PATH, share.REPORTS_DIR, share.SENT_PATH)
        share.CONSENT_PATH = os.path.join(self._tmp.name, ".share_consent.json")
        share.REPORTS_DIR = os.path.join(self._tmp.name, "session_reports")
        share.SENT_PATH = os.path.join(share.REPORTS_DIR, ".sent.json")

    def tearDown(self):
        import share
        (share.CONSENT_PATH, share.REPORTS_DIR,
         share.SENT_PATH) = self._saved
        self._tmp.cleanup()

    def _call(self, path, method="GET", body=None, headers=None, host=None):
        """One retry on a fresh socket.

        Windows lets a second socket bind a port another socket is LISTENING
        on — the SO_REUSEADDR quirk start_server documents — so under
        full-suite load a freshly started server can occasionally receive a
        request that nothing answers, and the test reports the product as
        broken. Seen as a once-in-three-runs flake, passing in isolation
        (2026-10-03). Retrying costs nothing and keeps a real failure visible.
        """
        for attempt in (0, 1):
            try:
                return self._call_once(path, method, body, headers, host)
            except OSError:
                if attempt:
                    raise
        return None

    def _call_once(self, path, method="GET", body=None, headers=None,
                   host=None):
        import urllib.error
        import urllib.request
        srv = coach_ui.start_server(0)
        try:
            port = srv.server_address[1]
            h = dict(headers or {})
            if host:
                h["Host"] = host
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                         data=body, method=method, headers=h)
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return port, r.status, r.read()
            except urllib.error.HTTPError as e:
                return port, e.code, e.read()
        finally:
            srv.shutdown()
            srv.server_close()

    def test_a_cross_origin_post_cannot_flip_consent(self):
        import json as _json
        import share
        _port, status, body = self._call(
            "/share", "POST", _json.dumps({"share": True}).encode(),
            {"Content-Type": "text/plain;charset=UTF-8",
             "Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertIn(b"bad origin", body)
        self.assertEqual(share.status(), "undecided",
                         "a hostile page changed the consent answer")

    def test_a_non_json_post_is_refused_even_from_loopback(self):
        """The content type is the line a cross-origin page cannot cross: it
        forces a preflight the browser will not pass."""
        import json as _json
        _port, status, body = self._call(
            "/share", "POST", _json.dumps({"share": True}).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 415)
        self.assertIn(b"application/json", body)

    def test_a_rebinding_host_is_refused_on_reads(self):
        _port, status, body = self._call("/analysis", host="evil.example")
        self.assertEqual(status, 403)
        self.assertIn(b"bad host", body)

    def test_a_sandboxed_or_file_origin_is_refused(self):
        for origin in ("null", "file://", "https://evil.example"):
            _port, status, _body = self._call(
                "/share", "POST", b'{"share": true}',
                {"Content-Type": "application/json", "Origin": origin})
            self.assertEqual(status, 403, f"origin {origin!r} was accepted")

    def test_an_ipv6_loopback_origin_is_allowed(self):
        """It looks like an attack and is not one: [::1] IS loopback, and an
        origin of http://[::1]:9999 means something local served that page. A
        local process can talk to the overlay regardless of Origin, so Origin
        is a browser-side control and this is the boundary it draws. (An
        earlier version of the test above asserted this was refused, which was
        the test being wrong rather than the guard being loose.)"""
        import share
        _port, status, _body = self._call(
            "/share", "POST", b'{"share": true}',
            {"Content-Type": "application/json", "Origin": "http://[::1]:9999"})
        self.assertEqual(status, 200)
        self.assertEqual(share.status(), "on")

    def test_the_overlays_own_traffic_still_works(self):
        import json as _json
        import share
        port, status, body = self._call("/analysis")
        self.assertEqual(status, 200)
        # exactly what the page sends: same-origin, JSON, loopback Origin
        _port, status, _body = self._call(
            "/share", "POST", _json.dumps({"share": True}).encode(),
            {"Content-Type": "application/json",
             "Origin": f"http://127.0.0.1:{port}"})
        self.assertEqual(status, 200)
        self.assertEqual(share.status(), "on")

    def test_host_only_reads_the_forms_that_occur(self):
        self.assertEqual(coach_ui._host_only("127.0.0.1:8747"), "127.0.0.1")
        self.assertEqual(coach_ui._host_only("localhost"), "localhost")
        self.assertEqual(coach_ui._host_only("[::1]:8747"), "[::1]")
        self.assertEqual(coach_ui._host_only("http://127.0.0.1:8747"),
                         "127.0.0.1")
        self.assertEqual(coach_ui._host_only("https://evil.example/x"), "evil.example")
        self.assertEqual(coach_ui._host_only("null"), "")
        self.assertEqual(coach_ui._host_only(None), "")


class TestReviewRoute(unittest.TestCase):
    """GET /review — the pivot's other half, reachable from the overlay.

    The live payload carries no plan at all (test_live_view.py), so this route
    and the end-of-game link are the ONLY way a player ever sees the model's
    line. If this regressed to a 404, the plan would simply be gone from the
    product with every other test still passing.
    """

    def setUp(self):
        self._saved = (coach_ui._state.review, coach_ui._state.review_label,
                       coach_ui._state.analysis)
        coach_ui._state.review = None
        coach_ui._state.review_label = None
        coach_ui._state.analysis = None

    def tearDown(self):
        (coach_ui._state.review, coach_ui._state.review_label,
         coach_ui._state.analysis) = self._saved

    def test_no_game_yet_says_so_and_names_the_fallback(self):
        code, headers, body = coach_ui._review_response()
        text = body.decode("utf-8")
        self.assertEqual(code, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("No finished game this session yet", text)
        # The CLI is the honest fallback: the overlay's review only ever covers
        # the game that just ended, and the logs are on disk.
        self.assertIn("settle_up.py", text)

    def test_a_game_in_progress_is_not_reported_as_never_having_played(self):
        coach_ui._state.analysis = {"hero": "Chenvaala"}
        _code, _headers, body = coach_ui._review_response()
        self.assertIn("in progress", body.decode("utf-8"))

    def test_a_ready_review_is_served_verbatim(self):
        coach_ui.set_review("<html>THE REVIEW</html>", "Settle up — Chenvaala")
        code, _headers, body = coach_ui._review_response()
        self.assertEqual(code, 200)
        self.assertEqual(body.decode("utf-8"), "<html>THE REVIEW</html>")
        ready, label = coach_ui.review_meta()
        self.assertTrue(ready)
        self.assertIn("Chenvaala", label)

    def test_an_empty_review_falls_back_to_pending_rather_than_a_blank_page(self):
        coach_ui.set_review("", "label")
        _code, _headers, body = coach_ui._review_response()
        self.assertIn(b"Settle Up", body)


class TestTheGameOverCardOffersSave(unittest.TestCase):
    """The old 'Settle up' link went when the Settle Up tab landed
    (2026-10-07): the plan is read in the tab now, over saved games, and
    the end-of-game card offers SAVE instead of a link off the page."""

    def test_the_end_of_game_card_is_what_the_save_button_keys_on(self):
        import json as _json
        payload = _json.loads(
            coach_ui.welcome_payload(game_over={"placement": 2, "turn": 16})
            .decode("utf-8"))
        self.assertIn("game_over", payload)
        self.assertNotIn("review_url", payload,
                         "the standalone page lost its button; the card "
                         "does not link off-page any more")

    def test_a_fresh_install_is_not_offered_a_save(self):
        # The first-run card is not a game-over card; offering to save a
        # game that was never played would be the "dead coach looks
        # finished" confusion in reverse.
        import json as _json
        payload = _json.loads(coach_ui.welcome_payload().decode("utf-8"))
        self.assertNotIn("game_over", payload)

    def test_the_page_draws_the_save_button_against_the_game_over_marker(self):
        self.assertIn("review/save", coach_ui._HTML)
        self.assertIn("a.game_over", coach_ui._HTML)
        self.assertNotIn("review_url", coach_ui._HTML)


if __name__ == "__main__":
    unittest.main()
