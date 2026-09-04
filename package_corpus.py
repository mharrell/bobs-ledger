#!/usr/bin/env python3
"""Package one Hearthstone session into a single corpus bundle for upload.

A bundle pairs the SANITIZED Power.log (BattleTags redacted by
sanitize_log.py — no personal data leaves the machine) with the matching
decision log (decision_logs/decision_<session>.jsonl) and a manifest
(sha256 of the raw log for provenance, coach version, counts). Everything
is one gzipped JSON file, so uploading is a single PUT whatever the
endpoint ends up being (GitHub Contents API, a Worker+R2 POST, email).

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

SCHEMA = 1


def package(log_path, out_dir):
    with open(log_path, "rb") as f:
        raw_bytes = f.read()
    log_sha = hashlib.sha256(raw_bytes).hexdigest()  # provenance: on-disk bytes
    raw = raw_bytes.decode("utf-8", errors="replace")

    sanitized, redacted = sanitize_text(raw)
    if redacted:
        print(f"sanitized: {len(redacted)} BattleTags redacted")
    decisions_path = os.path.join(
        decision_log.LOG_DIR,
        f"decision_{os.path.basename(log_path)}.jsonl")
    decisions = []
    if os.path.exists(decisions_path):
        with open(decisions_path, encoding="utf-8") as f:
            decisions = [json.loads(l) for l in f if l.strip()]

    bundle = {
        "schema": SCHEMA,
        "manifest": {
            "created": datetime_iso(),
            "coach_version": decision_log.coach_version(),
            "log_basename": os.path.basename(log_path),
            "log_sha256": log_sha,
            "log_lines": raw.count("\n"),
            "battletags_redacted": len(redacted),
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", nargs="?", help="path to a session Power.log")
    ap.add_argument("--latest", action="store_true",
                    help="package the newest session log")
    ap.add_argument("-o", "--out", default="corpus_out",
                    help="output directory (default: corpus_out/)")
    args = ap.parse_args()
    path = args.log
    if not path or args.latest:
        logs = sorted(glob.glob(r"C:\Program Files (x86)\Hearthstone\Logs"
                                r"\Hearthstone_*\Power.log"),
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