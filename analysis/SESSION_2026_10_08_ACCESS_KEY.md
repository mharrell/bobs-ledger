# The overlay's access key, and the Tavern viewer's first two rounds
(2026-10-08 session)

Moved out of the working notes on 2026-10-09 by the budget rule. What is
still live from it is summarised in the working notes; this is the full
record of the session that closed the loopback-auth audit item, shipped
release `dab2161`, and ran the first two rounds of the Tavern viewer's fix
lists.

## The session — main dab2161, RELEASED)

**The overlay's loopback server answers NOTHING without a per-run key now**, which
closes item 1 of the 2026-10-07 audit below. `start_server` mints
`secrets.token_urlsafe(16)`; `_Handler._authorized` refuses every request that does
not carry it (`?token=` on the URL, or an `X-BL-Token` header), and an EMPTY key
authorizes nothing, so a hand-built handler fails closed. `coach_ui.overlay_url(server)`
is the ONE place the address is built — live.py prints AND opens it, and the bare
`http://127.0.0.1:8747/` is now refused. The served page carries the real key
(`_HTML` keeps a single `__BL_TOKEN__` placeholder so the substitution stays
checkable), and card art (`/img/`, `/card/`) stays open: it is not data, and an
`<img src>` cannot carry a header. `_authorized` also SPLITS the request —
`self.path` is the path alone, everything else goes to `self.query_params` —
because ROUTING IS THE PATH: a `?token=` on the URL otherwise misses every
`self.path == "/x"` below `do_GET` and answers the overlay PAGE (a 200 of HTML
where the page's own poll wants JSON), and `/review/game` now reads its id from
the query instead of the old `^/review/game\?id=…$`.

**This was taken over mid-flight from a session that ran out of tokens, and the
in-flight version was broken in four ways no naive test can see.** All four are
pinned now, and each is a shape to check for in the next one:

1. Ten `fetch(` call sites had the closing paren INSIDE `auth()`:
   `fetch(auth('/analysis', {…})` for `fetch(auth('/analysis'), {…})`, plus
   `fetch(auth('/artmiss').then(…)` calling `.then` on a string. One of those is a
   SyntaxError, and a SyntaxError takes the ENTIRE page script with it — the
   overlay then draws nothing while every static assertion still passes.
   `test_overlay_auth.TestThePageScriptParses` runs the page's whole `<script>`
   through `node --check`, with a rehearsal that a broken fetch MUST fail it (the
   lesson `test_overlay_layout` already paid for).
2. `_authorized` was defined and never CALLED; `_TOKEN` was never defined; the
   placeholder was never substituted; live.py still built its own URL. The
   wired-check is `source.count("if not self._authorized():") == 2`.
3. A 403 is not an age. `freshnessLine` gained a third signal, so a tab left open
   across a restart says "This overlay is from an earlier run — open it again from
   the launcher" instead of reporting a refused tab as old advice ("wait for your
   next shop" being the one action that cannot fix it).
4. `test_settle_viewer` pinned `fetch('/review/rebuild'` — the suite's own pin is
   what caught the change, and it expects the `auth()` form now.

New control: `app/tests/test_overlay_auth.py`, 27 tests (no key, no data on
`/analysis`, `/review/list`, `/` and the consent flip; wrong, empty and non-ASCII
keys refused; the key in query or header; the query does not change the route; a
route that reads a parameter still gets it; art exempt; the page's real key; the
script parses; one address builder).

Suite: **1826 tests, 2 failures, 11 skipped** — both failures are
`test_overlay_layout` (headless Chrome cannot start under the sandbox:
`crashpad … OpenProcess: Access is denied`) and they fail IDENTICALLY on an
unmodified main checkout, measured by running that module alone against main.

OPEN: released as `dab2161` (below), so the access key, the Rebuild button and the
two viewer fixes are in players' hands. Audit item 2 below (`analysis/` is
public) is untouched and is a business call. And
`python -m unittest discover -s app/tests -p <one file>` CANNOT run a single
module: importing `coach_ui` first is a circular import (coach_ui → settle_up →
outcome_audit → live_coach → `from coach_ui import latest_manual_bans`), so
something that imports `live_coach` has to be primed first — pre-existing on main,
and it costs an hour if you meet it while debugging one file.

**Follow-up (same session): the Tavern viewer now RUNS in a browser, and running
it found two real bugs.** `app/tests/browser.py` is the shared headless-Chromium
harness (the layout suite's launch, extracted, plus the skip-vs-fail rule);
`app/tests/test_settle_browser.py` serves the REAL page, runs a fixture through
the REAL `_name_timeline_boards` join and the real `renderSettleGame`, and reads
the DOM back — strip, rail groups/caps, tray, NEW/delta tags, face-off, step
track and sizes. 20 tests. The two bugs no source assertion could see, both
fixed in `138fb26`:

1. **The sold ghost in Step-through drew at a full 130x172.**
   `.tavern .stepboard .tile` and `.tavern .tile.ghost` are equally specific
   (three classes) and the BOARD rule sits later in the sheet, so it won — a
   sold card sized like the minions around it reads as still being on the board.
   Fixed with a scoped `.tavern .stepboard .tile.ghost`. Both rules are correct
   in isolation; only a browser can see the collision.
2. **"1 casts" / "1 rolls" reached the player.** The rail's chips are the
   design's §4.3 summary, so they pluralize now.

Two things the harness itself got wrong first, worth not repeating: a page that
never calls `showTab('settle')` measures **0x0 for every card** (the viewer lives
in a hidden section), and counts need the `#` marker `browser.fields()` casts or
every `assertEqual(n, 2)` fails on `'2'` — the first run reported eleven
"failures" that were all correct values. `subprocess` also has to decode the DOM
as UTF-8 explicitly: `text=True` alone is cp1252 and dies on the page's own em
dashes, which surfaced as "no output and no error" from a browser that had run
fine.

**A browser that cannot START is now a SKIP, not a failure** (measured: this
sandbox refuses Chromium its process and pipe access on all six launch variants
tried, `--single-process` included). That flipped the two `test_overlay_layout`
failures into honest skips, and with a browser available the suite is
**1846 tests, OK, 11 skipped** — layout tests included. Do not read a green suite
in a sandboxed session as evidence about layout: check the skip count.

**`REPLAY_VIEWER_DESIGN.md` §9, measured against the code:** steps 1-5 are DONE
(tokens, single-turn layout, Summary rail, Battle face-off, Step-through). Step 6
is PART: keyboard is in; **tribe/tier pips, the board-strength sparkline,
hero-tinted accents and deep links are unwritten**. Three gaps against the
design's own text: **Summary-mode cards are still the 104px tile with its 56px
thumb — the specified 88x120 exists nowhere** (only Step-through's 130x172 is
implemented), §5's narrow-width rule (rail above the boards under ~900px) is not
implemented, and §7's visible focus ring is absent while the `--hp` contrast
check is deferred in a code comment.

**The viewer SHIPPED in `6432967`** (published 2026-10-08 17:57 — its note
announces it). This session first said the opposite ("players have no toggle at
all"), reasoning from a stale line in this file that called `32aeecb` the last
release, plus a `git merge-base` check against it. Both were true and both were
irrelevant: the channel said `6432967`. **The release state is a fact about the
CHANNEL — one `latest.json` fetch — not about git history or these notes.**

**RELEASED AND VERIFIED FROM THE PLAYER'S SIDE (2026-10-08): release `dab2161`** —
the two viewer fixes, the Rebuild button, the access key, and the README section
the viewer shipped without. All three gates passed on the FIRST attempt (no
`Authentication error [code: 10000]`), `latest.json` served the new manifest on
read 1, its signature verifies against the pinned `4d8fc45534ba558d`,
`zip_bytes`/`zip_sha256` match the download (1,505,480 bytes) through the SHIPPED
bounded-download path, the zip holds 252 entries with a root of exactly the two
launchers, README, licence and the two stamps and no maintainer-only part, the
pin inside matches this checkout, and GitHub's `releases/latest` carries the same
zip. The SHIPPED updater from a simulated `6432967` install offers
`6432967 -> dab2161` and exits 1 ("up to date" at dab2161), and the shipped
verifier refuses a manifest with a rewritten `note` or `zip_sha256`, naming the
fingerprint both times.

**The privacy gate caught a leak sitting in main since `d1f17f7`** — the THIRD
time a real Hearthstone session directory name was committed in a shipped fixture
(`app/tests/test_settle_up.py`, three places, reported as `session_dir x1`). No
release had been cut since, so none shipped. Two things to keep: the fixture now
uses the registered placeholder (`privacy_scan.SYNTHETIC_SESSIONS`), and **one of
the three was written as two adjacent string literals to fit the line, so the
concatenated value never appears contiguously and the TEXT scanner cannot see it
— the gate's count said one and there were three.** Keep a fixture name on one
line.

**Follow-up 2 (same session, later): eight Settle Up viewer fixes, from the
maintainer's list.** Six are the player's calls on how the Tavern view should
read; two are bugs the model had called correct. All eight are pinned in the
browser harness (31 tests there now):

1. **The rail sits LEFT, boards fill the rest.** `flex-wrap:wrap` on `.twrap`
   gave up rather than shrinking either side, so a 330px rail wrapped ABOVE the
   boards. `nowrap` + `flex:1 1 auto; min-width:0` on the card, and the design's
   §5 rule (rail back on top under 900px) is implemented for real.
2. **The art fills the card and the width tracks the window.** A Tavern tile was
   the live overlay's fixed 104px box with a 56px thumbnail inside, so a
   step-through card drew a 130x172 outline around a small picture — the
   "oversized empty frame". One `--tcardw` (`clamp(88px, 6.6vw, 124px)`; the
   step board swaps in `--tstepw`, `clamp(130px, 9.6vw, 190px)`), `aspect-ratio`
   for the height, absolute art, and the name/stats on a dark strip over it.
3. **A step highlights a card only when the action targets one.** The old rule
   was "the first eid not on the previous board", and step 1 has no previous
   board — so "Leveled up" outlined card 1. `stepDiff(cur, kind, card)`: buy and
   play only, matched by card id.
4. **Removed duplicates.** The "rebuilt the board" note was rendered twice (rail
   AND card) — the rail keeps it. The card's "THE TURN" line is classic-only;
   its numbers are rail chips now (played / spent / value / hero power /
   trinket), so nothing is lost and nothing is said twice.
5. **Deltas are attack/health** (`+0/+3`, attack gold, health red), not one green
   concatenated number.
6. **The strip marker reports the COST, not the winner**: HP dropped is the loss
   marker, no drop is a win marker, and no reading is a dash. Nothing renders a
   "?" — it was drawn inside the turn number ("1? −5"). `stripMark`'s contract
   changed, so `TestTheStripMarker` was rewritten to pin the new one.
7. **Step-through: a large action caption** (16px, above the board it labels,
   out of the control row), each tick's action as a hover tooltip, and the legend
   directly under the track.
8. **Board labels above their rows** (`.brow.stacked`), and the Summary | Step
   through toggle moved into the SETTLE HEADER beside the game dropdown. That
   turned up a shipped UI bug: **`.vseg` was never applied to `#settle-viewer`**,
   and `.vseg button.on` is the only rule that styles the active segment — so the
   Classic | Tavern toggle had NO visible active state at all. Both spans carry
   the class now.

**The harness lesson worth keeping: headless Chromium defaults to 800x600.** The
new 900px breakpoint meant the "is the rail beside the boards?" assertion was
really asking "is 800px narrow?" — and it is, so the fix looked broken. `browser.py`
now takes an explicit `size` (`WIDE = 1400x900`, `NARROW = 800x600`) and both ends
are asserted: side-by-side when wide, stacked when narrow, and the card at its
88px floor narrow against >88 wide. A layout claim has to say which width it means.

**Follow-up 3 (same session, later): `LIVE_VIEW_DESIGN.md` is implemented behind
a `Classic | Tavern` flag on the Live tab (main `bd6cd86`, NOT released).** The
flag lives in the top nav (`#live-viewer`, persisted `bl-live-viewer`, Classic the
default and untouched), mirroring the Settle Up flag. `renderLiveTavern()` draws
the reference layout into its own `#live-tavern` container:

* **§4.2 shop screen** — status bar (hero + Gold/Tier/HP/Turn/Place, gold in
  `--atk`), ONE tribe row (active chips tap-to-correct via `POST /bans`;
  out-of-play tribes appended struck-through and NOT clickable), then the tavern /
  board / hand rows with a one-line caption under each card, and a 340px rail with
  Facts | Comps | Lobby.
* **§1's language pass, which is the point of the redesign** — `lvFacts` renders
  the numbers the classic strip renders as verdicts: Effective HP, Took last
  fight, Last 3 fights, Lethal at, Damage cap, Board stats you vs last seen, Level
  up, and "Reference only. Numbers are observational, not causal." "FRAGILE — a
  14-hit ends it" and "favored/behind/strong" are gone from this view. **The
  payload gained `board_stats`/`opp_stats`/`opp_lobby`/`opp_age` for it** — the
  numbers, not a parse of `scout`/`forecast`, because deriving facts back out of a
  rendered string is the mistake `_top_move_text` had to undo.
* **§4.3's canonical pick screen** — options in the order the GAME offered them
  (`row[4]`) unless the player picks another order; each with the card and name,
  a headline figure (`60% picked in`) with `[±x vs offered avg]`, §5's eight-bar
  placement distribution, and its stat rows (capped at five, then `+ N more`).
  Controls: the type tabs (auto-selected; the others are inert and say why), the
  **Stats shown** toggles, and **Order: As offered | By picked % | By avg place**.
  A value nobody has is dropped, and an option the DBs know nothing about says
  `No data for this card on this patch yet.` rather than showing a zero.
* **§4.4 Browse, compact** (name + source tier + "N of M core owned") and **§4.2's
  Lobby tab** (sightings per seen seat, their last-staged board, their trinkets).
* **§5/§6 states** — `lv-kv` label/value rows, label-over-number stats, chips, the
  dashed card skeleton with "Reading the shop…", and a dash for a value nobody read
  (§6.4) where the classic strip prints `?`.

**A real bug the new harness caught**: the first version cleared `#app` to draw
itself, which DESTROYED `#col-decide`/`#col-ref` — so the toggle to Tavern worked
and the toggle BACK threw ("Cannot read properties of null"). The tavern view has
its own container now and the classic panes are only hidden; the shot order in
`test_live_browser` renders Classic AFTER Tavern, so the way back is pinned.

**The §1 control is a scan of the RENDERED TEXT** (`TestTheViewCarriesNoVerdict`),
not of the source: a verdict is about words on the screen, which is exactly what
the key-level wall cannot see. It scans the tavern root's `textContent` for
best/favored/behind/strong/fragile/dying/should/recommend/rank/… The source-level
half scans STRING LITERALS only (comments stripped) — a check that fails on its own
documentation ("never 'favored'") is a check nobody keeps.

**The pick screen's numbers needed a producer** (main `3b88d6e`):
`choices.option_stats(kind, options)` returns the pick rate, average placement,
the 1-to-8 distribution and the top-4 share per option, keyed by card id, emitted
only where the DB has them (a top-4 share needs all four of 1..4, or it would
under-report and read as a real number). `render_json` attaches it to
`a["choice"]`, and `lvPick` renders those numbers ONLY — **the rehearsal
is a test**: the fixture's classic fact strings say "fits your board", and the
browser test asserts that text cannot reach the Tavern screen. That is §1 enforced
at the source rather than by scanning for phrases the data already forbids.

**Follow-up 4 (same session, later): §4.4 and §6.5 — the design's build order is
DONE (main `d524322`, NOT released).** Every numbered item in §10 is now
implemented; what is left is §6.3, §3 and §9, all of them for reasons rather than
for want of time (below).

* **§4.4 Browse** is the real layout now, in the MAIN column — a 340px rail cannot
  hold two tier columns, and the design's own §4.2 keeps the Facts table for that
  width. Each source tier is one column (`S tier · 2|A tier · 7`), capped at
  `LIVE_COMP_ROWS = 5` with a `+ N more`; each row is `[name + tier/tribe chips]
  [34x46 core slots] [N of M owned] [avg placement] [compare]`. Owned means board
  OR HAND (§4.4's own words) — the payload's classic `owned` flag is board-only
  ("the board is what fights"), so a second `in_hand` flag rides each core row and
  the tavern count reads both. Out-of-play comps are HIDDEN and the count of them
  is stated; `menagerie` (tribe None) renders as `Mixed`; the filter chips are the
  tribes actually in play. The `Sort` control (Source tier default | Overlap |
  Avg placement) is opt-in and sorts INSIDE a tier group, never the columns.
* **The comps numbers are OUR OWN corpus** — `meta.corpus_stats.json`, written by
  `replay_stats.py --save`, read through the new `meta.corpus_stats()`. It is the
  one stats table with a GAMES COUNT, which is what §5's low-sample rule needs
  ("by games count, not a fixed percent"): `COMP_LOW_SAMPLE_GAMES = 10` and
  `_comp_stats()` turn a record into avg place / distribution / top-4 / 1st, and a
  comp the corpus has never seen gets a dash and "No corpus record" rather than a
  zero. It is also the only stats table §9's licensing question does not touch.
* **Detail and Compare** (§4.4): header chips (tier, tribe, difficulty), the Core
  row at 88x120 and the Flex row at 76x100 (a `aspect-ratio:76/100` rule — the
  design gives them different ratios), a per-card caption (`on board` / `in hand` /
  `not owned`), the statistics beside them, and `Guide text ▸` collapsed by default
  fetching `/guide/<slug>` on first expand into its OWN cache (`_lvGuideCache`, not
  the classic `loadGuide` node — a cached node carries one palette). Compare holds
  up to three (`LIVE_COMPARE_MAX`), in the pick screen's column layout with 52x70
  slots, the same rows in the same order, and the order the player picked in.
* **The tab row is `Shop | Comps | Lobby` (§4.1) and the Facts table is the rail.**
  They were all rail tabs before, which is why §4.4 had nowhere to live. The facts
  panel is now beside every screen instead of one of them; §4.2 lists it as the
  rail's first tab and this keeps it visible rather than hidden.
* **§6.5's game-over card — and the bug that hid it.** The end-of-game payload is
  `welcome: true` with NO board, and `render` returned at the welcome branch BEFORE
  consulting the viewer, so the Tavern game-over card was **unreachable in a real
  session** while a direct `renderLiveTavern` call in a test made it look alive.
  `renderTavernGameOver` is now its own entry point (page chrome included: the early
  return skips `renderShareToggle`/`renderRelease`), the placement+round are the
  large text, the auto-save checkbox and "Saved to the Settle Up tab automatically
  ✓" share ONE row (§6.5's merge), and the coach line and the sharing summary ride
  below as small text. The two end-of-game POSTs moved into shared helpers
  (`postAutoSave`/`postSaveReplay`) so the classic card and this one cannot drift —
  the 409 "still building" retry is the part that must not be lost. `lvClearTavern`
  is the one reset, and it fixed a second bug: a first-run welcome card (classic in
  either viewer) used to draw BEHIND a stale Tavern screen.
* **§8's accessibility pass** (Tavern scope): `.tavern :focus-visible` is the
  design's 2px `--sel` ring with an offset, and the tabs, `+ N more`, `‹ Comps` and
  the card buttons carry `min-height:44px`.

**What the harness found this time, all three in fixes no source assertion sees**: a
slot's missing state was emitted as `.missing` while the CSS styled `.miss`, so every
unowned core card drew as a SOLID (owned) box; the driver's `.lv-opts` read threw on
Compare (which reuses that class) because it assumed a `.lv-pickctl` parent, taking
the whole shot with it; and **the page keeps its view state between renders**, so a
shot that filtered or opened a Detail handed that state to the next shot — the
"more" shot inherited the tribe filter and had nothing to expand. The driver now
resets that state per shot (and `pre`/`preclicks` render a preceding screen, which is
how "the game-over card replaces what you were looking at" is testable at all). The
source-side scan also needed an escape-aware string regex: `'this project\'s corpus'`
closed the literal early, shifted the pairing by one, and pulled live code into what
the §1 check thought was a string — it reported a `?` from a ternary.

**Follow-up 5 (same session): RELEASED as `504047e` (2026-10-09), verified from the
player's side.** Three commits went out — `d524322` (§4.4 + §6.5), `f38c1a0` (§8)
and `504047e` (the bookmark + the README the Tavern viewer shipped without). All
three gates passed on the FIRST attempt (no `Authentication error [code: 10000]`),
`latest.json` served the new manifest on read 1, the signature verifies against the
pinned `4d8fc45534ba558d`, `zip_bytes`/`zip_sha256` match the download (1,556,505
bytes) through the SHIPPED bounded-download path, the zip holds 254 entries whose
root is exactly the two launchers, README, licence, `docs/` and the two stamps with
no maintainer-only part, and the GitHub asset is byte-identical to the manifest's.
A simulated `27a7b4a` install — extracted from the published zip, with that
release's REAL `created` stamp — is offered `27a7b4a -> 504047e` by the shipped
updater (exit 1 answering no), APPLIES it with `--yes` (254 files, VERSION and
`.update_state.json` re-stamped), and then reports "up to date" (exit 0). The
shipped verifier refuses a manifest with a rewritten `note` or `zip_sha256` through
the full `run()` flow, naming the fingerprint, and changes nothing.

**A verification trap worth keeping: `update.verified_manifest(manifest, action)`
verifies only when `action == "update"` (or `force`).** Any other action string
returns the manifest UNVERIFIED by design — that is the "don't nag an up-to-date
install" rule — so a hand-driven check that passes `"install"` reports ACCEPTED for a
tampered manifest and looks exactly like a broken signing gate. It is not: run one
through `run()`, or pass `"update"`.

**The bookmark (2026-10-09, the maintainer's complaint about `?token=` in the URL).**
`_authorized` now also accepts the key from a cookie, and a request that PROVED the
key by carrying it in the address leaves `bl_token` behind: `Path=/`, `HttpOnly`,
`SameSite=Strict`, `Max-Age=7d` (no `Secure` — the overlay is plain http on
loopback, so a Secure cookie would never be stored). **Nothing was weakened**: a
bare address with no cookie is still a 403, a stale cookie from an earlier run is
refused exactly like a stale URL, a refusal never hands out a key, and what turns
away another origin is the rest of the guard — `SameSite=Strict` means a foreign
page cannot make the browser send it at all, and `_foreign_caller` refuses the
request even when one rides along. The cookie is announced only when the browser
does not already have this run's key (the page's own polls all carry `?token=`, and
re-announcing it three times a second would be pure noise). 7 new tests in
`test_overlay_auth` (34 there now); the README documents the behaviour under "If
something's wrong". Verified against the SHIPPED zip, not the checkout: the
launcher's address serves the page and sets the cookie, the bare address then serves
it with the cookie, and `/analysis` without one is still 403.

**§9's attribution half is now implemented** (the licensing half is still the
maintainer's): the Tavern pick panel's source line names where the population
statistics come from ("scraped from hsreplay.net, read from the shipped meta DB"),
and the README's one sentence about the meta DB names it too. The comps statistics
are unaffected — they come from this project's own corpus, and say so. If naming the
site in the UI is the wrong call, that is a string in `lvPick` and half a sentence
in the README; the decision it belongs to (keep the DB local / rebuild from our own
corpus / seek permission) is untouched.

Suite at the release: **1936 tests, OK, 11 skipped** (browser tests RAN — this
session had full access), privacy scan clean on every changed file.

**Still open from the design, each for a reason:**
1. **§6.3's older-patch marker** needs a per-record patch and NOTHING carries one:
   the scraped tables (heroes, trinkets) and `corpus_stats.json` record no patch,
   and the live path never reads the client build. Only `out_of_play.json`,
   `patch_gaps.json` and `pool_roster.json` name a patch (36.6.1), and that is the
   patch THEY were written for. The comp stat block says so out loud ("no per-game
   patch recorded, so none is claimed") rather than printing the current patch over
   old numbers.
2. **§3's "amber for selection only"** is a change to the CLASSIC page (its gold is
   used for values as well as selection). Deliberately not made — the classic page
   is the shipped renderer and this session's mandate was the Tavern one.
3. **§9's data-licensing gate is the maintainer's to decide** (below). The README
   half is DONE as of `504047e`: it now documents the Live `Classic | Tavern`
   toggle, the three screens, and what the access key means for a bookmark. What
   is still owed there is a PICTURE of the live page — `docs/` shows the review
   only, and the README says so in both the Another Round section and Upcoming.

**§9's data-licensing gate is the maintainer's to decide, and it matters more
now**: the design says the aggregated stats come from a scraped third-party source
and that "before the next public release, decide among: keep the DB local and out
of releases; rebuild from our own corpus; seek permission; and always show source
attribution". The stats ride `app/meta/*.json`, which SHIPS in every release today,
and the Tavern pick screen renders them prominently. Nothing in this session
changed what ships — it made the question visible. **The comps numbers are the one
place it is already answered the other way**: they come from this project's own
games (`meta/corpus_stats.json`), which is why the comp stat block names that
source rather than a scraped one.

## From the 2026-10-08 morning session (detail: `analysis/SESSION_2026_10_08.md`)

Moved to `analysis/` on 2026-10-08 by the budget rule. Still live from it: the
phantom-turn fix (a fight's own `MAIN_ACTION..MAIN_END` pair is not a shop opening
— `32aeecb`) and the played-card snapshot fix (`ac0dd28`), both verified on real
games; the Classic | Tavern viewer flag (`dab8d4a`, `31bc645`, `619fd32`,
`2244b66` — the design's steps 1-5 DONE, only its optional-polish items left,
Classic still the default and byte-for-byte the shipped renderer); and release
`32aeecb` verified from the player's side (its first zip PUT died on the
documented `Authentication error [code: 10000]`). **Two of its open items are
CLOSED**: "old saved replays keep their old shape" by `d1f17f7` (the Settle Up
header's Rebuild button + `/review/rebuild`, which re-derives a rep from its own
source log) and `requests>=2.28` unpinned by `1ef24be`. What stays open from it:
the 20:53 game's LAST turn reads "no combat staged" (the log may end before the
final fight stages — the night session's item 1 family), and `ac0dd28` is still
not in a release, so the 08:14 replay keeps its old shape until one is cut and
re-saved.

## From the 2026-10-07 evening session (detail: `analysis/SESSION_2026_10_07_EVENING.md`)

1. **The working notes and `.claude/` are UNTRACKED local state**, kept out
   by `.git/info/exclude`; tracked files say "the working notes" instead of
   naming this file, and four FUNCTIONAL strings keep their names
   (`publish_release.EXCLUDE_DIRS/.EXCLUDE_FILES`, `update.PROTECTED` ×2) —
   `git grep -inE "claude|anthropic"` must show exactly those four.
2. **The trinket drift is CLOSED** (112/112 recorded). 11 entries still
   carry the `review` key — **the maintainer still owes them a read**
   (delete the key once agreed). Re-run `refresh_trinkets.py` after play
   sessions; the newest-6-log window moves.
3. The auto-save checkbox shipped in `33456e1` (verified from the player's
   side; first attempt died on the documented `10000`).
   `docs/save-replay.png` predates the checkbox; re-shoot whenever the
   end-of-game card is re-shot.
4. The corner release stamp (`dd11c3f`) SHIPS as of `32aeecb`.
5. NOT done, flagged: the env script still names itself in EXCLUDE_FILES
   (the maintainer's call — it may be sourced by name somewhere).
   `requests>=2.28` was left unpinned here and is FIXED now (`1ef24be`).

## From the 2026-10-07 night session (detail: `analysis/SESSION_2026_10_07_NIGHT.md`)

Settle Up became a TAB and saved games became files; released twice
(`c885b2e`, then `409a47e` with the turn cards defaulting to Shop). What is
still live from it:

1. **A fight straddling the turn boundary could leave the Result unreadable**
   (`winner` None on real fights) — REDUCED, not closed, by the 2026-10-08
   phantom-turn fix (the drain now lands in the fight's own bucket); the
   remaining Nones are the open item.
2. **A review costs TWO replays per game** (`outcome_audit` for the phase
   rows, `turn_review` for the boards); an injected coach would make it one.
3. **The sell "double-count" is DISPROVEN (2026-10-08, entity evidence)**:
   the recorded two `BG31_816` entries in that turn are two REAL sells —
   entities 3158 and 3868, each with its own Drag-To-Sell block 21 s apart.
   Repeats in the sells list are real copies, so the rail's run-length ×N is
   the honest display; `_sell_questions`' by-id dedupe stays right (one
   question per card, not per copy).
4. **A swap-led plan is still ungraded** (grading needs the sell AND its
   replacement as a pair).
5. The turn cards hold their size (one grid cell, `visibility` not
   `display` — pinned by `test_overlay_layout`), and the lesson that a green
   suite is evidence only about the tests that exist (a lost class statement
   ran 1691 green while its control was dead) stays worth not re-deriving.

## From the 2026-10-07 afternoon session (detail: `analysis/SESSION_2026_10_07_AFTERNOON.md`)

Moved to `analysis/` on 2026-10-09 by the budget rule: this file had gone over the
65,536 bytes a session loads, which truncates its TAIL — the Hazards list and the
oldest record — silently. Still live from it: the live pick panel carries
STATISTICS, never a rank, and `choice["ranked"][0]` is STILL the plan's pick (the
rankers must keep returning score-ordered rows while the page renders game
order); `share_state()` is one builder feeding every payload, with a test
asserting the analysis stays clean; the end-of-game card's placement comes from
`LiveCoach.final_placement()` (the LOWEST entity id), NOT `current_place`; and the
README's consent paragraph and its five in-page anchors were both corrected. Its
two OPEN items stand: **nothing offers a player the path that carries a LOG** (the
gap behind "we need more replays" — a consent-and-whitelist change, not a button),
and **the player's own record in the pick panel** (deferred by the maintainer, now
the first item of the README's "Upcoming features").

## From the 2026-10-07 hardening session (detail: `analysis/SESSION_2026_10_07_HARDENING.md`)

Moved to `analysis/` on 2026-10-09 by the budget rule. The full record — the
signing build, the pin/cutover verification, the history scan and its
numbers, and the two scanner bugs — lives there. Still live from it, beyond
what "Never break these" already carries: **the private key is backed up
off this machine** (verify a copy with `python app\release_sig.py --pubkey
<copy>` → `4d8fc45534ba558d`); the two publish gotchas (intermittent
`Authentication error [code: 10000]` — re-run; KV eventual consistency —
retry the read, do not re-publish); the history-scan tools (`gitleaks` +
`python app/history_scan.py`) and the **NO history rewrite** decision (the
one BattleTag is the maintainer's own self-disclosure; commit shas are the
release version strings); and audit item 2 — **`analysis/` is in a PUBLIC
repository and that is a business call, not a privacy one** (measured: no
opponent identity anywhere in it).
