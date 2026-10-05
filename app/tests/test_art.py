"""On-demand card art: cache miss -> art download; misses negative-cached
so the browser's repeated image requests don't re-hammer upstream — and the
two kinds of miss (upstream has none, upstream unreachable) kept apart."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from coach_ui import _art_lock, _art_miss, _fetch_render, _can_retry  # noqa: E402
import coach_ui  # noqa: E402

TEST_ID = "ZZZ_TEST_ART"


class TestArtFetch(unittest.TestCase):
    def setUp(self):
        # These drive the REAL _fetch_render, which records misses through
        # the real _art_miss_path — so a test run used to rewrite the
        # running install's .art_miss.json (and prune its live entries), and
        # the test id then showed up in GET /artmiss to a real player
        # (2026-10-02). Point the store at a scratch file instead.
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = coach_ui._art_miss_path
        coach_ui._art_miss_path = os.path.join(self._tmp.name, ".art_miss.json")

    def tearDown(self):
        coach_ui._art_miss_path = self._saved
        self._tmp.cleanup()
        with _art_lock:
            _art_miss.pop(TEST_ID, None)
        path = os.path.join(HERE, "img_cache", f"{TEST_ID}.png")
        if os.path.exists(path):
            os.remove(path)

    def test_fetch_failure_negative_caches(self):
        """A 404 upstream is remembered — the browser re-requests images on
        every DOM rebuild, so an uncached card must not re-hammer upstream."""
        with mock.patch("urllib.request.urlopen", side_effect=OSError("404")):
            ok = _fetch_render(TEST_ID)
        self.assertFalse(ok)
        self.assertFalse(_can_retry(TEST_ID))

    def test_fetch_success_writes_cache(self):
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"PNGDATA"

        with mock.patch("urllib.request.urlopen", return_value=Resp()):
            ok = _fetch_render(TEST_ID)
        self.assertTrue(ok)
        self.assertTrue(_can_retry(TEST_ID))
        with open(os.path.join(HERE, "img_cache", f"{TEST_ID}.png"), "rb") as f:
            self.assertEqual(f.read(), b"PNGDATA")


class TestMissHygiene(unittest.TestCase):
    """The miss list used to grow without bound and rewrote the whole file
    on every miss (502 ids x every rebuild). It now prunes expired entries
    and rate-limits the disk write; GET /artmiss serves only fresh ids."""

    def setUp(self):
        self._saved_writer = coach_ui._miss_last_write[0]
        # Freeze the rate-limiter's clock at "never written" but block the
        # disk write entirely: no test may touch the real .art_miss.json.
        coach_ui._miss_last_write[0] = float("inf")

    def tearDown(self):
        with _art_lock:
            _art_miss.pop(TEST_ID, None)
            _art_miss.pop(f"{TEST_ID}_OLD", None)
        coach_ui._miss_last_write[0] = self._saved_writer

    def _remember(self, cid, age):
        import time as _time
        with _art_lock:
            _art_miss[cid] = _time.time() - age

    def test_remember_miss_prunes_expired_entries(self):
        from coach_ui import MISS_TTL, _remember_miss
        self._remember(f"{TEST_ID}_OLD", MISS_TTL * 10)
        _remember_miss(TEST_ID)
        self.assertNotIn(f"{TEST_ID}_OLD", _art_miss)
        self.assertIn(TEST_ID, _art_miss)

    def test_disk_write_is_rate_limited(self):
        from coach_ui import _remember_miss
        with mock.patch("builtins.open", wraps=open) as op:
            _remember_miss(f"{TEST_ID}_W1")
            _remember_miss(f"{TEST_ID}_W2")
        self.assertEqual(op.call_count, 0)  # blocked by the inf timestamp

    def test_rate_limiter_allows_a_write_after_30s(self):
        from coach_ui import _remember_miss
        coach_ui._miss_last_write[0] = 0.0  # last write: never
        path = os.path.join(HERE, ".art_miss.json")
        with mock.patch("coach_ui._art_miss_path", path + ".test"):
            try:
                _remember_miss(TEST_ID)
                self.assertTrue(os.path.exists(path + ".test"))
            finally:
                if os.path.exists(path + ".test"):
                    os.remove(path + ".test")

    def test_active_misses_lists_only_fresh_ids(self):
        from coach_ui import MISS_TTL, _active_misses
        self._remember(TEST_ID, 0)
        self._remember(f"{TEST_ID}_OLD", MISS_TTL * 10)
        active = _active_misses()
        self.assertIn(TEST_ID, active)
        self.assertNotIn(f"{TEST_ID}_OLD", active)

    def test_active_misses_excludes_ids_with_art_on_disk(self):
        """The regression behind 'where did the images go?' (2026-09-24):
        patch-day art extraction adds files without touching the miss list,
        so 434 of 504 entries had art on disk — and the /artmiss client
        trust the list, placeholdering cards whose art EXISTS. A miss entry
        whose file exists must never be served as a miss."""
        from coach_ui import _active_misses
        art_path = os.path.join(HERE, "img_cache", f"{TEST_ID}.png")
        with open(art_path, "wb") as f:
            f.write(b"PNG")
        try:
            self._remember(TEST_ID, 0)
            self.assertNotIn(TEST_ID, _active_misses())
        finally:
            os.remove(art_path)
        # With the file gone, the same fresh entry is a real miss again.
        self._remember(TEST_ID, 0)
        self.assertIn(TEST_ID, _active_misses())


class TestArtSources(unittest.TestCase):
    """The distributed bug (2026-10-04): a fresh install drew placeholders for
    most of the board.

    The app fetched every image from `/v1/render/latest/enUS/256x/`, which
    404s EVERY current-patch Battlegrounds card — minions, tavern spells,
    trinkets, tokens — while the maintainer's checkout looked fine, because
    its art had come out of the local game client via hearth_art_extract.py
    (a door a player does not have). Probed per class:

        class                     bgs   render   orig
        current-patch minion     200     404     200
        trinket / spell / token  200     404     200
        returning minion         200     200     200
        hero / golden `_G`       404     200     200

    So each kind needs its own source, and the card render needs BOTH.
    """

    def test_the_portrait_source_covers_every_class(self):
        from coach_ui import PORTRAIT_URLS
        self.assertEqual(len(PORTRAIT_URLS), 1, "one source answers for all")
        self.assertIn("/v1/orig/", PORTRAIT_URLS[0])

    def test_the_card_chain_tries_battlegrounds_before_generic(self):
        from coach_ui import CARD_URLS
        self.assertEqual(len(CARD_URLS), 2)
        self.assertIn("/v1/bgs/", CARD_URLS[0])
        self.assertIn("/v1/render/", CARD_URLS[1])

    def test_no_endpoint_uses_the_url_that_caused_it(self):
        """The regression guard: the old single render URL may only appear as
        a last resort inside the card chain, never on its own."""
        from coach_ui import CARD_URLS, PORTRAIT_URLS, RENDER_URL
        self.assertNotEqual(PORTRAIT_URLS, (RENDER_URL,))
        self.assertNotEqual(CARD_URLS, (RENDER_URL,))
        self.assertIn(RENDER_URL, CARD_URLS, "kept as the chain's last resort")

    def test_the_two_kinds_do_not_share_a_source(self):
        """`object-fit: cover` in a 56x56 tile: a framed 256x388 render is
        cropped there, which is why the portrait endpoint is not the card
        chain."""
        from coach_ui import PORTRAIT_URLS, CARD_URLS
        self.assertFalse(set(PORTRAIT_URLS) & set(CARD_URLS))


class TestFetchChain(unittest.TestCase):
    """A 404 from one source must fall through to the next, and the two ways a
    card can go missing must not be confused with each other."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_path = coach_ui._art_miss_path
        coach_ui._art_miss_path = os.path.join(self._tmp.name, ".art_miss.json")
        self._saved_ok = coach_ui.ART_CACHE_OK
        coach_ui.ART_CACHE_OK = True

    def tearDown(self):
        coach_ui._art_miss_path = self._saved_path
        coach_ui.ART_CACHE_OK = self._saved_ok
        self._tmp.cleanup()
        with _art_lock:
            for cid in (TEST_ID, f"{TEST_ID}_CARD"):
                _art_miss.pop(cid, None)
                coach_ui._art_miss_card.pop(cid, None)
                coach_ui._art_soft.pop(cid, None)
        path = os.path.join(HERE, "img_cache", f"{TEST_ID}.png")
        if os.path.exists(path):
            os.remove(path)

    @staticmethod
    def _ok_response(payload=b"PNGDATA"):
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return payload
        return Resp()

    @staticmethod
    def _http_error(code):
        import urllib.error
        return urllib.error.HTTPError("u", code, "nope", {}, None)

    def test_a_404_falls_through_to_the_next_source(self):
        """The whole bug in one test: the first source 404s, the second has
        it, and the art lands."""
        seen = []

        def urlopen(req, timeout=None):
            seen.append(req.full_url)
            if len(seen) == 1:
                raise self._http_error(404)
            return self._ok_response()

        with tempfile.TemporaryDirectory() as dest, \
                mock.patch("urllib.request.urlopen", side_effect=urlopen):
            self.assertTrue(_fetch_render(
                TEST_ID, dest_dir=dest,
                urls=("https://a/{}.png", "https://b/{}.png")))
            self.assertEqual(seen, [f"https://a/{TEST_ID}.png",
                                    f"https://b/{TEST_ID}.png"])
            self.assertTrue(os.path.exists(os.path.join(dest, f"{TEST_ID}.png")))

    def test_all_sources_404_is_a_hard_miss(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=self._http_error(404)):
            self.assertFalse(_fetch_render(TEST_ID))
        self.assertIn(TEST_ID, _art_miss)

    def test_a_timeout_is_a_soft_miss_not_a_missing_card(self):
        """No art and unreachable art need different answers: only the first
        belongs on the client's placeholder list, and only the first deserves
        an hour-long wait."""
        from coach_ui import _active_misses
        with mock.patch("urllib.request.urlopen",
                        side_effect=OSError("timed out")):
            self.assertFalse(_fetch_render(TEST_ID))
        self.assertNotIn(TEST_ID, _art_miss, "a timeout is not 'no art'")
        self.assertIn(TEST_ID, coach_ui._art_soft)
        self.assertFalse(_can_retry(TEST_ID), "it must not re-hammer either")
        self.assertNotIn(TEST_ID, _active_misses(),
                         "the page would placeholder a card that may load")

    def test_a_soft_miss_expires_sooner_than_a_hard_one(self):
        from coach_ui import MISS_TTL, SOFT_MISS_TTL
        self.assertLess(SOFT_MISS_TTL, MISS_TTL)
        with mock.patch("urllib.request.urlopen",
                        side_effect=OSError("timed out")):
            self.assertFalse(_fetch_render(TEST_ID))
        with _art_lock:
            coach_ui._art_soft[TEST_ID] = time.time() - SOFT_MISS_TTL - 1
        self.assertTrue(_can_retry(TEST_ID), "the retry must come back")

    def test_the_card_render_keeps_its_own_miss_list(self):
        """Independent sources: a hero 404s on the Battlegrounds render, so a
        tile miss must not silence the tooltip (or the reverse)."""
        with mock.patch("urllib.request.urlopen",
                        side_effect=self._http_error(404)):
            self.assertFalse(_fetch_render(
                f"{TEST_ID}_CARD", dest_dir=self._tmp.name,
                urls=("https://a/{}.png",), card=True))
        self.assertIn(f"{TEST_ID}_CARD", coach_ui._art_miss_card)
        self.assertNotIn(f"{TEST_ID}_CARD", _art_miss)
        self.assertFalse(_can_retry(f"{TEST_ID}_CARD", card=True))
        self.assertTrue(_can_retry(f"{TEST_ID}_CARD"),
                        "the portrait endpoint has not been tried yet")

    def test_a_non_404_status_is_soft(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=self._http_error(503)):
            self.assertFalse(_fetch_render(TEST_ID))
        self.assertNotIn(TEST_ID, _art_miss)

    def test_an_in_flight_download_is_not_duplicated(self):
        """The page rebuilds every 300ms, so several requests for the same
        uncached tile arrive while its 300KB download is still running."""
        with _art_lock:
            coach_ui._art_inflight.add(TEST_ID)
        try:
            with mock.patch("urllib.request.urlopen") as u:
                self.assertFalse(_fetch_render(TEST_ID))
                u.assert_not_called()
        finally:
            with _art_lock:
                coach_ui._art_inflight.discard(TEST_ID)

    def test_the_in_flight_guard_is_always_released(self):
        """A leaked guard would freeze that card's art forever — both a 404
        and a success must clear it."""
        with mock.patch("urllib.request.urlopen",
                        side_effect=self._http_error(404)):
            _fetch_render(TEST_ID)
        self.assertNotIn(TEST_ID, coach_ui._art_inflight)
        with tempfile.TemporaryDirectory() as dest, \
                mock.patch("urllib.request.urlopen",
                           return_value=self._ok_response()):
            _fetch_render(TEST_ID, dest_dir=dest)
        self.assertNotIn(TEST_ID, coach_ui._art_inflight)


class TestArtCacheFallback(unittest.TestCase):
    """A read-only install folder must still GET art, not just be warned.

    Unzipping into Program Files (or a one-way-synced folder) is legitimate,
    and Windows offers no elevation prompt, so img_cache/ cannot be created
    there. The old behaviour gave up silently: /img answered 404 for every
    card and the page drew placeholders — the SAME face as the CDN bug fixed
    in the same week, so nobody could tell the two apart (reproduced
    2026-10-04: a card whose art is 249896 bytes upstream served 404 in that
    state). Now the cache moves to a per-user directory and art works.
    """

    def test_an_unwritable_install_falls_back_to_the_per_user_dir(self):
        with tempfile.TemporaryDirectory() as td:
            install = os.path.join(td, "install")
            os.makedirs(install)
            # A FILE where img_cache/ must go: the portable stand-in for
            # access-denied (the same trick TestArtCacheDir uses).
            with open(os.path.join(install, "img_cache"), "w") as f:
                f.write("not a directory")
            # `fallback` is the cache ROOT to use, exactly (production passes
            # nothing and gets <user cache>/img_cache).
            user = os.path.join(td, "user-cache", "img_cache")
            root, card, ok, source = coach_ui.resolve_art_cache(install, user)
            self.assertTrue(ok, "art must still work")
            self.assertEqual(source, "user")
            self.assertEqual(root, user)
            self.assertEqual(card, os.path.join(user, "card"))
            self.assertTrue(os.path.isdir(card))

    def test_a_writable_install_keeps_its_own_cache(self):
        with tempfile.TemporaryDirectory() as td:
            unused = os.path.join(td, "unused")
            root, card, ok, source = coach_ui.resolve_art_cache(td, unused)
            self.assertEqual((ok, source), (True, "install"))
            self.assertEqual(root, os.path.join(td, "img_cache"))
            self.assertFalse(os.path.exists(unused),
                             "the fallback must not be created when unneeded")

    def test_no_writable_location_anywhere_reports_not_ok(self):
        """The residual case, and the only one that still runs art-free."""
        with tempfile.TemporaryDirectory() as td:
            install = os.path.join(td, "install")
            os.makedirs(install)
            user = os.path.join(td, "user-cache", "img_cache")
            for blocker in (os.path.join(install, "img_cache"), user):
                os.makedirs(os.path.dirname(blocker), exist_ok=True)
                with open(blocker, "w") as f:
                    f.write("not a directory")
            _, _, ok, source = coach_ui.resolve_art_cache(install, user)
            self.assertFalse(ok)
            self.assertEqual(source, "none")

    def test_the_per_user_root_is_per_platform(self):
        def norm(p):
            return p.replace("\\", "/")
        self.assertEqual(
            norm(coach_ui.user_cache_root(
                env={"LOCALAPPDATA": "C:\\Users\\x\\AppData\\Local"},
                home="C:\\Users\\x", platform="win32")),
            "C:/Users/x/AppData/Local/bobs-ledger")
        self.assertEqual(
            norm(coach_ui.user_cache_root(env={}, home="/Users/x",
                                          platform="darwin")),
            "/Users/x/Library/Caches/bobs-ledger")
        self.assertEqual(
            norm(coach_ui.user_cache_root(env={"XDG_CACHE_HOME": "/tmp/c"},
                                          home="/home/x", platform="linux")),
            "/tmp/c/bobs-ledger")
        self.assertEqual(
            norm(coach_ui.user_cache_root(env={}, home="/home/x",
                                          platform="linux")),
            "/home/x/.cache/bobs-ledger")
        # No LOCALAPPDATA (a stripped-down Windows env) still resolves.
        self.assertEqual(
            norm(coach_ui.user_cache_root(env={}, home="C:\\Users\\x",
                                          platform="win32")),
            "C:/Users/x/AppData/Local/bobs-ledger")

    def test_the_fallback_never_lives_inside_the_install(self):
        """A read-only install must not be handed back as its own fallback:
        the art would still be unwritable, and the failure would be invisible
        for a second reason instead of one."""
        with tempfile.TemporaryDirectory() as td:
            install = os.path.join(td, "install")
            os.makedirs(install)
            with open(os.path.join(install, "img_cache"), "w") as f:
                f.write("not a directory")
            elsewhere = os.path.join(td, "elsewhere", "img_cache")
            root, _, ok, source = coach_ui.resolve_art_cache(install, elsewhere)
            self.assertEqual((ok, source, root), (True, "user", elsewhere))
            self.assertFalse(
                os.path.abspath(root).startswith(os.path.abspath(install)
                                                 + os.sep))

    def test_this_checkout_uses_its_own_cache(self):
        """The module-level answer here, and the one the maintainer, the
        extractor and doctor's art check all assume."""
        self.assertEqual(coach_ui.ART_CACHE_SOURCE, "install")
        self.assertEqual(coach_ui.ART_CACHE,
                         os.path.join(HERE, "img_cache"))


class TestFetchArtTool(unittest.TestCase):
    """`fetch_art.py` had the SAME bug in a second place: its own copy of the
    URL that 404s current-patch cards, writing framed 256x388 renders into the
    PORTRAIT cache (a 56x56 tile with object-fit:cover crops those). It now
    reads coach_ui's chain, so the two cannot drift apart again."""

    def test_the_tool_uses_the_portrait_cache_and_chain(self):
        import fetch_art
        from coach_ui import ART_CACHE, PORTRAIT_URLS
        self.assertEqual(fetch_art.CACHE, ART_CACHE,
                         "the tiles' art belongs in the portrait cache")
        self.assertEqual(fetch_art.portrait_urls("X"),
                         [u.format("X") for u in PORTRAIT_URLS])

    def test_the_tool_no_longer_hardcodes_the_card_render_url(self):
        import fetch_art
        from coach_ui import RENDER_URL
        for url in fetch_art.portrait_urls("X"):
            self.assertNotEqual(url, RENDER_URL.format("X"),
                                "the framed render is the tooltip's kind")

    def test_the_header_shape_survives_the_shared_user_agent(self):
        """coach_ui keeps the UA as a STRING and wraps it per request; this
        tool wants the dict. Importing the string straight into the dict slot
        killed every request with "'str' object has no attribute 'items'"."""
        import fetch_art
        from coach_ui import RENDER_UA
        self.assertIsInstance(fetch_art.UA, dict)
        self.assertEqual(fetch_art.UA, {"User-Agent": RENDER_UA})


class TestArtCacheDir(unittest.TestCase):
    """A read-only install folder must not kill the coach at import.

    Windows offers no elevation prompt when the install folder refuses a
    write — unzip into C:\\Program Files and the create is simply denied — so
    the unguarded makedirs that used to sit at module scope raised
    PermissionError [WinError 5] and the process died with a bare traceback
    before a single piece of advice could be shown (2026-10-02). Art is
    optional; the crash was not.
    """

    def test_ensure_dir_reports_failure_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as td:
            blocker = os.path.join(td, "a_file")
            with open(blocker, "w", encoding="utf-8") as f:
                f.write("not a directory")
            # A path under a FILE can never be created: the same class of
            # failure as access-denied, and it is portable to any machine.
            self.assertFalse(
                coach_ui.ensure_dir(os.path.join(blocker, "img_cache")))

    def test_ensure_dir_creates_and_reports_success(self):
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "img_cache", "card")
            self.assertTrue(coach_ui.ensure_dir(target))
            self.assertTrue(os.path.isdir(target))

    def test_this_checkout_can_write_its_cache(self):
        """The real module-level answer in a normal checkout — the guard must
        not silently disable art for everyone to fix the rare read-only case."""
        self.assertTrue(coach_ui.ART_CACHE_OK)

    def test_no_upstream_fetch_when_there_is_nowhere_to_write(self):
        """With an unwritable cache, _fetch_render must report failure
        without spending a network round-trip per card."""
        saved = coach_ui.ART_CACHE_OK
        coach_ui.ART_CACHE_OK = False
        try:
            with mock.patch("urllib.request.urlopen") as u:
                self.assertFalse(_fetch_render(TEST_ID))
                u.assert_not_called()
        finally:
            coach_ui.ART_CACHE_OK = saved


if __name__ == "__main__":
    unittest.main()