#!/usr/bin/env python3
"""Sign a release, and check one. The reason the update channel is not a
single point of trust any more.

The gap this closes, stated plainly: `update.py` downloaded a zip and checked
its sha256 against `release/latest.json` — served from the SAME server as the
zip. That proves the bytes were not corrupted in transit. It proves nothing
about who produced them: whoever can write the release manifest can write the
hash beside it too. The updater's own docstring said "verify its sha256 against
the manifest", and a checksum that arrives with the payload is not a check.

A signature is the difference between "the bytes match" and "I made these
bytes". The private key never touches the release server, so a compromised
Cloudflare account (or KV namespace, or the maintainer's laptop) can serve
whatever it likes and every install refuses it. The failure mode becomes an
outage instead of an infection, which is the trade worth making.

    PUBLIC KEY  is pinned below (`PUBKEY_B64`) and ships in every install.
    PRIVATE KEY lives offline. It is never in this repo, never in the release
                zip, never in the Cloudflare account, and never in CI.

Making a key, once:

    python app/release_sig.py --keygen ~/.bobs-ledger-release.key
    # prints the public key line to paste into PUBKEY_B64 below
    python app/release_sig.py --pubkey ~/.bobs-ledger-release.key   # re-print it

`publish_release.py` reads the private key from `HEARTH_SIGNING_KEY` (a PATH)
and REFUSES to publish without it. There is no --allow-unsigned: an unsigned
release is exactly the thing this module exists to make impossible, and a gate
with a convenience flag becomes a flag.

Set `HEARTH_RELEASE_PUBKEY` (base64) to verify against a different key — that
is how the tests sign without the real key, and how a self-hosted build could
pin its own.
"""
import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import sys

import ed25519            # vendored RFC 8032 Ed25519, beside this file

#: The pinned release key: base64 of the 32-byte Ed25519 public key whose
#: signature every release must carry.  EMPTY MEANS UNPINNED, and unpinned
#: means every update is refused (see verify_manifest) — deliberately. A build
#: that cannot check a signature must not pretend an unsigned release is fine;
#: it has to say so out loud, because the alternative is a client that keeps
#: installing whatever the server sends and calls that "verifying".
PUBKEY_B64 = "eUPhYxVly7fZDVD+lJlgGTtQ7XxLopX26h7mQJx77HU="

#: The manifest fields that carry the signature, and which algorithm it is.
#: `sig_alg` is inside the signed body, so it cannot be rewritten to point at
#: some scheme the client would treat more leniently.
SIG_KEY = "sig"
ALG_KEY = "sig_alg"
ALG = "ed25519"

#: A signature is 64 bytes of hex, and a hex string is not a place to be
#: flexible: a manifest carrying "0x..." or uppercase is one this module did
#: not write.
_SIG_HEX = re.compile(r"^[0-9a-f]{128}$")


def pinned_public_key(env=None):
    """The 32-byte key a release must be signed with, or None when unpinned.

    A malformed pin is NOT None — it is a hard refusal with its own reason, so
    a typo in the pinned key cannot quietly turn into "no key configured, carry
    on". See verify_manifest.
    """
    raw = (env or os.environ).get("HEARTH_RELEASE_PUBKEY")
    b64 = (raw if raw is not None else PUBKEY_B64) or ""
    b64 = b64.strip()
    if not b64:
        return None
    try:
        key = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("the pinned release public key is not valid base64")
    if len(key) != ed25519.PUBLIC_KEY_BYTES:
        raise ValueError(
            f"the pinned release public key must be "
            f"{ed25519.PUBLIC_KEY_BYTES} bytes, got {len(key)}")
    return key


def fingerprint(public_key):
    """A short, comparable name for a key: what `--keygen` and publish print.

    Not a security boundary — a fingerprint you can see is how a human notices
    that the key which signed a release is not the key they think they pinned.
    """
    return hashlib.sha256(bytes(public_key)).hexdigest()[:16]


def canonical(manifest):
    """The exact bytes a release signature covers.

    Every field EXCEPT the signature, sorted and compactly encoded, so the
    signature covers the whole claim: version, timestamp, note, and the zip's
    name, size and sha256. That last one is the point — the signature is over
    the hash of the artifact, which chains to the artifact itself.

    Sorting matters: a dict's order is not guaranteed to survive a round trip
    through JSON, so signing the serialized text as it happened to be ordered
    would produce signatures that verify on one machine and not another.
    """
    body = {k: v for k, v in (manifest or {}).items() if k != SIG_KEY}
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def sign_manifest(manifest, private_key):
    """`manifest` plus `sig_alg` and `sig`, signed by `private_key` (32 bytes).

    The returned dict is what gets published. `sig` is written LAST and is the
    only field canonical() drops, so inserting it cannot change what was signed.
    """
    signed = {k: v for k, v in dict(manifest).items() if k != SIG_KEY}
    signed[ALG_KEY] = ALG
    signed[SIG_KEY] = ed25519.sign(private_key, canonical(signed)).hex()
    return signed


def verify_manifest(manifest, public_key=None):
    """(ok, reason). Fail closed — every path that is not "proven" is False.

    Reasons are written to be printed to a player, because "the update was
    refused" with no reason is indistinguishable from a broken client. The
    caller decides what to say; this decides only whether the release is
    proven, and an unproven release is never installed.
    """
    if not isinstance(manifest, dict):
        return False, "the release manifest is not an object"
    sig_hex = manifest.get(SIG_KEY)
    alg = manifest.get(ALG_KEY)
    if not sig_hex:
        return False, ("this release carries no signature — it was published "
                       "before releases were signed, or the channel was "
                       "tampered with")
    if alg != ALG:
        return False, (f"release signed with {alg!r}, which this build does "
                       f"not know (it verifies {ALG!r})")
    if not isinstance(sig_hex, str) or not _SIG_HEX.match(sig_hex):
        return False, "the release signature is not a 64-byte hex string"
    try:
        key = public_key if public_key is not None else pinned_public_key()
    except ValueError as exc:
        return False, str(exc)
    if key is None:
        return False, ("no release signing key is pinned in this build, so no "
                       "release can be proven genuine")
    if len(key) != ed25519.PUBLIC_KEY_BYTES:
        return False, "the pinned release public key is the wrong size"
    if not ed25519.verify(key, canonical(manifest), bytes.fromhex(sig_hex)):
        return False, ("the release signature does not match the pinned key "
                       f"{fingerprint(key)}")
    return True, "signed"


# --- the operator's side: key files ------------------------------------------

def read_private_key(path):
    """The 32-byte seed in `path`: raw bytes, or hex if the file is text.

    Both shapes on purpose: a raw 32-byte file is what keygen writes, and hex
    survives being copied through a password manager or a chat window, which is
    how an offline key actually travels between a backup and a publishing
    machine.
    """
    with open(path, "rb") as f:
        raw = f.read()
    stripped = raw.strip()
    if len(stripped) == 2 * ed25519.PRIVATE_KEY_BYTES:
        try:
            return bytes.fromhex(stripped.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            pass
    if len(raw) != ed25519.PRIVATE_KEY_BYTES:
        raise ValueError(
            f"{path} holds {len(raw)} bytes — an Ed25519 private key is "
            f"{ed25519.PRIVATE_KEY_BYTES} raw bytes, or "
            f"{2 * ed25519.PRIVATE_KEY_BYTES} hex characters")
    return raw


def write_key(path, private_key):
    """Write a new private key, refusing to clobber one that already exists.

    The refusal is the important half: the single worst mistake available here
    is regenerating the key in place, which silently invalidates every installed
    copy's pin and forces a manual reinstall on every player.
    """
    if os.path.exists(path):
        raise ValueError(f"{path} already exists — refusing to overwrite a "
                         "signing key (move it aside first if that is really "
                         "what you want)")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(bytes(private_key))
    except Exception:
        os.remove(path)
        raise
    return path


def new_key(path):
    """(private_key, public_key, fingerprint) after writing a fresh key."""
    private_key, public_key = ed25519.keygen()
    write_key(path, private_key)
    return private_key, public_key, fingerprint(public_key)


def signing_key_from_env(env=None):
    """The private key `publish_release` signs with, or None when unset."""
    path = (env or os.environ).get("HEARTH_SIGNING_KEY")
    if not path:
        return None
    return read_private_key(path)


def main():
    ap = argparse.ArgumentParser(
        description="Create a release signing key, or print its public half.")
    ap.add_argument("--keygen", metavar="PATH",
                    help="create a new private key at PATH and print the "
                         "PUBKEY_B64 line to paste into this module")
    ap.add_argument("--pubkey", metavar="PATH",
                    help="print the public key and fingerprint of an existing "
                         "private key")
    args = ap.parse_args()
    if args.keygen:
        try:
            _, public, print_fp = new_key(args.keygen)
        except (ValueError, OSError) as exc:
            print(f"refused: {exc}")
            return 1
        b64 = base64.b64encode(public).decode("ascii")
        print(f"private key written to {args.keygen} (keep it offline)\n")
        print(f"fingerprint: {print_fp}\n")
        print("paste this into app/release_sig.py:\n")
        print(f'PUBKEY_B64 = "{b64}"')
        return 0
    if args.pubkey:
        try:
            private = read_private_key(args.pubkey)
        except (ValueError, OSError) as exc:
            print(f"could not read {args.pubkey}: {exc}")
            return 1
        public = ed25519.public_key_of(private)
        print(f"fingerprint: {fingerprint(public)}\n")
        print(f'PUBKEY_B64 = "{base64.b64encode(public).decode("ascii")}"')
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
