#!/usr/bin/env python3
"""Check for a Bob's Ledger release and apply it.

Flow (also wired into live.py's startup): GET the update manifest from the
collector, decide direction against this install (see decide()), and if the
release is NEWER — after a y/N prompt — download the release zip, verify its
sha256 against the manifest, and extract it over the install directory.
Your local data (decision_logs/, corpus_out/, .review_cache/ and the
dev-side .claude/.git) is never touched. live.py restarts itself when an
update applies, so a checked-and-accepted update is one prompt.

Direction: release versions are git shas — there is no ordering. The
manifest's publish timestamp decides, compared against the timestamp this
install last updated at. A released zip carries that stamp inside it
(`.update_state.json`, written by publish_release.py at build time), so a
freshly unzipped install can be told a newer release exists; without it the
first check could only ever answer "unknown" and the README's "zip installs
keep themselves current" was unreachable (found 2026-10-02). A git checkout
has no VERSION and stays "unknown" — shas can't prove which side is newer,
and guessing once downgraded a fresh clone of main onto the older published
zip. `--force` applies regardless.

An update check must never block play: every failure mode (offline, no
manifest, bad json) returns "no update" and the coach starts normally.

Usage:
    python update.py            # prompt+apply if the release is newer
    python update.py --check    # report only
    python update.py --yes      # apply without prompting
    python update.py --force    # apply even if direction is unknown/local-newer
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import urllib.request
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)          # the repo/install root
VERSION_FILE = os.path.join(ROOT, "VERSION")
STATE_FILE = os.path.join(ROOT, ".update_state.json")
MANIFEST_URL = os.environ.get(
    "HEARTH_UPDATE_URL",
    "https://hearth-telemetry-collector.bobs-ledger.workers.dev/release/latest.json")
UA = "hearth-coach-telemetry/1.0"  # workers.dev 403s the python-urllib UA

#: Zip entries that may never overwrite local data, by path segment.
#: Matched at ANY depth: every shipped path is nested under the repo folder
#: (`hearth-coach/decision_logs/...`), so a first-segment-only test never
#: fired — the guard was inert while both the docstring and PROTECTED
#: claimed local data was protected (found 2026-10-02 by applying a
#: realistically nested zip: decision logs were overwritten).
PROTECTED = {"decision_logs", "corpus_out", ".review_cache", ".git",
             ".claude"}


def local_version():
    """This install's version: the VERSION file a release carries, else the
    git sha (a developer checkout), else unknown — and unknown is offered
    the update."""
    if os.path.exists(VERSION_FILE):
        return open(VERSION_FILE, encoding="utf-8").read().strip()
    try:
        import subprocess
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=ROOT, capture_output=True, text=True,
                              timeout=5).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def fetch_manifest(timeout=8):
    """The latest release manifest, or None on any failure."""
    try:
        req = urllib.request.Request(MANIFEST_URL,
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - offline/4xx/bad json: not an error
        return None


def load_state():
    """The last-applied release record, or {} (git checkout / legacy zip)."""
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:  # noqa: BLE001 - absent/corrupt state == no state
        return {}


def save_state(manifest):
    """Record the release this install now carries (version + publish time)."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"version": manifest.get("version"),
                   "created": manifest.get("created")}, f)


def decide(local, manifest, state=None):
    """(action, detail) for this install vs the published release.

    Actions: "current" (nothing to do), "update" (the release is newer),
    "local-newer" (this install updated after the release was published),
    "unknown" (versions differ but nothing proves which is newer). Only
    "update" ever auto-offers. The timestamps are isoformat strings from
    the same publishing machine, so string comparison is the ordering.
    """
    if not manifest or not manifest.get("version"):
        return "current", ""
    created = manifest.get("created") or ""
    if state and state.get("created") and created:
        if created > state["created"]:
            return ("update",
                    f"{state.get('version') or local} -> {manifest['version']}")
        if created < state["created"]:
            return ("local-newer",
                    f"{state.get('version') or local} is newer than the "
                    f"published release {manifest['version']}")
        return "current", ""
    # No update state: a version match still counts as current, but any
    # other difference is unorderable — refuse to guess.
    if manifest["version"] == local:
        return "current", ""
    return ("unknown",
            f"installed {local or 'unknown'}, published {manifest['version']} "
            f"({created or 'no date'})")


def download_zip(manifest, key=None):
    """The release zip's bytes, sha-verified against the manifest."""
    key = key or os.environ.get("HEARTH_TELEMETRY_KEY")
    name = manifest.get("zip_name") or ""
    if not name.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise ValueError(f"suspicious zip name: {name!r}")
    headers = {"User-Agent": UA}
    if key:
        headers["X-Telemetry-Key"] = key
    req = urllib.request.Request(
        MANIFEST_URL.rsplit("/", 1)[0] + "/" + name, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    sha = hashlib.sha256(data).hexdigest()
    if sha != manifest.get("zip_sha256"):
        raise ValueError(
            f"zip sha mismatch: got {sha[:12]}, "
            f"manifest says {str(manifest.get('zip_sha256'))[:12]}")
    return data


def _safe_target(root, rel):
    """Absolute path for a zip entry, or None if it must be refused.

    Refuses zip-slip in every form Windows accepts, not just the POSIX
    ones: `..` components, absolute POSIX paths, drive-letter absolutes
    (`C:/evil.dll`), drive-relative paths and NTFS alternate data streams
    (any component containing `:`), and UNC (`//host/share`). The earlier
    guard tested only `startswith("/")` and `..`, so `C:/evil.dll` passed
    and `os.path.join` — where an absolute second argument discards the
    first — wrote outside the install root (found 2026-10-02).

    The resolved path is re-checked against the root afterwards, so a form
    nobody thought of still has to get past commonpath().
    """
    rel = (rel or "").replace("\\", "/")
    if rel.startswith("/"):
        return None                 # absolute POSIX path or UNC (//host/share)
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts:
        return None
    for part in parts:
        if part == ".." or ":" in part:
            return None
    root_abs = os.path.abspath(root)
    target = os.path.abspath(os.path.join(root_abs, *parts))
    try:
        if os.path.commonpath([root_abs, target]) != root_abs:
            return None
    except ValueError:          # different drives: not under root
        return None
    return target


def apply_zip(data, root=None):
    """Extract a release zip over the install, protecting local data.

    Returns the count of files written. Entries under a PROTECTED path
    segment are skipped at any depth (the user's decision logs and settings
    survive an update), and zip-slip entries are refused — see
    _safe_target.
    """
    root = root or ROOT
    written = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            rel = (info.filename or "").replace("\\", "/")
            if any(p in PROTECTED
                   for p in rel.split("/") if p not in ("", ".")):
                continue
            target = _safe_target(root, rel)
            if target is None:
                continue
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            written += 1
    return written


def run(prompt=True, assume_yes=False, key=None, force=False):
    """The full check flow. Returns 'applied', 'current', or 'declined'."""
    manifest = fetch_manifest()
    action, detail = decide(local_version(), manifest, load_state())
    if action == "current":
        print("Bob's Ledger is up to date.")
        return "current"
    if action == "update" or force:
        if action != "update":
            print(f"--force: applying regardless ({detail})")
        print(f"Update available: {detail}"
              + (f" — {manifest['note']}" if manifest.get("note") else ""))
        if prompt and not assume_yes:
            try:
                answer = input("update now? [y/N] ").strip().lower()
            except EOFError:
                answer = ""
            if answer != "y":
                print("skipped — you'll be asked again next start")
                return "declined"
        data = download_zip(manifest, key=key)
        n = apply_zip(data)
        save_state(manifest)
        print(f"updated to {manifest['version']} ({n} files). "
              "Restart live.py if it is running.")
        return "applied"
    # local-newer / unknown: never guess direction (a fresh clone of a
    # newer main once looked "behind" and would have been downgraded).
    # A checkout is told the truth about how it updates; only a released
    # install with no update state gets the --force advice.
    if action == "unknown" and not os.path.exists(VERSION_FILE):
        print("Development checkout — a clone updates with `git pull`, so "
              f"the release channel stands aside (published: "
              f"{manifest.get('version')}).")
        return "current"
    print(f"No update applied — {detail}. "
          "Use `python update.py --force` to install the published release "
          "anyway.")
    return "current"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="apply without prompting")
    ap.add_argument("--force", action="store_true",
                    help="apply even when the newer side can't be proven")
    args = ap.parse_args()
    if args.check:
        m = fetch_manifest()
        action, detail = decide(local_version(), m, load_state())
        if action == "update":
            print(f"update available: {detail}"
                  + (f" — {m.get('note')}" if m.get("note") else ""))
            return 1
        if action == "current":
            print("Bob's Ledger is up to date.")
        else:
            print(f"{action}: {detail} (use --force to install anyway)")
        return 0
    return 0 if run(prompt=not args.yes, assume_yes=args.yes,
                    force=args.force) != "declined" else 1


if __name__ == "__main__":
    sys.exit(main())
