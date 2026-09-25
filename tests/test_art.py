"""On-demand card art: cache miss -> render download; 404s negative-cached
so the browser's repeated image requests don't re-hammer upstream."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from coach_ui import _art_lock, _art_miss, _fetch_render, _can_retry  # noqa: E402
import coach_ui  # noqa: E402

TEST_ID = "ZZZ_TEST_ART"


class TestArtFetch(unittest.TestCase):
    def tearDown(self):
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


if __name__ == "__main__":
    unittest.main()