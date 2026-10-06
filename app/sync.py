#!/usr/bin/env python3
"""Sync work to main and origin in ONE command, so a session needs one approval.

Why this exists: a push from the agent's sandbox needs wider access, and that is
a per-*command* cost. Measured on this checkout 2026-10-06: `origin` is
`https://github.com/mharrell/bobs-ledger.git` with `credential.helper=manager`
(NOT the `git@github.com:...` ssh remote an earlier version of this docstring
described), and an unapproved `git push` dies in the credential helper —
`failed to execute prompt script (exit code 66)` then `could not read Username
for 'https://github.com': No such file or directory` — because Git Credential
Manager cannot spawn under the sandbox. Approved once, the same push succeeds.
So the fix is not a cleverer transport but ONE command that asks once.

So: this script does the worktree ceremony the project requires — commit,
merge the current branch into main, prune the merged branch, push — and prints
at most a few lines about what it did. Run it as the last act of a session,
FROM THE WORKTREE the session worked in:

    python app/sync.py --message "what changed"   # commit, merge, push
    python app/sync.py --dry-run                  # say what it would do

It works from a linked worktree: the merge runs in whichever directory holds
main (`worktree_for`), instead of `git checkout main`, which git refuses when
main is checked out somewhere else. Paths are resolved from the REPO ROOT, not
from this file's own `app/` directory, so `--new` can add a root-level file.

It refuses to invent a commit message, refuses to run with a dirty tree it
cannot attribute, and never force-pushes. A merge conflict stops it with the
conflicted paths printed — resolving that is a judgement call, not automation.
Two things it does NOT do: delete the worktree it ran in (finish that session
first), or delete the merged branch — that is left to a later judgement, not
automation.
"""
import argparse
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _repo_root():
    """The REPO ROOT — which is NOT this file's directory.

    The code lives in `app/`, so `dirname(__file__)` is `<root>/app`, and that
    is what every git call here used to run from. git does not mind (it finds
    the root from any subdirectory), but the PATHS do: a `status --porcelain`
    path is root-relative, so `git add PIVOT.md` run from `app/` dies with
    `fatal: pathspec 'PIVOT.md' did not match any files`. Every untracked file
    this script had ever been asked to add lived under `app/` — which is why
    `--new` looked like it worked until a root-level doc (2026-10-06).
    """
    p = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=_HERE,
                       capture_output=True, text=True)
    root = (p.stdout or "").strip()
    return root or os.path.dirname(_HERE)


REPO = _repo_root()


def git(*args, check=True, capture=True, cwd=None):
    p = subprocess.run(["git", *args], cwd=cwd or REPO, capture_output=capture,
                       text=True)
    if check and p.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n"
                         f"{(p.stdout or '') + (p.stderr or '')}".strip())
    return (p.stdout or "").strip()


def lines(*args, **kw):
    out = git(*args, **kw)
    return [ln for ln in out.splitlines() if ln.strip()]


def worktree_for(branch):
    """The directory where `branch` is checked out, or None.

    `git checkout main` cannot work from a LINKED worktree: main is checked
    out in the primary one and git refuses with "'main' is already used by
    worktree at ...". The project's own discipline is work-in-a-worktree, so
    the merge has to run IN whichever directory holds main instead of
    checking it out here — and `worktree list --porcelain` is what says which.
    (An older version of this script simply called `git checkout main`, which
    made `sync.py` fail at the merge step for every worktree session.)
    """
    out = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=REPO,
                         capture_output=True, text=True).stdout or ""
    path = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.startswith("branch ") and line.strip().endswith("/" + branch):
            return path
    return None


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
        # Merge WHERE MAIN LIVES. From a linked worktree that is another
        # directory, and checking main out here is impossible — see
        # worktree_for().
        holder = worktree_for("main")
        merge_dir = REPO
        if holder and os.path.realpath(holder) != os.path.realpath(REPO):
            merge_dir = holder
            print(f"  (main is checked out at {holder}; merging there)")
        else:
            git("checkout", "main")
        p = subprocess.run(["git", "merge", "--no-edit", branch], cwd=merge_dir,
                           capture_output=True, text=True)
        if p.returncode != 0:
            conflicted = lines("diff", "--name-only", "--diff-filter=U",
                               cwd=merge_dir)
            print("! merge conflict — resolve deliberately, nothing pushed")
            for c in conflicted[:10]:
                print(f"    {c}")
            return 3
        print(f"  merged {branch}: "
              f"{git('log', '-1', '--oneline', cwd=merge_dir)}")
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
