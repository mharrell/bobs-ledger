#!/usr/bin/env python3
"""Sync work to main and origin in ONE command, so a session needs one approval.

Why this exists: `origin` is `git@github.com:...`, git-for-windows runs ssh
through MSYS, and the agent's sandbox cannot start MSYS processes — every push
fails with `couldn't create signal pipe, Win32 error 5` until it is approved for
wider access. That is a per-*command* cost, so the fix is not a cleverer
transport (HTTPS was tried and is blocked for the same reason: git runs a `!`
credential helper through `sh.exe`, and even `gh auth git-credential`, which
answers correctly when run directly, is spawned via sh) — the fix is to make the
whole sequence ONE command that asks once.

So: this script does the worktree ceremony the project requires — commit,
merge the current branch into main, prune the merged branch, push — and prints
at most a few lines about what it did. Run it as the last act of a session:

    python sync.py --message "what changed"     # commit, merge, push
    python sync.py --dry-run                    # say what it would do

It refuses to invent a commit message, refuses to run with a dirty tree it
cannot attribute, and never force-pushes. A merge conflict stops it with the
conflicted paths printed — resolving that is a judgement call, not automation.
"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))


def git(*args, check=True, capture=True):
    p = subprocess.run(["git", *args], cwd=REPO, capture_output=capture,
                       text=True)
    if check and p.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n"
                         f"{(p.stdout or '') + (p.stderr or '')}".strip())
    return (p.stdout or "").strip()


def lines(*args, **kw):
    out = git(*args, **kw)
    return [ln for ln in out.splitlines() if ln.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--message", "-m", default=None,
                    help="commit message for the current tree (if dirty)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--new", action="store_true",
                    help="also commit untracked files (default: leave them "
                         "alone and say so)")
    args = ap.parse_args()

    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = lines("status", "--porcelain")
    untracked = [d[3:] for d in dirty if d.startswith("??")]
    modified = [d for d in dirty if not d.startswith("??")]
    ahead = lines("log", "--oneline", "origin/main..main")
    plan = []

    if modified:
        if not args.message:
            print(f"! {len(modified)} modified path(s) and no --message; "
                  f"refusing to invent one. First few:")
            for d in modified[:5]:
                print(f"    {d}")
            return 2
        plan.append(f"commit {len(modified)} modified path(s): "
                    f"{args.message[:50]}")
    if untracked:
        # Tracked-only by default: the repo root collects machine-specific
        # files by accident (an env script lived untracked through a whole
        # session), and `git add -A` would have swept them into a commit.
        verb = "also add" if args.new else "LEAVE untracked (use --new to add)"
        plan.append(f"{verb}: {', '.join(untracked[:5])}"
                    + (f" (+{len(untracked) - 5} more)"
                       if len(untracked) > 5 else ""))
    if branch != "main":
        plan.append(f"merge {branch} -> main")
    if ahead:
        plan.append(f"push {len(ahead)} commit(s) to origin/main")
    if not plan:
        print("nothing to do — tree clean, main in sync with origin")
        return 0

    print("sync plan:")
    for step in plan:
        print(f"  - {step}")
    if args.dry_run:
        print("(dry run)")
        return 0

    # 1. commit
    if modified:
        git("add", "-u")
        if args.new:
            git("add", *untracked)
        git("commit", "-q", "-m", args.message)
        print(f"  committed: {git('log', '-1', '--oneline')}")
    elif args.new and untracked:
        git("add", *untracked)
        git("commit", "-q", "-m", args.message or "add new files")
        print(f"  committed: {git('log', '-1', '--oneline')}")
    # 2. merge the branch into main
    if branch != "main":
        git("checkout", "main")
        p = subprocess.run(["git", "merge", "--no-edit", branch], cwd=REPO,
                           capture_output=True, text=True)
        if p.returncode != 0:
            conflicted = lines("diff", "--name-only", "--diff-filter=U")
            print("! merge conflict — resolve deliberately, nothing pushed")
            for c in conflicted[:10]:
                print(f"    {c}")
            return 3
        print(f"  merged {branch}: {git('log', '-1', '--oneline')}")
    # 3. push
    if not args.no_push:
        p = subprocess.run(["git", "push", "origin", "main"], cwd=REPO,
                           capture_output=True, text=True)
        if p.returncode != 0:
            print("! push failed (this is the sandbox's MSYS block unless you "
                  "approved wider access for this command):")
            print("   " + ((p.stderr or p.stdout or "").strip().splitlines() or
                           ["?"])[-1][:120])
            return 4
        print(f"  pushed: {p.stderr.strip() or 'up to date'}")
    # 4. leave the branch behind only if it is fully merged
    if branch != "main":
        merged = subprocess.run(["git", "branch", "--merged", "main"],
                                cwd=REPO, capture_output=True, text=True).stdout
        if branch in merged:
            print(f"  ({branch} is merged; remove the worktree when its "
                  f"session is done)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
