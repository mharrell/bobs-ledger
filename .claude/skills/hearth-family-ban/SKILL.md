---
name: hearth-family-ban
description: Determine the 5 allowed / 5 banned tribes for a Battlegrounds game from a Power.log, and filter comps by the family ban. Use when the coach needs to know which tribes are playable in a given game, or which comps are available.
---

# Family Ban — 5 allowed / 5 banned tribes per game

Each Battlegrounds game allows **exactly 5 tribes** and bans the other 5
(verified across the user's recent replays — always 5/5, not "~half"). A comp is
playable only if **every core card has at least one tribe in the allowed set**.

## Detect the 5 allowed tribes from a Power.log

The allowed tribes are the **pure single-tribe minions** in the tavern minion
pool. In the log, pool minions are `IS_BACON_POOL_MINION` entities (SHOW_ENTITY /
FULL_ENTITY blocks carrying that tag). For each pool minion, read its tribe from
the block's **own `tag=CARDRACE` line** — the log is the patch-proof source; the
hearthstonejson card DB (`.card_races.json`) is only the fallback for blocks that
print no race tag (it lags patches by weeks).

- A **pure** minion (exactly one tribe) is in the pool only if that tribe is
  active. A tribe counts as allowed once **3 distinct** pure pool minions of it
  are seen (`MIN_PURE_POOL_CARDS`) — card effects summon banned-tribe pool
  minions mid-game (2026-09-10: BG34_500 Flaming Enforcer, Demon, from a spell),
  and counting singletons pushed the set to 6-8 tribes, which fails the 5/5
  gate open and lists banned comps. Real allowed tribes show 10+ distinct pure
  minions in the first minutes; observed leaks are 1-2 cards.
- A **compound** minion (e.g. MECHANICAL/MURLOC) appears if *any* of its tribes
  is active, so it **cannot** reveal bans — ignore compound minions for detection.

The 5 tribes with no qualifying pure minion in the pool are banned; fewer than
5 qualifying tribes (pool not revealed yet, or a non-5/5 mode) = **fail open**
(no ban info), never "all banned".

## Filter comps by the ban

A comp whose own `tribe` is banned drops outright. Otherwise a comp survives
when a **majority of its core cards** are buyable:
- neutral (no tribe) or all-tribe (`ALL`) core → always available,
- at least one tribe in the allowed set → available,
- unknown tribe → fail open (never wrongly exclude).

Compound core cards (e.g. `DEMON/QUILBOAR`) are playable if *either* tribe is
allowed. When a minority of the core is banned-tribe the comp degraded-keeps
with `_blocked_core` (those cards are marked banned-this-game in the UI, not
buyable). More than half the core banned → the comp as written is dead and
drops.

## Implementation

`bans.py`:
- `bans_from_log(powerlog_path)` → per-game `{seed, allowed, banned}` (canonical
  tribe names). Uses the card DB cached at `.card_races.json`.
- `filter_comps_by_available_tribes(comps, card_races, allowed_tribes)` → the
  playable comps.

CLI: `python bans.py <Power.log>` prints per-game allowed/banned.

## Related

- `meta/comps.json` (core card ids), `meta/cards.json` (per-card
  tribe, incomplete), the full card DB (`.cards_full.json`).
- Memory `hearth-family-ban`.
