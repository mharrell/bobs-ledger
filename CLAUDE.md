# Bob's Ledger

**READ `PIVOT.md` FIRST.** As of 2026-10-06 the product is split in two, and that
split governs every UI decision from here: **the live overlay ships STATE, and
the model's verdict ships after the fact, in the review.** `PIVOT.md` carries the
reasoning, the corrections to the claim that triggered it, and the phase plan.

A Battlegrounds board reader and a post-game review. It reads the game from
Hearthstone's own `Power.log` and reconstructs the board; the numbers it shows
come from a **local value function plus growth simulator over a curated meta
DB**. The live path calls **no model and no API** — `coach_llm.py` is an
optional maintainer tool for patch-note extraction, and `compare_models.py`
is a model-comparison harness. Neither is imported by `live.py`,
`live_coach.py`, `value.py` or `coach_ui.py`, and neither ships in a release.

**The plan is still computed — it is only kept off the live page.**
`value.top_move` runs on every buy phase, `decision_log.record()` writes it, and
`coach_ui.LIVE_VERDICT_KEYS` is the single list that keeps it out of the overlay
payload. Do not "simplify" that by deleting the producer: the review and the
corpus are what the plan is FOR. `test_live_view.py` asserts all three halves of
that contract (dropped from the page, kept in the analysis, read by no page
code), and `test_readme_claims.py` is the control CLAUDE.md item 3 asked for.

**The review EXISTS** (`app/settle_up.py` — the pivot's Phase 2, 2026-10-06): one
row per advised buy phase, the model's line beside what the player actually did,
and the effective HP the following fight cost. The end-of-game card offers
**Save replay** (2026-10-07: the card's old "Settle up" link became the button
that keeps the game for the tab; `/review` remains for the CLI and tooling), and
`live._settle_up_in_background` builds it off-thread the moment
a game ends — off-thread because it replays the game. **The cast-grading gap is
CLOSED (2026-10-06)**: a plan that led with a cast used to read "not graded"
(8 of 16 phases on the first real game) because `value.top_move` derived every
step's `card` by parsing the rendered text, so only a buy step ever resolved
one, and `player_actions` counted spells instead of naming them. `_top_move_text`
now records which card each hand step is about and `player_actions` records
`spell_ids`; the same game reports ONE ungraded phase (a swap). What stays
ungraded and why: a swap needs the sell AND its replacement as a pair, and a
cast-led `taken` is weaker evidence than a buy-led one (a turn casting several
spells can satisfy "Cast X" incidentally) — the summary prints both facts.

**The name stays "Bob's Ledger", decided 2026-10-06.** It was already the pun:
Bob runs the Battlegrounds tavern, and a ledger is the tavernkeeper's book. The
pivot made the existing name MORE accurate, not less — it was always the odd part
of the old positioning. A rename would also cost ~26 files, including both
launcher filenames, the Cloudflare workers.dev subdomain every installed copy's
updater points at, and the desktop shortcuts already made on players' machines.
The bar-tab language lives in the review's name instead: "Settle up".

This repository is the product, and the release zip is this tree minus the
maintainer-only parts (`analysis/`, `telemetry/`, `CLAUDE.md`, `DESIGN.md`,
`ROADMAP.md`, the LLM tools and the caches).

## Layout

**The code lives in `app/`, not at the root.** The root keeps the launcher,
`README.md`, `LICENSE` and `docs/`, so someone who unzips a release sees the
thing to click, the documents and the pictures — and nothing else. `docs/` holds
the screenshots **the README shows**, re-shot 2026-10-07 against a layout that
exists (`save-replay`, `settle-up`, `turn-shop`, `turn-battle`, `turn-result`).
The set before it showed the pre-pivot overlay — the "DO THIS NOW" panel the
2026-10-06 pivot deleted — and shipped in the `94a07de` and `2ef006c` releases
before anyone noticed, which is why three rules now apply:

* **A new shot must show a layout that still exists**, and a README sentence
  describing a picture has to change in the same commit — a stale sentence about
  a picture is the same failure as a stale sentence about the code.
* **A screenshot is a claim nothing else checks.** `privacy_scan` reads
  `TEXT_SUFFIXES`, so it cannot see inside a PNG, and no gate looks at the
  pixels; the one field worth eyeballing before a shot ships is the overlay's
  "Next opponent" line, which renders `analysis.opp_comp.name` — where a real
  opponent's handle can ride.
* `test_readme_claims.TestTheScreenshotsMatchTheReadme` pins both directions
  (every image the README shows exists; every file in `docs/` is shown by the
  README, so a shipped zip carries no orphan). It cannot check what a picture
  SHOWS — that part is still human, which is the point of the two rules above.

The zip mirrors the repo
(it walks the working tree), with `VERSION` and `.update_state.json` written at
the zip ROOT: that directory is what `update.py` resolves as the install root,
one level above the code.

- Suite: `python -m unittest discover -s app/tests` (from the repo root).
- `app/meta/`, `app/img_cache/`, `app/decision_logs/`, `app/patch_reports/`:
  the code derives all of these from its own directory, so they moved with it.
- `analysis/` (research notes) and `telemetry/` (the release channel itself) stay
  at the root and never ship. **MEASURED 2026-10-07**, because "some naming real
  opponents" sat in this file for months without ever being checked and it turns
  out to overstate what is there: no opponent handle, player-name, account id or
  JSON name-key value appears in any tracked `analysis/` file, or anywhere in the
  repository's entire history. What the notes DO carry is the maintainer's own
  session directory names, and opponents described by hero and archetype rather
  than named. The exclusion stays regardless — `publish_release` walks the
  WORKING TREE, so an untracked note could ship without git ever seeing it, which
  is the shape of the incident the exclusion was written for. Maintainer
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
- **The release signature (2026-10-07).** `release_sig.py` pins the public key an
  install will accept, and `update.py` refuses an unsigned or mis-signed
  manifest — with **no bypass flag**, because `--force` overrides the direction
  guess, never the identity check. `publish_release.py` will not publish without
  the offline key, and refuses a key the shipped `PUBKEY_B64` does not pin. Do
  not weaken the verification to make a publish convenient, and never let the
  private key into this repo, the zip, or the Cloudflare account.
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
without uploading. There are **three** gates since 2026-10-07: privacy,
reproducibility, and the **signing** gate — the release must be signed with the
offline key (`--signing-key`, or `HEARTH_SIGNING_KEY`) and with the very key the
shipped `PUBKEY_B64` pins. `telemetry/README.md` has the operator's section,
including what losing that key costs.

Applies are atomic: `apply_zip` stages the release in `.staging`, verifies it
against the zip, then moves each file into place with the copies it replaces
set aside — so an interrupted update rolls back instead of leaving an install
that is part old and part new. Both launchers restore `.staging/old` before the
program check (a killed commit can leave `app/live.py` missing, and telling a
player to re-extract the zip is useless); `update.recover()`, or
`update.py --recover`, then finishes precisely — including removing files the
new version added — while `APPLIED` on disk means "do not undo this".

## The client root is RESOLVED, not assumed (2026-10-06)

`config.resolve_home()` owns the answer now, in this order: `HEARTHSTONE_HOME`,
then `app/.hs_home.json` (written by `config.py --set`, and IGNORED when the
folder it names has gone, so a drive that changed letter cannot pin a dead
path), then the Windows uninstall entry, then the platform default, then a drive
walk, then the default again — so the worst case is exactly what every earlier
version did. `HS_HOME_SOURCE` carries HOW it was chosen, which is what lets a
message name the folder instead of guessing at the reason.

The failure it replaces was THREE lines that cannot all be true: "File logging
is on" (the launcher had just switched it on), "no Hearthstone log folder at
`C:\Program Files (x86)\Hearthstone\Logs`", and "Hearthstone's file logging is
probably OFF". The false one sent the player to fix a setting that already
worked. `Logs/` lives INSIDE the client root; `log.config` does not — it is under
%LOCALAPPDATA% — which is why the logging switch worked on a non-default install
all along while the log lookup did not.

Measured 2026-10-06, so nobody has to re-derive it:

* The key is `HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\
  Uninstall\Hearthstone` → `InstallLocation` (and `DisplayIcon`, the game's own
  exe, as the second chance). It MUST be read with `KEY_WOW64_32KEY`: the game
  is 32-bit, and a 64-bit Python asking the default view gets "file not found"
  while the key sits right there. `HKCU` carries no Hearthstone entry here.
* Two dead ends, both checked: `HKLM\SOFTWARE\WOW6432Node\Blizzard
  Entertainment\Hearthstone` does not exist, and `HKCU\SOFTWARE\Blizzard
  Entertainment\Hearthstone` holds nothing but Unity display settings. Battle.net's
  own `C:\ProgramData\Battle.net\Agent\product.db` (6081 bytes here) carries no
  readable install path in UTF-8 or UTF-16 decoding — it needs the protobuf schema.
* A Google Drive letter answers `GetDriveTypeW == 3` (DRIVE_FIXED), so that
  filter does NOT keep the walk off a cloud mount. That is why the walk is last
  and only runs when nothing above it answered.
* **No D:\ install has ever been tested here.** The registry step is attested by
  mechanism (the key is rewritten when the game is installed or moved), the
  drive walk is the belt for it, and `test_client_home.py` pins the ORDER with
  the sources mocked — not the machine.

`app/.hs_home.json` is local state, and is guarded in all three places that
matter: a BASENAME in `.gitignore` (`sync.py --new` commits untracked files),
`publish_release.EXCLUDE_FILES` (machine-specific, and the reproducibility gate
would refuse it), and `update.PROTECTED` (a memory of the right folder is worth
nothing if an update overwrites it). `HEARTHSTONE_HOME_FILE` moves it, which is
how the tests avoid writing into `app/` and how a read-only install can still
remember.

Both messages are pure functions so they cannot drift back into blaming logging:
`live.no_log_advice()` and `coach_ui._welcome_hint()`, the latter branching on
whether the resolved root actually has a `Logs/` folder — and neither prints a
path from this machine, because the overlay ends up in screenshots.

## Where the 2026-10-07 night session left off (Settle Up becomes a tab — released as c885b2e, then 409a47e)

The pivot's Phase 2 shipped a review **page** (2026-10-06). This session turned it
into something a player can keep and browse, and re-pinned the wall it crosses.
12 commits, 10-06 23:53 → 10-07 10:23; a review pass the next hour added 3 more
(the two repairs in item 4/5, the golden consolidation in item 6, and this
record). Suite **1694 green (11 skipped)**.

**1. Saved reviews outlive the process.** `app/replay_store.py`: one JSON per
game under `app/saved_replays/` — readable ids
(`2026-10-06_185502-Chenvaala-2`, collision-suffixed), atomic writes,
corruption-tolerant listing, path-safe load. The stored rep keeps card IDS;
display names are joined at SERVE time (`coach_ui._name_timeline_boards`), so the
file stays canonical and a renamed card fixes old saves. Per-user data, the
`decision_logs` class: gitignored by BASENAME (the `sync.py --new` reason) and in
`publish_release.EXCLUDE_DIRS`. The source log rides as a POINTER (`log` +
`game`), never a copy.

**2. The tab.** A two-tab toggle at the top of the overlay page — **Another
Round** (the live view, byte-for-byte underneath) and **Settle Up** (a browser
over saved games, fetched ONLY from `/review/*`). Endpoints: `POST
/review/save` (the end-of-game card's only button now — the "Settle up" link and
the page's Clear button are gone, 2026-10-07), `GET /review/list`, `GET
/review/game?id=`, `POST /review/open-folder`. The id charset is the store's
filename charset.

**3. The turn cards, and the two rules that were paid for with a wrong answer.**
Each turn is three views — **Shop** (the default since 2026-10-07: it is where
the player's own decisions and the phase rows are read), **Battle**, **Result**.
The battle
board is the strongest burst **before the first death**: the staging burst reads
low (31 stats staged vs 51 a burst later, measured 10-06) and plain max-combined
landed on the duel's aftermath (4730 vs 448). A turn's decisive fight is the
**last** staging group (`_fights`), because the 10-07 final staged the round's
fight and the game's final duel in the SAME turn — first-burst selection showed
the wrong game. A RESULT comes from the fight itself: combat ends when one board
dies, so the side that drained first lost, and the winner is reported with their
last staged board rather than from the next shop's mid-teardown snapshots (those
once produced an aftermath with both sides "surviving").

**4. One control was DEAD for six commits, which matters more than the bug it
should have caught (found and fixed 2026-10-07).** `19fbcb5` — whose message is
literally "docs + the wall re-pinned" — replaced `class TestTheWall(_StoreRoot):`
with `class TestNamedBoards(_StoreRoot):` and left the old body indented under a
fresh `if __name__ == "__main__": unittest.main()`. Python accepts that, unittest
registers nothing, and `Ran 1691 tests … OK` said all was well while PIVOT.md §6.4
and `analysis/SETTLE_UP_BOARDS.md` both cited those two tests as the wall's
enforcement. Restored — and they PASS, so the invariant held while its control was
dead. Two lessons: a green suite is evidence only about the tests that EXIST (a
class statement lost in an edit is invisible to discovery), and a doc citing a
control is not a control.

**5. The same pass fixed a NameError that made the tab unable to open a game.**
`_name_timeline_boards` called `value.display_name` while coach_ui did `from
value import (…)` and never imported the module — `GET /review/game` answered 500
for every saved game, which is the tab's only way in. Three tests errored.

**6. Golden naming is ONE function now.** `value.display_name(names, cid)` is the
single place a golden is spelled out, lowercase `"(golden)"` — that is the string
the live plan text has always carried and `split_step` parses it back
(`test_value` anchors "Buy River Skipper (golden)"), so a second capitalization
would be a second convention. The uncommitted 10-07 draft added a second helper
spelling it "(Golden)"; `_shop_name` is gone and its eight call sites use the one
function. **And a timeline board never carries a `_G` id at all**:
`board_state._minion` strips the suffix and keeps the flag beside the base id —
measured on a real 15-turn rep, 0 board ids end in `_G` while 91 minions carry
`golden` — so the serve-time join NAMES and touches nothing else.

**OPEN, in the order worth doing them:**

1. **A fight straddling the turn boundary can leave the Result unreadable.**
   Measured on the newest game (`Hearthstone_2026_10_07_07_58_33`, Tavish
   Stormpike, 1st): `winner` is None on T6 and T9, both of which held a real
   fight — the LAST staging group in the bucket never drains inside the turn, and
   their board keeps draining (7→6→6→5→4→4→4) into the NEXT turn's buy snapshots.
   The Result view then prints "(fight result not readable)" and, in the same
   panel, "They survived with — none": the `w === null` branch falls through to
   the `— none` text. `_fights`' separator (their board coming BACK) is the
   suspect, and this is the same family as the wrong-fight selection `ac0b031`
   fixed. T2 and T11 are a different case and are fine: no coach analysis, so
   `gold` is None and the card header reads "—g".
2. **A review costs TWO replays per game** (~10 s for 15 turns):
   `outcome_audit.audit_game` for the phase rows and `turn_review.timeline` for
   the boards. An injected coach would make it one.
3. **`player_actions` may double-count a single sell** — unchanged from 10-06:
   turn 7 of that game reports three entries for two cards, and the count feeds
   `fight_table` and the audits, so it needs its own look, not a dedupe in the
   consumer.
4. **A swap-led plan is still ungraded** — grading one needs the sell AND the
   play that replaced it as a pair, which the row does not carry.
5. **`docs/` has its pictures back (DONE 2026-10-07).** Five shots against the
   current layout — `save-replay`, `settle-up`, `turn-shop`, `turn-battle`,
   `turn-result` — all shown by the README, all pinned by
   `test_readme_claims.TestTheScreenshotsMatchTheReadme`. Still missing: a shot of
   the LIVE page (**Another Round**), which no release has carried since the
   pivot, and `docs/` is the one shipped directory the privacy gate cannot read
   at all — see Layout. The turn shots were taken with Battle as the default, so
   the Shop one was reached by a click; re-shoot if the button order ever
   changes.
6. **PUBLISHED TWICE, BOTH VERIFIED FROM THE PLAYER'S SIDE (2026-10-07).**
   `c885b2e` shipped the tab, the replay store and the turn cards; `409a47e`
   followed within the hour with the turn cards defaulting to **Shop** and the
   screenshots back in `docs/` (plus the README sentences that had gone stale).
   For both: all three gates passed, the live manifest verifies against the
   pinned `PUBKEY_B64` (`4d8fc45534ba558d`) with `zip_bytes`/`zip_sha256`
   matching the downloaded zip, the pin INSIDE the zip matches this checkout, the
   two stamps sit at the root with no maintainer or local paths, the SHIPPED
   updater run from inside the zip offers the update from the previous release
   and exits 1 (only reachable through a successful verification), and that same
   shipped code REFUSES a manifest whose `note` was rewritten, printing the key
   fingerprint and downloading nothing. Neither publish hit either documented
   gotcha: no `Authentication error [code: 10000]`, and `latest.json` served the
   new manifest on the first read both times. `409a47e` is 245 entries / 1.4 MB
   and **carries `docs/*.png`** — the first release since the pivot with pictures
   in it, which means the one shipped directory `privacy_scan` cannot read is
   back in a download (see Layout). The KV + GitHub copies carry both
   (`releases/latest` is `409a47e`).

## Where the 2026-10-07 afternoon session left off (the pick panel, and what the corpus holds now)

**1. The live pick panel was still shipping a verdict, and the wall could not
see it.** `choices._rank_discover` labelled ROW 0 `"best available"` (and
`"best off-comp"` below a displayed comp) for a day after the pivot — the
verdict the pivot deleted, alive one layer UNDER the wall: `LIVE_VERDICT_KEYS`
drops verdict **keys**, and a verdict inside a fact **string** passed straight
through. `test_live_view` could not see it by construction. The control is now
`test_choices.TestTheFactsNameNoRank`, which runs the three real rankers and
fails on any fact containing a rank word; rehearsed by patching the old label
back (it fires, naming the fact). The panel header ("what each scores") and
`live._advise_pick`'s console copy went the same way.

**2. The options carry STATISTICS now, and the page renders GAME ORDER.**

* Heroes: the power text plus `picked in N% of games`. The blended 0-10 score
  used to be printed under the name, which is an index nobody can read.
* Trinkets: pick rate, `avg place`, and `top-4 in N% of its games` computed
  from `placement_distribution` — a whole distribution the DB has carried all
  along and nothing rendered. An average hides the difference between a
  consistent 4th and a coin-flip between 1st and 8th.
* Discovers: `core of <comp> (you have N of its M)` / `addon of <comp>` /
  `<tribe> - the tribe <comp> is built on` / `not a piece of the comp you are
  on`. With no displayed comp, NOTHING is claimed.
* **`choice["ranked"][0]` IS the plan's pick** (`value._top_move_text` reads
  row 0, and row 1 as the locked-hero fallback), so the ranker MUST keep
  returning score-ordered rows. The page sorts by a new 5th slot — the option's
  position in the list the game offered — so the panel shows game order without
  touching what the review grades. A "cleanup" that returns rows in game order
  would silently change which card the review says the model wanted.

**3. The corpus, measured again (2026-10-07): 30 reports, 30 games, 5,107
advisories** — against 10-04's "six reports are FOUR games", so there is real
data at last, and 24 of the 30 arrived in the last two days. By coach version:
`1ab34c4` (the 2026-10-05 build) **18**, `0189193` 4, and one each for
`94a07de`, `91be599`, `2196a27` and five older shas. Seven came in TODAY; six of
those landed between 11:05 and 12:39 on `1ab34c4`, which is one player's session
on a build three releases old. **Nothing has arrived from `c885b2e` or
`409a47e` yet**, so no measurement covers the newest code. Read it with
`npx wrangler kv key list --namespace-id abd7803c581b4470a2834e92ae0006a2
--remote` — `HEARTH_TELEMETRY_KEY` is NOT set on this machine and reading is
keyed by design, so wrangler is the operator's own path (telemetry/README.md).
**A report is advisories, not a replay**: nothing in the corpus carries a
Power.log, so what arrives can be re-read but never re-analyzed.

OPEN here:

1. **Nothing offers a player the path that carries a LOG.** `package_corpus.py` +
   `upload_corpus.py` build a redacted bundle *with* the Power.log and decision
   log (1-1.6 MB) and both tools ship, but no button in the app asks for one —
   so the only game data that arrives cannot be re-derived, only trusted. That
   is the gap behind "we need more replays" (maintainer, 2026-10-07), and it is
   a consent-and-whitelist change, not a button: `sanitize_log` + `privacy_scan`
   + the `session_report` posture all apply.
2. **The player's own record in the pick panel** — deferred by the maintainer,
   and now the first item of the README's new "Upcoming features" section.
   `replay_stats.aggregate` (Power.logs) and `settle_up._session_totals`
   (placements) already answer parts of it; nothing aggregates "how often was
   THIS CARD bought or chosen", which is the stat that would be new.

**4. "Stop sharing" is a quiet corner control now, and the README was pointing
at a button that does not exist.** The consent answer used to be changeable only
on the welcome/end-of-game card — on screen at a game's start or end, never
during the game it describes — so `coach_ui.share_state()` is now one builder
feeding BOTH payloads, `render_json` attaches it to every live payload, and a
small dimmed button at the right end of the tab row (`#share-toggle`,
`renderShareToggle`) shows the state and flips it. It is hidden while the
question is unanswered: the card asks, and two controls asking at once is how a
consent question becomes a shrug. `share_state()` is a PAGE payload added in
`render_json`, so it never reaches `decision_log` and therefore never reaches
`session_report.SPEC` (a test asserts the analysis stays clean). Writing this
turned up a real stale sentence in the one place being wrong matters: README's
consent section told players to "press **Clear** at the top-right of the
overlay", and the Clear button went with the tab work on 10-07 — no test could
see it, because no test reads that paragraph. Rewritten to describe the corner
control.

**5. PUBLISHED AND VERIFIED FROM THE PLAYER'S SIDE (2026-10-07): release
`ac00962`** — the pick panel's statistics and the corner sharing control, on top
of the two releases in the night-session section. All three gates passed and it is
signed with the pinned key; the live manifest verifies against `PUBKEY_B64`, its
`zip_bytes`/`zip_sha256` match the download (1430380 bytes, 245 entries), the pin
inside the zip matches this checkout, and the root holds exactly the launcher, the
README, the licence, `docs/` and the two stamps. Verified by RUNNING the shipped
code rather than by grepping it: the rankers inside the published zip return the
new facts (`picked in 60% of games`; `avg place 4.18 · top-4 in 56% of its games`;
`core of Beasts (you have 1 of its 1) · a second copy triples`) with the `order`
slot, and with no displayed comp they return **empty facts** — no claim, no rank.
The two `"best …"` strings still in the shipped `choices.py` are the docstring
that says they are gone, which is worth knowing before a future check reads a grep
as a leak. The SHIPPED updater, from a state reading `409a47e` (where players are),
offers the update and exits 1; the same shipped code refuses a tampered manifest
and names the key fingerprint. Neither gotcha appeared; `latest.json` served the
new manifest on the first read.

**6. The shared report can say how a game WENT now — and the end-of-game card's
placement was wrong (2026-10-07).**

* `session_report` gained two outcome fields, both named deliberately in the
  whitelist (a field it does not name is dropped on the way out):
  `manifest.placement` — the game's own final placement — and `hp_change` on
  every advisory: the effective HP the NEXT advisory of the SAME game reports
  minus this one's, i.e. what the fight between them cost. `hp_change` is None
  rather than 0 when the next row belongs to another game or either side has no
  health; a 0 would read as "the fight cost nothing".
* **The placement is NOT `current_place`, and this is measured.** Over three real
  games the last advisory's standing read **4** where the game's own
  `PLAYER_LEADERBOARD_PLACE` says **3**: the advisory is taken before the final
  fight resolves, and the game RE-CREATES the friendly hero for the final
  leaderboard with a fresh, higher entity id and a STALE placement — the trap
  `extract_game` documents. `LiveCoach.final_placement()` is the answer: the last
  write from the LOWEST entity id for our hero card. Checked against four real
  games (1, 3, 2, 7) — all match the log.
* **`coach_ui.show_game_over` takes that placement**, so the end-of-game card
  stops naming a standing the game later revised (it said "4th" for a 3rd-place
  finish). It falls back to `current_place` for the exit backstop, which has no
  coach to ask.
* Verified end to end on REAL data rather than on fixtures: a 212-advisory report
  built from the 10-03 decision log carries the placement, fills `hp_change` for
  201 of 212 rows, and passes all four gates (`check`, `source_problems`,
  `identity_findings`) — so a real report would still be sent. 13 new tests.
* **Still not measurable: whether the advice was FOLLOWED.** A report carries
  what the coach said, not what the player did — the actions live in the log
  (`player_actions`), so that is the next item and a `SPEC` decision of its own.

**7. `CLAUDE.md` was over the instruction budget, so the harness truncated it.**
67,753 bytes against 65,536 — twice in one session, silently dropping the tail
(the Hazards list and the oldest session record) from what a session is handed.
The 2026-10-04 section (20 KB) moved verbatim to
`analysis/SESSION_2026_10_04.md`; this file keeps a digest of what is still open
from it plus the two rules that still bind. Now 47,980 bytes. **The rule for next
time: a session section moves to `analysis/` when the next one lands.** This file
is loaded WHOLE by every session, and a record nobody can read is not a record.

**8. The turn card holds its size now, and LAYOUT is measurable (2026-10-07).**
Reported by the maintainer: *"when you switch between the phase views, the card
changes size and makes it hard to track where you're at now."* It did, for a
structural reason — the three view bodies were SIBLINGS of the buttons and
switching set the inactive ones to `display:none`, so a card was exactly as tall
as the view on screen and every turn below it moved.

* The fix is two lines of structure: the bodies share one grid cell (`.tviews`,
  `grid-area:1 / 1`) and the inactive ones are hidden with **`visibility`**, not
  `display` — they keep their layout space, so the card is always as tall as its
  TALLEST view. Measured in a real browser: `136 / 136 / 136` after, against
  `136 / 68 / 91` for the old structure.
* **`app/tests/test_overlay_layout.py` measures this in headless Chrome (or
  Edge)**, over a page built from the PAGE'S OWN `<style>`, reading `offsetHeight`
  back through `--dump-dom`. That is a new capability worth knowing about: the JS
  tests run under `node`, which lays nothing out, so any future "the page looks
  wrong" report had no control. It needs a browser, so it SKIPS and says so where
  there is none, like the node tests skip without node.
* **The rehearsal is inside the test and it earned its place**: the first version
  of the harness left `%s` in the bodies instead of substituting the rows, so all
  three views rendered EMPTY and every height came out 42 — the "same height"
  assertion passed for the wrong reason. The second case (the old structure must
  measure UNEQUAL) is what caught it. A layout check that cannot fail is worse
  than none, because equal heights are what a broken page reports too.
* Still human: whether the result LOOKS right. The measurement pins the height
  only, and the whitespace a shorter view leaves inside the shared box is a
  judgement about the layout, not a number.

**9. The README never introduced the TWO TABS (2026-10-07).** It described the
live page without ever naming it, and mentioned "Settle Up" only in passing
inside its own section — so a reader who opened the app met two tabs the README
had never named. There is a `## The two tabs` section now, ahead of "What you'll
see": what each one is for, that the tab you are on survives a reload, and that
the live poll runs on BOTH tabs so looking at an old game costs nothing (checked
in the source — `setInterval(poll, 300)` is unconditional — rather than assumed).

The same pass settled a 10-04 open item: the README's in-page anchors were an
unverified assumption about GitHub's slugger, and they are now verified
EXTERNALLY by fetching the rendered repo page and looking for the ids GitHub
emits (`user-content-<slug>`, all five present, `?` stripped). Two sentences were
tightened on the way through: the intro and the Settle Up section both said
"Result says who won" flatly, and a turn whose fights ran together says the
result is unreadable instead — the honesty is disclosed, not just the feature.

**10. PUBLISHED AND VERIFIED FROM THE PLAYER'S SIDE (2026-10-07): release
`745dcd5`** — the turn card that holds its size, the end-of-game card's real
placement, and the README's two-tabs section, on top of the three releases
recorded above.

* **Both documented publish gotchas reproduced in this one release, and the docs
  were right about both.** The first attempt died on the zip PUT with
  `Authentication error [code: 10000]` — re-running it published cleanly, and the
  channel kept serving `ac00962` (verified, not assumed: the manifest was read
  after the failure). Then the verification read `latest.json` and got the OLD
  manifest on attempt 1 and the new one on attempt 2, which is the eventual
  consistency the same README warns about — so "did it work?" took a retry, not a
  re-publish.
* Verified: the manifest verifies against the pinned `PUBKEY_B64`, its
  `zip_bytes`/`zip_sha256` match the download (1439785 bytes, 246 entries), the
  pin inside the zip matches this checkout, and the root holds exactly the
  launcher, the README, the licence, `docs/` and the two stamps. The shipped code
  was read for the two fixes (`.tviews` + `visibility` in `coach_ui`; `def
  final_placement` with the lowest-entity rule in `live_coach`, called from
  `live.py` and handed to both the card and the share; `placement` + `hp_change`
  in `session_report`) and the README inside the zip carries the new section.
* The SHIPPED updater, from an install reading `ac00962`, offers the update and
  exits 1; the same shipped code refuses a tampered manifest and names the key
  fingerprint.
* **A third check of mine was wrong before the code was**: the content probe
  looked for the placement wiring in `coach_ui.py` when the call site is in
  `live.py`, and reported the release broken. Worth remembering as a pattern —
  today's three false alarms (`best available` in a docstring, `%s` in a test
  harness, and this) were all the CHECK, not the artifact.

**11. THE OPENING BOARD SHOWED A FIGHT'S SUMMONS (reported and fixed
2026-10-07).** *"Sometimes, in battles, extra minions are summoned for various
reasons that go away once the shop phase starts. These minions are showing up in
the 'Opened With' section. We should be getting just the current ones. A max of
7."* Exactly right, and it was worse than reported: turn 15 of the 07:58 game
opened with NINE of our minions (four real golden Eternal Knights plus two the
Eternal Summoner's deathrattle left in PLAY — trap 3.6 of
`analysis/SETTLE_UP_BOARDS.md` has the numbers), turn 13 with nine, turn 12 with
eight, and turn 14's **Result** row inherited nine from turn 15's opening
snapshot. The filter is `turn_review._opening_board`, applied to `buy_start` and
to `battle_end` (they are the same snapshot, one turn apart), and it uses the two
things that are true of a real board and false of the leftovers: **at most seven
minions** and **no two minions in one SLOT** — the leftovers keep the position
they died at, and on all 7 measured collisions (6 games) the real minion is the
one with the LOWER entity id. That needed identity, so
`board_state._record_snapshot` now stamps `eid` (snapshots only — `_minion` is
untouched, the live board has no use for an internal id) and the live projection
carries `eid`/`pos` as slots 6 and 7. Every removal is reported in a line under
the board it is about; a silently shorter board would be a different lie.

Two things worth keeping: **`buy_end` is deliberately NOT filtered** — 88
buy-ends across 7 games never carried a leftover, so filtering the series every
growth number is read from would be pure risk. And **two plausible rules were
rejected on the evidence**: "a board cannot grow during a fight" is FALSE on
turns 2, 6 and 13 (the log's last buy snapshot predates a play the player really
made), and "never seen in a buy snapshot before" drops the battlecry-summoned
token that IS on the board. What the filter does not catch is measured and
written down rather than implied: a leftover on a FREE slot survives (turn 9's
`Cadaver Caretaker 4/3`), and one that surfaces mid-shop is never examined. Both
keep the board at seven, which is the reported harm. Verified end to end, not by
reading the source: the real game's review JSON now reads opened/ended/survived
≤ 7 on all 15 turns with the removals named, and the page's own
`settleTurnCard` was RUN in a headless browser against a row with the counts set,
printing the two notes in the right views (the layout suite does not exercise
that JS, so nothing else would have caught a syntax error).

## Where the 2026-10-07 session left off (release channel hardened)

Triggered by a security audit of the whole app after a Reddit thread called it a
"security nightmare". The audit's verdict was that most of that was wrong and
one part was right, and the right part is now fixed:

**1. Releases are SIGNED, and an unproven release is never installed.** This was
the real finding. `update.download_zip` checked a zip's sha256 against a manifest
fetched from the same server, so the check proved integrity and nothing about
authorship — a compromised Cloudflare account (or KV namespace, or this laptop,
or the GitHub account's copy of the same zip) could have shipped code to every
install that answered "y".

* `app/ed25519.py` — RFC 8032 Appendix A's implementation, extracted MECHANICALLY
  from the RFC text (no constant retyped by hand), Ed448/SHA-3 dropped.
  `app/tests/rfc8032_vectors.json` holds section 7.1's five vectors, also
  extracted by script; `test_ed25519.py` runs them, and because Ed25519 is
  deterministic a wrong constant fails rather than merely verifying less.
* `app/release_sig.py` — the policy: a pinned `PUBKEY_B64`, a canonical form that
  covers every manifest field except the signature (so `note`, `created`,
  `zip_bytes` and `zip_sha256` are all inside it), `verify_manifest` returning
  (ok, reason) and failing closed on everything unproven, plus keygen/read.
* `update.verified_manifest()` verifies exactly when an update would be OFFERED —
  not on every start, so an up-to-date install is not nagged about a channel it
  cannot act on. **`--force` is not a bypass**: it overrides the direction guess,
  never the identity check. `--check` refuses what the installer refuses.
* `publish_release.py` gained a **signing gate**: no key, no publish; and a key
  the shipped pin does not match is refused too (that mistake would otherwise
  surface one "REFUSING this update" at a time, on players' machines).
  `telemetry/README.md` has the operator's section, including the cost of losing
  the key: one manual reinstall per player, because there is no bypass flag.
* `update.PROTECTED`, `publish_release.EXCLUDE_FILES` and `.gitignore` all refuse
  the key file, the repo's usual three-place rule for local state.

**2. Size caps.** `download_zip` streamed nothing before: `r.read()` took whatever
the server sent into memory, and extraction had no ceiling. Now the SIGNED
`zip_bytes` is the cap (with `MAX_ZIP_BYTES` as the ceiling for a manifest
without one), and `stage_release` refuses more than `MAX_ENTRIES` entries or
`MAX_TOTAL_BYTES` declared bytes before writing anything.

**THE PIN IS SET AND THE CUTOVER RELEASE IS PUBLISHED (2026-10-07).**
`PUBKEY_B64` pins the key with fingerprint `4d8fc45534ba558d`. The private half
is `%USERPROFILE%\.bobs-ledger-release.key` on this machine — 32 raw bytes, ACL'd
to the user, its name guarded in `.gitignore`, `EXCLUDE_FILES` and `PROTECTED` —
and `HEARTH_SIGNING_KEY` points at it. **It is backed up off this machine
(2026-10-07)**, which was the last outstanding action from this session: losing
the only copy costs every player one manual reinstall, because there is no bypass
flag. Verify any copy by re-deriving the public half — `python app\release_sig.py
--pubkey <the copy>` must print `4d8fc45534ba558d`, and anything else is not the
key. Note for whoever reads this next: the "not backed up yet" line was true for
about an hour, and this repo's own rule is that a stale sentence about the state
of things is the same failure as a stale sentence about the code.

Release `91be599` is signed, published to KV and to the GitHub release, and was
verified from the PLAYER's side rather than from the publish log: the live
manifest verifies against the pinned key, the zip's sha256 and byte count match
the manifest, the pin inside the published zip matches this checkout, the
SHIPPED updater run from inside that zip (from a state reading `3233929`) offers
the update and exits 1 — which is only reachable through a successful
verification — and that same shipped code refuses a manifest whose `note` was
rewritten, printing the key fingerprint in the refusal.

Two things that surprise people publishing here, both hit while doing the above:
`Authentication error [code: 10000]` from the Cloudflare API is intermittent —
re-run it (that attempt died on the zip PUT, before the manifest, so the channel
kept serving the old release and nothing was half-published). And KV's eventual
consistency means `latest.json` can still serve the PREVIOUS manifest right after
a successful publish, so "did it work?" needs a minute of retries, not a
re-publish. Both are in `telemetry/README.md`'s gotchas already; they reproduced
exactly as written.

**3. The history scan (2026-10-07).** The audit's other real point: the privacy
gate scans the ZIP, so a value committed once and replaced with a placeholder
later passes every gate and stays in a public repository forever. Two tools now
answer that, and both are documented here because neither is obvious:

    gitleaks git . --log-opts="--all" --redact --no-banner   # credentials
    python app/history_scan.py                               # identities (--json, --full)

`gitleaks` (installed via winget, 8.30.1) found **5 leaks in 479 commits, all
false positives** — `app/tests/rfc8032_vectors.json` holds fields literally
called `secret_key` (RFC 8032's public test vectors), which its generic-api-key
rule reads as "secret" + high entropy. `.gitleaks.toml` allowlists exactly that
rule, path and shape, and extends the default ruleset rather than replacing it,
so tomorrow's real key in that file is still a finding. Rehearsed: clean after,
on both history and the working tree.

`app/history_scan.py` runs `privacy_scan` (the gate's own verifier, never a
second copy of the patterns) over every blob reachable from every ref, one row
per (value, file) with a blob count, masked unless `--full`, and it does not
ship (`EXCLUDE_FILES`). The baseline on 2026-10-07: **19 places, 38 blob
occurrences, 5 still in the working tree** — one session directory each in
`CLAUDE.md`, `PIVOT.md` and `analysis/SETTLE_UP_BOARDS.md`, plus two `user_path`
false positives (`telemetry/README.md`'s own `C:\Users\<you>` example, and
`telemetry/collector.js`'s detector pattern in a comment). All three
session-dir files are maintainer-only, so nothing personal is in a shipped file.

**The one finding that matters is a BattleTag.** It was committed on 2026-10-02
into two SHIPPED test files (`app/tests/test_share.py`,
`app/tests/test_session_privacy.py`) and removed the same day in `91858dc` —
"Docs for what actually happens, and the gate that caught my own fixtures" — so
the gate did its job while the file was live. It is history-only now, and
`https://api.github.com/repos/mharrell/bobs-ledger` answers **200 to an
unauthenticated request: the repository is public.** Getting it out of history
means `git-filter-repo` and a force-push, which rewrites every commit id — and
the commit shas ARE this project's release version strings and the
`VERSION`/manifest version of every published zip. So: decide whether the tag is
the maintainer's own (it looks like it, from the commit that removed it) and
accept it, or rewrite. Recorded rather than decided.

**DECISION (2026-10-07): NO history rewrite.** The one BattleTag is the
maintainer's own — one distinct value in 479 commits, in two test fixtures, and
the commit that took it out is literally "the gate that caught my own fixtures".
The scan puts the rest of the picture beyond doubt: `player_name`,
`player_entity` and `account_id` findings number **zero** across all of history,
and no `"name"` key in any tracked `analysis/` file carries a person. So the tag
is a self-disclosure of a gaming handle, not a credential, and it is not worth
rewriting 479 commit ids — which are this project's release version strings.

**What was actually published is a separate question, and it is clean too.**
git history is not the only thing shipped: `analysis/` went out in early
releases. Every release on the GitHub Releases page (31 of them, from `2a6fb40`
to `91be599`, enumerated through `api.github.com/repos/mharrell/bobs-ledger/
releases?per_page=100`) carries **zero privacy findings and no `analysis/` at
all**. Caveat worth keeping: that is the GitHub list, and an early KV-only
release would not appear in it, so this measures the audit trail rather than
proving nobody ever received a note.

Two scanner bugs the tests caught, both the kind that under-report quietly:
git stores identical content once, so a report built from `rev-list --objects`
names ONE path while the value may sit in several (`_paths_touching` fixes it);
and one commit subject in this repo carries a BOM, which crashed the report
mid-print on a cp1252 console — the same fix and the same reason as
`publish_release.py`'s. Also worth knowing: the gate DOES scan `.py`
(`privacy_scan.TEXT_SUFFIXES`), which was news to me — it refused the first
version of `test_history_scan.py` because a docstring spelled the tag shape out
literally, so that wording changed.

Suite: 1657 green (11 skipped — the pin-coherence test now RUNS rather than
skipping, which is itself the proof the pin is real), and both directions of the
signing gate were rehearsed against a throwaway key — no key refuses, an unpinned
key refuses, a pinned key passes and round-trips a probe manifest.

Still open from the same audit, in the order worth doing them:

1. **The loopback control plane has no auth token.** The Host/Origin/JSON guard
   is browser-shaped and correct for what it defends (cross-site requests), but a
   local process — any user's, on a shared PC — can still `POST /share` to opt the
   player in, and `GET /analysis` (live board plus the opponent's handle). A
   per-run token in the overlay URL would close it.
2. **`analysis/` is in a PUBLIC repository** (confirmed 2026-10-07: the GitHub
   API answers 200 to an unauthenticated request; `analysis/` is 41 tracked
   files). After the history scan this is a BUSINESS decision, not a privacy one:
   the folder carries no opponent identity — measured, not assumed — just one
   session directory per file and the maintainer's own research. "Not shipped"
   only ever meant "not in the zip", which is the reviewer's fair point; the
   remaining question is whether the research notes should be public at all, and
   removing them now would not remove them from history anyway.
3. `requests>=2.28` is unpinned, and the maintainer corpus tools
   (`upload_corpus.py`, `fetch_sessions.py`, `scrape_comps.py`,
   `refresh_trinkets.py`, `hearth_art_extract.py`) still ship to players.

## Where THIS session left off (2026-10-06, main ff84f05)

A large session. Everything below is on main and pushed; the suite was 1595
green at each commit and both publish gates passed at each release.

**Three releases went out, and players are on the third:**

| version | what |
| --- | --- |
| `94a07de` | the pivot: the live overlay stops advising (`LIVE_VERDICT_KEYS`) |
| `2ef006c` | Settle Up ships: the review, the turn-by-turn boards, session/history |
| `3233929` | the four stale `docs/` screenshots removed (the directory went with them; `docs/` came back with a current set on 10-07) |

**1. The pivot (`PIVOT.md`).** The live page shows state, not verdicts; the
model's plan is shown only after the game. One choke point
(`coach_ui.render_json` drops `LIVE_VERDICT_KEYS`) and one control
(`test_live_view.py` asserts all three halves). `test_readme_claims.py` is the
README-vs-code control that CLAUDE.md item 3 had been asking for since 10-05.

**2. The review (`app/settle_up.py`).** Reachable three ways: the end-of-game
card's link, the `/review` route, and the CLI (`--latest`, `--session`,
`--history N`, `--json`, `--html`). Built on `outcome_audit.audit_game`.
(The card's link became the **Save replay** button on 10-07 — see the night
session above; the CLI and `/review` are unchanged.)

**3. The turn timeline (`app/turn_review.py`).** The board at three points per
turn — buy end, combat start (BOTH sides), battle end — from the combat staging
burst the log already carried. Design, evidence and the trap list:
`analysis/SETTLE_UP_BOARDS.md`. Every trap there was measured, and two of them
would have produced a confident wrong answer: a feed-only replay leaves
`friendly` None so BOTH boards look like the opponent's, and combat snapshots
carry non-persistent buffs so board growth must be read at buy end.

**4. The cast-grading gap is closed at the source** — see the top of this file.

**5. `sync.py` was fixed**, because it failed twice in a row the way this repo
uses it: git calls ran from `<root>/app` (so `--new` could not add a root-level
file) and the merge did `git checkout main`, which git refuses from a linked
worktree. `worktree_for()` merges in whichever directory holds main. Covered by
`test_sync.py`; verified by using it.

OPEN, and each is recorded where the next session will trip over it:

1. **`player_actions` may double-count a single sell.** Measured: turn 7 of the
   10-06 game reports `['TB_BaconUps_159', 'Fire Baller', 'Fire Baller']` — three
   entries for two cards. Deduped only where the review asks its question; the
   underlying count feeds `fight_table` and the audits too, so it needs its own
   look rather than a fix in the consumer.
2. **A review costs TWO replays per game** (~10 s for 15 turns): the phase rows
   and the timeline run separate passes. `outcome_audit.audit_game` taking an
   injected coach would make it one.
3. **A swap-led plan is still ungraded** — grading one needs the sell AND the
   play that replaced it as a pair, which the row does not carry.
4. **~~`docs/` has no screenshots~~** — DONE 2026-10-07; `docs/` came back with a
   current set (see Layout).
5. **The replay-reviewer idea is captured in `ROADMAP.md`**, including the
   maintainer's decision that "save" writes the Power.log slice — with the three
   guards that folder will need, none of which exists yet.

## What the 2026-10-04 session left open (detail: `analysis/SESSION_2026_10_04.md`)

That session's narrative — the share-idempotency fixes, the consent-scope rule,
the tier refresh, the card-art URL, the read-only-install cache — is 20 KB and
now lives in `analysis/SESSION_2026_10_04.md`, because this file has to stay
inside the budget a session loads. What is still LIVE from it:

1. **The macOS launcher has never been parsed by any shell on this machine.**
   `Start Bob's Ledger.command`'s `--check` fix is reasoned, not run.
2. **9 tests are dead behind `HEARTH_REAL_SESSION_TESTS`** — nothing sets it.
3. **`upload_corpus.py` and `fetch_sessions.py` ship to players**, and the corpus
   path is the only one that carries a log (see the afternoon session's item 1).
4. **~~The README's `#is-this-allowed` anchor is an unverified assumption~~** —
   VERIFIED 2026-10-07 by fetching the RENDERED repo page and looking for the id
   GitHub emits: `user-content-is-this-allowed` is there, and so are the four
   other in-page anchors (`settle-up-the-review`, `the-one-question-it-asks-you`,
   `turn-on-hearthstones-logging`, `if-somethings-wrong`). The `?` IS stripped.
   The cheap version of this check is a `curl` of the repo page plus a grep for
   `user-content-<slug>`, which needs no browser and no checkout.
5. **Six guide files belong to pruned comps** (`demons-apm-shop-buff`,
   `elementals-stat-scaling`, `mechs-magnetics`, `murlocs-apm`,
   `nagas-groundbreaker`, `nagas-end-of-turn-spell-buff`) — kept on purpose.
6. **`requests>=2.28` is unpinned.**
7. **The `readme-rewrite` branch is still on origin**, identical to `main`, kept
   only so a non-technical tester's link keeps working.

Two rules from that session that STILL bind, and are worth not re-deriving: the
report whitelist `SPEC` has teeth in both directions (a new analysis field
REFUSES the send until it is named — `analysis/SESSION_2026_10_04.md` has the
560-of-641 incident that bought it), and `identity_findings()` is POSITIONAL
(a handle inside a name the GAME defines does not count; one real opponent is
literally called "Demon").

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
- **The live wall is KEY-level, so a verdict inside a STRING walks through it.**
  `LIVE_VERDICT_KEYS` drops verdict keys from the payload; `test_live_view`
  asserts those keys are absent. Neither can see wording. `choices._rank_discover`
  shipped a literal `"best available"` for a day after the pivot because of
  exactly that gap. The string-level control is
  `test_choices.TestTheFactsNameNoRank` — if you add a label, a tag or a note
  that reaches the live page, check it against that test, not against the key
  list.
- **`choice["ranked"][0]` IS the plan's pick.** `value._top_move_text` reads row
  0 (row 1 is the locked-hero fallback), so the rankers must keep returning
  score-ordered rows even though the overlay renders the options in the GAME's
  order — the page sorts by the row's 5th slot, the option's position in the
  offered list. "Tidying" the ranker to return game order would silently change
  which card the review says the model wanted, and every graded number after it.
