"""Corpus upload: one Contents-API PUT per bundle; gh CLI or token auth."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import upload_corpus  # noqa: E402


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

    def test_token_env_passed_through(self):
        any_file = os.path.join(HERE, "meta", "comps.json")
        with mock.patch.dict(os.environ, {"GH_TELEMETRY_TOKEN": "t0k"}):
            with mock.patch.object(upload_corpus, "put_file",
                                   return_value="url") as pf:
                upload_corpus.upload(any_file)
        self.assertEqual(pf.call_args[1]["token"], "t0k")


if __name__ == "__main__":
    unittest.main()