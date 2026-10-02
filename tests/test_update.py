"""The auto-update contract: check on start, prompt with substance, apply
atomically over the install while protecting local data, never trusting a
byte that doesn't match the manifest's hash."""
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import update  # noqa: E402

MANIFEST = {"schema": 1, "version": "abc1234", "note": "tempo mode",
            "zip_name": "bobs-ledger-abc1234.zip",
            "zip_sha256": "0" * 64, "zip_bytes": 10}


class TestBehind(unittest.TestCase):
    def test_no_manifest_is_no_update(self):
        self.assertFalse(update.behind("anything", None))
        self.assertFalse(update.behind("anything", {}))

    def test_same_version_is_current(self):
        self.assertFalse(update.behind("abc1234", MANIFEST))

    def test_different_version_is_behind(self):
        self.assertTrue(update.behind("old", MANIFEST))
        self.assertTrue(update.behind("unknown", MANIFEST))


class TestApplyZip(unittest.TestCase):
    def _zip(self, entries):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, data in entries.items():
                z.writestr(name, data)
        return buf.getvalue()

    def test_applies_files_and_version_protects_local_data(self):
        data = self._zip({
            "VERSION": "abc1234\n",
            "hearth-coach/live.py": "print('new')",
            "README.md": "new readme",
            "decision_logs/decision_x.jsonl": "LOCAL DATA",
            "../evil.txt": "nope",
        })
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, "decision_logs"))
            local = os.path.join(td, "decision_logs", "decision_x.jsonl")
            with open(local, "w", encoding="utf-8") as f:
                f.write("LOCAL DATA")
            n = update.apply_zip(data, root=td)
            self.assertEqual(n, 3)  # VERSION + live.py + README; slip skipped
            with open(os.path.join(td, "VERSION")) as f:
                self.assertEqual(f.read().strip(), "abc1234")
            with open(os.path.join(td, "hearth-coach", "live.py")) as f:
                self.assertIn("new", f.read())
            with open(local) as f:
                self.assertEqual(f.read(), "LOCAL DATA")
            self.assertFalse(os.path.exists(
                os.path.join(td, "evil.txt")))

    def test_zip_slip_entries_are_refused(self):
        data = self._zip({"a/../../evil.txt": "nope"})
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(update.apply_zip(data, root=td), 0)
            self.assertEqual(os.listdir(td), [])

    def test_download_zip_verifies_sha_and_sends_key(self):
        import hashlib
        from unittest import mock

        good_zip = self._zip({"VERSION": "x\n"})
        good = dict(MANIFEST, zip_sha256=hashlib.sha256(good_zip).hexdigest())
        captured = {}

        class R:
            def __init__(self, data):
                self._d = data

            def read(self):
                return self._d

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            return R(good_zip)

        with mock.patch.object(update.urllib.request, "urlopen",
                               fake_urlopen), \
             mock.patch.dict(os.environ,
                             {"HEARTH_TELEMETRY_KEY": "k"}):
            data = update.download_zip(good)
        self.assertEqual(data, good_zip)
        self.assertTrue(captured["url"].endswith(
            "/release/bobs-ledger-abc1234.zip"))
        headers = {k.lower(): v for k, v in captured["headers"].items()}
        self.assertEqual(headers.get("x-telemetry-key"), "k")
        self.assertEqual(headers.get("user-agent"),
                         "hearth-coach-telemetry/1.0")
        # a tampered payload must raise, never apply
        bad = dict(MANIFEST, zip_sha256="f" * 64)
        with mock.patch.object(update.urllib.request, "urlopen",
                               fake_urlopen), \
             mock.patch.dict(os.environ,
                             {"HEARTH_TELEMETRY_KEY": "k"}):
            with self.assertRaises(ValueError):
                update.download_zip(bad)


if __name__ == "__main__":
    unittest.main()
