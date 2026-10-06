#!/usr/bin/env python3
"""Scan every blob ever committed for THIS project's personal data.

The release gate (`publish_release.privacy_gate`) scans the ZIP. It cannot see
HISTORY, and that gap has a shape: a BattleTag committed on Tuesday and replaced
with a placeholder on Wednesday is still in the repository forever, and this
repository is public. So "is there anything personal in here?" has two answers,
and this tool is the second one.

It is `privacy_scan` — the same independent verifier the gate uses, never a
second copy of the patterns — pointed at every blob reachable from every ref
instead of at the files in a zip. What it sees is exactly what privacy_scan
sees: BattleTags, player-name fields, bare opponent handles, account ids, local
user paths and session directory names. What it cannot see is the category
CLAUDE.md warns about (a handle under a JSON `"name"` key); `package_corpus`
strips those by name, and no pattern scanner can.

The other half is credentials, which this does not look for at all:

    gitleaks git . --log-opts="--all" --redact --no-banner
    python app/history_scan.py --json

Values are MASKED by default: the useful output is a category, a path and a
commit, not someone's handle printed a second time. `--full` prints them, for
the maintainer's own eyes on the maintainer's own machine — and it is the reason
this tool is a maintainer tool and does not ship.
"""
import argparse
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import privacy_scan  # noqa: E402  (beside this file)

REPO = os.path.dirname(_HERE)


def _git(repo, *args, text=True):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    return r.stdout.decode("utf-8", "replace") if text else r.stdout


def blob_map(repo):
    """{blob sha: the path it is reachable as} for every ref, every commit."""
    out = {}
    for line in _git(repo, "rev-list", "--objects", "--all").splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2:
            out[parts[0]] = parts[1]
    return out


def blob_contents(repo, shas):
    """{sha: bytes} — one `cat-file --batch` for all of them, not one process each.

    A history scan reads thousands of objects; shelling out per object is the
    difference between two seconds and two minutes.
    """
    p = subprocess.Popen(["git", "-C", repo, "cat-file", "--batch"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    out, _ = p.communicate(("\n".join(shas) + "\n").encode())
    contents, i = {}, 0
    while i < len(out):
        nl = out.index(b"\n", i)
        header = out[i:nl].decode("utf-8", "replace").split()
        if len(header) != 3:
            break
        sha, _kind, size = header[0], header[1], int(header[2])
        contents[sha] = out[nl + 1:nl + 1 + size]
        i = nl + 1 + size + 1
    return contents


def _head_blob(repo, path):
    r = subprocess.run(["git", "-C", repo, "rev-parse", f"HEAD:{path}"],
                       capture_output=True)
    return r.stdout.decode().strip() if r.returncode == 0 else None


def _paths_touching(repo, sha):
    """Every path that ever carried this blob.

    `rev-list --objects` attaches ONE path to an object, and git stores
    identical content once: two fixtures with the same text are a single blob
    with a single path, so a report built only from that map can name one file
    while the value sits in two (found by this tool's own test, 2026-10-07).
    The question a report has to answer is "which files is this in", so the
    paths come from the commits that touched the object instead.
    """
    lines = _git(repo, "log", "--all", "--format=", "--name-only",
                 f"--find-object={sha}")
    return sorted({l.strip() for l in lines.splitlines() if l.strip()})


def _added_by(repo, path, limit=2):
    """The commit(s) that first put this path in the repository.

    The useful question about a historical finding is "when did this enter",
    and `--diff-filter=A` answers it directly. Per-blob commit lists would
    otherwise list every edit that ever rewrote the file, which is noise: one
    unchanged line in a file edited twenty times is twenty blobs.
    """
    lines = _git(repo, "log", "--all", "--date=short", "--diff-filter=A",
                 "--format=%h %ad %s", "--", path)
    return [l for l in lines.splitlines() if l.strip()][:limit]


def scan(repo=REPO):
    """One row per (category, value, FILE) in the whole history.

    Aggregation is deliberate. git stores a new blob for every edit, so a tag
    sitting untouched in a file with 20 revisions is 20 blobs — reporting that
    as "20 findings" buries the two facts that matter: which files carry it,
    and whether it is still there. `blobs` counts the occurrences instead.
    """
    blobs = blob_map(repo)
    contents = blob_contents(repo, list(blobs))
    findings, head_cache = {}, {}
    for sha, data in contents.items():
        if b"\x00" in data[:4096]:      # binary: not ours to interpret
            continue
        text = data.decode("utf-8", "replace")
        found = privacy_scan.find(text)
        if not found:
            continue
        # Only for flagged blobs: this is one git call per flagged object, not
        # one per object in the repository.
        paths = _paths_touching(repo, sha) or [blobs.get(sha, "?")]
        for path in paths:
            if path not in head_cache:
                head_cache[path] = _head_blob(repo, path)
        for category, values in found.items():
            for value in values:
                for path in paths:
                    key = (category, value, path)
                    rec = findings.get(key)
                    if rec is None:
                        rec = findings[key] = {
                            "category": category,
                            "value": value,
                            "path": path,
                            "paths": paths,
                            "blobs": 0,
                            "in_head": False,
                            "added_by": _added_by(repo, path),
                        }
                    rec["blobs"] += 1
                    rec["paths"] = sorted(set(rec["paths"]) | set(paths))
                    if head_cache[path] == sha:
                        rec["in_head"] = True
    return sorted(findings.values(),
                  key=lambda r: (r["category"], r["path"], r["value"]))


def mask(value):
    """Enough to recognise it, not enough to republish it."""
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 3)}{value[-1]}"


def report(findings, full=False, per_category=6):
    if not findings:
        print("history scan: nothing personal in any committed blob.")
        return 0
    by_cat = {}
    for f in findings:
        by_cat.setdefault(f["category"], []).append(f)
    live = [f for f in findings if f["in_head"]]
    blobs = sum(f.get("blobs", 1) for f in findings)
    print(f"history scan: {len(findings)} place(s) — one per value and file — "
          f"across {len(by_cat)} categor(y/ies)\n"
          f"              {blobs} blob occurrence(s); {len(live)} place(s) "
          f"still in the working tree\n")
    for category in sorted(by_cat):
        rows = by_cat[category]
        files = sorted({r["path"] for r in rows})
        print(f"[{category}] {len(rows)} place(s) in {len(files)} file(s)")
        for f in rows[:per_category]:
            where = ("IN THE WORKING TREE" if f["in_head"]
                     else "removed later, still in history")
            shown = f["value"] if full else mask(f["value"])
            print(f"   {shown}  ({where}, {f.get('blobs', 1)} blob(s))")
            print(f"     path: {f['path']}")
            for c in (f.get("added_by") or [])[:2]:
                print(f"     added by: {c}")
        if len(rows) > per_category:
            print(f"   ... and {len(rows) - per_category} more")
        print()
    print("What to do with each: a value IN THE WORKING TREE is an edit and a "
          "commit.\nA value that was removed later is a history question — "
          "git-filter-repo, or\naccept it, because rewriting history changes "
          "every commit id and the shas are\nthis project's release version "
          "strings.")
    return 1


def main():
    # A finding is a person's name or a non-ASCII handle, and this repo's own
    # commit subjects carry a BOM (one of them crashes a cp1252 console mid-
    # report, which would hide the very findings this exists to surface).
    # Same fix, same reason, as publish_release.py's gate output.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:               # noqa: BLE001 - older stream, best effort
        pass
    ap = argparse.ArgumentParser(
        description="Scan every blob in git history for personal data, using "
                    "privacy_scan (the same verifier the release gate uses).")
    ap.add_argument("--repo", default=REPO, help="the repository to scan")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--full", action="store_true",
                    help="print the values themselves instead of masking them "
                         "(for your own eyes, on your own machine)")
    args = ap.parse_args()
    findings = scan(args.repo)
    if args.json:
        print(json.dumps({"findings": findings,
                          "in_head": sum(1 for f in findings if f["in_head"]),
                          "total": len(findings)},
                         ensure_ascii=False, indent=1))
        return 1 if findings else 0
    return report(findings, full=args.full)


if __name__ == "__main__":
    sys.exit(main())
