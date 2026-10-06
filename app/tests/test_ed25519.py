"""The vendored Ed25519, pinned to the RFC's own test vectors.

`app/ed25519.py` claims to be RFC 8032 Appendix A's implementation, extracted
mechanically from the RFC text. A claim like that is worth nothing unless it can
be checked, so this module runs the RFC's section 7.1 vectors through it: five
vectors, taken from the RFC itself and committed as a fixture by a script rather
than retyped, covering an empty message, one byte, two bytes, 1023 bytes and the
SHA(abc) case.

What that buys: Ed25519 signatures are DETERMINISTIC, so a correct
implementation must reproduce the RFC's signature bytes exactly, not merely
verify them. One altered curve constant, one mis-copied hash or a flipped
comparison fails here rather than silently accepting forgeries later.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
for path in (APP, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import ed25519  # noqa: E402

VECTORS_PATH = os.path.join(HERE, "rfc8032_vectors.json")


def _vectors():
    with open(VECTORS_PATH, encoding="utf-8") as f:
        return json.load(f)["vectors"]


class TestRfc8032Section71(unittest.TestCase):
    """The RFC's vectors, and the RFC's implementation, agreeing."""

    def test_the_fixture_still_holds_the_five_vectors(self):
        """A control on the control: an empty or truncated fixture would make
        every other test in this class pass by doing nothing."""
        vectors = _vectors()
        self.assertEqual([v["name"] for v in vectors],
                         ["TEST 1", "TEST 2", "TEST 3", "TEST 1024",
                          "TEST SHA(abc)"])
        self.assertEqual(sorted(len(bytes.fromhex(v["message"]))
                                for v in vectors),
                         [0, 1, 2, 64, 1023],
                         "the message lengths ARE the coverage: an empty one, "
                         "an odd one, and one that spans many hash blocks")

    def test_signatures_are_reproduced_byte_for_byte(self):
        for v in _vectors():
            with self.subTest(vector=v["name"]):
                mine = ed25519.sign(bytes.fromhex(v["secret_key"]),
                                    bytes.fromhex(v["message"]))
                self.assertEqual(mine.hex(), v["signature"])

    def test_public_keys_derive_from_the_seed(self):
        for v in _vectors():
            with self.subTest(vector=v["name"]):
                self.assertEqual(
                    ed25519.public_key_of(bytes.fromhex(v["secret_key"])).hex(),
                    v["public_key"])

    def test_the_rfcs_signatures_verify(self):
        for v in _vectors():
            with self.subTest(vector=v["name"]):
                self.assertTrue(ed25519.verify(
                    bytes.fromhex(v["public_key"]),
                    bytes.fromhex(v["message"]),
                    bytes.fromhex(v["signature"])))


class TestItFailsClosed(unittest.TestCase):
    """`verify` returns False for everything it cannot prove.

    This is the property the updater leans on: the caller's alternative to
    "proven" is "refuse the release", so a verifier that raises, or that says
    yes to a malformed input, is a verifier the update path cannot trust.
    """

    def setUp(self):
        self.seed = bytes(range(32))
        self.public = ed25519.public_key_of(self.seed)
        self.other = ed25519.public_key_of(bytes(range(1, 33)))
        self.message = b"a release manifest"
        self.sig = ed25519.sign(self.seed, self.message)

    def test_the_good_case_works(self):
        """Without this, every refusal below could be refusing everything."""
        self.assertTrue(ed25519.verify(self.public, self.message, self.sig))

    def test_a_changed_message_is_refused(self):
        self.assertFalse(ed25519.verify(self.public, self.message + b"!",
                                        self.sig))
        self.assertFalse(ed25519.verify(self.public, self.message[:-1],
                                        self.sig))

    def test_a_changed_signature_is_refused(self):
        for i in (0, 31, 32, 63):
            flipped = bytearray(self.sig)
            flipped[i] ^= 0x01
            with self.subTest(byte=i):
                self.assertFalse(ed25519.verify(self.public, self.message,
                                                bytes(flipped)))

    def test_a_different_key_cannot_verify_it(self):
        self.assertFalse(ed25519.verify(self.other, self.message, self.sig))

    def test_wrong_sizes_and_shapes_are_refused_not_raised(self):
        cases = [
            (b"", self.message, self.sig),                 # no key
            (self.public, self.message, self.sig[:-1]),     # short signature
            (self.public, self.message, self.sig + b"\x00"),  # long signature
            (self.public[:-1], self.message, self.sig),     # short key
            (self.public, self.message, b""),               # no signature
            (None, self.message, self.sig),                 # not bytes
            (self.public, None, self.sig),
            (self.public, self.message, None),
            ("x" * 32, self.message, self.sig),             # str, not bytes
        ]
        for key, msg, sig in cases:
            with self.subTest(key=key, sig=sig):
                self.assertFalse(ed25519.verify(key, msg, sig))

    def test_a_public_key_that_is_not_a_point_is_refused(self):
        """32 bytes of y that never lie on the curve: the decode raises inside
        the vendored code, and that has to come back as False, not as a
        traceback out of an update check."""
        self.assertFalse(ed25519.verify(b"\xff" * 32, self.message, self.sig))
        self.assertFalse(ed25519.verify(b"\x00" * 32, self.message, self.sig))

    def test_a_key_of_the_wrong_length_cannot_be_signed_with(self):
        with self.assertRaises(ValueError):
            ed25519.sign(b"\x01" * 31, self.message)


class TestTheVendoringIsWhatItClaims(unittest.TestCase):
    """The provenance note, and the absence of what was deliberately dropped."""

    def _source(self):
        with open(os.path.join(APP, "ed25519.py"), encoding="utf-8") as f:
            return f.read()

    def test_it_names_its_source(self):
        text = self._source()
        self.assertIn("RFC 8032", text)
        self.assertIn("Appendix A", text)

    def test_the_dropped_sections_really_are_dropped(self):
        """Ed448 and the SHA-3/SHAKE machinery were left out on purpose. These
        are CODE symbols the dropped sections define, so this stays a check on
        what was vendored rather than on what the prose happens to mention."""
        text = self._source()
        for absent in ("Edwards448Point", "shake256", "sha3_transform"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, text)


if __name__ == "__main__":
    unittest.main()
