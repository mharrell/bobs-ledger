# Bob's Ledger

A real-time coaching overlay for Hearthstone Battlegrounds. It reads the game
from Hearthstone's own `Power.log`, reconstructs the board, and advises each
buy phase from a **local value function plus growth simulator over a curated
meta DB**. The live path calls **no model and no API** — `coach_llm.py` is an
optional maintainer tool for patch-note extraction, and `compare_models.py`
is a model-comparison harness. Neither is imported by `live.py`,
`live_coach.py`, `value.py` or `coach_ui.py`, and neither ships in a release.

This repository is the product, and the release zip is this tree minus the
maintainer-only parts (`analysis/`, `telemetry/`, `CLAUDE.md`, `DESIGN.md`,
`ROADMAP.md`, the LLM tools and the caches).

## Layout

**The code lives in `app/`, not at the root.** The root keeps the launcher,
`README.md`, `LICENSE` and `docs/`, so someone who unzips a release sees the
thing to click and the documents — and nothing else. The zip mirrors the repo
(it walks the working tree), with `VERSION` and `.update_state.json` written at
the zip ROOT: that directory is what `update.py` resolves as the install root,
one level above the code.

- Suite: `python -m unittest discover -s app/tests` (from the repo root).
- `app/meta/`, `app/img_cache/`, `app/decision_logs/`, `app/patch_reports/`:
  the code derives all of these from its own directory, so they moved with it.
- `analysis/` (research notes, some naming real opponents) and `telemetry/`
  (the release channel itself) stay at the root and never ship. Maintainer
  tools that read `analysis/` therefore resolve `dirname(_HERE)/analysis` —
  deriving it from `_HERE` alone silently turned the patch-coverage gate into
  a no-op.
- Installs from before the move are reshaped on update by
  `update.py::migrate_flat_layout`: local data moves into `app/`, the old loose
  files are removed, and anything unrecognised at the root is left alone.

## Worktree discipline

- Code work happens in git worktrees under `.claude/worktrees/`. **Main is the
  only truth; origin is backup. If it's not in main, it's not done.**
- Every session that touched code ends with `python app/sync.py` (commit + merge
  into main + push) — or ends by explicitly reporting "branch X, N commits,
  NOT merged".
- Branch from FRESH main. Starting from a stale base is how the same bug got
  fixed twice on two branches.
- After a merge, delete the remote branch too.

## Never break these

- **Privacy.** `sanitize_log.py` redacts every identity in a shared log
  (BattleTags, bare opponent handles, account ids); `privacy_scan.py` is the
  independent verifier; `publish_release.py` refuses to publish if any shipped
  text file carries personal data. Do not weaken the redactor, do not make the
  verifier share its patterns, and do not add a real handle to a fixture
  (use the documented placeholders).
- **The update join.** `VERSION` + `.update_state.json` are stamped into each
  release and are what let a zip install be told a newer release exists.
  `update.py::_install_root` prefers whichever directory holds a `VERSION`, so
  the code can sit one level below the stamps (the `app/` layout) without the
  extraction landing in the wrong place.
- **The two publish gates.** They have deliberate overrides; using one should
  be a decision, never a convenience.
- **Consent gates the only outbound player data.** `share.py` sends nothing
  until the stored answer is yes, refuses a report its own verifier rejects,
  and never raises into the coach. `session_report.py`'s whitelist `SPEC` IS
  the privacy control: a field it does not name cannot appear, so adding a
  field to the report means adding it to the spec on purpose.
- **`privacy_scan` cannot see a JSON name field.** It matches the shapes the
  log writes (`PlayerName=`, `Entity=`, `GameAccountId=`) and a handle under
  a key called `"name"` matches none of them. The opponent's handle rides in
  `analysis.opp_comp.name` — one real session carried 50 — which is why a
  bundle of raw decisions could pass "verified clean" while carrying one.
  Strip by name; do not lean on the scan for that category.

## Domain facts that keep biting (log ground truth)

- **Minions cost a FLAT 3 gold, all tiers.** Their `tag=479` COST tags are
  stale legacy tier costs and must not be trusted; `value._buy_prices` is the
  one price layer. Tavern spells keep their own prices.
- **Tavern upgrade prices are dynamic**: start at (target+3) gold, drop 1 per
  round waited — read the live button cost, never compute it.
- **The per-game ban list is provably NOT in the log** (identical CREATE_GAME
  across different-ban games). The 5/5 inference is pool-statistical, and the
  overlay's manual ban picker (`POST /bans`) supplies exact bans.
- **Casting a spell from HAND is free** — only the tavern BUY charges.
- **Combat-phase stat gains are non-persistent**, so combat-only buff-givers
  are `W_COMBAT_SCALE` power, not growth engines.
- Card ids drift across patches; identity matching prefers names for trinkets
  and heroes, ids for minions.

## Tool map (see DESIGN.md for the full list)

Live path: `live.py` (monitor + overlay server) → `live_coach.py` (incremental
analysis) → `value.py` (value function, top move) → `coach_ui.py` (overlay).
Support: `board_state.py`, `bans.py`, `pool.py`, `lobby.py`, `choices.py`,
`simulate_growth.py`, `meta.py`, `tribes.py`, `config.py`.

Maintainer: `doctor.py` (one-shot pre-flight verdict — start here),
`patch_day.py`, `logquery.py`, `review_kit.py`, `replay_review.py`,
`comp_miner.py`, `pool_roster.py`, `check_meta.py`, `check_patch_db.py`,
`privacy_scan.py`. Every entry point is bounded to a few lines and takes
`--json`: output tokens are the expensive side.

## Release & first run

`python app/publish_release.py --note "..."` builds the zip, runs both gates, and
PUTs it plus the manifest to the collector's KV namespace (the collector lives
in `telemetry/`, deployed at `bobs-ledger.workers.dev`; the same URL serves
every release, so installed copies keep updating). `--dry-run` runs the gates
without uploading.

Applies are atomic: `apply_zip` stages the release in `.staging`, verifies it
against the zip, then moves each file into place with the copies it replaces
set aside — so an interrupted update rolls back instead of leaving an install
that is part old and part new. Both launchers restore `.staging/old` before the
program check (a killed commit can leave `app/live.py` missing, and telling a
player to re-extract the zip is useless); `update.recover()`, or
`update.py --recover`, then finishes precisely — including removing files the
new version added — while `APPLIED` on disk means "do not undo this".

## Where the last session left off (2026-10-04, main bf242f2)

Sharing sends ONE REPORT PER GAME, and as of main 72d6b60 the share path is
idempotent per report id. TWO CLAIMS IN AN EARLIER VERSION OF THIS FILE WERE
WRONG — the artifacts say so, so do not re-diagnose from the old text:

* "three games produced three reports" counted FILES, not games. Two of the
  three were one game's advisory set uploaded twice under two ids, because a
  session-level report keys a different id from a per-game one and the two
  schemes did not dedup against each other. `share_latest` is per game now.
* The truncated upload was NOT the game-end trigger firing early. That game ran
  to turn 13; the log's only `PLAYSTATE=LOST` is at 11:57:38, while
  `.report_ids.json` was already minted at 11:42:06 holding 14 of the game's
  eventual 128 advisories. It was the EXIT backstop — a Ctrl-C mid-game — so a
  settle delay after the game end would not have prevented it. `_share_finished`
  now shares only games that have ENDED, and `monitor()` publishes its view of
  the live game (`_LAST_GAME`) for `main()`'s finally, which has no coach.

The `.sent.json` gap was the write ORDER, not the timing. The ledger entry was
written only after a completed response and never for a 409, so a lost response
left the cloud holding a report the client denied sending — and every retry
rebuilt the payload, which `manifest.created` makes different bytes, so the 409
became permanent. A report id's file IS the payload now, a 409 counts as
delivered, and both outcomes are recorded.

`monitor()` has a smoke test (`app/tests/test_monitor_smoke.py`). It has to reach
the game-end share line and a session switch — where the two `opts` NameErrors
shipped — and it fails if nothing was advised or if a tick SWALLOWED an exception,
because `monitor()` catches per-tick and per-line errors and keeps looping by
design. Reintroducing the `opts` NameError fails it.

**The report spec is now a control with teeth, and that has an operational cost
worth knowing before it surprises anyone.** `scenario`, `choice` and
`comp_progress` name their keys one by one instead of accepting any map, and
`source_problems()` reads the SOURCE — so **a new analysis field, or a new key
inside one of those maps, now REFUSES the send** until it is added to `SPEC` or
listed in `DROPPED_FROM_ANALYSIS` (`session_report.py`). That is deliberate: the
alternative is what happened to `scenario.trinkets`, dropped silently from 560 of
641 real advisories for a whole patch. The refusal names the field and the fix is
one line. `identity_findings()` additionally refuses a payload containing any
handle the session's own records showed — the check `privacy_scan` cannot do,
since a bare display name matches nothing it looks for — with handles that are
also game vocabulary exempt, because one real opponent is literally called
"Demon" and the payload carries that word 88 times as a tribe.

`package_corpus.inspect()` really decompresses the log now (it scanned mojibake,
so the corpus path's only independent log check could never fail), and
`upload_corpus.py` runs it and refuses before uploading — it used to print "the
BattleTag-redacted Power.log" over a raw log it had never checked.

The overlay's freshness line no longer accuses a working coach: the gap between
buy phases is a median 81 seconds (measured over 13 real phases), and 8 seconds
of it used to read "is live.py still running? (it is frozen, not live)". Only a
coach that has stopped ANSWERING alarms now; old advice says when the next shop
updates it. `freshnessLine()` is a pure function and
`test_overlay_freshness.py` executes it under node. A finished game's plan also
clears at the game's end rather than at the next `CREATE_GAME`.

**Consent is scoped to the answer** (main bf242f2). A yes covers the games played
from that point on, and nothing else: a game recorded while the answer was no — or
before there was one — is never sent, not even later. Before this, answering yes
uploaded the whole decision log, which is not what "Nothing is sent unless you say
yes" leads a player to expect and which nothing on screen disclosed. `set_choice`
already stamped `decided`, so the rule is one comparison in `share._consented()`;
the overlay says the scope where it asks, and `test_consent_scope.py` owns it.
Also settled in the same pass: `Clear` brings the CARD back, not the question (the
README said otherwise and now describes what happens), and `--poll 0.5` — the form
README:172 documents — parses instead of dying with an `IndexError` at startup.

NEXT, still open:

1. THE CORPUS, MEASURED (2026-10-04, with the read key — `HEARTH_TELEMETRY_KEY`,
   an ENVIRONMENT variable; nothing reads a file, see telemetry/README.md):
   **six stored reports are FOUR games, and not one of them came from a fixed
   build.**

   * Two games are stored TWICE, under two ids each: `1f4abb4e70e3` =
     `be2253ec8e05ea21` (the 10-02 22:16 game) and `f50bc4c4d71af87c` =
     `69c55cfcefde1724` (the 10-04 10:30 game), with byte-identical advisory
     sets. Any count over "6 reports" therefore double-counts half the corpus.
   * `451ada39fa79745b` holds **14 of that game's 128 advisories, permanently**:
     the collector has no delete route and refuses a replacement (409), so the
     other 114 exist only in the install's local copy.
   * Distinct advisories: **527**, against the 828 those files sum to. Coach
     versions `38b9aef`, `ef2a33f`, `4a16e0c`, `5b7e83c` all predate every fix
     described above, and no report carries `coach_versions` — so nothing in the
     cloud was produced by fixed code, and the first clean games are whichever
     the testers play next. `scenario.trinkets` in a report is the cheap marker
     of post-9bbf45e code.

   Four games cannot support a conclusion about advice, so the README's "has not
   been measured" caveat stands. What the count does show is that the two defects
   above were not hypothetical.
2. From the wider audit, untouched: the macOS launcher has still never been parsed
   by any shell on this machine (its `--check` fix is reasoned, not run); 9 tests
   are dead behind `HEARTH_REAL_SESSION_TESTS` (nothing sets it);
   `upload_corpus.py` and `fetch_sessions.py` ship to players; `README.md` has no
   test at all, which is how a sentence about `Clear` stayed wrong.

Smaller open items: the KV namespace also holds every `release/…` zip, so filter
by the `sessions/` prefix rather than scanning. The dashboard download names files
`sessions_<date>_<id>.json.gz`, and the values are gzip, which is correct.

The `readme-rewrite` branch is still on origin, unmerged and now identical to
`main`, kept only so a non-technical tester's link keeps working.

Users start with `Start Bob's Ledger.cmd` at the zip root: it finds Python,
asks before installing `requests`, and **offers to turn Hearthstone's file
logging on** — `setup_logging.py` edits the game's own `log.config` in place
(backing it up first and touching only the two keys the coach needs, because
that file has five other sections that a Deck Tracker user depends on), then
offers a Desktop shortcut wearing `app/bobs-ledger.ico`, and runs
`app\live.py --open`. Windows
draws no icon on a `.cmd`, so the shortcut is the only clickable thing that can wear
one — and it must be created on the user's machine, since a `.lnk` embeds
absolute paths.

`Start Bob's Ledger.command` is the macOS twin, kept in step by hand. It is
**unverified**: no Mac has run it, and the packaging machine has no bash to
even parse it. Platform branches live in `config.py` (client root, launcher
names, both `Power.log` shapes) and `setup_logging.py` (`log.config` under
`~/Library/Preferences` on macOS; a `pgrep` probe instead of `tasklist`).
Dependencies go into a `.venv` rather than `--user`, because Homebrew's Python
refuses system-wide installs (PEP 668) — and the Windows launcher already
prefers a venv, so both use the same one.

## Hazards worth remembering

- `publish_release.py` walks the WORKING TREE, not git: an untracked scratch
  directory once inflated a release from 236 entries to 472. The
  reproducibility gate catches it; do not paper over it with `--allow-dirty`.
- A release cannot be built from a linked worktree: `.git` is a FILE there, and
  `EXCLUDE_DIRS` only prunes directory names, so the zip picks it up and the
  reproducibility gate refuses (`1 entry/entries in the zip are not tracked by
  git: .git`). Run the gates from the main checkout — which is where publishing
  happens anyway.
- `scrape_comps.py --diff` REPORTS but still WRITES — `--dry-run` is the flag
  that does not. `refresh_trinkets.py` writes by default for the same reason.
- `python-hslog/` is vendored and TRACKED (upstream's tests are not, because
  their fixtures carry third-party BattleTags). `parse_bg.py` is the only
  tool that needs it; `extract_game.py` is stdlib-only.
- Hearthstone logs live at `C:\Program Files (x86)\Hearthstone\Logs\...`;
  Hearthstone ROTATES them, so a measurement quoting a session dir may not be
  re-derivable later.
- Real logs carry real people's handles. Local `decision_logs/` and
  `Power.log`s hold everything by design and never leave the machine except
  through the sanitized corpus path.
