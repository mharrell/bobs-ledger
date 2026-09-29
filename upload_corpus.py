#!/usr/bin/env python3
"""Upload a corpus bundle to the coach's telemetry.

Two transports, picked by what's configured:

  1. A COLLECTOR URL (no GitHub account needed): --url or
     HEARTH_TELEMETRY_URL. One POST per bundle; the optional shared secret
     HEARTH_TELEMETRY_KEY rides in an X-Telemetry-Key header. The reference
     collector (a Cloudflare Worker writing to R2) ships in telemetry/.
  2. The GitHub repo (the maintainer's own path): one PUT per bundle via
     the Contents API — the `gh` CLI, or GH_TELEMETRY_TOKEN (a
     fine-grained PAT with Contents write on that repo ONLY). Repo
     defaults to HEARTH_TELEMETRY_REPO or mharrell/hearth-telemetry.

Usage:
  python upload_corpus.py corpus_out/corpus_XXXX.json.gz
  python upload_corpus.py --latest        # package the newest session, then upload

Uploading is opt-in and never happens automatically: each run shows what it
would send (the BattleTag-redacted session log + this session's decisions)
and where it's going, and asks for confirmation unless --yes is given.
"""
import argparse
import base64
import glob
import json
import os
import subprocess
import urllib.request

from config import HS_LOG_GLOB

DEFAULT_REPO = "mharrell/hearth-telemetry"
_HERE = os.path.dirname(os.path.abspath(__file__))


def gh_available():
    try:
        return subprocess.run(["gh", "--version"], capture_output=True,
                              timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def put_file(repo, remote_path, data, token=None):
    """Write one file to the repo via the Contents API. Returns the file URL.

    Uses `gh api` (stdin body — a 5MB base64 payload exceeds Windows arg
    limits) or a raw REST PUT with the token.
    """
    body = json.dumps({
        "message": f"corpus: {remote_path}",
        "content": base64.b64encode(data).decode("ascii"),
    }).encode("utf-8")
    url = f"https://api.github.com/repos/{repo}/contents/{remote_path}"
    if token is None:
        req = subprocess.run(
            ["gh", "api", "-X", "PUT", f"repos/{repo}/contents/{remote_path}",
             "--input", "-", "--jq", ".content.download_url"],
            input=body, capture_output=True, timeout=300)
        if req.returncode != 0:
            raise RuntimeError(f"gh api failed: {req.stderr.decode()[:300]}")
        return req.stdout.decode().strip()
    req = urllib.request.Request(
        url, data=body, method="PUT",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["content"]["download_url"]


def put_url(url, data, key=None, name=None):
    """POST one bundle to a collector endpoint. Returns the collector's reply.

    The user needs nothing but the URL: no GitHub account, no PAT. The
    shared key (HEARTH_TELEMETRY_KEY) is optional and is the ONLY
    credential — it throttles strangers, it is not an identity.
    """
    headers = {"Content-Type": "application/gzip"}
    if key:
        headers["X-Telemetry-Key"] = key
    if name:
        headers["X-Bundle-Name"] = os.path.basename(name)
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read().decode("utf-8", "replace").strip()[:300]


def upload(bundle_path, repo=None, token=None):
    repo = repo or os.environ.get("HEARTH_TELEMETRY_REPO", DEFAULT_REPO)
    if token is None:
        token = os.environ.get("GH_TELEMETRY_TOKEN")
    with open(bundle_path, "rb") as f:
        data = f.read()
    remote_path = f"corpus/{os.path.basename(bundle_path)}"
    url = put_file(repo, remote_path, data, token=token)
    print(f"uploaded: {repo}/{remote_path} ({len(data) / 1e6:.1f} MB)")
    print(url)
    return url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle", nargs="?", help="a corpus_*.json.gz bundle")
    ap.add_argument("--latest", action="store_true",
                    help="package the newest session, then upload it")
    ap.add_argument("--url", help="collector endpoint (a POST URL — no "
                    "GitHub account needed; default "
                    "$HEARTH_TELEMETRY_URL)")
    ap.add_argument("--repo", help="telemetry repo (default "
                    f"{DEFAULT_REPO})")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="skip the confirmation prompt")
    args = ap.parse_args()
    bundle = args.bundle
    if args.latest or not bundle:
        import package_corpus
        logs = sorted(glob.glob(HS_LOG_GLOB),
                      key=os.path.getmtime, reverse=True)
        if not logs:
            print("no session log found")
            return 1
        out_dir = os.path.join(_HERE, "corpus_out")
        bundle = package_corpus.package(logs[0], out_dir)
    if not os.path.exists(bundle):
        print(f"no such bundle: {bundle}")
        return 1
    url = args.url or os.environ.get("HEARTH_TELEMETRY_URL")
    if url:
        destination = url
    else:
        if not gh_available() and not os.environ.get("GH_TELEMETRY_TOKEN"):
            print("no auth: set HEARTH_TELEMETRY_URL (a collector URL — "
                  "no GitHub needed), or install/login `gh`, or set "
                  "GH_TELEMETRY_TOKEN")
            return 1
        repo = args.repo or os.environ.get("HEARTH_TELEMETRY_REPO",
                                           DEFAULT_REPO)
        destination = f"{repo}/corpus/{os.path.basename(bundle)}"
    print(f"about to upload: {bundle}")
    print("  contents: the BattleTag-redacted Power.log + this session's "
          "decision log (no other personal data)")
    print(f"  destination: {destination}")
    if not args.yes:
        try:
            answer = input("upload? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer != "y":
            print("cancelled — nothing uploaded")
            return 1
    try:
        if url:
            with open(bundle, "rb") as f:
                data = f.read()
            print(put_url(url, data,
                          key=os.environ.get("HEARTH_TELEMETRY_KEY"),
                          name=bundle))
        else:
            upload(bundle, repo=args.repo)
    except Exception as e:  # noqa: BLE001
        print(f"upload failed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())