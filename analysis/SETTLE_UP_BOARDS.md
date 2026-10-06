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

**Phase A — the extractor (next).** One replay pass that drives the coach (per
3.1) and keeps it, so a single pass yields both the existing audit rows and the
per-turn timeline. Output per turn: `{buy_end: board, combat_start: {ours,
theirs}, battle_end: board}` where each board is the structured
`{card, atk, health, golden, keywords}` shape `fight_table._board` already
produces. Verified against this game by eye before anything renders it — the
three states above are the expected values.

**Phase B — the metrics.** Gold held/spent, board stats at buy-end (persisted
series), comp commitment, and the two blunder detectors. Each labelled with what
it is and is not: stat total is not the value function's opinion, and a blunder
detector that fires is a question, never a verdict.

**Phase C — render it.** Per-turn cards in the Settle Up page: the board as
three rows of tiles (ours/theirs where they exist), the stat and gold deltas, and
any blunder flag with the reason. This is where the review finally shows a
picture of the game rather than a line of text per phase.

**Phase D — the boring half of the ask.** Grade the casts (`value.top_move`
writes `card: None` on a cast step; `player_actions` counts spells instead of
naming them) and a session/history view across games.

**Standing constraint, unchanged by any of this.** Nothing here may appear on
the LIVE page. The timeline is a verdict-shaped artefact — it says what the
player should have done — and it belongs in the review, reachable only after the
game it describes is over. `test_live_view.py` is the control that keeps it
there.
