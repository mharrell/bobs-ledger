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
import datetime
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_COACH = os.path.join(_HERE, "hearth-coach")
sys.path.insert(0, _COACH)

import privacy_scan  # noqa: E402  (hearth-coach/privacy_scan.py)

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
                ".wrangler", "logs_archive", "transcripts"}

#: Paths that never ship, matched as prefixes from the repo root. Basename
#: matching can't express these — "tests" would drop hearth-coach/tests too.
EXCLUDE_PATHS = {
    # Internal research: replay reviews name real opponents and session
    # directories. The 2026-09-2x reviews carried the maintainer's own
    # BattleTag and an opponent's handle into a public download.
    "hearth-coach/analysis",
    # Maintainer infrastructure: KV namespace id + deploy runbook.
    "telemetry",
    # Upstream python-hslog keeps real third-party BattleTags in its test
    # fixtures; shipping someone else's account handles is not ours to do.
    "hearth-coach/python-hslog/tests",
    "hearth-coach/python-hslog/.github",
    "hearth-coach/python-hslog/hslog.egg-info",
}

EXCLUDE_FILES = {".art_miss.json", ".cards_cache.json",
                 ".trinkets_hsjson_cache.json", ".trinkets_guides_cache.json",
                 ".cards_full.json", ".observed_tribes.json",
                 ".patch_state.json", ".patch_config.json",
                 "comp_candidates.json",
                 ".dev.vars", "claude_code_zai_env.sh", "VERSION",
                 "CLAUDE.md", "catch_up_main.ps1", "wt_status.ps1",
                 "register_patch_check.ps1", "sync.py", "publish_release.py"}

#: Always written fresh by this script, so a stale local copy must not win
#: the zip's duplicate-entry race (VERSION is excluded for the same reason).
GENERATED = ("VERSION", ".update_state.json")

#: Entries allowed to be in the zip without being tracked by git: the two
#: generated stamps, the vendored parser (gitignored by design, but required
#: to run, so it must ship), and the card->tribe map. That last one used to
#: be fetched from HearthstoneJSON on first use — a ~10 MB blocking download
#: on the live path that also made the README's "no internet for normal
#: play" false, and that failed silently when offline (2026-10-02).
#: Shipping the snapshot removes the first-run download; log-derived tribes
#: still override it for new cards (bans.bans_from_log).
UNTRACKED_OK = {"VERSION", ".update_state.json", "hearth-coach/.card_races.json"}
UNTRACKED_OK_PREFIX = ("hearth-coach/python-hslog/",)


def git_sha():
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=_HERE,
                          capture_output=True, text=True,
                          timeout=10).stdout.strip() or "unknown"


def tracked_files():
    r = subprocess.run(["git", "ls-files"], cwd=_HERE, capture_output=True,
                       text=True, timeout=60)
    return {p.replace("\\", "/") for p in r.stdout.splitlines() if p.strip()}


def uncommitted():
    """Tracked files whose content differs from HEAD (staged or not)."""
    r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                       cwd=_HERE, capture_output=True, text=True, timeout=60)
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
        for dirpath, dirnames, filenames in os.walk(_HERE):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for fn in filenames:
                if fn in EXCLUDE_FILES or fn in GENERATED \
                        or fn.endswith(".pyc") or fn.endswith(".env"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, _HERE).replace(os.sep, "/")
                if _excluded(rel):
                    continue
                z.write(full, rel)
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
    print("published. Users update via `python update.py` or on their next "
          "live.py start.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
