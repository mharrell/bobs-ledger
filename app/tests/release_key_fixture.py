"""A test-only release signing key, and a signed manifest to go with it.

NOT a real key, and never used to sign a real release: the seed is
`bytes(range(32))`, written as an expression rather than as a blob of hex, so
that no key-shaped string sits in this repository for a scanner — or a reader —
to find. A fixture's job is to be obviously synthetic.

The pin travels by ENVIRONMENT (`HEARTH_RELEASE_PUBKEY`), which is the same
door `release_sig.py` opens for a self-hosted build. That matters for more than
convenience: it means these tests exercise the REAL verification path rather
than a patched-out stand-in, so a change that breaks verification breaks them.
"""
import base64
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
if APP not in sys.path:
    sys.path.insert(0, APP)

import ed25519          # noqa: E402  (app/ed25519.py)
import release_sig      # noqa: E402  (app/release_sig.py)

#: The fixture seed. Any 32 bytes would do; counting is easier to recognise.
TEST_SEED = bytes(range(32))

TEST_PUBLIC_B64 = base64.b64encode(
    ed25519.public_key_of(TEST_SEED)).decode("ascii")

#: A published release, as the fixture key signs it. The sha256 is of the
#: string "zip", which is all these tests need it to be.
MANIFEST = {"schema": 1, "version": "newer999", "note": "fixes the ranking",
            "created": "2026-10-07T12:00:00",
            "zip_name": "bobs-ledger-newer999.zip",
            "zip_sha256": "0" * 64, "zip_bytes": 3}


def signed(manifest=None):
    """`manifest` (or MANIFEST) signed by the fixture key."""
    return release_sig.sign_manifest(dict(manifest or MANIFEST), TEST_SEED)


def pin():
    """Point this process at the fixture key. Returns a restore callable.

    Used as `self.addCleanup(release_key_fixture.pin())`: the pin is set now,
    and the environment is put back when the test ends.
    """
    saved = os.environ.get("HEARTH_RELEASE_PUBKEY")
    os.environ["HEARTH_RELEASE_PUBKEY"] = TEST_PUBLIC_B64

    def restore():
        if saved is None:
            os.environ.pop("HEARTH_RELEASE_PUBKEY", None)
        else:
            os.environ["HEARTH_RELEASE_PUBKEY"] = saved
    return restore


def unpin():
    """Make this process look like a build with no key pinned at all.

    Clears the environment override AND the compiled-in pin, because either one
    alone would still answer.
    """
    saved_env = os.environ.pop("HEARTH_RELEASE_PUBKEY", None)
    saved_pin = release_sig.PUBKEY_B64
    release_sig.PUBKEY_B64 = ""

    def restore():
        release_sig.PUBKEY_B64 = saved_pin
        if saved_env is not None:
            os.environ["HEARTH_RELEASE_PUBKEY"] = saved_env
    return restore
