#!/usr/bin/env python3
"""Package the current tree as a release and publish it for auto-update.

One command per release (maintainer only — it uses your `wrangler` auth):

    python publish_release.py --note "tempo mode, welcome screen"

Writes a zip of the project (code + meta + docs; NO local data —
decision_logs/, corpus_out/, .review_cache/, .git/.claude/ and the
regenerable caches are excluded, and img_cache/ stays out because the
overlay fetches art on demand), a VERSION file stamped with the git sha,
and a manifest {version, note, zip sha256, created} — then PUTs the zip
and manifest to the KV namespace the collector serves:

    GET  <collector>/release/latest.json   (public)
    GET  <collector>/release/<zip>         (shared key required)

Beta users pick updates up through `update.py` / live.py's startup check.
"""
import argparse
import datetime
import hashlib
import io
import json
import os
import shutil
import subprocess
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))

#: Directory and file names that never ship: local data, dev plumbing,
#: and regenerable caches. img_cache stays out on purpose — the overlay
#: fetches art on demand (hearth_art_extract is a local convenience).
EXCLUDE_DIRS = {".git", ".claude", "decision_logs", "corpus_out",
                ".review_cache", "__pycache__", ".venv", "venv", ".idea",
                "img_cache", "node_modules", "patch_reports"}
EXCLUDE_FILES = {".art_miss.json", ".cards_cache.json",
                 ".trinkets_hsjson_cache.json"}


def git_sha():
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=_HERE,
                          capture_output=True, text=True,
                          timeout=10).stdout.strip() or "unknown"


def build_zip(version):
    """The release zip in memory. VERSION at the root is the update join:
    update.py compares it against the manifest's version."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("VERSION", version + "\n")
        for dirpath, dirnames, filenames in os.walk(_HERE):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for fn in filenames:
                if fn in EXCLUDE_FILES or fn.endswith(".pyc"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, _HERE).replace(os.sep, "/")
                z.write(full, rel)
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--note", required=True,
                    help="one line for the user-facing update alert")
    ap.add_argument("--namespace", default="abd7803c581b4470a2834e92ae0006a2",
                    help="the collector's KV namespace id")
    args = ap.parse_args()

    version = git_sha()
    data = build_zip(version)
    sha = hashlib.sha256(data).hexdigest()
    zip_name = f"bobs-ledger-{version}.zip"
    manifest = {
        "schema": 1,
        "version": version,
        "note": args.note,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "zip_name": zip_name,
        "zip_sha256": sha,
        "zip_bytes": len(data),
    }
    print(f"release {version}: {zip_name} "
          f"({len(data) / 1e6:.1f} MB, sha {sha[:12]})")
    print(f"  note: {args.note}")

    env = dict(os.environ)
    tmp = os.path.join(os.environ.get("TEMP", _HERE), f"rel_{version}.zip")
    with open(tmp, "wb") as f:
        f.write(data)
    try:
        for key, path in ((f"release/{zip_name}", tmp),
                          ("release/latest.json", None)):
            # npx is npx.cmd on Windows — CreateProcess needs the resolved
            # name, not the npm shim.
            cmd = [shutil.which("npx") or "npx.cmd", "--yes", "wrangler",
                   "kv", "key", "put", key,
                   "--namespace-id", args.namespace, "--remote"]
            stdin_payload = None
            if path:
                cmd += ["--path", path]
            else:
                # wrangler reads the value from stdin when no --path is given
                stdin_payload = json.dumps(manifest, ensure_ascii=False).encode()
            r = subprocess.run(cmd, input=stdin_payload, cwd=_HERE,
                               capture_output=True, timeout=300)
            if r.returncode != 0:
                raise RuntimeError(
                    f"kv put {key} failed: {r.stderr.decode()[:300]}")
            print(f"  uploaded {key}")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    print("published. Users update via `python update.py` or on their next "
          "live.py start.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
