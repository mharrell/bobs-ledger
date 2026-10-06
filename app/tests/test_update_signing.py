"""What the updater does with a release it cannot prove, and with one that is
too large to be one.

Two gates, both added 2026-10-07 after the release channel was audited:

  * a SIGNATURE check, wired so that an unproven release is never offered,
    never downloaded and never applied — including under --force, which exists
    to override a direction guess, not an identity check;
  * SIZE CAPS on the download and on extraction, because `download_zip` used to
    read whatever the server sent into memory and unpack it over the install.

The tests below are deliberately about the REFUSAL paths. The happy path is
covered by test_update.py, which now signs its manifests with the fixture key.
"""
import hashlib
import io
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
for path in (APP, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import release_key_fixture as fixture  # noqa: E402
import update  # noqa: E402

#: An install that last updated BEFORE the fixture release was published, so
#: decide() offers the update the way a real install would.
OLD_STATE = {"version": "old1111", "created": "2026-01-01T00:00:00"}


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
    return buf.getvalue()


class _Stream:
    """A urlopen() response that can only be read in bounded chunks."""

    def __init__(self, data):
        self._data = data
        self._at = 0

    def read(self, size=None):
        if size is None:
            size = len(self._data) - self._at
        chunk = self._data[self._at:self._at + size]
        self._at += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestARefusedReleaseNeverInstalls(unittest.TestCase):
    """run() must stop at the refusal, and a refusal nobody sees is not one."""

    def setUp(self):
        self.restore = fixture.pin()
        self.addCleanup(self.restore)

    def _run(self, manifest, **kwargs):
        out = io.StringIO()
        with mock.patch.object(update, "recover", lambda *a, **k: None), \
                mock.patch.object(update, "local_version",
                                  lambda *a, **k: "old1111"), \
                mock.patch.object(update, "load_state",
                                  lambda *a, **k: dict(OLD_STATE)), \
                mock.patch.object(update, "fetch_manifest",
                                  lambda *a, **k: manifest), \
                mock.patch.object(update, "download_zip") as download, \
                mock.patch.object(update, "apply_zip") as apply_it, \
                mock.patch("sys.stdout", out):
            status = update.run(**kwargs)
        return status, out.getvalue(), download, apply_it

    def test_an_unsigned_release_is_refused(self):
        status, text, download, apply_it = self._run(dict(fixture.MANIFEST))
        self.assertEqual(status, "unproven")
        self.assertIn("REFUSING", text)
        self.assertIn("no signature", text)
        download.assert_not_called()
        apply_it.assert_not_called()

    def test_a_forged_signature_is_refused(self):
        forged = dict(fixture.MANIFEST)
        forged["sig"] = "0" * 128
        forged["sig_alg"] = "ed25519"
        status, text, download, _ = self._run(forged)
        self.assertEqual(status, "unproven")
        self.assertIn("does not match the pinned key", text)
        download.assert_not_called()

    def test_a_field_changed_after_signing_is_refused(self):
        """The realistic tamper: keep the signature, rewrite the payload it
        covers — here the note a player would read in the prompt."""
        tampered = dict(fixture.signed())
        tampered["note"] = "harmless, honest"
        status, text, download, _ = self._run(tampered)
        self.assertEqual(status, "unproven")
        download.assert_not_called()

    def test_force_is_not_a_bypass(self):
        """--force overrides the direction guess. It does not override
        "is this ours?" — a signature check with a bypass flag IS the flag."""
        with mock.patch.object(update, "recover", lambda *a, **k: None), \
                mock.patch.object(update, "local_version",
                                  lambda *a, **k: "old1111"), \
                mock.patch.object(update, "load_state",
                                  lambda *a, **k: {"version": "old1111",
                                                   "created": "2099-01-01T00:00:00"}), \
                mock.patch.object(update, "fetch_manifest",
                                  lambda *a, **k: dict(fixture.MANIFEST)), \
                mock.patch.object(update, "download_zip") as download, \
                mock.patch("sys.stdout", io.StringIO()) as out:
            status = update.run(force=True)
            text = out.getvalue()
        self.assertEqual(status, "unproven", text)
        self.assertIn("REFUSING", text)
        download.assert_not_called()

    def test_a_signed_release_still_reaches_the_download(self):
        """The control: without this, every refusal above could be a function
        that refuses everything."""
        out = io.StringIO()
        with mock.patch.object(update, "recover", lambda *a, **k: None), \
                mock.patch.object(update, "local_version",
                                  lambda *a, **k: "old1111"), \
                mock.patch.object(update, "load_state",
                                  lambda *a, **k: dict(OLD_STATE)), \
                mock.patch.object(update, "fetch_manifest",
                                  lambda *a, **k: fixture.signed()), \
                mock.patch.object(update, "download_zip",
                                  side_effect=OSError("offline")) as download, \
                mock.patch.object(update, "apply_zip") as apply_it, \
                mock.patch("sys.stdout", out):
            status = update.run(prompt=False, assume_yes=True)
        download.assert_called_once()
        apply_it.assert_not_called()
        self.assertEqual(status, "current")
        self.assertIn("could not download", out.getvalue())

    def test_an_up_to_date_install_is_not_nagged_about_an_unsigned_manifest(self):
        """Verification runs when an update would be OFFERED. An install with
        nothing to install has nothing to lose, and a scary line every launch
        would be noise about something the player cannot act on."""
        out = io.StringIO()
        with mock.patch.object(update, "recover", lambda *a, **k: None), \
                mock.patch.object(update, "local_version",
                                  lambda *a, **k: "newer999"), \
                mock.patch.object(update, "load_state",
                                  lambda *a, **k: {"version": "newer999",
                                                   "created":
                                                   fixture.MANIFEST["created"]}), \
                mock.patch.object(update, "fetch_manifest",
                                  lambda *a, **k: dict(fixture.MANIFEST)), \
                mock.patch("sys.stdout", out):
            status = update.run()
        text = out.getvalue()
        self.assertEqual(status, "current", text)
        self.assertIn("up to date", text)
        self.assertNotIn("REFUSING", text)


class TestCheckReportsTheSameRefusal(unittest.TestCase):
    """--check reports what an install would do, so it must refuse what the
    installer refuses — otherwise it advertises an update that cannot apply."""

    def setUp(self):
        self.restore = fixture.pin()
        self.addCleanup(self.restore)

    def _check(self, manifest):
        out = io.StringIO()
        with mock.patch.object(update, "local_version",
                               lambda *a, **k: "old1111"), \
                mock.patch.object(update, "load_state",
                                  lambda *a, **k: dict(OLD_STATE)), \
                mock.patch.object(update, "fetch_manifest",
                                  lambda *a, **k: manifest), \
                mock.patch.object(sys, "argv", ["update.py", "--check"]), \
                mock.patch("sys.stdout", out):
            code = update.main()
        return code, out.getvalue()

    def test_an_unsigned_release_is_reported_as_a_refusal(self):
        code, text = self._check(dict(fixture.MANIFEST))
        self.assertEqual(code, 2, text)
        self.assertIn("REFUSING", text)
        self.assertNotIn("update available", text)

    def test_a_signed_release_is_reported_as_available(self):
        code, text = self._check(fixture.signed())
        self.assertEqual(code, 1, text)
        self.assertIn("update available", text)


class TestSizeCaps(unittest.TestCase):
    """A download and an unpack both have a ceiling now."""

    def test_the_manifest_size_is_the_cap_when_it_has_one(self):
        """`zip_bytes` is inside the SIGNED body, so this is the publisher's
        number rather than the server's."""
        manifest = dict(fixture.MANIFEST, zip_bytes=10, zip_sha256="0" * 64)
        with mock.patch.object(update.urllib.request, "urlopen",
                               lambda req, timeout=None: _Stream(b"x" * 500)):
            with self.assertRaises(ValueError) as caught:
                update.download_zip(manifest)
        self.assertIn("the manifest", str(caught.exception))
        self.assertIn("10", str(caught.exception))

    def test_the_client_ceiling_catches_a_manifest_with_no_size(self):
        manifest = dict(fixture.MANIFEST)
        manifest.pop("zip_bytes")
        with mock.patch.object(update, "MAX_ZIP_BYTES", 100), \
                mock.patch.object(update.urllib.request, "urlopen",
                                  lambda req, timeout=None: _Stream(b"x" * 500)):
            with self.assertRaises(ValueError) as caught:
                update.download_zip(manifest)
        self.assertIn("ceiling", str(caught.exception))

    def test_a_payload_within_the_cap_is_read_whole(self):
        """The control for the two above: the cap must not truncate a real
        release. The fake can only be read in chunks, so this also pins the
        chunked read itself."""
        body = _zip({"VERSION": "x\n"})
        manifest = dict(fixture.MANIFEST, zip_bytes=len(body),
                        zip_sha256=hashlib.sha256(body).hexdigest())
        with mock.patch.object(update.urllib.request, "urlopen",
                               lambda req, timeout=None: _Stream(body)):
            self.assertEqual(update.download_zip(manifest), body)

    def test_too_many_entries_is_refused_before_unpacking(self):
        with tempfile.TemporaryDirectory() as td:
            data = _zip({"a.py": "a", "b.py": "b", "c.py": "c"})
            with mock.patch.object(update, "MAX_ENTRIES", 2):
                n = update.apply_zip(data, root=td)
            self.assertEqual(n, 0)
            self.assertIn("entries", update.LAST_ERROR)
            self.assertFalse(os.path.exists(os.path.join(td, "a.py")),
                             "nothing may be written when the cap refuses")

    def test_a_bomb_larger_than_the_ceiling_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            data = _zip({"app/live.py": "x" * 200})
            with mock.patch.object(update, "MAX_TOTAL_BYTES", 100):
                n = update.apply_zip(data, root=td)
            self.assertEqual(n, 0)
            self.assertIn("unpacks to", update.LAST_ERROR)

    def test_a_real_release_is_not_near_the_caps(self):
        """The caps exist to bound a hostile server, not to make normal
        releases fragile: this is the shipped tree's order of magnitude."""
        with tempfile.TemporaryDirectory() as td:
            data = _zip({"app/live.py": "x" * 40, "README.md": "y" * 40})
            n = update.apply_zip(data, root=td)
            self.assertEqual(n, 2)
        self.assertLess(len(data), update.MAX_ZIP_BYTES)
        self.assertEqual(update.MAX_ENTRIES, 20000)
        self.assertEqual(update.MAX_TOTAL_BYTES, 256 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
