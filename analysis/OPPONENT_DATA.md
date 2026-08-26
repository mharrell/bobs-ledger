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

Use **`python-hslog`** — the official HearthSim Power.log deserializer (MIT,
Python), the same library HDT uses under the hood. Cloned into `python-hslog/`.
It yields per-game `Game` objects (players, entities, tags) and supports a
`FriendlyPlayerExporter` to identify the human player.

## Validation task (parked / to-do)

Build a per-game split + opponent-move extractor:
1. Split one `Power.log` into individual games (by `CREATE_GAME`).
2. Extract each player's hero, tavern tier path, card purchases, and placement.
3. Print a first-place vs last-place game side-by-side to eyeball data richness.

Deliverable: `parse_bg.py` (smoke test) + a fuller extractor once `hslog` is
installed.

## Validated on real data (session 2026-08-25)

Directly extracted from the raw `Power.log` (no `hslog` yet — grep only):

- **Game 1** (20:43, seed 1336465919): You = **Yogg-Saron** (TB_BaconShop_HERO_35),
  **5th (LOST)**. Board: pirates/mech hybrid (Gatekeeper Amalgam, Rimescale
  Priestess, Captain Cookie, Timecap'n Hooktail, Proud Privateer). Opponents seen:
  Cap'n Hoggarr (8th), Guff Runetotem (7th), Shudderwock (4th).
- **Game 2** (21:02, seed 1233865749): You = **George the Fallen**
  (TB_BaconShop_HERO_15), **1st (WON)**. Opponents seen: Arch-Villain Rafaam (2nd),
  Genn (3rd), Mutanus (4th), Maiev (5th), Lord Barov (6th).

Confirmations:
- Full 8-player visibility (heroes, placements, opponent identities) recoverable.
- Hero choice + pick reconstructable (offered list -> chosen hero).
- Board composition + spells/trinkets recoverable per player.

Natural first/last contrast: a losing pirates/mech board (5th) vs a winning
George game (1st) — ideal for the planned comparison.

## Honest caveats

- **Volume scales with games played.** Per-game efficiency is 8x, but raw volume
  depends on install base.
- **Observational, not causal.** Placement is confounded by 7 other players and
  shop randomness. "Players who took X placed better" is a *correlation*. Use
  bucketing + outcome tables, and sham-control any "coaching improves placement"
  claim (dead-model-calibration discipline from breakoutBot).
