"""The auto-update contract: check on start, prompt with substance, apply
atomically over the install while protecting local data, never trusting a
byte that doesn't match the manifest's hash."""
import importlib.util
import io
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TESTS = os.path.join(HERE, "tests")
for _p in (HERE, _TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import release_key_fixture as fixture  # noqa: E402  (tests/)
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
            "live.py": "print('new')",
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
            # The release puts the code at the zip ROOT: the zip and this repo
            # are the same tree (2026-10-02, the spin-out).
            with open(os.path.join(td, "live.py")) as f:
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
                     "../../../evil.py"):
            data = self._zip({evil: "pwned"})
            with tempfile.TemporaryDirectory() as td:
                self.assertEqual(update.apply_zip(data, root=td), 0, evil)
                self.assertEqual(os.listdir(td), [], evil)

    def test_nested_local_data_is_protected(self):
        """Every shipped path is nested under the repo folder, so a
        first-segment-only PROTECTED test never matched anything — the
        guard was inert while it claimed to protect these dirs."""
        data = self._zip({
            "value.py": "print('new')",
            "decision_logs/decision_mine.jsonl": "OVERWRITTEN",
            "corpus_out/pending.json.gz": "OVERWRITTEN",
            ".review_cache/c.json": "OVERWRITTEN",
        })
        with tempfile.TemporaryDirectory() as td:
            for rel, body in (("decision_logs", "decision_mine.jsonl"),
                              ("corpus_out", "pending.json.gz"),
                              (".review_cache", "c.json")):
                os.makedirs(os.path.join(td, *rel.split("/")))
                with open(os.path.join(td, *rel.split("/"), body),
                          "w", encoding="utf-8") as f:
                    f.write("LOCAL DATA")
            n = update.apply_zip(data, root=td)
            self.assertEqual(n, 1)          # value.py only
            for rel, body in (("decision_logs", "decision_mine.jsonl"),
                              ("corpus_out", "pending.json.gz"),
                              (".review_cache", "c.json")):
                with open(os.path.join(td, *rel.split("/"), body),
                          encoding="utf-8") as f:
                    self.assertEqual(f.read(), "LOCAL DATA", rel)

    @unittest.skipUnless(
        importlib.util.find_spec("publish_release") is not None,
        "publish_release.py is maintainer tooling and is not in a release")
    def test_update_state_seeded_in_release_lets_a_fresh_zip_update(self):
        """A zip install has no .update_state.json unless the release ships
        one, so the first check could only answer 'unknown' and no update
        was ever offered — the README promised otherwise (2026-10-02)."""
        root = HERE                            # repo root == the zip root
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
        # zip_bytes is a CAP now, not decoration: it is inside the signed body,
        # so the size a publisher states is the size the client will read.
        good = dict(MANIFEST, zip_bytes=len(good_zip),
                    zip_sha256=hashlib.sha256(good_zip).hexdigest())
        captured = {}

        class R:
            def __init__(self, data):
                self._d = data
                self._at = 0

            def read(self, size=None):
                # download_zip reads in bounded chunks now (a hostile server no
                # longer gets to decide how much memory the coach spends), so
                # the fake has to behave like a stream rather than a buffer.
                if size is None:
                    size = len(self._d) - self._at
                chunk = self._d[self._at:self._at + size]
                self._at += len(chunk)
                return chunk

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


class TestInstallRoot(unittest.TestCase):
    """VERSION and .update_state.json must be found in BOTH layouts.

    This repo (and so the release zip) puts the code at the root, with the
    stamps beside `update.py`. The project's earlier layout nested the code
    one level down with the stamps above it, and `update.py` still has to
    work in a checkout of that shape — the preference is whichever directory
    actually holds a VERSION file (2026-10-02, the spin-out).
    """

    def setUp(self):
        self._saved = update._HERE

    def tearDown(self):
        update._HERE = self._saved

    def test_flat_layout_prefers_the_code_directory(self):
        with tempfile.TemporaryDirectory() as td:
            open(os.path.join(td, "VERSION"), "w").close()
            update._HERE = td
            self.assertEqual(update._install_root(), td)

    def test_nested_layout_finds_the_stamp_above(self):
        with tempfile.TemporaryDirectory() as td:
            inner = os.path.join(td, "hearth-coach")
            os.makedirs(inner)
            open(os.path.join(td, "VERSION"), "w").close()
            update._HERE = inner
            self.assertEqual(update._install_root(), td)

    def test_a_dev_checkout_with_no_stamp_falls_back_to_the_code_dir(self):
        with tempfile.TemporaryDirectory() as td:
            inner = os.path.join(td, "code")
            os.makedirs(inner)
            update._HERE = inner
            self.assertEqual(update._install_root(), inner)


class TestUpdatePromptNeverHangs(unittest.TestCase):
    """The update check runs BEFORE the overlay starts, so a question nobody
    answers is a coach that never appears: the player double-clicks, does not
    read the console, and nothing happens. The first version called input()
    and waited forever (2026-10-03)."""

    def test_no_terminal_means_no_question(self):
        with mock.patch.object(update.sys, "stdin", io.StringIO("")):
            start = time.time()
            self.assertEqual(update._ask("update now? [y/N] ", timeout=5), "")
            self.assertLess(time.time() - start, 1.0)

    def test_a_terminal_that_never_answers_gives_up(self):
        import types

        class FakeTTY(io.StringIO):
            def isatty(self):
                return True

        fake_msvcrt = types.SimpleNamespace(kbhit=lambda: False,
                                            getwch=lambda: "")
        with mock.patch.object(update.sys, "stdin", FakeTTY("")), \
                mock.patch.dict(sys.modules, {"msvcrt": fake_msvcrt}), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            start = time.time()
            self.assertEqual(update._ask("update now? [y/N] ", timeout=0.3), "")
            self.assertLess(time.time() - start, 3.0)

    def test_an_answer_of_y_is_returned(self):
        import types

        class FakeTTY(io.StringIO):
            def isatty(self):
                return True

        fake_msvcrt = types.SimpleNamespace(kbhit=lambda: True,
                                            getwch=lambda: "y")
        with mock.patch.object(update.sys, "stdin", FakeTTY("")), \
                mock.patch.dict(sys.modules, {"msvcrt": fake_msvcrt}), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(update._ask("update now? [y/N] ", timeout=1.0), "y")

    def test_declining_returns_declined_without_downloading_anything(self):
        # The manifest has to be genuinely SIGNED now: an unproven release is
        # refused before the prompt, so an unsigned fixture here would be
        # testing the refusal instead of the decline (2026-10-07).
        self.addCleanup(fixture.pin())
        with mock.patch.object(update, "fetch_manifest",
                               lambda *a, **k: fixture.signed()), \
                mock.patch.object(update, "decide",
                                  lambda *a, **k: ("update", "old -> new")), \
                mock.patch.object(update, "_ask", lambda *a, **k: ""), \
                mock.patch.object(update, "download_zip") as dl, \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(update.run(prompt=True), "declined")
        dl.assert_not_called()


class TestAFailedDownloadSaysSo(unittest.TestCase):
    """An update the player ACCEPTED must not fail silently.

    With --yes they were not even asked, so the console was the only signal they
    could get, and it said nothing: a dropped connection, a 404 on the zip or a
    sha256 mismatch used to vanish into live.py's blanket guard around run() (an
    update that fails must never stop play). The coach simply started on the old
    version and the player had no way to know the update had failed (measured
    2026-10-04).
    """

    def _run_with(self, exc):
        """run() with the download failing, and everything else faked."""
        # Signed, so the failure under test is the DOWNLOAD and not the
        # signature gate that now stands in front of it (2026-10-07).
        self.addCleanup(fixture.pin())
        out = io.StringIO()
        with mock.patch.object(update, "recover", lambda *a, **k: ""), \
                mock.patch.object(update, "load_state",
                                  lambda *a, **k: {"version": "old1111",
                                                   "created": "2026-01-01"}), \
                mock.patch.object(update, "fetch_manifest",
                                  lambda *a, **k: fixture.signed(dict(
                                      fixture.MANIFEST,
                                      version="newer999",
                                      note="fixes the ranking"))), \
                mock.patch.object(update, "decide",
                                  lambda *a, **k: ("update", "old1111 -> newer999")), \
                mock.patch.object(update, "download_zip", side_effect=exc), \
                mock.patch.object(update, "apply_zip") as applied, \
                mock.patch("sys.stdout", out):
            status = update.run(prompt=False, assume_yes=True)
        return status, out.getvalue(), applied

    def test_a_network_failure_is_reported(self):
        status, text, applied = self._run_with(
            OSError("connection reset by peer"))
        self.assertEqual(status, "current",
                         "nothing was applied, so this must not claim success")
        self.assertIn("could not download", text)
        self.assertIn("newer999", text)
        applied.assert_not_called()

    def test_a_sha_mismatch_is_reported_too(self):
        """The other way a download fails: the bytes arrived and are wrong."""
        status, text, _ = self._run_with(
            ValueError("zip sha mismatch: got abc123, manifest says def456"))
        self.assertIn("could not download", text)
        self.assertIn("sha mismatch", text)
        self.assertEqual(status, "current")

    def test_it_still_never_raises(self):
        """live.py wraps this call precisely so a bad update cannot stop play."""
        status, _, _ = self._run_with(Exception("anything at all"))
        self.assertEqual(status, "current")


if __name__ == "__main__":
    unittest.main()
