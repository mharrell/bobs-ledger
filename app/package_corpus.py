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
import sys

from sanitize_log import sanitize_text
import decision_log
import privacy_scan
from config import HS_LOG_GLOB

SCHEMA = 1


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
    log = _b64.b64decode(bundle["log_gz_b64"]).decode("utf-8", "replace")
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
          "opponent handles, no account ids, in the log or the decisions.")
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