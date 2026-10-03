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
import stat
import sys
import urllib.request
import zipfile

from config import LAUNCHERS  # noqa: E402 - config.py, beside this file

_HERE = os.path.dirname(os.path.abspath(__file__))


def _install_root():
    """Where VERSION and .update_state.json live.

    A release unpacks the code at the zip's ROOT, so the stamps sit beside
    this file. The project's earlier layout nested the code one level down
    (`hearth-coach/`) with the stamps above it, and a checkout of that shape
    must keep working — so prefer whichever directory actually holds a
    VERSION file, and fall back to this one (2026-10-02, the spin-out into
    its own repository made the flat layout the normal case).
    """
    if os.path.exists(os.path.join(_HERE, "VERSION")):
        return _HERE
    parent = os.path.dirname(_HERE)
    if os.path.exists(os.path.join(parent, "VERSION")):
        return parent
    return _HERE


ROOT = _install_root()                 # the install root: VERSION's home
VERSION_FILE = os.path.join(ROOT, "VERSION")
STATE_FILE = os.path.join(ROOT, ".update_state.json")
MANIFEST_URL = os.environ.get(
    "HEARTH_UPDATE_URL",
    "https://hearth-telemetry-collector.bobs-ledger.workers.dev/release/latest.json")
UA = "hearth-coach-telemetry/1.0"  # workers.dev 403s the python-urllib UA

#: Zip entries that may never overwrite local data, by path segment.
#: Matched at ANY depth: every shipped path is nested under the repo folder
#: (`decision_logs/...`), so a first-segment-only test never
#: fired — the guard was inert while both the docstring and PROTECTED
#: claimed local data was protected (found 2026-10-02 by applying a
#: realistically nested zip: decision logs were overwritten).
PROTECTED = {"decision_logs", "corpus_out", ".review_cache", ".git",
             ".claude", "img_cache",
             # The player's sharing answer and the local copies of what was
             # shared: an update must never overwrite either, and a consent
             # question silently re-asked after an update would be its own
             # kind of wrong.
             ".share_consent.json", "session_reports"}


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
            if os.path.exists(target) and not os.access(target, os.W_OK):
                # Windows cannot open a read-only file for writing, so a file
                # that arrived read-only would fail the whole update. Same
                # attribute problem as _force_rmtree, same fix.
                try:
                    os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
                except OSError:
                    pass
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if rel in LAUNCHERS and os.name == "posix":
                # zipfile does not restore permissions on extract, so a
                # launcher that arrived with a mode in the zip would still land
                # non-executable here — and a Mac player cannot double-click a
                # .command without +x. Applying the mode is our job, not the
                # archiver's.
                try:
                    os.chmod(target, 0o755)
                except OSError:
                    pass
            written += 1
    return written


# --- reshaping a pre-app/ install -------------------------------------------
#: Before app/, the release unpacked the code AT the install root. Updating
#: one of those installs only ADDS app/ — the old flat tree stays behind, so
#: the player keeps all 62 loose files the reorganisation existed to remove.
#: These lists are the whole migration: local data follows the code, the old
#: shipped tree is deleted, nothing else at the root is touched.
_OLD_ROOT_DIRS = ("meta", "tests", "python-hslog", "__pycache__")
_OLD_ROOT_FILES = ("bobs-ledger.ico", "requirements.txt",
                   "requirements-dev.txt", "DESIGN.md", "ROADMAP.md",
                   ".gitattributes", ".gitignore")
_MOVES_INTO_APP = ("decision_logs", "corpus_out", ".review_cache", "img_cache",
                   "patch_reports", "transcripts", "reports",
                   ".art_miss.json", ".card_races.json", ".cards_cache.json",
                   ".cards_full.json", ".observed_tribes.json",
                   ".patch_state.json", ".patch_config.json",
                   ".trinkets_hsjson_cache.json",
                   ".trinkets_guides_cache.json", "comp_candidates.json")
#: Root entries a reshape must never delete: the new layout uses them too, or
#: they are the player's own.
_KEEP_AT_ROOT = {"README.md", "LICENSE", "docs",
                 "VERSION", ".update_state.json", "Bob's Ledger.lnk", "app",
                 # Every zip carries both launchers, and a reshape must not
                 # eat the one this platform actually starts.
                 *LAUNCHERS}


def _app_dir():
    return os.path.join(ROOT, "app")


def _force_rmtree(path):
    """rmtree that survives Windows' read-only bit.

    A directory that was copied off OneDrive, a CD or a read-only share
    carries FILE_ATTRIBUTE_READONLY, and rmtree refuses to delete such a
    directory with WinError 5 - nothing is locked, it is just an attribute.
    The rehearsal against a real OneDrive install left three stale
    directories behind for exactly this reason (2026-10-02), so clear the bit
    and retry instead of reporting a failure that is not one.
    """
    def _retry(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            raise

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry)
    else:                           # onexc arrived in 3.12; README says 3.9+
        shutil.rmtree(path, onerror=_retry)


def looks_pre_app(data):
    """True when the release uses app/ and the install is still the flat one:
    the zip carries app/live.py and a live.py sits at the install root."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = {n.replace("\\", "/") for n in z.namelist()}
    except Exception:  # noqa: BLE001 - apply_zip reports an unreadable zip
        return False
    return "app/live.py" in names and os.path.exists(
        os.path.join(ROOT, "live.py"))


def _move_into_app(name):
    """Move one local-data item into app/. Returns a line, or None.

    A directory is MERGED, never replaced: a collision must not destroy a
    file. A file the release already provided is dropped instead, because the
    shipped copy is the newer one.
    """
    src = os.path.join(ROOT, name)
    if name in _KEEP_AT_ROOT or not os.path.exists(src):
        return None
    dst = os.path.join(_app_dir(), name)
    os.makedirs(_app_dir(), exist_ok=True)
    if os.path.isdir(src):
        if not os.path.exists(dst):
            shutil.move(src, dst)
            return f"moved {name}/"
        merged = 0
        for entry in sorted(os.listdir(src)):
            if not os.path.exists(os.path.join(dst, entry)):
                shutil.move(os.path.join(src, entry),
                            os.path.join(dst, entry))
                merged += 1
        try:
            os.rmdir(src)
        except OSError:
            pass                # a colliding file is legitimately still there
        return f"merged {merged} file(s) into {name}/"
    if os.path.exists(dst):
        os.remove(src)
        return f"dropped the outdated {name}"
    shutil.move(src, dst)
    return f"moved {name}"


def migrate_flat_layout(data):
    """Reshape a flat install into the app/ layout. Returns what it did.

    Called AFTER apply_zip, deliberately: a failure here leaves a working
    install with some data still at the root, which is recoverable. Moving
    first would leave the OLD code running with its data already gone.
    """
    if not looks_pre_app(data):
        return []
    done = []
    for name in _MOVES_INTO_APP:
        try:
            line = _move_into_app(name)
        except OSError as exc:      # a locked cache must not stop the update
            line = f"could not move {name} ({exc})"
        if line:
            done.append(line)
    for name in _OLD_ROOT_DIRS:
        path = os.path.join(ROOT, name)
        if name in _KEEP_AT_ROOT or not os.path.exists(path):
            continue
        # Only once the release has put its own copy in app/ — before that,
        # this directory is the only code the install has.
        if name != "__pycache__" and not os.path.exists(
                os.path.join(_app_dir(), name)):
            continue
        try:
            _force_rmtree(path)
            done.append(f"removed the old {name}/")
        except OSError as exc:
            done.append(f"could not remove the old {name}/ ({exc})")
    stale = [f for f in _OLD_ROOT_FILES
             if os.path.exists(os.path.join(ROOT, f))]
    # Every module that now lives in app/ has a stale twin at the root. A
    # root .py with NO twin is the player's own file and is left alone.
    stale += [f for f in os.listdir(ROOT)
              if f.endswith(".py")
              and os.path.exists(os.path.join(_app_dir(), f))]
    for name in sorted(set(stale)):
        if name in _KEEP_AT_ROOT:
            continue
        try:
            os.remove(os.path.join(ROOT, name))
            done.append(f"removed the old {name}")
        except OSError as exc:
            done.append(f"could not remove {name} ({exc})")
    return done


def _ask(prompt_text, timeout=20.0):
    """A y/n answer from the console that can never hang.

    The update check runs BEFORE the overlay starts (live.py), so a question
    nobody answers is a coach that never appears: the player double-clicks,
    does not read the console, and nothing happens. The first version of this
    called input() and waited forever (2026-10-03).

    No terminal at all — a service, a redirected stdin, a scheduled task —
    means no question: the answer is "no" and they are asked again next start,
    which is exactly what a decline does.
    """
    if not sys.stdin or not sys.stdin.isatty():
        return ""
    print(prompt_text, end="", flush=True)
    try:
        import msvcrt
        import time as _time
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                print(ch)
                return ch.strip().lower()
            _time.sleep(0.05)
        print()
        return ""
    except ImportError:
        import select
        ready, _w, _x = select.select([sys.stdin], [], [], timeout)
        if not ready:
            print()
            return ""
        return sys.stdin.readline().strip().lower()


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
            if _ask("update now? [y/N] ") != "y":
                print("skipped — you'll be asked again next start")
                return "declined"
        data = download_zip(manifest, key=key)
        n = apply_zip(data)
        reshaped = migrate_flat_layout(data)
        save_state(manifest)
        print(f"updated to {manifest['version']} ({n} files). "
              "Restart the coach if it is running.")
        if reshaped:
            print("  tidied up after the old layout: "
                  + "; ".join(reshaped[:6])
                  + (" ..." if len(reshaped) > 6 else ""))
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
