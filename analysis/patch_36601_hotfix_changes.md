# 36.6.1 data hotfix (Data build 36601) — changes applied from log evidence

_2026-10-01. No patch-notes article exists for this update yet: the news page's
newest article is still "36.6 Patch Notes" (article 24294373, "[Updated
9/29/2026]"), and its Battlegrounds section is byte-identical to the version we
processed on 2026-09-22 (re-diffed 2026-10-01). Every change below comes from
the one source the game itself makes authoritative: the per-game pool dump
(`pool_roster.py`; every in-pool minion is created as a FULL_ENTITY block with
`tag=TECH_LEVEL`, `tag=ATK`, `tag=HEALTH`, `tag=CARDRACE`)._

## Evidence timeline

| session | BattleNet Data | pool observations |
|---|---|---|
| 2026-09-22 (roster build) | 36600 | Willbreaker t3, Slacker t2, Mindslasher 3/1 (saved roster) |
| 2026-09-27 14:22 | 36600 | same pre-hotfix values |
| 2026-09-29 06:16 | 36600 | **Willbreaker t2, Slacker t3, Conniver PIRATE** (server-side wave 1, no client bump) |
| 2026-09-30 16:46 / 20:53 | 36600 | wave-1 values stable; Mindslasher still 3/1 |
| 2026-10-01 21:04 | **36601** | **wave 2: Mindslasher 1/2, Corroder 4/5, Envoy 2/2, Vanguard 10/10, Snapper 6/8** |

The `36.6.1` label in `meta/pool_roster.json` / `patch_gaps.json` was applied
during the 2026-09-22/23 notes processing, ahead of the client: the client ran
Data 36600 until 2026-10-01 and became actual 36.6.1 (36601) today. `Data
= 36nxx` comes from `Hearthstone.log`'s `BattleNet version` line per session.

## Changes applied to `meta/minions.json` (8 rows, each with `auto_updated`)

| id | card | field | was | now | evidence |
|---|---|---|---|---|---|
| BG36_100 | Wandering Willbreaker | tier | 3 | **2** | pool dump 4 sessions (09-29 → 10-01) |
| BG36_101 | Unwilling Slacker | tier | 2 | **3** | pool dump 3 sessions (09-29 → 09-30) |
| BG36_108 | Vicious Mindslasher | atk/hp | 3/1 | **1/2** | pool dump 10-01 (Data 36601); article had published 3/1 |
| BG36_115 | Nightmare Corroder | atk/hp | 7/4 | **4/5** | pool dump 10-01; article had published 7/4 |
| BG36_311 | Abyssal Envoy | atk/hp | 3/4 | **2/2** | pool dump 10-01; article had published 3/4 |
| BG36_372 | Holy Vanguard | atk/hp | 5/5 | **10/10** | pool dump 10-01; article had published 5/5 |
| BG36_851 | Spark Snapper | atk/hp | 5/5 | **6/8** | pool dump 10-01; buff, Magnetics/APM core |
| BG36_369 | Greedy Conniver | tribe | Aberration | **Pirate** | pool dump 2 sessions (09-27, 09-29, CARDRACE); tribe_src article→log |

Notes:

- **Greedy Conniver** was a DB mis-encode, not a client change: the 36.6 article
  itself lists it under "New **non-Aberration** minions" (§4.3 of
  `patch_3661_changes.md`), and the pool dump prints `CARDRACE=PIRATE`.
- **Holy Vanguard**: only the base stats were observed; the conditional text
  ("+15/+15 while you have 15 or less Health") is unchanged as far as the log
  can see. If Blizzard re-tuned the conditional too, only the notes article will
  tell — re-verify when it updates.
- Composites checked: comps.json references are id-only (tiers/stats always
  read from minions.json), so no comp edits were needed. Snapper is a core of
  Mechs-Magnetics and Mechs-APM (buffed); Corroder is core of Aberrations-Sludge
  (nerfed body, Deathrattle function intact); Slacker is core of
  Aberrations-Deathrattle/Spells (now a tier-3 core — reachability gating picks
  the new tier up automatically from minions.json).

## Open questions resolved and still open

- **RESOLVED — Geomagus Roogug** (`BG28_583`, pending since 09-23 "disagreement
  5"): observed IN the pool 09-29 + 09-30 at tier 4, 4/6, QUILBOAR — exactly the
  DB values. No change; the card is back and the DB was right.
- **RESOLVED — Auto Accelerator** (`BG34_170`, pending since 09-23
  "disagreement 6"): observed IN the pool 09-30 + 10-01 at tier 3, 3/3,
  MECHANICAL — exactly the DB values. No change.
- **OPEN — pool removals**: today's 36601 epoch has a single session so far, so
  cards absent today cannot be distinguished from cards absent from one lobby.
  `meta/pool_roster.json` was left on the 09-22 build until the 36601 epoch
  accumulates sessions (`pool_roster.py --apply` once a few games are in).
- **OPEN — notes article**: when Blizzard publishes the 36.6.1/hotfix notes (or
  re-dates the 36.6 article), re-run `check_patch_notes.py` and reconcile this
  list against the prose.

## Verification

```
python check_meta.py   -> meta OK: 34 comps, 89 cards, 334 minions
```
