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
2. **Card-level opponent snapshots (medium):** extend the lobby scout —
   staged-burst capture keyed by seat, subtract our exact board, staleness
   per seat → tribe-pressure lines for the Build column + next-opponent comp
   preview for the Decide column (upgrade over today's stat-total-only
   preview in `live_coach.py`).
3. **LLM context:** feed pressure summaries + remaining() into coach_llm
   context; honesty labels ("of seen seats", "as of round N").
4. **Not built:** generic confidence percentages; fractions over unseen
   seats.

Tool: `pool_forensics.py <Power.log> [--game N] [--bursts] [--elim] [--tags]`
re-derives everything above from any session log — re-run after client
patches that touch BG entity staging.
