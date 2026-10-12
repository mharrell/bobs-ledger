# The 2026-10-12 history rewrite: every co-author attribution removed

**Asked**, in order: *"remove claude as a contributor"* → then, after the
measurement below, *"rewrite all 605 commits, force-push, move the 31 release
tags"*, *"keep claude and dsh files and directories .gitignored"*, and *"remove
commit attributions to anyone except me"* — with the explicit bound *"we don't
need to completely scrub Claude, I just don't want it to be obvious to non-devs
who look at the repo"*.

## What a "contributor" turned out to be (measured before anything moved)

* **GitHub's contributor list was never the problem.**
  `api.github.com/repos/mharrell/bobs-ledger/contributors` →
  `[('mharrell', 605)]`, and the repo page HTML carries no `claude`/`anthropic`
  text at all. Claude was not a listed contributor.
* **All 605 commits are AUTHORED and COMMITTED by the maintainer.** So
  `.mailmap` cannot fix a thing: it maps author/committer identities, and the
  trailers are not identities. Checked, not assumed — and deliberately NOT used.
  Three commits are *committed* by `GitHub <noreply@github.com>`
  (`136141f`, `9f38ca7`, `eccf5fc` — all "Merge pull request #N from
  mharrell/worktree-…"): the web UI, not a person, left alone on purpose.
* **The artifact was the trailer.** 262 commits carry
  `Co-Authored-By: Claude Code <noreply@anthropic.com>` and 50 carry
  `Co-Authored-By: Claude <noreply@anthropic.com>` — **312 of 605** — rendered
  on every commit page and as a second attribution in the commit list. Those two
  identities are the ONLY trailers in the whole history (no `Signed-off-by`,
  nothing else).
* **The root commit `72abcaa` (2026-08-25) carries one too**, so stripping them
  rewrites **all 605 commits**, not the 312 that have a trailer.
* No tracked file needed changing: README, LICENSE and the release notes never
  mention it. The only tracked hits were the four functional strings in
  `publish_release.py`/`update.py` plus `analysis/` notes naming the local
  `CLAUDE.md`.

## The rewrite

`bobs-ledger-history-rewrite/rewrite_history.py` (kept outside the repo, with
`move_tags.py`): `git fast-export --all --reencode=no` → scrub → `git
fast-import --force`. **Never a shell pipeline** — a PowerShell pipe is not a
byte channel and this stream carries the repo's PNGs.

* The scrub drops every `^Co-Authored-By:` line — the **KEY**, not just the
  name, so a future trailer is caught by the same rule.
* Exactly ONE message line was reworded, in the root commit:
  `- Claude skills converted from DeepSeek harness (.dsh)` →
  `- Reusable agent-skill files converted from the DeepSeek harness (.dsh)`.
  It read as credit for the work rather than as a file name; the other 37
  `CLAUDE.md` / `.claude/` body mentions were left alone by the maintainer's
  call.
* **312 of 605 messages rewritten.** Dry run first on a scratch mirror clone,
  then the identical run on the live checkout — both produced **identical new
  SHAs**, which is the property that makes the answer here reproducible rather
  than a one-off.
* `rewrite_history.py verify` refuses unless: 605 → 605 commits; the same ref
  NAMES; every ref's tree hash unchanged; the multiset of (tree, parent count,
  author, committer, author/committer dates, cleaned message) identical; zero
  trailered messages left; and — the guard that stops a vacuous pass — a NONZERO
  trailer count on the old side (312). HEAD's tree is `117ce47d…` on both sides.
* Suite after: **2009 tests, OK, 11 skipped**. The working tree is byte-identical,
  so this is a control on the checkout, not a re-verification of the rewrite.

## Pushed (force — deliberately outside `sync.py`, which never force-pushes)

* `main` `c703118` → `abff06e`; `readme-rewrite` `5e89337` → `864606a`, both with
  `--force-with-lease` after a `fetch` so the lease was honest.
* Tags: the 31 carried by this checkout were rewritten by the import. **The
  remote had 21 more** — every release tag `publish_release.py` ever cut — and
  they still pointed into the pre-rewrite history, which would have kept the old
  commit pages (trailer and all) alive and reachable. `move_tags.py` translated
  each through the SHA map and push forced them; **52 tags, 0 left on a
  pre-rewrite commit.**
* **The trap worth keeping**: `git fetch origin` fetches TAGS by default (tag
  following) even with an explicit heads-only refspec, so the first fetch
  silently imported those 21 remote-only tags AFTER the rewrite had run — while
  a rewrite done in a link-checked checkout looks finished the moment `main` is
  pushed. What caught it was comparing `git ls-remote --tags` against the local
  tag set, not the push output.

## What it cost, and what it did NOT

* Every SHA this project cites as evidence (the working notes, `analysis/`,
  decision logs, and each published release's `version`) is now a PRE-rewrite
  SHA. `analysis/SHA_MAP_PRE_REWRITE_2026_10_12.txt` maps all 605
  (old12 → new12), 0 unmatched, 0 ambiguous keys.
* **The player update join is safe, and the reason an earlier note gave for not
  rewriting was measured wrong**: `update.decide` orders releases by the
  manifest's `created` stamp, not by the version string. Published releases stay
  valid — the channel serves immutable signed bytes, and every install carries
  its own `.update_state.json`. Nothing was republished AT THAT MOMENT: the
  channel served `98af874` (created 2026-10-10T23:44), whose commit is now
  `9b31936`. The maintainer asked for a release later in the same session, so
  **`03f1411` is the published version now** — 2026-10-12T08:11:08, 1,592,566
  bytes, signed with the pinned `4d8fc45534ba558d`, the GitHub asset
  byte-identical to the KV copy, and the SHIPPED updater offered
  `98af874 -> 03f1411` from a simulated previous install, applied 254 files, and
  then reported up to date. Its note describes the 2026-10-12 tier refresh, which
  is the player-visible change; `03f1411` is the commit that carries both the
  refresh and this session's notes.
* Left as known artifacts: `refs/tags/<old-sha>` names no longer describe their
  commit (already true of the 31 rewritten tags — the name-preserving rule);
  GitHub keeps unreachable objects for a while, so an old commit is still
  fetchable by API, and **any fork or clone taken before today keeps the
  trailers forever**. Removal is best-effort, and that is the honest bound.
* Verified from GitHub's side after the push: contributors = `mharrell` (605);
  the `/commits/main` list page: 0 `claude`/`anthropic` hits; a new commit page:
  0; the release page for tag `98af874`: resolves to the rewritten commit, 0; and
  the OLD `main` commit URL renders with 0 (GitHub serves the replacement).

## The `.gitignore` half

* The tracked `.gitignore` now names the local-only paths — `.claude/`, `.dsh/`,
  `CLAUDE.md`, `claude_code_zai_env.sh` and the three design notes — in addition
  to `.git/info/exclude`, which is per-install and absent from a fresh clone that
  then runs `sync.py --new` (which commits untracked files). Confirmed with
  `git check-ignore -v CLAUDE.md` → `.gitignore:22`.
* The package rule "tracked files must contain no mention of the assistant" now
  has exactly one deliberate carve-out: those three `.gitignore` lines.
  Measured after the change: `git grep -inE "claude|anthropic"` outside
  `analysis/` returns **7** hits — those 3 and the 4 functional strings
  (`publish_release.EXCLUDE_DIRS`, `.EXCLUDE_FILES` ×2, `update.PROTECTED` ×2,
  four LINES). The two session notes that stated "exactly those four" carry dated
  addenda; nothing was edited as if it had always been true.

## Not done, on purpose

1. The 3 web-UI merge commits `committed by GitHub` — the platform, not a person.
2. The 38 body mentions of the notes file / tooling directory (37 after the
   root-commit reword) — "we don't need to completely scrub Claude".
3. GitHub's own object GC: nothing more to do from here.
4. The local safety net is kept OUTSIDE the repo at
   `PycharmProjects/bobs-ledger-history-pre-rewrite.git` (mirror clone + a 159 MB
   bundle + the pre-rewrite ref and commit dumps). Deleting it is a maintainer
   call once the map is trusted.
5. `.claude/worktrees/settle-up-round3` was deliberately left alone: it holds 5
   files with uncommitted edits. Its branch moved to its rewritten twin
   (`4b91e36` → `26f38f7`) and its working tree is unaffected, because a
   message-only rewrite keeps every tree byte-identical.
