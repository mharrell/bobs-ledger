# Session 2026-10-07 afternoon: the pick panel, and what the corpus holds now

Moved from the working notes on 2026-10-09 by the budget rule (a session section
moves to `analysis/` when the next one lands) — that file had gone over the
65,536-byte cap a session loads, which truncates its TAIL silently. One
reference to the notes file reworded to the tracked-file standard; what is still
live from this session is digested in the working notes.

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

**7. The working notes were over the instruction budget, so the harness truncated it.**
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

**12. PUBLISHED AND VERIFIED FROM THE PLAYER'S SIDE (2026-10-07): release
`b547905`** — the opening board without the fight's summons, on top of the four
releases recorded above. It took two attempts, and the first one is the useful
part:

* **The privacy gate refused the release, and it was right.** Both new
  docstrings quoted the log directory the measurement came from
  (`app/turn_review.py`, `app/tests/test_turn_review.py`): `session_dir x1`. A
  session directory name belongs in the maintainer notes — it stays in
  `analysis/SETTLE_UP_BOARDS.md` and this file, neither of which ships — and
  never in `app/`. That is the SECOND time a docstring or fixture was the thing
  the gate caught, after the BattleTag of 2026-10-02. Nothing was uploaded: the
  gates run before the PUT and the channel kept serving `745dcd5`.
* Verified, from the manifest an install actually fetches rather than from the
  publish log: the signature verifies against the pinned key
  (`4d8fc45534ba558d`), `zip_bytes`/`zip_sha256` match the download exactly
  (1,445,528 bytes, `e70a2dda1d26…`) through the SHIPPED bounded-download path,
  the pin inside the zip matches this checkout, the root holds exactly the two
  launchers, the README, the licence, `docs/`, `app/` and the two stamps (246
  entries), and a grep of every shipped text file finds no session name — the
  gate's catch is gone from the artifact, not just from the gate's report.
* The SHIPPED updater, from an install reading `745dcd5`, offers the update and
  exits 1; the same shipped code refuses a manifest whose `note` was rewritten,
  naming the pinned fingerprint. **One thing worth knowing about that first
  check**: a state file holding only `{"version": …}` reads as UNORDERABLE
  (`decide` needs the `created` stamp a real `save_state` writes), so the probe
  printed "unknown … use --force" and exited 0 at first, which looks like "no
  update available" and is not. Simulating an install means simulating its state.
* Neither documented gotcha appeared: no `Authentication error [code: 10000]`,
  and `latest.json` served the new manifest on the first read.
