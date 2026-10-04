"""Corpus upload: one Contents-API PUT per bundle; gh CLI or token auth.

Every bundle is verified with package_corpus.inspect before anything leaves, and
these tests pin that gate as well as the transports.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import upload_corpus  # noqa: E402

#: Assembled, like test_friendly_player.py: this file ships, and a handle-shaped
#: literal in it reads as a real player to the release's privacy gate.
_PLACEHOLDER = "Tester" + "#" + "1234"


class TestUpload(unittest.TestCase):
    def test_put_file_builds_contents_api_body(self):
        captured = {}

        def fake_run(cmd, input=None, capture_output=True, timeout=None):
            captured["cmd"] = cmd
            captured["input"] = input

            class R:
                returncode = 0
                stdout = b"https://example.com/file"
                stderr = b""

            return R()

        with mock.patch.object(upload_corpus.subprocess, "run", fake_run):
            url = upload_corpus.put_file("mharrell/hearth-telemetry",
                                         "corpus/x.json.gz", b"BUNDLE")
        self.assertEqual(url, "https://example.com/file")
        self.assertIn(
            "repos/mharrell/hearth-telemetry/contents/corpus/x.json.gz",
            captured["cmd"])
        body = captured["input"].decode()
        self.assertIn('"message"', body)
        # the bundle bytes are base64 in the body
        import base64
        self.assertIn(base64.b64encode(b"BUNDLE").decode(), body)

    def test_upload_uses_default_repo_and_streams_the_file(self):
        with mock.patch.object(upload_corpus, "put_file",
                               return_value="url") as pf:
            upload_corpus.upload(os.path.join(HERE, "meta", "comps.json"))
        self.assertEqual(pf.call_args[0][0], "mharrell/hearth-telemetry")
        self.assertTrue(pf.call_args[0][1].startswith("corpus/"))

    def test_repo_env_override(self):
        any_file = os.path.join(HERE, "meta", "comps.json")
        with mock.patch.dict(os.environ, {"HEARTH_TELEMETRY_REPO": "me/t"}):
            with mock.patch.object(upload_corpus, "put_file",
                                   return_value="url") as pf:
                upload_corpus.upload(any_file)
        self.assertEqual(pf.call_args[0][0], "me/t")

    def test_put_url_posts_the_bundle_with_key_and_name(self):
        """The no-GitHub transport: a plain POST with an optional shared
        key — the user needs nothing but the URL."""
        captured = {}

        class R:
            def __init__(self, reply):
                self._reply = reply

            def read(self):
                return self._reply.encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["method"] = req.method
            captured["headers"] = dict(req.header_items())
            captured["body_len"] = len(req.data)
            return R("stored corpus/x.json.gz (5 bytes)")

        with mock.patch.object(upload_corpus.urllib.request,
                               "urlopen", fake_urlopen):
            reply = upload_corpus.put_url(
                "https://col.example/post", b"BUNDLEDATA",
                key="s3cr3t", name="corpus_20260929.json.gz")
        self.assertEqual(reply, "stored corpus/x.json.gz (5 bytes)")
        self.assertEqual(captured["url"], "https://col.example/post")
        self.assertEqual(captured["method"], "POST")
        headers = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertEqual(headers.get("x-telemetry-key"), "s3cr3t")
        self.assertEqual(headers.get("x-bundle-name"),
                         "corpus_20260929.json.gz")
        self.assertEqual(headers.get("content-type"), "application/gzip")
        self.assertEqual(captured["body_len"], len(b"BUNDLEDATA"))

    def test_put_url_without_key_sends_no_key_header(self):
        captured = {}

        class R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"ok"

        def fake_urlopen(req, timeout=None):
            captured["headers"] = dict(req.header_items())
            return R()

        with mock.patch.object(upload_corpus.urllib.request,
                               "urlopen", fake_urlopen):
            upload_corpus.put_url("https://col.example/post", b"B")
        headers = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertNotIn("x-telemetry-key", headers)

    def test_token_env_passed_through(self):
        any_file = os.path.join(HERE, "meta", "comps.json")
        with mock.patch.dict(os.environ, {"GH_TELEMETRY_TOKEN": "t0k"}):
            with mock.patch.object(upload_corpus, "put_file",
                                   return_value="url") as pf:
                upload_corpus.upload(any_file)
        self.assertEqual(pf.call_args[1]["token"], "t0k")


class TestItVerifiesBeforeItClaims(unittest.TestCase):
    """The upload path said the log was redacted without ever checking.

    It printed "contents: the BattleTag-redacted Power.log ... (no other personal
    data)" as a fixed sentence about whatever file it was handed, and a raw
    Power.log went to the collector verbatim — BattleTag, opponent handles and
    account id — underneath it (measured 2026-10-04). `privacy_scan` was never
    called on this path at all.

    The detection itself is proven for real in test_package_corpus (inspect() on
    a bundle whose log carries a session name); what these tests pin is the
    wiring: nothing leaves until that check has said yes.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sent = []

    def _main(self, argv, clean=True):
        def fake_put(url, data, key=None, name=None):
            self.sent.append(data)
            return "stored"

        with mock.patch.object(sys, "argv", ["upload_corpus.py"] + argv), \
                mock.patch.object(upload_corpus, "put_url", fake_put), \
                mock.patch.object(upload_corpus, "gh_available",
                                  return_value=True), \
                mock.patch.dict(os.environ,
                                {"HEARTH_TELEMETRY_URL":
                                 "http://collector.example/post"}):
            return upload_corpus.main()

    def test_a_file_that_is_not_a_bundle_is_refused(self):
        raw = os.path.join(self.tmp.name, "Power.log")
        with open(raw, "w", encoding="utf-8") as f:
            f.write("PlayerName=" + _PLACEHOLDER + " tag=RESOURCES value=3\n")
        self.assertEqual(self._main([raw, "--yes"]), 1)
        self.assertEqual(self.sent, [], "a raw log was uploaded")

    def test_a_bundle_that_fails_the_scan_is_refused(self):
        bundle = os.path.join(self.tmp.name, "corpus_x.json.gz")
        with open(bundle, "w", encoding="utf-8") as f:
            f.write("placeholder")
        with mock.patch.object(upload_corpus.package_corpus, "inspect",
                               return_value=1):
            self.assertEqual(self._main([bundle, "--yes"]), 1)
        self.assertEqual(self.sent, [], "a bundle the scan rejected was uploaded")

    def test_a_clean_bundle_still_uploads(self):
        bundle = os.path.join(self.tmp.name, "corpus_x.json.gz")
        with open(bundle, "w", encoding="utf-8") as f:
            f.write("placeholder")
        with mock.patch.object(upload_corpus.package_corpus, "inspect",
                               return_value=0):
            self.assertEqual(self._main([bundle, "--yes"]), 0)
        self.assertEqual(len(self.sent), 1)

    def test_an_unreadable_bundle_is_refused(self):
        """A .json.gz that is not JSON at all: refuse, do not traceback."""
        bundle = os.path.join(self.tmp.name, "corpus_nope.json.gz")
        with open(bundle, "wb") as f:
            f.write(b"not json, not gzip")
        self.assertEqual(self._main([bundle, "--yes"]), 1)
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()