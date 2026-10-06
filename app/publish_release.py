#!/usr/bin/env python3
"""Package the current tree as a release and publish it for auto-update.

One command per release (maintainer only — it uses your `wrangler` auth):

    python publish_release.py --note "tempo mode, welcome screen"
    python publish_release.py --note "..." --dry-run    # gate only, no upload

Writes a zip of the project (code + meta + user docs; NO local data —
decision_logs/, corpus_out/, .review_cache/, .git/.claude/, the regenerable
caches and the internal research notes are excluded), a VERSION file
stamped with the git sha, an .update_state.json so a freshly unzipped
install can itself be offered the NEXT release, and a manifest {version,
note, zip sha256, created} — then PUTs the zip and manifest to the KV
namespace the collector serves:

    GET  <collector>/release/latest.json   (public)
    GET  <collector>/release/latest.zip    (public — 302 to the current zip)
    GET  <collector>/release/<zip>.zip     (public — the install path)

TWO GATES RUN BEFORE ANYTHING IS UPLOADED (added 2026-10-02, after the
published zip turned out to carry the maintainer's BattleTag, an opponent's
name, five third-party BattleTags, a local Windows profile path and the
maintainer's session directory names — while the README promised BattleTags
were redacted before anything left the machine):

  1. PRIVACY — every text entry is scanned by privacy_scan, which is
     independent code from the sanitizer. Any finding refuses the publish.
  2. REPRODUCIBILITY — the zip is built by walking the WORKING TREE while
     `version` is HEAD, so uncommitted or stray content would ship under a
     committed sha. Uncommitted edits and unexpected untracked entries also
     refuse the publish.

Both have explicit overrides (`--allow-personal`, `--allow-dirty`) so a
deliberate exception is a decision rather than an accident.
"""
import argparse
import base64
import datetime
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))     # the code: <repo>/app
#: The tree that SHIPS — one level above the code, so a player's folder is
#: the launcher, the README, the licence and app/ and nothing else.
#: git and the zip walk both need this rather than _HERE: `git ls-files` run
#: from a subdirectory lists only that subdirectory, which would have made
#: every shipped file look stray (2026-10-02).
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)          # the code sits in app/

import privacy_scan  # noqa: E402  (privacy_scan.py, beside this file)
import release_sig  # noqa: E402  (release_sig.py + ed25519.py, beside this file)
from config import LAUNCHERS  # noqa: E402  (config.py, beside this file)

# A gate that finds non-ASCII content (accented handles, the em dash in its
# own report) must not die reporting it: the Windows console is cp1252, and
# a UnicodeEncodeError here would hide the very findings the gate exists to
# surface. Best effort — an older stream without reconfigure() still works.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

#: Directory and file names that never ship, by basename anywhere in the
#: tree: local data, dev plumbing, regenerable caches.
EXCLUDE_DIRS = {".git", ".claude", "decision_logs", "corpus_out",
                ".review_cache", "__pycache__", ".venv", "venv", ".idea",
                "img_cache", "node_modules", "patch_reports",
                ".wrangler", "logs_archive", "transcripts",
                # Local sharing state: the player's consent answer lives in
                # .share_consent.json, the copies of everything sent live in
                # session_reports/, and the maintainer's fetched reports land
                # in sessions_in/. None of it belongs in a download.
                "session_reports", "sessions_in"}

#: Paths that never ship, matched as prefixes from the repo root. Basename
#: matching can't express these — "tests" would drop the test suite too.
EXCLUDE_PATHS = {
    # Internal research: replay reviews name real opponents and session
    # directories. The 2026-09-2x reviews carried the maintainer's own
    # BattleTag and an opponent's handle into a public download.
    "analysis",
    # Maintainer infrastructure: KV namespace id + deploy runbook. It is the
    # release channel itself, not something a player runs.
    "telemetry",
    # The vendored parser ships, but upstream's tests keep real third-party
    # BattleTags in their fixtures — shipping someone else's account handles
    # is not ours to do.
    "app/python-hslog/tests",
    "app/python-hslog/.github",
    "app/python-hslog/hslog.egg-info",
}

EXCLUDE_FILES = {".art_miss.json", ".cards_cache.json",
                 ".trinkets_hsjson_cache.json", ".trinkets_guides_cache.json",
                 ".cards_full.json", ".observed_tribes.json",
                 ".patch_state.json", ".patch_config.json",
                 ".share_consent.json",
                 # Where THIS install was told the game lives (2026-10-06).
                 # Machine-specific, written by config.py --set, and read at
                 # import by every tool: shipping it would hand a player the
                 # packager's path, and the reproducibility gate would refuse
                 # it as an untracked entry anyway.
                 ".hs_home.json",
                 # The release signing key (2026-10-07). The private half never
                 # travels, and naming it here means a maintainer who keeps it
                 # inside the tree cannot ship it by accident — the thing the
                 # whole update channel's trust rests on must not be one
                 # --allow-dirty away from a public download.
                 ".bobs-ledger-release.key", "release_signing_key",
                 "comp_candidates.json",
                 # Maintainer tooling that reads this repository's own history
                 # and can print what it finds unmasked (`--full`). A player has
                 # no history to scan, and the one thing it must not do is
                 # travel: it exists to find names, not to carry them.
                 "history_scan.py",
                 # The secrets-scan config: maintainer tooling, and the
                 # allowlist in it is about this repo's test vectors.
                 ".gitleaks.toml",
                 ".dev.vars", "claude_code_zai_env.sh", "VERSION",
                 "CLAUDE.md", "catch_up_main.ps1", "wt_status.ps1",
                 "register_patch_check.ps1", "sync.py", "publish_release.py",
                 # The LLM tooling. The coach advises from a local value
                 # function and the meta DB — no model is called during play
                 # — but these made a user-facing download look like an LLM
                 # product: coach_llm.py is the client, compare_models.py is
                 # a model-comparison harness, and patch_notes.py /
                 # check_patch_notes.py / patch_day.py exist only to feed the
                 # patch-notes extractor. They stay in the repo for the
                 # maintainer; the release is the rule-based coach
                 # (2026-10-02).
                 "coach_llm.py", "compare_models.py", "patch_notes.py",
                 "check_patch_notes.py", "patch_day.py",
                 # Repo plumbing and maintainer docs. They stay in the repo
                 # for whoever works on the coach; a player's folder is the
                 # launcher, the README, the licence and app/.
                 # PIVOT.md is the ToS/posture decision record: it argues about
                 # what the product is allowed to say, which is the last thing a
                 # player's download should carry.
                 ".gitattributes", ".gitignore", "DESIGN.md", "ROADMAP.md",
                 "PIVOT.md"}

#: Always written fresh by this script, so a stale local copy must not win
#: the zip's duplicate-entry race (VERSION is excluded for the same reason).
GENERATED = ("VERSION", ".update_state.json")

#: Entries allowed to be in the zip without being tracked by git: the two
#: generated stamps and the card->tribe map. That last one used to be fetched
#: from HearthstoneJSON on first use — a ~10 MB blocking download on the live
#: path that also made the README's "no internet for normal play" false, and
#: that failed silently when offline (2026-10-02). Shipping the snapshot
#: removes the first-run download; log-derived tribes still override it for
#: new cards (bans.bans_from_log).
UNTRACKED_OK = {"VERSION", ".update_state.json", "app/.card_races.json"}
#: The vendored parser used to be gitignored, so a clone lacked it while the
#: zip had it. It is tracked now (the spin-out made repo and release the same
#: tree), and this prefix stays as a safety net for a checkout that got it
#: some other way.
UNTRACKED_OK_PREFIX = ("app/python-hslog/",)


def git_sha():
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=_REPO,
                          capture_output=True, text=True,
                          timeout=10).stdout.strip() or "unknown"


def tracked_files():
    r = subprocess.run(["git", "ls-files"], cwd=_REPO, capture_output=True,
                       text=True, timeout=60)
    return {p.replace("\\", "/") for p in r.stdout.splitlines() if p.strip()}


def uncommitted():
    """Tracked files whose content differs from HEAD (staged or not)."""
    r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                       cwd=_REPO, capture_output=True, text=True, timeout=60)
    return [l for l in r.stdout.splitlines() if l.strip()]


def _excluded(rel):
    if rel in EXCLUDE_FILES or os.path.basename(rel) in EXCLUDE_FILES:
        return True
    # Never ship a shortcut: a .lnk embeds ABSOLUTE paths, so one made on the
    # packager's machine is broken on everyone else's. The launcher creates
    # its own, on the machine that will use it.
    if rel.lower().endswith(".lnk"):
        return True
    return any(rel == p or rel.startswith(p + "/") for p in EXCLUDE_PATHS)


def _mark_executable(z, rel):
    """Give a launcher the executable bit inside the zip.

    The zip is built on Windows, where a file has no Unix mode, so the entry
    lands as 0o666 — and macOS unarchives a .command that nobody can run or
    double-click (measured in the published zip: 0o666, 2026-10-03).
    create_system 3 is what tells an unarchiver these bits are Unix ones
    rather than a DOS attribute.
    """
    info = z.getinfo(rel)
    info.create_system = 3
    info.external_attr = 0o100755 << 16


def build_zip(version, created):
    """The release zip in memory.

    VERSION at the root is the update join: update.py compares it against
    the manifest's version. `.update_state.json` is the same join's OTHER
    half — the publish time this install carries — and without it a fresh
    zip could never be offered a later release (2026-10-02).
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("VERSION", version + "\n")
        z.writestr(".update_state.json",
                   json.dumps({"version": version, "created": created}))
        for dirpath, dirnames, filenames in os.walk(_REPO):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for fn in filenames:
                if fn in EXCLUDE_FILES or fn in GENERATED \
                        or fn.endswith(".pyc") or fn.endswith(".env"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, _REPO).replace(os.sep, "/")
                if _excluded(rel):
                    continue
                z.write(full, rel)
                if rel in LAUNCHERS:
                    _mark_executable(z, rel)
    return buf.getvalue()


def privacy_gate(data):
    """Every privacy_scan finding inside the zip, as (entry, findings)."""
    found = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            if not info.filename.lower().endswith(privacy_scan.TEXT_SUFFIXES):
                continue
            try:
                body = z.read(info).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 - unreadable entry, skip
                continue
            hits = privacy_scan.find(body)
            if hits:
                found.append((info.filename, hits))
    return found


def reproducibility_gate(data):
    """Zip entries that are neither tracked nor expected artifacts."""
    tracked = tracked_files()
    stray = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            rel = name.replace("\\", "/")
            if rel in UNTRACKED_OK or rel in tracked:
                continue
            if rel.startswith(UNTRACKED_OK_PREFIX):
                continue
            stray.append(rel)
    return stray


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--note", required=True,
                    help="one line for the user-facing update alert")
    ap.add_argument("--namespace", default="abd7803c581b4470a2834e92ae0006a2",
                    help="the collector's KV namespace id")
    ap.add_argument("--dry-run", action="store_true",
                    help="build and run both gates, upload nothing")
    ap.add_argument("--allow-personal", action="store_true",
                    help="publish even if the privacy gate finds something")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="publish with uncommitted or stray content")
    ap.add_argument("--no-github", action="store_true",
                    help="skip creating/updating the GitHub release (the KV "
                         "copy still ships, but the Releases page a player "
                         "downloads from would be left behind)")
    ap.add_argument("--signing-key", metavar="PATH",
                    help="the offline Ed25519 private key to sign this release "
                         "with (default: $HEARTH_SIGNING_KEY). Required: an "
                         "unsigned release is refused by every install that "
                         "has the signature check.")
    args = ap.parse_args()

    version = git_sha()
    created = datetime.datetime.now().isoformat(timespec="seconds")
    data = build_zip(version, created)
    sha = hashlib.sha256(data).hexdigest()
    zip_name = f"bobs-ledger-{version}.zip"
    print(f"release {version}: {zip_name} "
          f"({len(data) / 1e6:.1f} MB, sha {sha[:12]})")
    print(f"  note: {args.note}")

    blocked = False

    print("\nprivacy gate:")
    hits = privacy_gate(data)
    if hits:
        blocked = not args.allow_personal
        print(f"  FAIL — {len(hits)} file(s) in the zip carry personal data:")
        for name, findings in hits[:20]:
            for line in privacy_scan.describe(name, findings):
                print(line)
        if len(hits) > 20:
            print(f"  (+{len(hits) - 20} more files)")
        print("  add the path to EXCLUDE_PATHS/EXCLUDE_FILES, or redact the "
              "file; --allow-personal overrides.")
    else:
        print("  PASS — no BattleTags, opponent handles, account ids, local "
              "paths or session names in any shipped text file.")

    print("\nreproducibility gate:")
    dirty = uncommitted()
    stray = reproducibility_gate(data)
    if dirty or stray:
        blocked = blocked or not args.allow_dirty
        if dirty:
            print(f"  uncommitted changes to {len(dirty)} tracked file(s):")
            for line in dirty[:10]:
                print(f"    {line}")
        if stray:
            print(f"  {len(stray)} entry/entries in the zip are not tracked "
                  "by git:")
            for rel in stray[:10]:
                print(f"    {rel}")
        print("  commit first, exclude the path, or pass --allow-dirty.")
    else:
        print("  PASS — the zip matches HEAD, with no stray entries.")

    print("\nsigning gate:")
    key_path = args.signing_key or os.environ.get("HEARTH_SIGNING_KEY")
    private_key = None
    if not key_path:
        blocked = True
        print("  FAIL — no signing key: pass --signing-key PATH, or set "
              "HEARTH_SIGNING_KEY.")
        print("  Every install that has the check refuses an unsigned release, "
              "so there is nothing to publish without a key. Make one with:")
        print("    python app/release_sig.py --keygen ~/.bobs-ledger-release.key")
    else:
        try:
            private_key = release_sig.read_private_key(key_path)
            public = release_sig.ed25519.public_key_of(private_key)
        except (ValueError, OSError) as exc:
            blocked = True
            print(f"  FAIL — cannot use the key at {key_path}: {exc}")
        else:
            print(f"  key: {key_path}  fingerprint "
                  f"{release_sig.fingerprint(public)}")
            # The pin is what INSTALLS check, so a release signed by a key the
            # shipped client does not carry is a release nobody can install.
            # That failure would only show up on a player's machine, one
            # "REFUSING this update" at a time, so it is caught here instead.
            shipped = release_sig.pinned_public_key(env={})
            if shipped is None:
                blocked = True
                print("  FAIL — app/release_sig.py pins no public key "
                      "(PUBKEY_B64 is empty), so nothing could verify this "
                      "release. Paste this line in and publish again:")
                print(f'    PUBKEY_B64 = '
                      f'"{base64.b64encode(public).decode("ascii")}"')
            elif shipped != public:
                blocked = True
                print(f"  FAIL — this build pins "
                      f"{release_sig.fingerprint(shipped)}, but {key_path} is "
                      f"{release_sig.fingerprint(public)}. Publishing now would "
                      f"ship a release that every install refuses.")
            else:
                ok, why = release_sig.verify_manifest(
                    release_sig.sign_manifest({"probe": 1}, private_key),
                    public)
                if not ok:
                    blocked = True
                    print(f"  FAIL — the key cannot sign and verify a probe "
                          f"manifest: {why}")
                else:
                    print("  PASS — signed with the pinned key, and a probe "
                          "manifest round-trips through the verifier.")

    if blocked:
        print("\nREFUSING to publish. Nothing was uploaded.")
        return 1

    if args.dry_run:
        print("\ndry run: gates passed, nothing uploaded.")
        return 0

    manifest = {
        "schema": 1,
        "version": version,
        "note": args.note,
        "created": created,
        "zip_name": zip_name,
        "zip_sha256": sha,
        "zip_bytes": len(data),
    }
    # Signed LAST, over every field above: the signature covers the note a
    # player is shown, the timestamp that decides "newer", and the sha256 that
    # chains to the zip itself (2026-10-07).
    manifest = release_sig.sign_manifest(manifest, private_key)
    signer = release_sig.fingerprint(
        release_sig.ed25519.public_key_of(private_key))
    print(f"\nsigned with {signer} (sig {manifest['sig'][:16]}...)")
    tmp_zip = os.path.join(os.environ.get("TEMP", _HERE),
                           f"rel_{version}.zip")
    tmp_manifest = os.path.join(os.environ.get("TEMP", _HERE),
                                "release_latest.json")
    with open(tmp_zip, "wb") as f:
        f.write(data)
    with open(tmp_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    try:
        for key, path in ((f"release/{zip_name}", tmp_zip),
                          ("release/latest.json", tmp_manifest)):
            # npx is npx.cmd on Windows — CreateProcess needs the resolved
            # name, not the npm shim. Both values go via --path: wrangler v4
            # takes exactly one of <value> (positional) or --path, and a
            # JSON manifest as a positional arg is quoting roulette.
            cmd = [shutil.which("npx") or "npx.cmd", "--yes", "wrangler",
                   "kv", "key", "put", key,
                   "--namespace-id", args.namespace, "--remote",
                   "--path", path]
            r = subprocess.run(cmd, cwd=_HERE,
                               capture_output=True, timeout=300)
            if r.returncode != 0:
                raise RuntimeError(
                    f"kv put {key} failed: {r.stderr.decode()[:300]}")
            print(f"  uploaded {key}")
    finally:
        for p in (tmp_zip, tmp_manifest):
            if os.path.exists(p):
                os.remove(p)

    # A GitHub release too, so there is a page a human can land on:
    # /releases/latest shows the version, the note and a Download button. The
    # README used to tell players to fetch latest.json and read "zip_name" out
    # of it — an API instruction dressed up as a user instruction, since the
    # name carries a commit sha nobody can guess (2026-10-02).
    if not args.no_github:
        github_release(version, args.note, data, zip_name)

    print("published. Users update via `python update.py` or on their next "
          "live.py start.")
    return 0


def github_release(version, note, data, zip_name):
    """Attach the zip to the GitHub release for this version.

    Best effort on purpose: the KV copy is what the UPDATER reads, and a
    GitHub hiccup must not fail a publish — but it is said loudly, because
    the README sends players to the Releases page.
    """
    gh = shutil.which("gh")
    if not gh:
        print("  note: `gh` not found — skipping the GitHub release. Players "
              "can still download from /release/latest.zip")
        return
    # Name the temp file what the ASSET should be called: `gh release
    # create` takes the asset name from the filename, and the first
    # release went out as "gh_cb95911.zip" — a scratch name a player
    # would be right to distrust (2026-10-03).
    tmp = os.path.join(os.environ.get("TEMP", _HERE), zip_name)
    with open(tmp, "wb") as f:
        f.write(data)
    try:
        exists = subprocess.run([gh, "release", "view", version],
                                cwd=_HERE, capture_output=True,
                                timeout=120).returncode == 0
        if exists:
            cmd = [gh, "release", "upload", version, tmp, "--clobber"]
            what = "updated"
        else:
            body = (f"{note}\n\n"
                    "### Install\n\n"
                    "1. Download and unzip `" + zip_name +
                    "` anywhere.\n"
                    "2. Double-click **Start Bob's Ledger.cmd** in the folder "
                    "you unzipped.\n\n"
                    "It finds Python, checks the one dependency (asking "
                    "first), and starts the overlay. Windows only; "
                    "Hearthstone's file logging must be on — the coach's "
                    "welcome card shows the exact setting.\n")
            cmd = [gh, "release", "create", version, tmp,
                   "--title", f"Bob's Ledger {version}",
                   "--notes", body]
            what = "created"
        r = subprocess.run(cmd, cwd=_HERE, capture_output=True, timeout=300)
        if r.returncode != 0:
            print(f"  WARNING: `gh release {what}` failed — the Releases page "
                  f"is now BEHIND this release: "
                  f"{r.stderr.decode()[:200].strip()}")
        else:
            print(f"  GitHub release {what}: "
                  f"https://github.com/mharrell/bobs-ledger/releases/latest")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


if __name__ == "__main__":
    sys.exit(main())
