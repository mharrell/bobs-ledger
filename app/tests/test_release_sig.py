"""The release signature policy: what a release must prove before it installs.

`app/update.py` used to accept any zip whose sha256 matched the manifest it came
with — the same server, the same request, the same trust. These tests are the
control on the replacement: a release is installed only when it carries a
signature by the PINNED key over every field that matters, and every way of
being unproven ends in a refusal rather than in a download.

The fixture key is synthetic (`bytes(range(32))`); the real private key lives
offline and is never in this repository or in a release.
"""
import base64
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
for path in (APP, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import ed25519          # noqa: E402
import release_key_fixture as fixture  # noqa: E402
import release_sig      # noqa: E402


class TestCanonical(unittest.TestCase):
    """What the signature covers, and how it stays stable."""

    def test_it_is_stable_across_field_order(self):
        """A dict's order does not survive a JSON round trip, so signing the
        serialization as it happened to be ordered would produce signatures
        that verify on the publisher's machine and not on a player's."""
        a = {"version": "v1", "created": "t", "zip_sha256": "s"}
        b = {"zip_sha256": "s", "created": "t", "version": "v1"}
        self.assertEqual(release_sig.canonical(a), release_sig.canonical(b))

    def test_it_drops_only_the_signature(self):
        base = {"version": "v1", "sig": "a" * 128}
        self.assertEqual(release_sig.canonical(base),
                         release_sig.canonical({"version": "v1"}))

    def test_it_is_bytes_and_json(self):
        canon = release_sig.canonical({"version": "v1"})
        self.assertIsInstance(canon, bytes)
        self.assertEqual(canon, b'{"version":"v1"}')

    def test_an_empty_or_odd_manifest_does_not_raise(self):
        self.assertEqual(release_sig.canonical(None), b"{}")
        self.assertEqual(release_sig.canonical({}), b"{}")


class TestSignAndVerify(unittest.TestCase):

    def setUp(self):
        self.restore = fixture.pin()
        self.addCleanup(self.restore)
        self.manifest = fixture.signed()

    def test_a_signed_manifest_verifies(self):
        ok, why = release_sig.verify_manifest(self.manifest)
        self.assertTrue(ok, why)
        self.assertEqual(why, "signed")

    def test_every_field_is_covered(self):
        """Change anything the signature claims and it stops verifying — the
        version, the timestamp that decides "newer", the note shown to the
        player, and the zip's name, size and hash."""
        for key in fixture.MANIFEST:
            tampered = dict(self.manifest)
            value = tampered[key]
            tampered[key] = (value + 1) if isinstance(value, int) else (
                str(value) + "x")
            with self.subTest(field=key):
                ok, why = release_sig.verify_manifest(tampered)
                self.assertFalse(ok, f"a changed {key} must not verify")
                self.assertIn("does not match the pinned key", why)

    def test_a_changed_signature_is_refused(self):
        tampered = dict(self.manifest)
        tampered["sig"] = "0" + tampered["sig"][1:]
        ok, why = release_sig.verify_manifest(tampered)
        self.assertFalse(ok)
        self.assertIn("does not match", why)

    def test_signing_another_key_does_not_help(self):
        """The whole threat model in one test: an attacker who can serve any
        manifest they like still cannot produce one this client accepts."""
        private_other = bytes(range(1, 33))
        forged = release_sig.sign_manifest(fixture.MANIFEST, private_other)
        ok, why = release_sig.verify_manifest(forged)
        self.assertFalse(ok)
        self.assertIn("does not match the pinned key", why)

    def test_the_signature_survives_the_json_round_trip(self):
        """The manifest is published as JSON TEXT and parsed back on the client,
        and `publish_release` writes it with ensure_ascii=False. The signature
        covers the VALUES, so a release note carrying an em dash or an accented
        character has to verify after that trip — this is the one place the
        signature could agree in Python and disagree over the wire."""
        manifest = fixture.signed(dict(fixture.MANIFEST,
                                       note="tempo mode \u2014 caf\u00e9 \u2603"))
        wire = json.dumps(manifest, ensure_ascii=False)
        ok, why = release_sig.verify_manifest(json.loads(wire))
        self.assertTrue(ok, why)
        # ...and the same value re-encoded the other way must not matter either.
        escaped = json.dumps(manifest, ensure_ascii=True)
        self.assertTrue(release_sig.verify_manifest(json.loads(escaped))[0])


class TestUnprovenReleasesAreRefused(unittest.TestCase):
    """Each refusal that stands between a tampered channel and an install."""

    def setUp(self):
        self.restore = fixture.pin()
        self.addCleanup(self.restore)

    def _refuse(self, manifest):
        ok, why = release_sig.verify_manifest(manifest)
        self.assertFalse(ok)
        return why

    def test_an_unsigned_manifest_is_refused(self):
        why = self._refuse(dict(fixture.MANIFEST))
        self.assertIn("no signature", why)

    def test_a_signature_with_no_algorithm_is_refused(self):
        """A `sig` whose `sig_alg` was stripped is not a signature this build
        can act on: it cannot know what scheme produced it."""
        signed = fixture.signed()
        del signed["sig_alg"]
        why = self._refuse(signed)
        self.assertIn("does not know", why)

    def test_an_unknown_algorithm_is_refused(self):
        signed = fixture.signed()
        signed["sig_alg"] = "rsa-please-trust-me"
        why = self._refuse(signed)
        self.assertIn("does not know", why)

    def test_signature_shapes_are_not_negotiable(self):
        for bad in ["", "beef", "A" * 128, "z" * 128, "0" * 127, 12345, None]:
            signed = fixture.signed()
            signed["sig"] = bad
            with self.subTest(sig=bad):
                self._refuse(signed)

    def test_a_manifest_that_is_not_an_object_is_refused(self):
        for bad in [None, [], "signed", 7]:
            with self.subTest(manifest=bad):
                ok, why = release_sig.verify_manifest(bad)
                self.assertFalse(ok)
                self.assertIn("not an object", why)

    def test_a_build_with_no_pinned_key_refuses_everything(self):
        """Including a perfectly signed release: without a pin there is
        nothing to check against, and "no pin" must never mean "no check"."""
        unpin = fixture.unpin()
        self.addCleanup(unpin)
        why = self._refuse(fixture.signed())
        self.assertIn("no release signing key is pinned", why)

    def test_a_malformed_pin_is_a_refusal_not_a_pass(self):
        for bad in ["not base64!!", base64.b64encode(b"short").decode()]:
            os.environ["HEARTH_RELEASE_PUBKEY"] = bad
            self.addCleanup(os.environ.pop, "HEARTH_RELEASE_PUBKEY", None)
            with self.subTest(pin=bad):
                self.assertFalse(
                    release_sig.verify_manifest(fixture.signed())[0])


class TestKeyFiles(unittest.TestCase):
    """The operator's side: how a key is made, read and never clobbered."""

    def test_a_raw_key_round_trips(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "release.key")
            private, public, print_fp = release_sig.new_key(path)
            self.assertEqual(release_sig.read_private_key(path), private)
            self.assertEqual(print_fp, release_sig.fingerprint(public))
            self.assertEqual(ed25519.public_key_of(private), public)

    def test_a_hex_key_file_is_read_too(self):
        """Because that is how an offline key actually travels between a
        backup and a publishing machine."""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "key.hex")
            seed = bytes(range(32))
            with open(path, "w", encoding="utf-8") as f:
                f.write(seed.hex() + "\n")
            self.assertEqual(release_sig.read_private_key(path), seed)

    def test_a_key_of_the_wrong_size_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "short.key")
            with open(path, "wb") as f:
                f.write(b"\x01" * 20)
            with self.assertRaises(ValueError):
                release_sig.read_private_key(path)

    def test_keygen_refuses_to_overwrite_an_existing_key(self):
        """The worst mistake available here: regenerating in place silently
        invalidates every installed copy's pin."""
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "release.key")
            release_sig.new_key(path)
            with open(path, "rb") as f:
                before = f.read()
            with self.assertRaises(ValueError):
                release_sig.new_key(path)
            with open(path, "rb") as f:
                self.assertEqual(f.read(), before)

    def test_a_new_key_is_not_world_readable(self):
        if os.name != "posix":
            self.skipTest("mode bits are a POSIX idea")
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "release.key")
            release_sig.new_key(path)
            self.assertEqual(os.stat(path).st_mode & 0o077, 0)

    def test_the_shipped_pin_is_coherent(self):
        """Either a real 32-byte key is pinned, or nothing is — and if nothing
        is, verification refuses (which the class above proves). What must never
        happen is a pin that is present and unusable."""
        if not release_sig.PUBKEY_B64:
            self.skipTest("this build pins no key yet (verification refuses)")
        key = release_sig.pinned_public_key(env={})
        self.assertEqual(len(key), ed25519.PUBLIC_KEY_BYTES)

    def test_env_override_beats_the_shipped_pin(self):
        key = release_sig.pinned_public_key(
            env={"HEARTH_RELEASE_PUBKEY": fixture.TEST_PUBLIC_B64})
        self.assertEqual(key, ed25519.public_key_of(fixture.TEST_SEED))


if __name__ == "__main__":
    unittest.main()
