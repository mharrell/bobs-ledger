# Battlegrounds Power.log structure — what's actually recoverable

Validated against a real session (`Hearthstone_2026_08_24\Power_old.log`,
2 games). This supersedes the earlier "grep only" notes in `OPPONENT_DATA.md`.

## The headline: hslog is the wrong tool for BG

`python-hslog`'s `EntityTreeExporter` is built for constructed (2 players). It
**mangles Battlegrounds' 8-player structure**: it collapses all 7 opponents
into the single "spectator" player, so `game.players` yields 2 entries (you +
one opponent), the hero is a placeholder (`TB_BaconShop_HERO_PH`), and
placement is unreliable.

The raw log is richer and simpler to parse directly. `extract_game.py` does
this with stdlib regex only — no `hslog` at runtime.

## How BG encodes 8 players in a 2-player log

- **Only 2 player numbers exist per game**: the friendly player (e.g. `5`) and
  the spectator (`13`). All 7 opponents share the spectator number.
- **The 8 heroes are distinguished by card id, not player number.** Each hero is
  a separate entity with its own `cardId` (`BG36_HERO_105`, `TB_BaconShop_HERO_12`,
  …) and its own `PLAYER_LEADERBOARD_PLACE` / `PLAYER_TECH_LEVEL` tags.
- **Hero card ids come in three shapes** (all real heroes):
  - `BGxx_HERO_xxx` (modern heroes, e.g. `BG36_HERO_105`)
  - `TB_BaconShop_HERO_xx` (legacy heroes, e.g. `TB_BaconShop_HERO_12`)
  - `TB_BaconShop_HERO_xx_SKIN_*` (a skin variant, e.g. `TB_BaconShop_HERO_70_SKIN_I`)
  - Exclude: hero powers (`…_p`, `…_p2`, `…_pe`), placeholders (`_PH`, `_KelThuzad`).

## The tags that matter

| Signal | Tag | Notes |
|--------|-----|-------|
| Placement | `PLAYER_LEADERBOARD_PLACE` | On the hero entity. **Last value wins** (it fluctuates 1→N as players die). |
| Tavern tier | `PLAYER_TECH_LEVEL` | On the hero entity. Per-hero, so tier timing is recoverable for **all 8**. |
| Hero name | `entityName=` in the `Entity=[…]` block | e.g. `Nightmare Lord Xavius`. |
| Account name | `Entity=<name> tag=HERO_ENTITY value=<id>` | Maps an account to its hero entity. |
| Buy | `tag=CONTROLLER value=<friendly>` | A minion's controller flips spectator→friendly when bought. |
| Sell | `tag=ZONE value=GRAVEYARD` with `DAMAGE=0` | A sold minion is undamaged; a combat death is not. |

## The re-created-hero dedup

Near the end of a game the friendly hero is **re-created** for the final
leaderboard display: a fresh entity (higher id) with the same card id but a
**stale placement** (e.g. original id `109` place `5`, re-created id `10119`
place `3`). Fix: per card id, keep the **lowest entity id** (the original, live
hero). Entity ids are monotonic, so the original always has the lower id.

## What is NOT recoverable

- **Opponents' individual buys/sells.** All 7 opponents share the spectator
  player number, so their minions are indistinguishable by controller. Only the
  friendly player's move stream is recoverable. (Tier timing *is* per-hero.)
- **Sells are approximate.** The `DAMAGE=0` filter removes combat deaths, but
  deathrattle-resummon edge cases still double-count a few sells.

## The first-vs-last comparison is honest but thin

Tier timing is the one clean per-player signal, and it does **not** always
explain placement:

- **Game 1**: winner reached tier 6, loser stalled at tier 4 — a clear gap.
- **Game 2**: winner and loser both reached tier 5 within seconds of each other
  (t5 at 22:12:23 vs 22:12:18). Tier timing alone does not separate them.

So tier timing is a *necessary* signal, not a *sufficient* one. Board
composition, hero choice, and combat RNG carry the rest — which is exactly why
the coach needs the board-state parser (Phase 2), not just the move stream.

## Board-state reconstruction (Phase 2)

`board_state.py` reconstructs the friendly board (minions + stats) from the raw
log. Three log quirks had to be handled:

1. **Empty-CardID FULL_ENTITY blocks.** Enchantment entities are created with
   `FULL_ENTITY - Creating ID=<id> CardID=` (empty card id) and revealed later
   via `SHOW_ENTITY`. The FULL_ENTITY regex must use `\w*` not `\w+`, or the
   block's tag lines (e.g. `tag=CARDTYPE value=ENCHANTMENT`) get attributed to
   the *previous* entity, corrupting that minion's cardtype.

2. **End-of-game cleanup.** At game end (`PLAYSTATE=WON/LOST`) every minion is
   moved to `REMOVEDFROMGAME` and its stats reset to base. The friendly board is
   then re-created as fresh, high-id entities in PLAY — and *those* carry the
   buffed stats (e.g. a 6/6 Naga re-created as 82/58). The original entities in
   REMOVEDFROMGAME are reset to base, so the buffed stats live only on the
   re-created entities.

3. **Friendly board = re-created entities in PLAY.** The friendly final board is
   read from the minions in PLAY at game end (the re-created entities), which
   carry the buffed stats. The opponents' board is read from the last snapshot
   (taken on each friendly HAND→PLAY), with stats frozen at snapshot time —
   because the opponents' minions are moved to REMOVEDFROMGAME and reset to base
   at game end, so their buffed stats are only recoverable mid-game.

The friendly board is fully reconstructable (minions + buffed stats). The
opponents' board is only recoverable as a combined pool (all 7 share the
spectator player number), and only the minions that happen to be in PLAY at the
last friendly play — a partial view, not the full 7×7 board.

## Deliverable

`extract_game.py` — stdlib-only, per-game:

```
python extract_game.py <Power.log> [--games N] [--moves] [--compare]
```

- default: 8 heroes (card, name, placement, tier) + account→hero map.
- `--moves`: tier timing for all 8 + friendly buys/sells.
- `--compare`: first-place vs last-place tier timing.

`board_state.py` — stdlib-only, per-game:

```
python board_state.py <Power.log> [--games N]
```

- friendly final board (minions + buffed stats) + hand + hero tier/gold/armor.
- opponents' board as a combined pool (see caveat above).
