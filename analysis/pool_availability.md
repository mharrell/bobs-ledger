# Card availability: log mechanics verified (Phase 0)

Feasibility review of the external `bg_pool_estimator.py` blueprint, then a
forensics pass (`pool_forensics.py`, this branch) against a real session
(`Hearthstone_2026_09_11`, 2 games: friendly=1/12 rounds and
friendly=5/19 rounds). This doc records what the log actually supports, what
it doesn't, and what the estimator must therefore look like.

## The premise holds: the pool is shared, not per-player

TFT-style per-player pools would have killed the whole feature. Confirmed
against community sources (Blizzard forums, hearthstone.fandom.com): the
minion pool is shared lobby-wide — T1:18, T2:15, T3:13, T4:11, T5:9, T6:6,
T7:5 copies. Opponent holdings genuinely deplete availability, and eliminated
players' boards return to the pool (community rule — not yet log-verified;
see open items). Pool sizes have drifted across seasons (older lobbies used
16/15/13/11/9/7), so they belong in `meta/` (patch_notes-owned), not a module
constant.

## What the log supports

### The combat staging burst (the snapshot source)

Each combat window stages **both boards** as fresh entities under the shared
combat-slot controller:

- **The staging marker is `tag=CREATOR`** pointing at the persistent
  `TB_BaconShop_8P_PlayerE` enchantment entity (id 45 in session 1).
  Board copies are created by it; combat summons are created by other minions
  (`CREATOR=<minion eid>`); heroes/hero-powers/trinkets are re-created with
  `CREATOR=1` (GameEntity) or their own ids; **shop offers are not staged by
  it at all** (zero buy-phase staged creations in both games).
- Order within a round: **our board first, then the opponent's** (position
  runs restart 1..7 → 1..N). The final duel stages only the opponent's board
  — consistent with the final-duel extract quirk in `BG_LOG_STRUCTURE.md`.
- The **blueprint's central blind spot**: both staged boards share the combat
  slot controller, so "controller==9 minions" is NOT the opponent's board.
  The estimator must subtract our exactly-known board from the staged burst
  (Counter subtraction), or take the position-restarting tail group.
- Goldens arrive as `_G` card ids AND `tag=PREMIUM value=1` — either works.
- Hand-carried minions surface as `SHOW_ENTITY` reveals mid-combat (rare:
  1 per few rounds), plus occasional pos-less staged copies.
- `BACON_CURRENT_COMBAT_PLAYER_ID` fires per pairing (both players) and is
  reset to **0 after the fight** — a clean fight boundary signal.
- Shop pollution is real but doubly gated: shop offers live in buy windows
  AND lack the staging creator. Phase-gate to combat windows, filter
  `CREATOR` → clean.

### Seats and the bridge

- `BACON_CURRENT_COMBAT_PLAYER_ID` values are a per-game **seat space (1..8)**;
  0 = slot cleared. Seats are the only stable opponent key: opponent hero
  entities are re-created under the combat slot every round, so their player
  numbers (9 / 13 in the two games) are per-round ghosts.
- Each seat row names the account; `extract_game`'s HERO_ENTITY map joins
  account → hero card. The friendly seat equalled the friendly player number
  in both games (1/1 and 5/5).
- `NEXT_OPPONENT_PLAYER_ID` is announced during the buy phase in **seat
  space** — the same key. (Our existing lobby scout's `next_opponent` is a
  seat value.)

### Controller variance (blueprint fix)

Session 1 game 1: friendly=1, combat slot=9. Game 2: friendly=5, slot=13.
The blueprint's hardcoded `controller==1` / `controller==9` are one session's
values. All our parsers already resolve these dynamically — the estimator
must too.

### Elimination: there is no tag

Vocabulary sweep found **no elimination flag**:

- `PLAYSTATE` — 7 events/game, game-end only (plus transient `LOSING`
  blips mid-combat that revert).
- `BACON_DIED_LAST_COMBAT` — per-MINION card-text flag (set on our dead
  minions in SETASIDE), not per-player.
- Nothing else in the full `BACON_*` vocabulary matches
  (89 distinct tags swept; candidates like `BACON_PAIR_CANDIDATE` are pairing
  machinery).

Practical detector: a seat stops being paired + its
`PLAYER_LEADERBOARD_PLACE` freezes at its final value. In game 1, seat 6 was
never paired once in 12 rounds (died before we ever met them) — pairing
absence is informative but **not sufficient per-round** (you fight 1 of 7
seats per round; alive seats go unseen for stretches). Round-level
"eliminated" should use leaderboard-place improvement events: the number of
alive players drops exactly when places shift.

## What the log does NOT support (honest limits for the UI)

1. **Opponent churn between sightings** — bought-and-sold-in-between is
   invisible in both directions. `remaining()` is a bounded estimate, exact
   only at the moment of a fresh sighting.
2. **Opponent hands and shops** — invisible (except rare combat
   SHOW_ENTITY reveals). Their held copies are undercounted → availability
   runs optimistic.
3. **T1–T4 remaining() is a guess** — too many churning seats; only T5+ can
   earn the blueprint's `is_trustworthy` coverage check.
4. **"Returned to pool on elimination" is community knowledge**, not
   log-verified — pool contents aren't logged. Verify opportunistically in
   live play (a busted seat's unique copy reappearing in our rolls).
5. Tavern spells have their own pool; unmodeled here.

## Integration plan (phases)

1. **Own-pool accounting (exact, small) — LANDED (phase 1).** `pool.py`
   (state-based holdings: board + hand, golden = 3; sizes from
   `meta/pool.json`, patch-notes-owned) → `own_pool` on the live analysis →
   Market chips ("N pool left" / "last pool copy" / "pool dry") and three
   value gates: hand hold flips to play when the pool can't produce a 3rd
   copy, the triple note says when the pool can't produce the remainder,
   and `_hunt_check` refuses cores whose pool we've drained.
2. **Seat-level opponent snapshots — LANDED (phase 2, `lobby.py`).**
   Staged-burst capture inside LiveCoach (open at the buy-phase MAIN_END
   with our exact holdings, close at the next MAIN_ACTION), resolved into
   per-seat board Counters via position-run grouping: staged boards arrive
   as zonepos runs (1..N, restart 1..M) and windows can carry a second,
   STALE run — the run with the largest position reach wins, our exact
   holdings subtract out, and a resolved board above 7 copies is marked
   BLENDED: it still feeds the pool ledger (an upper bound on holds) but
   never the composition preview. Consumers:
   - **Next opponent preview (Decide column):** the announced seat's
     last-known board as tiles, hero + account named, "as of round N".
   - **Tribe pressure (Build column):** "3 of 4 seen seats (2+ copies)"
     per tribe, ban-filtered, over ALL seen seats — unseen seats are
     omitted, not assumed absent.
   - **Market chips:** fresh seats' held copies (≤2 rounds old) subtract
     from the phase-1 own-side floor.
3. **LLM context:** feed pressure summaries + remaining() into coach_llm
   context; honesty labels ("of seen seats", "as of round N").
4. **Not built:** generic confidence percentages; fractions over unseen
   seats; elimination flush (dead seats simply age out of the 2-round
   freshness window — their last-known board keeps subtracting from the
   ledger until then, a bounded and conservative error); tavern-spell
   pools; Duos.

### Phase-2 known limits (all labeled in the UI)

- A blended window inflates a seat's held-count until its next clean
  sighting; the preview hides it, the chips only get conservative.
- Opponent hands/shops stay invisible (held copies undercounted →
  availability optimistic between sightings).
- NEXT_OPPONENT tags that stream before the hero parses are dropped
  (pre-existing scout behavior) — round-1 attribution can be missing in
  replay walks; live play parses the hero during the pick, before turn 1.

Tool: `pool_forensics.py <Power.log> [--game N] [--bursts] [--elim] [--tags]`
re-derives everything above from any session log — re-run after client
patches that touch BG entity staging.
