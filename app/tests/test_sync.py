"""sync.py resolves the REPO ROOT and the main worktree — the two things that
made a worktree session's last command fail (2026-10-06).

Both bugs were silent in the only case anyone had exercised:

* Every git call ran with `cwd = dirname(__file__)`, i.e. `<root>/app`. A
  porcelain path is root-relative, so `--new` could only ever add files that
  lived under `app/` — which is where every untracked file it had been used
  for (`.hs_home.json`, the `app/meta/` caches) happened to live. A root-level
  file died with `fatal: pathspec 'PIVOT.md' did not match any files`.
* The merge step ran `git checkout main`, which git refuses from a linked
  worktree ("'main' is already used by worktree at ..."). So the combination
  CLAUDE.md mandates — work in a worktree, end with `python app/sync.py` —
  committed, then stopped before merging.

Neither can be exercised end to end without building throwaway repos, which
would test git rather than this script. What IS pinned here is the resolution
both depend on, plus a skip when there is no checkout at all (a release zip
carries no `.git`, and `app/tests` ships in it).
"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import sync  # noqa: E402


def _in_git_checkout():
    p = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                       cwd=HERE, capture_output=True, text=True)
    return p.returncode == 0 and (p.stdout or "").strip() == "true"


@unittest.skipUnless(_in_git_checkout(), "not a git checkout")
class TestRepoRoot(unittest.TestCase):
    def test_repo_is_the_root_not_the_app_directory(self):
        # The bug in one line: dirname(__file__) IS the app directory.
        self.assertNotEqual(os.path.basename(sync.REPO), "app")
        self.assertFalse(os.path.samefile(sync.REPO, sync._HERE))

    def test_root_is_where_the_layout_says_it_is(self):
        # The root holds app/ and the README; the app directory holds neither.
        self.assertTrue(os.path.isdir(os.path.join(sync.REPO, "app")))
        self.assertTrue(os.path.isfile(os.path.join(sync.REPO, "README.md")))

    def test_root_holds_the_git_entry(self):
        # A linked worktree has a `.git` FILE; the primary checkout a `.git`
        # directory. Either way it is at the root — not one level up.
        self.assertTrue(os.path.exists(os.path.join(sync.REPO, ".git")))

    def test_paths_the_untracked_branch_adds_resolve_from_the_root(self):
        # `--new` hands porcelain paths straight to `git add`; those are
        # root-relative, so the join has to work for a root-level file.
        rel = "README.md"
        self.assertTrue(os.path.isfile(os.path.join(sync.REPO, rel)))


@unittest.skipUnless(_in_git_checkout(), "not a git checkout")
class TestMainWorktree(unittest.TestCase):
    def test_main_worktree_is_found(self):
        holder = sync.worktree_for("main")
        self.assertIsNotNone(holder, "worktree list --porcelain named no main")
        self.assertTrue(os.path.isdir(holder))
        self.assertTrue(os.path.isfile(os.path.join(holder, "README.md")))

    def test_an_absent_branch_resolves_to_none(self):
        # The parser must not fall out of the loop holding the LAST worktree
        # it saw: a wrong directory here means merging into the wrong tree.
        self.assertIsNone(sync.worktree_for("no-such-branch-anywhere"))

    def test_path_is_absolute(self):
        self.assertTrue(os.path.isabs(sync.worktree_for("main")))


if __name__ == "__main__":
    unittest.main()
