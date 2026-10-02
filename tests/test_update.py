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
            "zip_sha256": "0" * 64, "zip_bytes": 10,
            "created": "2026-10-01T12:00:00"}


def _decide(local, manifest, state=None):
    return update.decide(local, manifest, state or {})[0]


class TestDecide(unittest.TestCase):
    """Direction is decided by the manifest's publish timestamp vs the
    install's last-update state — NEVER by sha inequality, which once
    downgraded a fresh clone of a newer main onto the older zip."""

    def test_no_manifest_is_no_update(self):
        self.assertEqual(_decide("anything", None), "current")
        self.assertEqual(_decide("anything", {}), "current")

    def test_state_timestamps_decide_direction(self):
        state = {"version": "old1234", "created": "2026-09-30T08:00:00"}
        self.assertEqual(_decide("old1234", MANIFEST, state), "update")
        older = dict(MANIFEST, created="2026-09-29T00:00:00")
        self.assertEqual(_decide("old1234", older, state), "local-newer")
        same = dict(MANIFEST, created=state["created"])
        self.assertEqual(_decide("old1234", same, state), "current")

    def test_stateless_install_is_current_only_on_exact_match(self):
        self.assertEqual(_decide("abc1234", MANIFEST), "current")
        # a git checkout of a newer main must NOT look behind
        self.assertEqual(_decide("def5678", MANIFEST), "unknown")
        self.assertEqual(_decide("unknown", MANIFEST), "unknown")

    def test_manifest_without_created_never_guesses(self):
        self.assertEqual(_decide("old1234", dict(MANIFEST, created="")),
                         "unknown")

    def test_decide_detail_names_both_sides(self):
        _, detail = update.decide(
            "old1234", MANIFEST,
            {"version": "old1234", "created": "2026-09-30T08:00:00"})
        self.assertIn("old1234 -> abc1234", detail)


class TestState(unittest.TestCase):
    def test_save_then_load_round_trips(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            state_file = os.path.join(td, ".update_state.json")
            with mock.patch.object(update, "STATE_FILE", state_file):
                self.assertEqual(update.load_state(), {})  # absent is {}
                update.save_state(MANIFEST)
                self.assertEqual(update.load_state(),
                                 {"version": "abc1234",
                                  "created": "2026-10-01T12:00:00"})


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

    def test_windows_drive_slip_entries_are_refused(self):
        """`C:/evil.dll` is absolute on Windows: os.path.join discards the
        root for it, so the old guard (startswith("/") or "..") let a write
        land outside the install (2026-10-02)."""
        for evil in ("C:/evil.dll", "D:/evil.py", "C:evil.dll",
                     "//host/share/e.txt", "a/../../b/c.txt",
                     "hearth-coach/../../../evil.py"):
            data = self._zip({evil: "pwned"})
            with tempfile.TemporaryDirectory() as td:
                self.assertEqual(update.apply_zip(data, root=td), 0, evil)
                self.assertEqual(os.listdir(td), [], evil)

    def test_nested_local_data_is_protected(self):
        """Every shipped path is nested under the repo folder, so a
        first-segment-only PROTECTED test never matched anything — the
        guard was inert while it claimed to protect these dirs."""
        data = self._zip({
            "hearth-coach/value.py": "print('new')",
            "hearth-coach/decision_logs/decision_mine.jsonl": "OVERWRITTEN",
            "hearth-coach/corpus_out/pending.json.gz": "OVERWRITTEN",
            "hearth-coach/.review_cache/c.json": "OVERWRITTEN",
        })
        with tempfile.TemporaryDirectory() as td:
            for rel, body in (("hearth-coach/decision_logs", "decision_mine.jsonl"),
                              ("hearth-coach/corpus_out", "pending.json.gz"),
                              ("hearth-coach/.review_cache", "c.json")):
                os.makedirs(os.path.join(td, *rel.split("/")))
                with open(os.path.join(td, *rel.split("/"), body),
                          "w", encoding="utf-8") as f:
                    f.write("LOCAL DATA")
            n = update.apply_zip(data, root=td)
            self.assertEqual(n, 1)          # value.py only
            for rel, body in (("hearth-coach/decision_logs", "decision_mine.jsonl"),
                              ("hearth-coach/corpus_out", "pending.json.gz"),
                              ("hearth-coach/.review_cache", "c.json")):
                with open(os.path.join(td, *rel.split("/"), body),
                          encoding="utf-8") as f:
                    self.assertEqual(f.read(), "LOCAL DATA", rel)

    def test_update_state_seeded_in_release_lets_a_fresh_zip_update(self):
        """A zip install has no .update_state.json unless the release ships
        one, so the first check could only answer 'unknown' and no update
        was ever offered — the README promised otherwise (2026-10-02)."""
        root = os.path.dirname(HERE)          # the repo root
        if root not in sys.path:
            sys.path.insert(0, root)
        import publish_release
        created = "2026-10-02T11:33:25"
        data = publish_release.build_zip("abc1234", created)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            state = json.loads(z.read(".update_state.json"))
        self.assertEqual(state, {"version": "abc1234", "created": created})
        # and that state is enough to be offered a later release
        later = dict(MANIFEST, created="2026-10-03T09:00:00", version="def5678")
        action, _ = update.decide("abc1234", later, state)
        self.assertEqual(action, "update")

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
