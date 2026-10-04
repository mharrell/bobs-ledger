#!/usr/bin/env python3
"""Package one Hearthstone session into a single corpus bundle for upload.

A bundle pairs the SANITIZED Power.log (every player identity redacted by
sanitize_log.py — BattleTags, the bare opponent handles Battlegrounds
writes, and account ids) with the matching decision log
(decision_logs/decision_<session>.jsonl) and a manifest (sha256 of the raw
log for provenance, coach version, counts). Everything is one gzipped JSON
file, so uploading is a single PUT whatever the endpoint ends up being
(GitHub Contents API, a Worker+R2 POST, email).

`--inspect` re-checks the bundle with privacy_scan — separate code from the
sanitizer — so the pre-send "it's clean" claim is verified, not asserted.

Usage:
  python package_corpus.py <Power.log> [-o out/]
  python package_corpus.py --latest [-o out/]
"""
import argparse
import base64
import datetime
import glob
import gzip
import hashlib
import json
import os
import re
import sys

from sanitize_log import sanitize_text
import decision_log
import privacy_scan
from config import HS_LOG_GLOB

SCHEMA = 1

#: The decision log's session field, and the paths inside a record that hold a
#: PERSON rather than game data.
#:
#: `analysis.opp_comp.name` is the opponent's display handle — the field the
#: overlay renders as "Hero · Odin3539". privacy_scan cannot see it: the
#: scanner matches the shapes the log writes (PlayerName=, Entity=, account
#: ids), and a name in a JSON key called "name" matches none of them. So this
#: bundle used to carry handles while `inspect` printed "verified clean ... no
#: opponent handles ... in the log or the decisions" — one real session had
#: 50 advisories carrying it (found 2026-10-03, while designing the automatic
#: upload path that would have made it a player-facing leak).
#:
#: MEASURED LATER THE SAME DAY, on the session that prompted the follow-up
#: work: every identity reference in its 212 raw records (93 of them, across 9
#: distinct handles) sat in THIS field, so this pop removed all 93 and missed
#: nothing. The gap was never that this list was too short — it is that nothing
#: could CHECK it, and that a handle arriving by any other route (advice text,
#: a field added later) would have shipped with `inspect` still saying clean.
#: Bundles written BEFORE this pop existed are the ones to distrust, including
#: anything already uploaded.
_PERSON_PATHS = ("analysis.opp_comp.name",)
#: The record's log field: normally just "Power.log", but a record written
#: from a full path would carry the session DIRECTORY, which links a player's
#: sessions — privacy_scan flags that as session_dir.
_SESSION_PLACEHOLDER = "[session]"


def _clean_string(value, identities):
    """(value, hits) — identities swapped for the token the log itself uses.

    Embedded as well as exact: a rendered advice line can read "swing at
    <handle> now", and a leftover substring is the same leak. Word boundaries
    keep a short handle from eating the letters out of a longer game name that
    merely contains it.
    """
    if not identities:
        return value, 0
    if value in identities:
        return identities[value], 1
    hits = 0
    for handle, token in identities.items():
        if handle and handle in value:
            pattern = re.compile(r"(?<!\w)" + re.escape(handle) + r"(?!\w)")
            value, n = pattern.subn(token, value)
            hits += n
    return value, hits


def _scrub(node, identities, counts):
    """Walk a record, replacing identities wherever they sit."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            new_key, hits = _clean_string(key, identities)
            counts[0] += hits
            out[new_key] = _scrub(value, identities, counts)
        return out
    if isinstance(node, list):
        return [_scrub(v, identities, counts) for v in node]
    if isinstance(node, str):
        value, hits = _clean_string(node, identities)
        counts[0] += hits
        return value
    return node


def sanitize_decisions(decisions, identities=None):
    """(records, removed) — the decisions with every session identity gone.

    WHY THIS IS NOT A LIST OF FIELD NAMES ANY MORE

    It used to pop exactly one key, `analysis.opp_comp.name` — where the
    overlay's "Hero · Odin3539" line comes from. That single pop was the whole
    guarantee, and it could not be checked: privacy_scan matches the shapes the
    LOG writes (PlayerName=, Entity=, account ids), and a bare display handle in
    a JSON key called "name" matches none of them. One session's bundle carried
    fifty of them while `inspect` printed "no opponent handles ... in the
    decisions" (found 2026-10-03, while designing the upload path that would
    have made it a player-facing leak).

    `identities` is what sanitize_text returned for THIS session's log: every
    handle it found, mapped to the token it wrote in their place. Checking
    against that covers any depth, keys as well as values, and fields that did
    not exist when this was written. The scan does not prove its own success —
    the caller verifies with identities_left() and refuses to write a bundle
    that still holds one.
    """
    identities = identities or {}
    counts = [0]
    out = []
    for rec in decisions:
        rec = json.loads(json.dumps(rec))      # never mutate the caller's
        if rec.get("log"):
            rec["log"] = _SESSION_PLACEHOLDER
        oc = (rec.get("analysis") or {}).get("opp_comp")
        if isinstance(oc, dict) and oc.get("name"):
            oc.pop("name", None)
            counts[0] += 1
        out.append(_scrub(rec, identities, counts))
    return out, counts[0]


def identities_left(records, identities):
    """Field PATHS still holding an identity. Never the identity itself.

    Exposed so the caller can refuse to write a bundle instead of trusting that
    the walk caught everything, and returning paths on purpose: reporting a
    leak by printing the handle is its own leak.
    """
    found = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}.{key}" if path else str(key)
                if key in identities:
                    found.append(child + " (key)")
                walk(value, child)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
        elif isinstance(node, str):
            for handle in identities:
                if handle and handle in node:
                    found.append(path)
                    break

    for i, rec in enumerate(records):
        walk(rec, f"[{i}]")
    return found


def decisions_for_session(log_path):
    """The packaged session's advisories — and ONLY that session's.

    Reads decision_<session>.jsonl (decision_log.session_stem). Falls back
    to the legacy shared pile (decision_Power.log.jsonl, where every
    session collapsed into one basename-keyed file) filtered to records
    timestamped within the log's own creation→last-write window.
    """
    path = os.path.join(decision_log.LOG_DIR,
                        f"decision_{decision_log.session_stem(log_path)}.jsonl")
    if not os.path.exists(path):
        legacy = os.path.join(decision_log.LOG_DIR,
                              "decision_Power.log.jsonl")
        if not os.path.exists(legacy):
            return []
        lo = datetime.datetime.fromtimestamp(os.path.getctime(log_path))
        hi = datetime.datetime.fromtimestamp(os.path.getmtime(log_path))
        out = []
        with open(legacy, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                try:
                    ts = datetime.datetime.fromisoformat(rec.get("ts") or "")
                except ValueError:
                    continue
                if lo <= ts <= hi:
                    out.append(rec)
        return out
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def package(log_path, out_dir):
    with open(log_path, "rb") as f:
        raw_bytes = f.read()
    log_sha = hashlib.sha256(raw_bytes).hexdigest()  # provenance: on-disk bytes
    raw = raw_bytes.decode("utf-8", errors="replace")

    sanitized, redacted = sanitize_text(raw)
    if redacted:
        print(f"sanitized: {len(redacted)} identities redacted")
    decisions = decisions_for_session(log_path)
    # The identities the LOG sanitizer found, handed to the decision sanitizer:
    # one check against this session's actual people, instead of a list of
    # field names that only covers what somebody remembered to list.
    decisions, handles_dropped = sanitize_decisions(decisions, identities=redacted)
    if handles_dropped:
        print(f"stripped {handles_dropped} session identity reference(s) from "
              "the decision log — privacy_scan does not see bare handles (see "
              "sanitize_decisions)")
    left = identities_left(decisions, redacted)
    if left:
        # Fail closed. A bundle that still names somebody does not get written,
        # and the report names PATHS: saying which field leaked by printing the
        # handle would be its own leak.
        raise SystemExit(
            f"refusing to package: {len(left)} identity reference(s) survived "
            f"sanitizing, at {', '.join(left[:3])}"
            + (" ..." if len(left) > 3 else ""))

    bundle = {
        "schema": SCHEMA,
        "manifest": {
            "created": datetime_iso(),
            "coach_version": decision_log.coach_version(),
            "log_basename": os.path.basename(log_path),
            "log_sha256": log_sha,
            "log_lines": raw.count("\n"),
            # Identities = BattleTags AND the bare opponent handles
            # Battlegrounds writes for most opponents (2026-10-02: the old
            # name counted tags only, so a session that shipped fifteen
            # opponent handles reported "1 redacted").
            "identities_redacted": len(redacted),
            "decision_count": len(decisions),
            "opponent_names_dropped": handles_dropped,
        },
        "log_gz_b64": None,  # gzip+base64 of the sanitized log
        "decisions": decisions,
    }
    gz = gzip.compress(sanitized.encode("utf-8"))
    bundle["log_gz_b64"] = base64.b64encode(gz).decode("ascii")

    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime_iso().replace(":", "").replace("-", "")[:12]
    out_path = os.path.join(out_dir, f"corpus_{stamp}.json.gz")
    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        json.dump(bundle, f)
    print(f"bundle: {out_path} "
          f"({os.path.getsize(out_path) / 1e6:.1f} MB, "
          f"{len(decisions)} decisions, log sha {log_sha[:12]})")
    return out_path


def datetime_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def inspect(bundle_path):
    """What's in the bundle, in the open — the pre-send trust view.

    Decodes the bundle and RE-SCANS the sanitized log with privacy_scan,
    which is independent code from the sanitizer on purpose. Until
    2026-10-02 this re-scanned with `sanitize_text` itself — the same regex
    that had just failed to remove anything — so it printed "0 unredacted
    BattleTags" over a bundle carrying fifteen opponent handles. A check
    that asks the cleaner whether it cleaned is not a check.

    Returns 1 (and says so loudly) when anything personal survives.
    """
    if not os.path.exists(bundle_path):
        print(f"no such bundle: {bundle_path}")
        return 1
    with gzip.open(bundle_path, "rt", encoding="utf-8") as f:
        bundle = json.load(f)
    m = bundle["manifest"]
    print(f"bundle: {bundle_path} "
          f"({os.path.getsize(bundle_path) / 1e6:.1f} MB)")
    for k, v in m.items():
        print(f"  {k}: {v}")
    print(f"  decisions: {len(bundle['decisions'])} advisories")
    if bundle["decisions"]:
        first = bundle["decisions"][0]
        sample = json.dumps(first, ensure_ascii=False)
        print(f"  first decision: {sample[:220]}")
    import base64 as _b64
    # gzip.decompress, not just b64decode: `log_gz_b64` is base64(gzip(log)), so
    # decoding only the base64 handed privacy_scan a stream starting "\x1f\x8b"
    # and it scanned mojibake. Every category read as absent, so this printed
    # "verified clean by an independent scan" for a bundle whose log provably
    # carried a session-directory name — the corpus path's only independent log
    # check could not fail (found 2026-10-04; test_package_corpus.py:55 has
    # always decoded it correctly, which is why nothing caught it).
    log = gzip.decompress(_b64.b64decode(bundle["log_gz_b64"])).decode(
        "utf-8", "replace")
    findings = privacy_scan.find(log)
    decision_findings = privacy_scan.find(
        json.dumps(bundle["decisions"], ensure_ascii=False))
    for label, found in (("log", findings), ("decisions", decision_findings)):
        for line in privacy_scan.describe(label, found):
            print(line)
    if findings or decision_findings:
        print("\n  NOT CLEAN — do not send this bundle. Something in the "
              "categories above survived sanitizing; please report it.")
        return 1
    print("\n  verified clean by an independent scan: no BattleTags, no "
          "account ids, no session names, in the log or the decisions.")
    print("  opponent HANDLES are a separate check, because a bare display "
          "name matches nothing a scanner can look for: package() verifies the "
          "decisions against the identities sanitize_text found in this "
          "session's own log and refuses to write a bundle that still holds "
          "one. Re-running package() is what proves it, per session.")
    print("  that is the whole bundle: sanitized log + decision log + "
          "manifest. Nothing else is included.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", nargs="?", help="path to a session Power.log")
    ap.add_argument("--latest", action="store_true",
                    help="package the newest session log")
    ap.add_argument("-o", "--out", default="corpus_out",
                    help="output directory (default: corpus_out/)")
    ap.add_argument("--inspect", metavar="BUNDLE",
                    help="show exactly what a packaged bundle contains")
    args = ap.parse_args()
    if args.inspect:
        return inspect(args.inspect)
    path = args.log
    if not path or args.latest:
        logs = sorted(glob.glob(HS_LOG_GLOB),
                      key=os.path.getmtime, reverse=True)
        if not logs:
            print("no session log found")
            return 1
        path = logs[0]
    if not os.path.exists(path):
        print(f"no such log: {path}")
        return 1
    package(path, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())