# The dev live-replay harness (2026-10-12)

Moved out of CLAUDE.md on 2026-10-23 by the budget rule (the file had
crossed the 65,536 bytes a session loads). Unchanged from the session
note; the commits it names are `d3473da`.

## Where THIS session left off (2026-10-12: the dev live-replay harness, `d3473da`)

**Another Round is now drivable from a finished game.** `app/live_replay.py`
(maintainer-only: in `publish_release.EXCLUDE_FILES` with its tests, and
deliberately absent from the README) serves the REAL overlay and replays a saved
game's log into it: `n`/`p` walk the buy phases, `k` reaches the hero pick and
the mid-game Choose-1 panels, `m` a rolled-into shop, `e` the end-of-game card
plus its review, `w`/`r` the welcome card and a re-push. Every frame is pushed by
`live._advise` / `live._advise_pick` / `coach_ui.show_game_over` with
`record=False`, so what a dev looks at IS a live payload — the wall holds by
construction, and `test_live_replay` asserts the equality against
`replay_review._advise_point` rather than trusting it.

**The measurement that shaped it, so nobody re-derives the wrong design.** The
first version kept ONE coach and resumed each phase where the last settled — the
obvious shape, and it is wrong: `analyze()` is not a pure read of the parse
state. Measured on the 16-phase 2026-10-12 game, incremental vs the review's
fresh-coach cadence: phase 1 identical but for `generated`, phase 8 **15 keys
differing with `board`/`gold`/`board_stats` among them**, phase 16 worse. Those
are the numbers on screen, so each step now re-feeds from line 0 through the
review's own cadence (~0.1s early, ~4.5s for the last phase of a 330k-line
game, printed per step).

**Three seams in shipped code, all additive:** `live._advise`/`_advise_pick`
gained `record=True` (default keeps every live call site byte-identical);
`replay_review.feed_to_settle(coach, lines, lo, hi, start=0)` was extracted from
`_advise_point` so the dev view and the review share ONE cadence (two copies
would drift, and the dev one puts frames on screen); `settle_up.log_path_for`
was extracted from `rebuild` so a stored pointer resolves in exactly one place.

**Found on the way, worth keeping:** `feed_to_settle` returns `len(chunk)` as its
"never settled" sentinel, so a cursor taken straight from it makes a shopless
phase look like the end of the game — measured, it made `n` report "phase 16 is
the last one" from phase 2 onward, on the real 2026-10-12 game. The phase number
is STORED and the lines fed are bounded by the phase's own end
(`test_a_phase_with_no_settled_shop_does_not_end_the_game`). `step()`'s out-of-
range phase used to report "needs a phase number" (it swallowed the SpecError);
it now says "phase 99 does not exist — this game has 16 buy phase(s)".

**Guards it does NOT get to skip:** no decision-log record, no share, no saved
replay written by the tool (the card's own Save button still does — that is the
feature under test), `replay_store.backfill()` never runs (it DELETES duplicates;
`live.py` runs it on purpose), no update check, and `e` refuses for a game the
log says has not ended — a review built for `--latest` against a live log would
serve a plan for a game still being played. All pinned with the collaborators
patched to raise.

Suite **2053 tests, OK, 109 skipped** (up 44; my module contributes 2 of the
skips because **Chromium cannot start in this sandbox** — `crashpad ...
Access is denied`, the documented SKIP-not-fail case, so the band's browser test
is UNVERIFIED here and ran nowhere else). Privacy scan clean on all seven
changed files. `publish_release --dry-run` from the main checkout: privacy PASS,
reproducibility PASS, signing FAIL (no offline key — nothing published). The zip
is **254 entries, byte-count identical to the last release's shape**, with
`live_replay.py` and `test_live_replay.py` confirmed ABSENT. Merged to main and
pushed (`d3473da`); worktree `.claude/worktrees/live-replay` is left in place and
merged — remove it when convenient. Nothing was released.

Open from this work: the in-page control bar was deliberately NOT built (the
console stepper was the v1 bet — reassess after using it); the freshness strip
says "it updates when your next shop opens" after 8s on a replayed frame, which
is untrue there and has an opt-in `--hide-freshness`.

