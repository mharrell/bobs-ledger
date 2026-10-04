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

## Where the last session left off (2026-10-04, main 72d6b60)

Sharing sends ONE REPORT PER GAME, and as of main 72d6b60 the share path is
idempotent per report id. TWO CLAIMS IN THE PREVIOUS VERSION OF THIS FILE WERE
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
design. Reintroducing the `opts` NameError fails it (the other 1229 tests still
pass through it).

NEXT, from the 2026-10-04 review, none of these fixed yet:

1. `package_corpus.inspect()` decodes `log_gz_b64` WITHOUT `gzip.decompress`
   (`package_corpus.py:299`), so the corpus path's only independent log check
   scans mojibake and reports "verified clean" for any bundle. Its test decodes
   it correctly, which is why nothing caught it.
2. The report whitelist is only a whitelist where it names keys: `scenario`,
   `choice` and `comp_progress` are open maps (`session_report.py:98-107`) and no
   string field's CONTENT is checked, so a bare handle in `top_move_steps[].reason`
   POSTs with `verify()` and `privacy_scan` both clean — demonstrated with a real
   `share_session`. (`scenario.trinkets` is a list, so MAP_SCALARS drops it too.)
3. `upload_corpus.py` posts whatever path it is handed while printing that the log
   was BattleTag-redacted; `privacy_scan` is never called on that path.
4. The overlay calls a healthy coach "frozen, not live" during every combat phase
   (`coach_ui.py:497`'s 8 s threshold against a median 81 s between buy phases),
   and a finished game's plan stays on screen until the next `CREATE_GAME`.
5. `Clear` does not bring the sharing question back although README:97-99 tells
   testers it does, and consent is RETROACTIVE: games played while sharing was off
   are uploaded once the answer becomes yes.
6. Nothing tests the publish gates, and deleting `privacy_scan`'s whole
   `player_name` category passes all 1252 tests.

Smaller open items: the Cloudflare read key (`HEARTH_TELEMETRY_KEY`) is not in
`telemetry\.dev.vars`, so the KV listing needs the dashboard; and the KV
namespace also holds every `release/…` zip, so filter by the `sessions/` prefix
rather than scanning. The dashboard download names files
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
