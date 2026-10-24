"""The double-click promise: an overlay opens in the browser.

Two halves have to agree, and each has a way of going quiet on its own:

* the LAUNCHERS pass `--open` to `app/live.py`. The .command's half is pinned in
  `test_launcher_sh`; the .cmd's was not pinned anywhere until this file, which
  is the half a Windows player actually double-clicks.
* `live.py` must not CLAIM an open it did not do. The line read "Opening the
  overlay in your browser" whether or not `--open` was present, so a direct
  `python app/live.py` printed the promise and then sat there with no browser —
  reported on 2026-10-24 as "the browser window stopped opening", and a
  plausible reading of a line that is simply false when the flag is absent.

`_overlay_line` is a pure function, so the message itself can be executed here
rather than eyeballed in a console nobody keeps.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.join(ROOT, "app")
sys.path.insert(0, HERE)          # location-independent: no cwd or -t needed

import live  # noqa: E402

WINDOWS_LAUNCHER = os.path.join(ROOT, "Start Bob's Ledger.cmd")
MAC_LAUNCHER = os.path.join(ROOT, "Start Bob's Ledger.command")


class TestTheLaunchersAskForTheBrowser(unittest.TestCase):
    def _text(self, path):
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()

    def test_the_windows_launcher_passes_open(self):
        """The line that starts the coach, not a mention of it: the .cmd passes
        `--open` BEFORE the pass-through args so a player's own flags cannot
        remove it."""
        text = self._text(WINDOWS_LAUNCHER)
        self.assertIn('app\\live.py" --open', text)
        run = text.index('app\\live.py" --open')
        self.assertLess(run, text.index("%PASS%", run))

    def test_the_mac_launcher_passes_open(self):
        text = self._text(MAC_LAUNCHER)
        self.assertIn('app/live.py" --open', text)

    def test_live_py_opens_only_when_it_was_asked(self):
        source = self._text(os.path.join(HERE, "live.py"))
        self.assertIn('opening = "--open" in opts', source)
        self.assertIn("threading.Thread(target=_open_overlay", source)


class TestAFailedOpenIsSaidOutLoud(unittest.TestCase):
    """A browser that does not start must not look like one that did: the call
    used to sit in a daemon thread whose return value nobody read."""

    def test_a_browser_that_answers_false_gets_the_address_on_screen(self):
        import contextlib
        import io
        from unittest import mock
        buf = io.StringIO()
        with mock.patch("webbrowser.open", lambda url: False):
            with contextlib.redirect_stdout(buf):
                ok = live._open_overlay("http://127.0.0.1:8747/?token=x")
        self.assertFalse(ok)
        self.assertIn("Could not open a browser", buf.getvalue())
        self.assertIn("http://127.0.0.1:8747/?token=x", buf.getvalue())

    def test_a_handler_that_raises_gets_the_address_on_screen(self):
        import contextlib
        import io
        from unittest import mock
        buf = io.StringIO()

        def boom(url):
            raise OSError("no default browser")

        with mock.patch("webbrowser.open", boom):
            with contextlib.redirect_stdout(buf):
                ok = live._open_overlay("http://127.0.0.1:8747/?token=x")
        self.assertFalse(ok)
        self.assertIn("no default browser", buf.getvalue())
        self.assertIn("http://127.0.0.1:8747/?token=x", buf.getvalue())

    def test_a_working_open_says_nothing(self):
        import contextlib
        import io
        from unittest import mock
        buf = io.StringIO()
        with mock.patch("webbrowser.open", lambda url: True):
            with contextlib.redirect_stdout(buf):
                ok = live._open_overlay("http://127.0.0.1:8747/?token=x")
        self.assertTrue(ok)
        self.assertEqual(buf.getvalue(), "")


class TestTheLineTellsTheTruth(unittest.TestCase):
    def test_with_open_it_says_it_is_opening(self):
        line = live._overlay_line("http://127.0.0.1:8747/?token=abc", True)
        self.assertEqual(
            line, "Opening the overlay in your browser: "
                  "http://127.0.0.1:8747/?token=abc")

    def test_without_open_it_does_not_claim_to_open_anything(self):
        line = live._overlay_line("http://127.0.0.1:8747/?token=abc", False)
        self.assertNotIn("Opening", line)
        self.assertIn("http://127.0.0.1:8747/?token=abc", line)
        self.assertIn("--open", line)


if __name__ == "__main__":
    unittest.main()
