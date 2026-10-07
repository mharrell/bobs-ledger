# Settle Up: the board timeline (design, measured 2026-10-06)

**The ask** (maintainer, 2026-10-06): *"There's no in-game method to review your
game at all. The player should have some idea what the board looked like at the
end of the buy phase, what it looked like as combat began (after the 'when combat
begins' part), and what it looked like at the end of the battle for each turn.
Also: how much gold did they have/spend, how much did the value of their board
increase, did they commit more to a comp, did they commit any major blunders
(selling a key minion instead of the throwaway)."*

**Verdict: all three board states are already recoverable, and the machinery is
half-built.** `board_state.snapshots` records a full board (with stats frozen at
snapshot time) on every entry to and exit from PLAY; `live_coach` projects those
into `_snap_by_turn[turn]` as `{phase: "buy"|"combat", minions: [(player, card,
atk, health, golden, keywords), ...]}`; and `fight_table._their_board` already
picks the opponent's staged board out of it for the maintainer's fight table.
Nothing below needs a new log parser. What it needs is a player-facing
reconstruction, which does not exist.

Everything here was measured on `Hearthstone_2026_10_06_10_52_24`, game 1
(Chenvaala, 2nd, 16 advised phases), by driving `LiveCoach` the way
`outcome_audit.audit_game` does.

---

## 1. The three states, and exactly where each comes from

| State | Source | Fidelity |
| --- | --- | --- |
| **End of buy phase** | our side of the LAST `phase == "buy"` snapshot of the turn | **LAGS** — see the correction below |
| **As combat began** | our + their side of the FIRST `phase == "combat"` snapshot of that turn's fight | exact, and the authoritative pre-fight board for BOTH sides |
| **End of battle** | the NEXT turn's first `buy` snapshot — i.e. `_snap_by_turn[turn+1][0]` | exact for what PERSISTED; not a literal end-of-combat frame (§3.4) |

### Correction, measured after the first build: the buy-end snapshot lags

The first version of this doc claimed the last buy snapshot IS the end of the
buy phase. It is not, and `turn_review.py` now says so per turn. Buy-phase
snapshots fire on each minion entering PLAY and each leaving it, and **the
player keeps playing after the coach's last look**:

```
turn 4  LAST BUY   : our side = 1 minion  (Crackling Cyclone 2/1)
        FIRST COMBAT: our side = 3 minions (Crackling Cyclone 2/1,
                      Locked-up Mutineer 6/3, Crackling Cyclone 2/1)
turn 5  LAST BUY   : our side = 3 minions
        FIRST COMBAT: our side = 5 minions (adds Wolf Pup 3/6, Fire Baller 4/3)
```

So **the combat staging burst is the authoritative "what you went in with"**,
for both sides — which is exactly the state the maintainer asked for ("what it
looked like as combat began"). The buy-phase board stays useful for one thing
the combat board cannot do: it carries PERSISTENT stats only, so it is the right
series for board growth (§3.2). Every turn therefore reports both, plus the
count of minions played after the last buy snapshot.

**One good thing this also settled:** side attribution during a staging burst is
CORRECT. The snapshots carry both ids (`player=5` ours, `player=13` theirs) in
the same burst, so the naive "not us" split is right, and
`fight_table._their_board`'s split is right with it. The blind spot
`pool_availability.md` warns about — "controller==9 minions is NOT the
opponent's board" — does not bite here, because `board_state` resolves ownership
from the CONTROLLER tag per entity rather than from the combat-slot controller.

The turn-6 opening is the clearest demonstration of the third row: it reads
`ours=5, stats 31` — turn 5's fight survivors, at their pre-combat stat values —
where the tail of turn 5's own combat snapshots drained `5 → 4 → 3 → 2 → 1 → 0`
as deaths emptied the board.

### The fight, in one turn (turn 5, abridged)

```
[15] phase=combat ours=5 (stats 31) theirs=2   <- combat began: both boards staged
        us   Locked-up Mutineer 6/3, Crackling Cyclone 2/1 ×2, Wolf Pup 3/6, Fire Baller 4/3
        them Dune Dweller 3/3, Fetid Corroder 3/3
[21] phase=combat ours=4 (stats 37) theirs=4   <- deaths inside the fight
[29] phase=combat ours=0 (stats  0) theirs=0   <- teardown: snapshots drain to nothing
[30] phase=combat ours=5 (stats 31) theirs=9   <- a LATER burst, pre-buff stats again
```

---

## 2. What this unlocks for the four metrics

- **Gold held / spent.** Held: the coach's `gold` per turn (already in every
  advisory). Spent: reconstructable per turn from the player's own actions —
  `3 × buys` (minions are a FLAT 3, all tiers), `1 × refreshes`, the level
  button cost, plus tavern-spell prices from `shop_costs`. `player_actions`
  already returns buys/refreshes/upgrades/sells/freezes per turn.
- **Board value increase.** Sum of `atk + health` over OUR side of the buy-end
  snapshot, differenced turn over turn. **Must be read at buy-phase end, never
  at combat** — see trap 2. A comp-aware price is also available
  (`value.shop_ranking` scores cards, `comp_progress` prices comp pieces), but
  the stat total is the honest default and the one the player can verify by
  eye.
- **Comp commitment.** `value.comp_progress(...)` per turn already answers "how
  close is each candidate comp to its commit threshold" and is what the overlay
  shows live. Per-turn series = the same call at each buy-phase end. Note it
  needs the same inputs the live coach has (playable comps, recent cards,
  trinkets), so this is a call during the replay pass, not a lookup.
- **Blunders.** Two independent detectors, both from data that already exists:
  - *Sell-side*: `value.sell_reason()` on the sold card at that moment returns
    "comp core" / "comp glue" / "scaler" / "filler" / "off-comp filler". So
    "sold a comp core while fillers stayed" is a direct comparison between the
    sold card's role and the roles of the cards kept. This is the maintainer's
    example, and it needs no new engine work.
  - *Buy-side*: `outcome_audit.disagreement_rows` compares the model's
    top-ranked shop card against what the player actually bought — already
    written, currently unused by any player-facing surface.

---

## 3. The traps, all measured, all of which would produce a confident wrong answer

**3.1 `friendly` is None unless the coach is driven on a cadence.** The first
probe fed the whole chunk through `LiveCoach.feed()` and never called
`analyze()`. Result: `friendly = None`, so **every minion on both sides was
attributed to the opponent** — a board of 10 "theirs" that was really 5 and 5.
`REPLAY_LEARNING.md` predicts exactly this ("Every offline replay that wants
scout data must call `analyze()` on a cadence, or it will silently measure
nothing"). Any new replay pass must drive the settle loop, not just feed.

**3.2 Combat-snapshot stats include non-persistent combat buffs.** Turn 5:
`stats 31` at combat start → **`stats 51`** later in the same fight (Locked-up
Mutineer 6/3→10/4, Crackling Cyclone 2/1→6/2, Fire Baller 4/3→8/4) → `31` again
at the next restaging. Turn 6 reaches `stats 68` mid-fight with an enemy
Flighty Scout at 17/19. Measuring board growth off combat snapshots would book
one-fight scaling as permanent progress. **Growth is a buy-phase measurement.**

**3.3 Several combat bursts can belong to one grouped turn.** Turn 5 shows three
distinct stagings with three different opponent boards; turn 4 shows four. The
existing selection rule is `fight_table._their_board`'s — prefer `phase ==
"combat"`, then take the snapshot with the greatest opponent presence, on the
reasoning that combat reveals their board progressively and deaths empty it, so
the fullest view is the honest estimate. That rule is defensible for THEIR side;
for OUR side the burst should be matched against our known board instead, since
we know it exactly. This needs a decision, not a default.

**3.4 The first buy snapshot of a turn carries the PREVIOUS fight's teardown.**
Turn 6 `[0] phase=buy ours=5 theirs=4` — that `theirs=4` is the last opponent's
surviving staged board, not the seat being fought this turn. Attributing it
would show the player the wrong opponent every single turn.

**3.5 A turn's snapshots drain to zero and then restage.** `[29] ours=0` is not
"the player had no board"; it is the teardown. Any "weakest moment" or
"board value over time" series must ignore the drain-to-zero snapshots, or
every turn ends in a cliff to nothing.

---

## 4. Plan

**Phase A — the extractor. DONE** (`app/turn_review.py`). Per turn: buy-end
board, combat-start boards for both sides, battle-end board, plus lag and notes.
Verified against the 10-06 game, where T5/T6/T7 match the hand-measured states
exactly. 31 tests over a pure `_turn_rows()` assembler.

**Phase B — the metrics. DONE, and it caught a bug in itself.** All four, in
`turn_review`, rendered by `settle_up`:

- **Gold** — `tier_review._spend` prices every purchased card through
  `value._buy_prices`, the one price layer. **The first version did `3 × buys`
  and was wrong**: 5 of that game's 24 buys were tavern SPELLS (Enchanted Lasso,
  Repair Job, Armor Stash, Energizing Chamber, Natural Blessing), which keep
  their own prices — Repair Job costs 2, so pricing it at 3 inflates the turn.
  Measured totals for the game: 22 cards for 62g, 32 rolls for 32g, 5 levels,
  **120g countable spend** across 15 turns. Still not included, and named as
  such: a hero power that costs gold.
- **Board value** — stat total at buy end, differenced per turn (persistent
  stats only, per trap 3.2). T6 growth +37, T9 +63, T10 +599.
- **Comp commitment** — projected straight from the analysis's own
  `comp_progress`, so the per-turn series is free. It names the target from T9
  in this game.
- **Blunders (sell side)** — `_sell_questions`: a card whose role is comp
  core / addon / glue / engine / scaler that LEFT while a filler STAYED, both
  roles from `value.sell_reason`, the same function the live "Your board" row
  prints, so the review cannot disagree with what the player was shown. Two
  fired in this game (a Fire Baller, an Elite Navigator). Named `sell_questions`
  because that is what they are: a comp core is sometimes right to sell, and
  this cannot see the player's reasoning.

Two smaller things Phase B settled, both worth keeping:

- **The sell list can repeat a card.** Turn 7 reports
  `['TB_BaconUps_159', 'Fire Baller', 'Fire Baller']` — three entries for two
  distinct cards. The review asks one question per distinct card+role; whether
  `player_actions` is double-counting a single sell is an OPEN question for that
  module and its other consumers, not something to fix by deduping here.
- **The lag note needs a buy board to lag.** Turn 1 has no buy snapshot, and the
  first version printed "1 minion was played after the last buy-phase snapshot"
  directly above "no buy-phase board snapshot".

**Phase C — render it. DONE (text + HTML).** `settle_up` now carries
`timeline`, and both renderers show it: console gets a TURN BY TURN section
before the phase list, and the page gets one card per turn with `went in` /
`they had` / `kept`, the gold and stat deltas, the comp target, and any sell
question. Boards are text ("Locked-up Mutineer 6/3, Crackling Cyclone 2/1\*",
`*` = golden) rather than card tiles, because the page is standalone and art
lives behind the overlay's `/img` route. A timeline failure is recorded as
`timeline_error` and the phase list still renders — never silent.

**Phase D — the rest of the ask. DONE (2026-10-06).**

- **The cast-grading gap is closed at the source.** `value.top_move` derived
  every step's `card` by PARSING the rendered text, so only a buy step ever
  resolved one, and `player_actions` counted spells instead of naming them.
  `_top_move_text` now records which card each hand step is about while it still
  holds the ids, and `player_actions` records `spell_ids`. Same game:
  **8 ungraded phases → 1** (a swap). `_plan_shape` reports the card for
  cast/play, and `_verdict` grades both.
- **A session view and a history view.** `--session` summarises every game in a
  log; `--history N` aggregates the newest N logs. Both ride the same pure
  `_summarise` / `_session_totals` pair, so the numbers mean the same thing at
  one night or ten. Cost is stated in the flag's help: every game is replayed
  twice (~7 s), so history is minutes and never runs on the game-end path.

**The sell detector needed a second pass, and this is why.** The first version
fired per sold card and produced **12 questions in an 11-turn game**, nearly all
of them the same sentence: one filler (`BG36_210`) sat on the board while four
scalers were sold in a single turn, so that board state printed four times. Two
changes:

- **One question per turn**, naming the strongest card sold and the filler kept,
  plus `also_sold` for the rest. One turn is one decision about what to sell.
- **A turn that sells most of its board is a REBUILD**, and says so. Selling
  four minions at once is repositioning or pivoting, not four mistakes — the
  choice the detector can see (this card over that filler) is not what happened
  there. Threshold is three sold; `rebuild` rides the question so a renderer
  cannot present it as a blunder.

The same session, after: **14 questions → 6**, and of game 2's four entries
three are labelled rebuilds and one is a real question ("sold Mechagnome
Interpreter (scaler) while keeping Hoarding Hyena").

**One cost to know.** A review is now TWO full replays of the game — the phase
rows (`outcome_audit.audit_game`) and the timeline (`turn_review.timeline`) —
about 10 s for a 15-turn game. `outcome_audit.audit_game` could take an injected
coach so one pass serves both; that refactor is the obvious next efficiency win
and was deliberately not done at the end of a session in a shared, tested
function.

**Standing constraint, unchanged by any of this.** Nothing here may appear on
the LIVE page. The timeline is a verdict-shaped artefact — it says what the
player should have done — and it belongs in the review, reachable only after the
game it describes is over. `test_live_view.py` is the control that keeps it
there.

---

## Phase E — save the replay, and the tab (2026-10-07)

**The ask** (maintainer): an option to SAVE a replay when a game ends, two
tabs at the top of the page — **Another Round** (the live overlay, unchanged)
and **Settle Up** (a browser: pick a saved game from a dropdown, see it turn
by turn, board state first).

**What was already true, and what was missing.** Every piece of the display
existed; nothing outlived the process. The review was one in-memory HTML
blob for the latest game, and the timeline's boards rendered as text only
because the standalone page has no art route. Three additions close it:

- **`app/replay_store.py`** — save/list/load over `app/saved_replays/`, one
  JSON per game. Readable ids (`2026-10-06_185502-Chenvaala-2`,
  collision-suffixed), atomic writes, corruption-tolerant listing,
  path-safe load. The stored rep keeps card IDS — it is data, not
  rendering; display names are joined at SERVE time
  (`coach_ui._name_timeline_boards`), so the file stays canonical and a
  renamed card fixes old saves. Per-user data, `decision_logs` class:
  gitignored (bare basename — the `sync.py --new` reason) and in
  `publish_release.EXCLUDE_DIRS`. The source log is a POINTER (`log` +
  `game`), not a copy; the rep is self-sufficient for display, and the
  archive follow-up (megabytes per game) is deliberately not here.
- **The endpoints** — `POST /review/save` (the end-of-game card's **Save
  replay** button; 409 with the reason when nothing has finished),
  `GET /review/list`, `GET /review/game?id=` (id charset = the store's
  filename charset). `set_review` now carries the rep alongside the HTML.
  `/review` itself is untouched.
- **The tabs** — a two-tab toggle at the top of the overlay page. Another
  Round is the existing live view byte-for-byte underneath; Settle Up
  fetches only from `/review/*` and renders one card per TURN: went in /
  they had / kept as **card tiles** (the live page's own `tile()` markup
  and `/img` art — the thing the standalone page cannot do), gold, board
  stats + growth, spend, comp target, sell questions, notes, and that
  turn's phase rows (verdict, what you did, next-fight HP). Tab choice
  survives reload; switching never clears live state; the poll runs
  regardless.

**The wall moved half a step, on purpose, and was re-pinned.** PIVOT.md's
contract is that verdicts never reach the player while a decision can be
acted on. The tab does not breach it — everything it shows describes a
game that is OVER — but it does put the review one tab away from the live
page, which `test_live_view.py` never imagined. The control now runs from
both sides: `test_live_view.py` still pins the live payload, and
`test_settle_tab.py::TestTheWall` pins that a review rep sitting in
coach_ui state never leaks into `/analysis` (and that the rep survives a
new game's clear exactly as the HTML always has, 2026-10-04).

**A settled decision extended, not reverted.** The standalone page stays
exactly as built — its reason (a keepsake with no process behind it) is
intact, and README still says so. The tab is the browsing layer over the
store on top of it.
