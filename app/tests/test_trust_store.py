"""The macOS trust store — the one call the whole https surface depends on.

MEASURED 2026-10-16 on the maintainer's Mac: a python.org Python 3.15 has no CA
bundle until its installer's own "Install Certificates.command" is run, so EVERY
`urllib.request.urlopen` failed with

    URLError: [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer

It was never a sharing bug. `share.py`, `update.py`, `fetch_art.py`,
`fetch_sessions.py`, `upload_corpus.py` and the overlay's card art all go through
the same bare urlopen — and Windows never shows it, which is how the project got
all the way to its first Mac run without noticing.

The fix is one call to `config.trust_store()` at the top of each of those
modules. So these tests cover three behaviours (it offers a real bundle, it does
not overrule a player who set their own, it degrades quietly without `certifi`)
and the pin that actually matters: that every network module calls it. A seventh
module added later would otherwise inherit the bug in silence, on a platform the
maintainer develops on.
"""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # app/
sys.path.insert(0, HERE)          # the code dir, wherever this runs from

import config  # noqa: E402

#: Every module that reaches the network through `urllib`. A LIST, not a glob:
#: adding a network module is then a deliberate act with a failing test attached
#: to it, rather than something a new file quietly escapes.
NETWORK_MODULES = ("share.py", "update.py", "fetch_art.py", "fetch_sessions.py",
                   "upload_corpus.py", "coach_ui.py")


class TestTheTrustStoreIsOffered(unittest.TestCase):

    def test_it_points_at_a_bundle_that_exists(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SSL_CERT_FILE", None)
            try:
                import certifi
            except ImportError:
                self.skipTest("certifi is not installed here")
            path = config.trust_store()
            self.assertIsNotNone(path, "certifi exists but no bundle was offered")
            self.assertTrue(os.path.exists(path), path)
            self.assertEqual(os.environ["SSL_CERT_FILE"], path,
                             "the bundle was found but the process was not told, "
                             "so OpenSSL would still refuse")

    def test_a_bundle_the_player_set_wins(self):
        """Their own bundle, or the installer's command's, is not overruled."""
        with mock.patch.dict(os.environ, {"SSL_CERT_FILE": "/tmp/mine.pem"}):
            self.assertEqual(config.trust_store(), "/tmp/mine.pem")
            self.assertEqual(os.environ["SSL_CERT_FILE"], "/tmp/mine.pem",
                             "their own bundle was overwritten")

    def test_a_missing_certifi_is_not_an_error(self):
        """Without certifi the failure has to stay the ORIGINAL one — a clear
        SSL error on the request — and not an ImportError thrown from a startup
        path, which would take the whole tool down instead of one upload."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SSL_CERT_FILE", None)
            with mock.patch.dict(sys.modules, {"certifi": None}):
                self.assertIsNone(config.trust_store())


class TestEveryNetworkModuleAsksForIt(unittest.TestCase):

    def test_each_one_calls_it(self):
        for name in NETWORK_MODULES:
            with open(os.path.join(HERE, name), encoding="utf-8") as fh:
                src = fh.read()
            self.assertIn("trust_store()", src,
                          f"{name} makes https requests and never calls "
                          f"trust_store() — on macOS every one of them fails "
                          f"with CERTIFICATE_VERIFY_FAILED")

    def test_the_call_is_at_import_time(self):
        """Module level, not inside a function.

        MEASURED: setting the variable after a request has already been
        attempted still failed — OpenSSL has built its verify paths by then. So
        the call has to happen while the module is being imported, before any
        request, and an indented call would be a fix that does not fix.
        """
        for name in NETWORK_MODULES:
            with open(os.path.join(HERE, name), encoding="utf-8") as fh:
                found = None
                for line in fh:
                    if "trust_store()" in line:
                        found = line
                        break
            self.assertIsNotNone(found, f"{name} never calls trust_store()")
            self.assertFalse(found.startswith((" ", "\t")),
                             f"{name}: the trust_store() call is indented, so it "
                             f"runs later (or never) instead of at import")


if __name__ == "__main__":
    unittest.main()
