#!/usr/bin/env python3
"""Fetch the session reports players have shared, into a local directory.

The collector stores each report under `sessions/<date>/<report_id>.json.gz`
with NO client identifier: reports are not linked to each other, to an
install, or to a person. That is deliberate, and it means this tool is the
only way to get at them — there is no per-player view to ask for.

Idempotent: an already-fetched report is skipped, so it is safe to re-run
after more sessions arrive.

Env (same names as upload_corpus.py):
  HEARTH_TELEMETRY_URL  the collector
  HEARTH_TELEMETRY_KEY  the shared secret; reading is keyed, sending is not

Usage:
  python fetch_sessions.py [--out sessions_in] [--list] [--force]
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "https://hearth-telemetry-collector.bobs-ledger.workers.dev"
UA = "hearth-coach-telemetry/1.0"      # workers.dev 403s the python-urllib UA


def _get(url, key, raw=False, timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "X-Telemetry-Key": key or ""})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if raw else json.loads(r.read().decode("utf-8"))


def list_keys(base, key):
    """Every stored report key, as `sessions/<date>/<id>.json.gz`."""
    got = _get(base.rstrip("/") + "/sessions", key)
    keys = got.get("keys") or []
    if got.get("truncated"):
        print(f"  WARNING: the listing hit the 1000-key page limit; "
              f"{len(keys)} returned. Re-run later or list per date.")
    return keys


def fetch(base, key, out_dir, force=False):
    """(downloaded, skipped) — one file per report, mirroring the key path."""
    base = base.rstrip("/")
    keys = list_keys(base, key)
    downloaded = skipped = 0
    for full in keys:
        # sessions/<date>/<id>.json.gz -> <out>/<date>/<id>.json.gz
        rel = full[len("sessions/"):] if full.startswith("sessions/") else full
        dest = os.path.join(out_dir, *rel.split("/"))
        if os.path.exists(dest) and not force:
            skipped += 1
            continue
        try:
            data = _get(f"{base}/{full}", key, raw=True)
        except urllib.error.HTTPError as e:
            print(f"  {rel}: HTTP {e.code}")
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        downloaded += 1
    return downloaded, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("HEARTH_TELEMETRY_URL",
                                                    DEFAULT_URL))
    ap.add_argument("--key", default=os.environ.get("HEARTH_TELEMETRY_KEY"))
    ap.add_argument("--out", default="sessions_in",
                    help="where reports land (default sessions_in/)")
    ap.add_argument("--list", action="store_true", help="list, fetch nothing")
    ap.add_argument("--force", action="store_true",
                    help="re-download reports already on disk")
    args = ap.parse_args()
    if not args.key:
        print("no key: set HEARTH_TELEMETRY_KEY (reading is keyed; sending is "
              "not)")
        return 1
    if args.list:
        keys = list_keys(args.url, args.key)
        print(f"{len(keys)} report(s) stored")
        for k in keys:
            print(f"  {k}")
        return 0
    try:
        got, skipped = fetch(args.url, args.key, args.out, force=args.force)
    except urllib.error.HTTPError as e:
        print(f"listing failed: HTTP {e.code} — is HEARTH_TELEMETRY_KEY right?")
        return 1
    print(f"{got} new report(s) in {args.out}/, {skipped} already there")
    return 0


if __name__ == "__main__":
    sys.exit(main())
