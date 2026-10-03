"""Corpus packaging: sanitized log + decision log in one gzipped bundle,
with a provenance manifest â€” the unit beta users would send back."""
import base64
import gzip
import hashlib
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import decision_log  # noqa: E402
import package_corpus  # noqa: E402
import privacy_scan  # noqa: E402


def _write_log(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class TestPackage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "Hearthstone_test_1", "Power.log")
        os.makedirs(os.path.dirname(self.log))
        _write_log(self.log,
                   "TAG_CHANGE Entity=Tester#1234 tag=RESOURCES value=3\n"
                   "GameState.DebugPrintPower() - CREATE_GAME\n")
        # a matching decision log with one entry
        decision_log.LOG_DIR = os.path.join(self.tmp.name, "decision_logs")
        decision_log.record({"top_move": "1. roll", "gold": 3, "tier": 1},
                            log_path=self.log, log_offset=42, game_no=1)

    def tearDown(self):
        self.tmp.cleanup()

    def test_bundle_contains_both_and_no_tags(self):
        out = package_corpus.package(self.log, self.tmp.name)
        with gzip.open(out, "rt", encoding="utf-8") as f:
            b = json.load(f)
        self.assertEqual(b["schema"], package_corpus.SCHEMA)
        m = b["manifest"]
        self.assertEqual(m["decision_count"], 1)
        self.assertEqual(m["identities_redacted"], 1)
        self.assertEqual(m["log_basename"], "Power.log")
        with open(self.log, "rb") as raw:
            self.assertEqual(m["log_sha256"], hashlib.sha256(raw.read()).hexdigest())
        # the sanitized log round-trips, keeps the game data, and carries no
        # player identity (checked by the independent scanner, not the
        # sanitizer's own opinion of its work)
        log = gzip.decompress(base64.b64decode(b["log_gz_b64"])).decode()
        self.assertNotIn("Tester", log)
        self.assertIn("RESOURCES", log)
        self.assertEqual(privacy_scan.find(log), {})
        self.assertEqual(len(b["decisions"]), 1)
        self.assertEqual(b["decisions"][0]["offset"], 42)

    def test_no_decision_log_still_packages(self):
        os.remove(os.path.join(
            decision_log.LOG_DIR,
            f"decision_{decision_log.session_stem(self.log)}.jsonl"))
        out = package_corpus.package(self.log, self.tmp.name)
        with gzip.open(out, "rt", encoding="utf-8") as f:
            b = json.load(f)
        self.assertEqual(b["decisions"], [])


if __name__ == "__main__":
    unittest.main()