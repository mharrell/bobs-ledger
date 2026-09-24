#!/usr/bin/env python3
"""One call that answers "is anything wrong right now?" — in <=15 lines.

Every problem this session hit was found by accident, mid-task, and then cost
tokens to diagnose: the `requests` import dead for 2.5 weeks, the Battlegrounds
section extracting to 92 characters, `refresh_trinkets.py` unrun since 09-13,
`Aberration` missing from the tribe roster, `BACON_COMBAT_DAMAGE_CAP` frozen at 2.
Each would have shown up here in one line.

Design rules, both from the billing model:
  - the OUTPUT is the expensive part, so every check prints one line and the
    whole thing stays under ~15, with a single verdict at the end;
  - never a raw dump. Detail is behind --json or left to the tool that owns it
    (`check_patch_db.py`, `playable.py`, `check_meta.py` are the gates; this
    just tells you whether to run them).

Usage:
  python doctor.py [--online] [--full] [--json]
    --online  also check the Blizzard news page for a patch newer than the DB
    --full    also run the test suite (adds ~20s)
"""
import argparse
import datetime
import glob
import json
import os
import subprocess
import sys
from collections import OrderedDict

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import logquery  # noqa: E402
import meta  # noqa: E402

FAIL, WARN, OK = "FAIL", "WARN", "ok"


def _run(script, *args):
    """Run a sibling tool; return (ok, last non-empty line)."""
    try:
        p = subprocess.run([sys.executable, script, *args], cwd=_HERE,
                           capture_output=True, text=True, timeout=300)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}"
    tail = [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
    return p.returncode == 0, (tail[-1] if tail else "")


def _db_patch():
    """What patch the DB is actually ON.

    Preferred source is the log-mined roster, because that is written by our own
    pipeline and describes the card pool we really have. `meta/.patch_state.json`
    is only check_patch_notes.py's dedup latch, and it stays on the last patch
    that tool reported — after 36.6.1 was applied by hand it still read 36.4.2,
    which made the online check announce a patch we had already integrated. A
    health check that cries wolf trains you to ignore it.
    """
    try:
        with open(os.path.join(_HERE, "meta", "pool_roster.json"),
                  encoding="utf-8") as f:
            got = json.load(f).get("patch")
            if got:
                return got, "roster"
    except (OSError, ValueError):
        pass
    try:
        with open(os.path.join(_HERE, "meta", ".patch_state.json"),
                  encoding="utf-8") as f:
            return json.load(f).get("last_title") or "?", "patch_state"
    except (OSError, ValueError):
        return "?", "nothing"


def check_patch(online):
    """Is the meta DB on the newest patch the official page knows about?"""
    have, source = _db_patch()
    if not online:
        return WARN, (f"DB patch: {have} (from {source}) — pass --online to "
                      f"check the official page")
    try:
        import patch_notes as pn
        url, article = pn.discover_latest()
    except Exception as exc:  # noqa: BLE001
        return WARN, f"patch check skipped ({type(exc).__name__}: {exc})"
    newer = pn._version_key(article.get("title")) > pn._version_key(have)
    if newer:
        return FAIL, (f"NEW PATCH: {article.get('title')} — the DB is on {have}; "
                      f"run the patch sequence")
    return OK, f"patch up to date ({have}, from {source})"


def check_art():
    """Art coverage for the patch's own cards, and what is missing."""
    have = {os.path.splitext(os.path.basename(p))[0]
            for p in glob.glob(os.path.join(_HERE, "img_cache", "**", "*.png"),
                               recursive=True)}
    minions = meta._raw("minions.json") or []
    trinkets = meta._raw("trinkets.json") or []
    aber = [m["id"] for m in minions if m.get("tribe") == "Aberration"]
    missing_aber = [i for i in aber if i not in have]
    tids = {t["id"] for t in trinkets if t.get("id")}
    missing_tr = sorted(tids - have)
    label = (f"art: aberration {len(aber) - len(missing_aber)}/{len(aber)}, "
             f"trinkets {len(tids) - len(missing_tr)}/{len(tids)}")
    if missing_tr:
        return WARN, f"{label} — missing {missing_tr[:3]} (no-carddef ids are expected)"
    return OK, label


def check_roster():
    """Is the log-mined pool current, and does it agree with the registry?"""
    try:
        with open(os.path.join(_HERE, "meta", "pool_roster.json"),
                  encoding="utf-8") as f:
            roster = json.load(f)
    except (OSError, ValueError):
        return FAIL, "no meta/pool_roster.json — run pool_roster.py --apply"
    ok, line = _run("playable.py")
    built = roster.get("built")
    stale = ""
    if built:
        age = (datetime.date.today() - datetime.date.fromisoformat(built)).days
        if age > 7:
            stale = f" (built {age}d ago)"
    lvl = OK if ok else FAIL
    return lvl, (f"roster patch {roster.get('patch')}, "
                 f"{len(roster.get('cards') or {})} pool cards{stale}; "
                 f"registry check {'clean' if ok else 'CONFLICTS'}")


def check_unresolved():
    """Would a review of the newest session render raw card ids?"""
    path = logquery.newest_log()
    if not path:
        return WARN, "no Power.log found"
    sess = logquery.Session(path)
    row = logquery.q_games(sess, argparse.Namespace(game=None))[-1]
    n = row["unresolved"]
    if n:
        return WARN, (f"newest game ({row['hero']}) has {n} id(s) no meta DB "
                      f"names: {', '.join(row['top_unresolved'][:4])}")
    return OK, f"newest game ({row['hero']}, place {row['place']}) renders every id"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--online", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    checks = OrderedDict()
    checks["patch"] = check_patch(args.online)
    checks["coverage"] = _gated("check_patch_db.py", "change list vs DB")
    checks["meta"] = _gated("check_meta.py", "meta validator")
    checks["roster"] = check_roster()
    checks["art"] = check_art()
    checks["discard engine"] = _engine_check()
    checks["newest log"] = check_unresolved()
    if args.full:
        checks["suite"] = _gated(None, "test suite", "-m", "unittest",
                                 "discover", "-s", "tests")

    if args.json:
        print(json.dumps({k: {"level": v[0], "detail": v[1]}
                          for k, v in checks.items()}, indent=1))
        return 1 if any(v[0] == FAIL for v in checks.values()) else 0

    worst = OK
    print("hearth-coach doctor")
    for name, (level, detail) in checks.items():
        if level == FAIL or (level == WARN and worst == OK):
            worst = level
        mark = {"FAIL": "!", "WARN": "?", "ok": " "}[level]
        print(f" {mark} {name:14} {detail}")
    print(f"verdict: {'PROBLEM' if worst == FAIL else 'check warnings' if worst == WARN else 'all clear'}")
    return 1 if worst == FAIL else 0


def _gated(script, label, *pre):
    """Run a gate tool and reduce it to one line."""
    cmd = [sys.executable, script, *pre] if script else [sys.executable, *pre]
    try:
        p = subprocess.run(cmd, cwd=_HERE, capture_output=True, text=True,
                           timeout=600)
    except Exception as exc:  # noqa: BLE001
        return WARN, f"{label}: could not run ({type(exc).__name__})"
    if p.returncode == 0:
        return OK, f"{label}: pass"
    first = next((ln.strip() for ln in (p.stdout or "").splitlines()
                  if ln.strip().startswith("!")), None)
    if not first:
        first = next((ln.strip() for ln in (p.stdout or "").splitlines()
                      if ln.strip()), "")
    return FAIL, f"{label}: FAIL — {first[:90]}"


def _engine_check():
    try:
        with open(os.path.join(_HERE, "meta", "engines.json"),
                  encoding="utf-8") as f:
            eng = json.load(f)
    except (OSError, ValueError):
        return FAIL, "meta/engines.json unreadable"
    keys = [k for k in eng if k != "_comment"]
    has_discard = "aberrations-discard-deity" in eng
    label = f"{len(keys)} engines, discard/Deity {'present' if has_discard else 'MISSING'}"
    return (OK if has_discard else FAIL), label


if __name__ == "__main__":
    sys.exit(main())
