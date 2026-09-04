#!/usr/bin/env python3
"""Upload a corpus bundle to the private telemetry repo on GitHub.

One PUT per bundle via the Contents API. Auth, in order of preference:
  1. the `gh` CLI (its own keyring — no secrets stored by this tool)
  2. the GH_TELEMETRY_TOKEN env var (a fine-grained PAT with Contents write
     on the telemetry repo ONLY — that's the blast radius if it leaks)
The repo defaults to HEARTH_TELEMETRY_REPO or mharrell/hearth-telemetry.

Usage:
  python upload_corpus.py corpus_out/corpus_XXXX.json.gz
  python upload_corpus.py --latest        # package the newest session, then upload
"""
import argparse
import base64
import glob
import json
import os
import subprocess
import urllib.request

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
    ap.add_argument("--repo", help="telemetry repo (default "
                    f"{DEFAULT_REPO})")
    args = ap.parse_args()
    bundle = args.bundle
    if args.latest or not bundle:
        import package_corpus
        logs = sorted(glob.glob(r"C:\Program Files (x86)\Hearthstone\Logs"
                                r"\Hearthstone_*\Power.log"),
                      key=os.path.getmtime, reverse=True)
        if not logs:
            print("no session log found")
            return 1
        out_dir = os.path.join(_HERE, "corpus_out")
        bundle = package_corpus.package(logs[0], out_dir)
    if not os.path.exists(bundle):
        print(f"no such bundle: {bundle}")
        return 1
    if not gh_available() and not os.environ.get("GH_TELEMETRY_TOKEN"):
        print("no auth: install/login `gh`, or set GH_TELEMETRY_TOKEN")
        return 1
    try:
        upload(bundle, repo=args.repo)
    except Exception as e:  # noqa: BLE001
        print(f"upload failed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())