# Opponent Observation from Own Replays — the data asset

## Thesis

Each Hearthstone `Power.log` game contains the **full move stream of all 8
players** (hero, purchases, sells, tavern tiers, final placement). Therefore
**every game you play yields ~8 decision trajectories**, not just your own.

## Why it matters

1. **8x per-game yield.** One replay = you + 7 opponents' complete decisions.
2. **More than the tracker stores.** HDT's `BgsLastGames.xml` keeps only *your
   own* final board + placement — no opponent data. Your raw log is richer.
3. **Not exposed by the incumbents' API.** HSReplay surfaces only aggregate
   stats; raw replays are proprietary. Your logs are the only path to
   opponent-level detail.

## What it enables

- **MMR-localized coaching** — your opponents are near your rating, so you can
  build win-tables local to the skill band you actually coach.
- **Opponent-modeling feature** — learn common patterns at your MMR band and have
  the coach warn live about threats.
- **Full-time-stream training set** — bucket states -> outcome win-tables, and
  model "what does a high-finisher do from this board?"

## Where the data lives

- Hearthstone session logs:
  `C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_<timestamp>\Power.log`
  (or `Power_old.log` after rotation).
- Format is the standard Battlegrounds Power.log:
  - `CREATE_GAME` / `GAME_SEED` — unique match id
  - `BACON_*` tags (`BACON_BARTENDER_CARD_ID`, `TECH_LEVEL_MANA_GEM`)
  - `SHOW_ENTITY` / `CardID=` — every minion/card entering play
  - `TECH_LEVEL` — tavern tier changes
  - `TAG_PLAYSTATE value=PLAYING/WON/LOST` — game state / endings

## Parser

**`hslog` mangles Battlegrounds.** Its `EntityTreeExporter` is built for
constructed (2 players) and collapses all 7 opponents into the "spectator"
player. So we parse the raw log directly with stdlib regex — see
`extract_game.py` and `analysis/BG_LOG_STRUCTURE.md` for the full structure.

## Validation task — DONE (session 2026-08-25)

`extract_game.py` (stdlib-only) now does the full per-game split + extractor:

1. Split one `Power.log` into games (by `CREATE_GAME`).
2. Extract all 8 players' hero, hero name, account name, placement, and tier.
3. Extract the move stream: tier timing (all 8) + friendly buys/sells.
4. Print a first-place vs last-place comparison (`--compare`).

```
python extract_game.py <Power.log> [--games N] [--moves] [--compare]
```

## Validated on real data (session 2026-08-24)

Extracted from `Hearthstone_2026_08_24\Power_old.log` (2 games):

- **Game 1**: You = **Nightmare Lord Xavius** (BG36_HERO_105), **5th**. Winner:
  Inge, the Iron Hymn (tier 6); last: Murloc Holmes (tier 4).
- **Game 2**: You = **Sire Denathrius** (BG24_HERO_100), **8th**. Winner:
  Shudderwock (tier 5); last: you (tier 5).

Confirmations:
- Full 8-player visibility (heroes, hero names, account names, placements,
  tiers) recoverable — all 8 account names resolve in both games.
- Tier timing recoverable per-hero for all 8 players.
- Friendly move stream (buys/sells) recoverable; opponents' individual
  buys/sells are **not** (they share the spectator player number).

Honest note: tier timing alone does not separate the game-2 winner from the
loser (both hit tier 5 within seconds). Board composition and combat RNG carry
the rest — see `BG_LOG_STRUCTURE.md`.

## Honest caveats

- **Volume scales with games played.** Per-game efficiency is 8x, but raw volume
  depends on install base.
- **Observational, not causal.** Placement is confounded by 7 other players and
  shop randomness. "Players who took X placed better" is a *correlation*. Use
  bucketing + outcome tables, and sham-control any "coaching improves placement"
  claim (dead-model-calibration discipline from breakoutBot).
