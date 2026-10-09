"""The overlay's per-run access key, and the harm it closes (2026-10-08 audit).

The Host/Origin guard (`test_coach_ui_http.TestForeignCallers`) closed the
BROWSER-shaped hole: a page the player merely visited can no longer read the
overlay or flip the sharing consent. It never closed the LOCAL one, and the
audit named it as the remaining finding: the server is loopback and
unauthenticated, so any process on the machine — another user's, on a shared
PC — could `POST /share` to opt the player into uploading their games, or
`GET /analysis`, which during play carries the live board AND the opponent's
handle (`analysis.opp_comp.name`, the field `privacy_scan` cannot see).

So the server mints one key per run (`start_server`), every request must carry
it (`?token=` on the URL, or an `X-BL-Token` header), and an empty key
authorizes nothing. What is pinned below, in the order the harm runs:

* no key, no data — the data endpoints, the page and the consent flip are all
  refused, and the refusal does not contain the payload it was refusing;
* the key that works arrives two ways; a wrong one is refused, and a
  non-ASCII one is refused rather than crashing the request thread;
* the path is what routing uses: the key is taken out of the request and the
  remaining parameters are held aside, so `/analysis?token=…` (or that URL
  with any other parameter on it) reaches /analysis rather than falling
  through to the page branch and answering 200 with HTML, and a route that
  reads a parameter still gets it;
* card art stays open: `/img/` and `/card/` are not data, and the tooltips
  load them from a bare `<img src>` that cannot carry a header;
* the page the browser gets holds the REAL key, never the placeholder;
* the page's whole script still PARSES, under node. That check is the one this
  change needed and did not have: one misplaced closing paren in a
  `fetch(auth(...))` call is a SyntaxError that takes the entire overlay
  script with it, and nothing else in the suite runs the page's JS — every
  static assertion still passes on a page that cannot draw a single box;
* the address the player opens is built in ONE place, `coach_ui.overlay_url`,
  which is what live.py prints and opens.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed

# live_coach FIRST, and not for anything in it: coach_ui imports settle_up ->
# outcome_audit -> live_coach, and live_coach imports a NAME back out of
# coach_ui, so importing coach_ui first is a circular import that resolves only
# if something already pulled live_coach in. The full suite gets that for free
# (test_advice_worklist sorts earlier and imports outcome_audit); a single-file
# run does not, which made `python -m unittest ... -p test_overlay_auth.py`
# fail with "cannot import name 'latest_manual_bans'" — measured on main too,
# so it is the package's shape rather than this file's. Listing it here is what
# keeps this module runnable on its own.
import live_coach  # noqa: F401,E402
import coach_ui  # noqa: E402


def _bare(path, headers=None):
    """A handler with no socket under it, the way test_coach_ui_http drives one.

    Everything it answers lands in a BytesIO this test can read back, which is
    how a case that must not even reach a route (or the routing table) is
    checked without a port.
    """
    import io
    h = object.__new__(coach_ui._Handler)
    h.path = path
    h.command = "GET"
    h.request_version = "HTTP/1.1"
    h.requestline = f"GET {path} HTTP/1.1"
    h.client_address = ("127.0.0.1", 0)
    h.headers = headers or {}
    h.wfile = io.BytesIO()
    return h


def _status(h):
    """The status code a bare handler answered with."""
    return int(h.wfile.getvalue().split(b"\r\n", 1)[0].split(b" ")[1])


def open_text(name):
    """A sibling module's source, closed properly (a bare open() in a test
    leaks a file handle and Python says so on stderr, which is noise in a
    suite run)."""
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read()


class _ServerCase(unittest.TestCase):
    """One server at a time, and a consent answer that cannot touch the real one.

    The key is a module global, so a second server RETIRES the first one's key
    (that is the point of a per-run key) — which means a test may never hold
    two servers open and expect both to answer. Every helper here starts,
    asks and shuts down.
    """

    def setUp(self):
        import share
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._saved = (share.CONSENT_PATH, share.REPORTS_DIR, share.SENT_PATH)
        share.CONSENT_PATH = os.path.join(self._tmp.name, ".share_consent.json")
        share.REPORTS_DIR = os.path.join(self._tmp.name, "session_reports")
        share.SENT_PATH = os.path.join(share.REPORTS_DIR, ".sent.json")

    def tearDown(self):
        import share
        (share.CONSENT_PATH, share.REPORTS_DIR,
         share.SENT_PATH) = self._saved

    def _call(self, path, method="GET", body=None, headers=None, key=True):
        """One request against a fresh server, retried once on a fresh socket.

        Windows lets a second socket bind a port another socket is LISTENING on
        (the SO_REUSEADDR quirk), so under full-suite load a freshly started
        server can receive a request nothing answers and the suite would report
        the product as broken (2026-10-03, test_coach_ui_http). Retrying keeps
        a real failure visible.
        """
        for attempt in (0, 1):
            try:
                return self._call_once(path, method, body, headers, key)
            except OSError:
                if attempt:
                    raise
        return None

    def _call_once(self, path, method="GET", body=None, headers=None,
                   key=True):
        srv = coach_ui.start_server(0)
        try:
            port = srv.server_address[1]
            h = dict(headers or {})
            if key:
                h.setdefault("X-BL-Token", coach_ui.server_token())
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                         data=body, method=method, headers=h)
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, r.read()
            except urllib.error.HTTPError as e:
                return e.code, e.read()
        finally:
            srv.shutdown()
            srv.server_close()

    def _fresh_key(self):
        srv = coach_ui.start_server(0)
        try:
            return coach_ui.server_token()
        finally:
            srv.shutdown()
            srv.server_close()


class TestNoKeyNoData(_ServerCase):
    """The finding itself: a local process with no key gets nothing."""

    def setUp(self):
        super().setUp()
        self._saved_state = (coach_ui._state.payload, coach_ui._state.etag)

    def tearDown(self):
        (coach_ui._state.payload, coach_ui._state.etag) = self._saved_state
        super().tearDown()

    def _live_board(self):
        """A payload shaped like a real one mid-game: the opponent's handle is
        in it, because that is the field this guard exists to protect."""
        data = json.dumps({"hero": "Reno Jackson",
                           "opp_comp": {"name": "SomeHandle"}}).encode()
        coach_ui._state.payload = data
        coach_ui._state.etag = hashlib.sha1(data).hexdigest()

    def test_the_live_board_is_refused_without_the_key(self):
        self._live_board()
        status, body = self._call("/analysis", key=False)
        self.assertEqual(status, 403)
        self.assertNotIn(b"SomeHandle", body,
                         "the refusal carried the board it refused to serve")
        self.assertNotIn(b"Reno Jackson", body)

    def test_the_saved_games_list_is_refused_without_the_key(self):
        status, _body = self._call("/review/list", key=False)
        self.assertEqual(status, 403)

    def test_the_page_itself_is_refused_and_says_where_the_key_is(self):
        """A bare bookmarked address is the one way a player meets this
        refusal, so it has to name the way in rather than look broken."""
        status, body = self._call("/", key=False)
        self.assertEqual(status, 403)
        self.assertIn(b"access key", body)
        self.assertIn(b"?token=", body)

    def test_the_consent_cannot_be_flipped_without_the_key(self):
        """The measured harm: this is the request that opts a player into
        uploading their games, from any process on the machine."""
        import share
        status, _body = self._call(
            "/share", "POST", json.dumps({"share": True}).encode(),
            {"Content-Type": "application/json"}, key=False)
        self.assertEqual(status, 403)
        self.assertEqual(share.status(), "undecided",
                         "a keyless local process changed the consent answer")

    def test_the_ban_list_cannot_be_written_without_the_key(self):
        from unittest import mock
        with mock.patch.object(coach_ui, "store_manual_bans") as store:
            status, _body = self._call(
                "/bans", "POST", json.dumps({"banned": ["Beast"]}).encode(),
                {"Content-Type": "application/json"}, key=False)
        self.assertEqual(status, 403)
        self.assertFalse(store.called, "a keyless POST /bans was honoured")

    def test_a_wrong_key_is_refused(self):
        real = self._fresh_key()
        for wrong in (real + "x", real[:-1], "x" * len(real), "nope"):
            status, _body = self._call(f"/analysis?token={wrong}", key=False)
            self.assertEqual(status, 403, f"{wrong!r} was accepted")

    def test_a_non_ascii_key_is_refused_rather_than_crashing(self):
        """hmac.compare_digest raises TypeError on non-ASCII str, which would
        be a 500 and a traceback in the coach's window for any junk request."""
        h = _bare("/analysis?token=h\u00e9llo")
        h.do_GET()
        self.assertEqual(_status(h), 403)

    def test_an_empty_key_authorizes_nothing(self):
        """The handler with no server behind it is the state a hand-built
        handler starts in, and it must fail closed rather than open."""
        saved = coach_ui._TOKEN
        coach_ui._TOKEN = ""
        try:
            h = _bare("/analysis?token=")
            h.do_GET()
            self.assertEqual(_status(h), 403)
            h = _bare("/analysis")
            h.do_GET()
            self.assertEqual(_status(h), 403)
        finally:
            coach_ui._TOKEN = saved


class TestTheKeyThatWorks(_ServerCase):
    """...and the overlay itself is not locked out by its own guard."""

    def test_the_key_in_the_query_opens_the_board(self):
        srv = coach_ui.start_server(0)
        try:
            port = srv.server_address[1]
            url = f"http://127.0.0.1:{port}/analysis?token={coach_ui.server_token()}"
            with urllib.request.urlopen(url, timeout=10) as r:
                self.assertEqual(r.status, 200)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_the_key_in_a_header_opens_the_board(self):
        status, _body = self._call("/analysis")
        self.assertEqual(status, 200)

    def test_the_key_in_the_query_does_not_change_the_route(self):
        """The trap in both directions: every route below do_GET compares
        self.path, so `/analysis?token=…` would MISS /analysis and fall through
        to the page branch — a 200 carrying HTML where the page's own poll
        expects JSON, which is an overlay that never updates and never says
        why."""
        srv = coach_ui.start_server(0)
        try:
            port = srv.server_address[1]
            tok = coach_ui.server_token()
            for path in (f"/analysis?token={tok}", f"/analysis?x=1&token={tok}"):
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}",
                                            timeout=10) as r:
                    body = r.read()
                    self.assertEqual(r.headers["Content-Type"],
                                     "application/json", path)
                self.assertNotIn(b"<!doctype html", body.lower(), path)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_a_route_that_reads_a_parameter_still_gets_it(self):
        """/review/game takes its id from the query — the key goes, the id
        stays, in either order."""
        srv = coach_ui.start_server(0)
        try:
            port = srv.server_address[1]
            tok = coach_ui.server_token()
            for path in (f"/review/game?id=nope&token={tok}",
                         f"/review/game?token={tok}&id=nope"):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}",
                                                timeout=10) as r:
                        body = r.read()
                except urllib.error.HTTPError as e:
                    # 404 "no saved replay 'nope'" IS the route answering; the
                    # point is that it reached the game route and not the page.
                    body = e.read()
                self.assertIn(b"nope", body,
                              f"{path} did not reach the game route")
                self.assertNotIn(b"<!doctype html", body.lower(), path)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_a_wandering_id_is_refused_rather_than_served_as_a_page(self):
        """The id used to be guarded by a charset regex in the route table, and
        a miss fell through to the overlay page — a JSON endpoint answering
        HTML on a bad request, which hides bugs on both sides. The id goes to
        replay_store now, which owns the filename safety (test_settle_tab),
        and a bad one is a 404."""
        srv = coach_ui.start_server(0)
        try:
            port = srv.server_address[1]
            tok = coach_ui.server_token()
            path = f"/review/game?id=../../etc&token={tok}"
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}",
                                            timeout=10) as r:
                    status, body = r.status, r.read()
            except urllib.error.HTTPError as e:
                status, body = e.code, e.read()
            self.assertEqual(status, 404)
            self.assertNotIn(b"<!doctype html", body.lower())
        finally:
            srv.shutdown()
            srv.server_close()

    def test_each_run_mints_a_new_key(self):
        """A key that survives a restart is a key an attacker has already
        read out of a previous session's console or history."""
        first, second = self._fresh_key(), self._fresh_key()
        self.assertNotEqual(first, second)
        for key in (first, second):
            self.assertGreaterEqual(len(key), 16)
            self.assertNotIn("__BL_TOKEN__", key)

    def test_the_guard_is_wired_into_both_verbs(self):
        """The dead-code trap: a guard that is DEFINED but never called passes
        every test that tests it directly and protects nothing."""
        source = open_text("coach_ui.py")
        self.assertEqual(source.count("if not self._authorized():"), 2,
                         "do_GET and do_POST must both ask")


class TestArtStaysOpen(unittest.TestCase):
    """Card art is not data, and an <img src> cannot carry a header.

    Both art routes are exempt; the tile and the tooltip render are fetched by
    the browser itself, so requiring the key there would silently blank every
    piece of art on the page.
    """

    def _drive(self, path):
        from unittest import mock
        h = _bare(path)
        with mock.patch.object(coach_ui, "_fetch_render",
                               return_value=False) as fetch:
            h.do_GET()
        self.assertNotEqual(_status(h), 403,
                            f"{path} was refused, so the art never loads")
        return fetch

    def test_the_tile_route_answers_without_a_key(self):
        fetch = self._drive("/img/ZZZ_TEST_AUTH.png")
        self.assertEqual(fetch.call_count, 1)

    def test_the_tooltip_route_answers_without_a_key(self):
        fetch = self._drive("/card/ZZZ_TEST_AUTH.png")
        self.assertEqual(fetch.call_count, 1)


class TestThePageCarriesTheKey(unittest.TestCase):
    """The page's own fetches ride the key, so the served markup needs it."""

    def _served(self):
        srv = coach_ui.start_server(0)
        try:
            url = coach_ui.overlay_url(srv)
            with urllib.request.urlopen(url, timeout=10) as r:
                self.assertEqual(r.status, 200)
                return r.read().decode("utf-8"), coach_ui.server_token()
        finally:
            srv.shutdown()
            srv.server_close()

    def test_the_served_page_holds_the_real_key(self):
        page, token = self._served()
        self.assertIn(f'const BL_TOKEN = "{token}";', page)

    def test_the_placeholder_never_reaches_the_browser(self):
        """A page that shipped `__BL_TOKEN__` would 403 on every poll — an
        overlay that looks alive and never updates."""
        page, _token = self._served()
        self.assertNotIn("__BL_TOKEN__", page)

    def test_the_source_keeps_exactly_one_placeholder(self):
        # So the substitution is the only route to the browser, and this stays
        # checkable by eye.
        self.assertEqual(coach_ui._HTML.count("__BL_TOKEN__"), 1)

    def test_every_fetch_in_the_page_rides_the_key(self):
        """A new endpoint added without auth() is a request that 403s in
        silence; this is the cheap net under that."""
        page, _token = self._served()
        unauthored = [c for c in re.findall(r"fetch\([^)]*", page)
                      if "fetch(auth(" not in c]
        self.assertEqual(unauthored, [], "these fetches carry no key")


class TestThePageScriptParses(unittest.TestCase):
    """The whole script, run through node's parser.

    This is the control the in-flight version of this change needed: a single
    misplaced closing paren — `fetch(auth('/x', {…})` instead of
    `fetch(auth('/x'), {…})` — is a SyntaxError, and a SyntaxError takes the
    ENTIRE script with it. Nothing else in the suite executes or even parses
    the page's JS, so a page that cannot draw a single box passes all of it.
    """

    def setUp(self):
        if shutil.which("node") is None:
            self.skipTest("node is not installed, so the page's script cannot "
                          "be parsed")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _check(self, page):
        js = re.search(r"<script>(.*?)</script>", page, re.S)
        self.assertIsNotNone(js, "the page has no <script> block to parse")
        path = os.path.join(self.tmp.name, "page.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(js.group(1))
        return subprocess.run(["node", "--check", path], capture_output=True,
                              text=True, timeout=30)

    def test_the_served_script_parses(self):
        srv = coach_ui.start_server(0)
        try:
            with urllib.request.urlopen(coach_ui.overlay_url(srv),
                                        timeout=10) as r:
                page = r.read().decode("utf-8")
        finally:
            srv.shutdown()
            srv.server_close()
        proc = self._check(page)
        self.assertEqual(proc.returncode, 0,
                         f"the page's script does not parse, so the overlay "
                         f"is dead on arrival:\n{proc.stderr[:500]}")

    def test_the_check_can_fail(self):
        """Rehearsal, and not a formality: the first version of the harness in
        test_overlay_layout passed for the wrong reason, and a syntax check
        that cannot fail is worse than none because 'it parsed' is also what a
        broken harness reports."""
        broken = coach_ui._page_html().replace("fetch(auth('/artmiss'))",
                                               "fetch(auth('/artmiss')", 1)
        self.assertNotEqual(broken, coach_ui._page_html())
        self.assertNotEqual(self._check(broken).returncode, 0,
                            "a page with an unbalanced fetch() still parsed")


class TestTheUrlThePlayerOpens(unittest.TestCase):
    """One place builds the address, and it is the one that works."""

    def test_the_url_carries_the_key_and_serves_the_page(self):
        srv = coach_ui.start_server(0)
        try:
            url = coach_ui.overlay_url(srv)
            self.assertIn("?token=", url)
            self.assertIn(coach_ui.server_token(), url)
            with urllib.request.urlopen(url, timeout=10) as r:
                self.assertEqual(r.status, 200)
                self.assertIn(b"<!doctype html", r.read()[:64].lower())
        finally:
            srv.shutdown()
            srv.server_close()

    def test_the_url_names_the_port_actually_bound(self):
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            busy = s.getsockname()[1]
            srv = coach_ui.start_server(busy)
            try:
                self.assertNotEqual(srv.server_address[1], busy)
                self.assertIn(f":{srv.server_address[1]}/",
                              coach_ui.overlay_url(srv))
            finally:
                srv.shutdown()
                srv.server_close()

    def test_live_py_opens_the_helper_and_not_a_home_made_url(self):
        src = open_text("live.py")
        self.assertIn("coach_ui.overlay_url(server)", src)
        self.assertNotIn("127.0.0.1", src,
                         "live.py builds an address of its own again — the key "
                         "rides the URL, so a local copy loses it")

    def test_the_standalone_server_prints_the_helpful_url(self):
        import inspect
        src = inspect.getsource(coach_ui.main)
        self.assertIn("overlay_url(server)", src,
                      "coach_ui --port prints an address with no key in it")


if __name__ == "__main__":
    unittest.main()
