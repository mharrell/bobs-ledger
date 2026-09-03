"""On-demand card art: cache miss -> render download; 404s negative-cached
so the browser's repeated image requests don't re-hammer upstream."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from coach_ui import _art_lock, _art_miss, _fetch_render, _can_retry  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()