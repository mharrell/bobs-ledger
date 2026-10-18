# replay audit — saved file vs a rebuild from its own log

## 2026-10-16_144509-Malygos-4.json
- Hearthstone_2026_10_16_14_19_10 game 1
- hero saved='Malygos' rebuilt='Malygos'
- place saved=4 rebuilt=4
- turns saved=12 rebuilt=12
- field mismatches: 6
    - turn 11 battle_end: saved=0 rebuilt=6
    - turn 12 winner: saved=None rebuilt='them'
    - turn 12 battle_end: saved=7 rebuilt=0
    - turn 12 theirs_survivors: saved=0 rebuilt=1
    - turn 12 buy_end: saved=0 rebuilt=7
    - turn 12 notes: saved=2 rebuilt=0

## 2026-10-16_150418-Professor-Putricide-7.json
- Hearthstone_2026_10_16_14_19_10 game 2
- hero saved='Professor Putricide' rebuilt='Professor Putricide'
- place saved=7 rebuilt=6
- turns saved=10 rebuilt=10
- field mismatches: 7
    - turn 9 battle_end: saved=0 rebuilt=7
    - turn 10 winner: saved=None rebuilt='them'
    - turn 10 battle_end: saved=7 rebuilt=0
    - turn 10 theirs_survivors: saved=0 rebuilt=1
    - turn 10 buy_end: saved=0 rebuilt=6
    - turn 10 notes: saved=2 rebuilt=1
    - turn 10 lag: saved=0 rebuilt=1

## 2026-10-16_195648-Carny-Silas-6.json
- Hearthstone_2026_10_16_19_30_51 game 1
- hero saved='Carny Silas' rebuilt='Carny Silas'
- place saved=6 rebuilt=6
- turns saved=12 rebuilt=12
- field mismatches: 6
    - turn 11 battle_end: saved=0 rebuilt=6
    - turn 12 winner: saved=None rebuilt='them'
    - turn 12 battle_end: saved=7 rebuilt=0
    - turn 12 theirs_survivors: saved=0 rebuilt=1
    - turn 12 buy_end: saved=0 rebuilt=7
    - turn 12 notes: saved=2 rebuilt=0

## 2026-10-16_210307-Sylvanas-Windrunner-3.json
- Hearthstone_2026_10_16_20_37_05 game 1
- hero saved='Sylvanas Windrunner' rebuilt='Sylvanas Windrunner'
- place saved=3 rebuilt=3
- turns saved=13 rebuilt=13
- field mismatches: 6
    - turn 12 battle_end: saved=0 rebuilt=6
    - turn 13 winner: saved=None rebuilt='them'
    - turn 13 battle_end: saved=7 rebuilt=0
    - turn 13 theirs_survivors: saved=0 rebuilt=1
    - turn 13 buy_end: saved=0 rebuilt=7
    - turn 13 notes: saved=2 rebuilt=0

## 2026-10-16_213226-Genn-Worgen-King-7.json
- Hearthstone_2026_10_16_21_14_03 game 1
- hero saved='Genn, Worgen King' rebuilt='Genn, Worgen King'
- place saved=7 rebuilt=7
- turns saved=9 rebuilt=9
- field mismatches: 6
    - turn 8 battle_end: saved=0 rebuilt=7
    - turn 9 winner: saved=None rebuilt='them'
    - turn 9 battle_end: saved=7 rebuilt=0
    - turn 9 theirs_survivors: saved=0 rebuilt=1
    - turn 9 buy_end: saved=0 rebuilt=7
    - turn 9 notes: saved=2 rebuilt=0

## 2026-10-16_214853-Carny-Silas-7.json
- Hearthstone_2026_10_16_21_14_03 game 2
- hero saved='Carny Silas' rebuilt='Carny Silas'
- place saved=7 rebuilt=7
- turns saved=9 rebuilt=9
- field mismatches: 2
    - turn 9 battle_end: saved=7 rebuilt=0
    - turn 9 theirs_survivors: saved=2 rebuilt=1

## 2026-10-16_221124-Ambassador-Faelin-7.json
- Hearthstone_2026_10_16_21_14_03 game 3
- hero saved='Ambassador Faelin' rebuilt='Ambassador Faelin'
- place saved=7 rebuilt=8
- turns saved=8 rebuilt=8
- field mismatches: 6
    - turn 7 battle_end: saved=0 rebuilt=7
    - turn 8 winner: saved=None rebuilt='them'
    - turn 8 battle_end: saved=6 rebuilt=0
    - turn 8 theirs_survivors: saved=0 rebuilt=1
    - turn 8 buy_end: saved=0 rebuilt=7
    - turn 8 notes: saved=2 rebuilt=0

## 2026-10-16_222936-Queen-Wagtoggle-7.json
- Hearthstone_2026_10_16_21_14_03 game 4
- hero saved='Queen Wagtoggle' rebuilt='Queen Wagtoggle'
- place saved=7 rebuilt=7
- turns saved=10 rebuilt=10
- field mismatches: 1
    - turn 10 battle_end: saved=7 rebuilt=0

## 2026-10-16_230627-Alexstrasza-2.json
- Hearthstone_2026_10_16_21_14_03 game 5
- hero saved='Alexstrasza' rebuilt='Alexstrasza'
- place saved=2 rebuilt=2
- turns saved=17 rebuilt=17
- field mismatches: 1
    - turn 17 notes: saved=1 rebuilt=0

## 2026-10-17_095135-Teron-Gorefiend-6.json
- Hearthstone_2026_10_17_09_29_27 game 1
- hero saved='Teron Gorefiend' rebuilt='Teron Gorefiend'
- place saved=6 rebuilt=6
- turns saved=11 rebuilt=11
- field mismatches: 1
    - turn 11 notes: saved=1 rebuilt=0

## 2026-10-17_103143-Reno-Jackson-1.json
- Hearthstone_2026_10_17_09_29_27 game 2
- hero saved='Reno Jackson' rebuilt='Reno Jackson'
- place saved=1 rebuilt=1
- turns saved=15 rebuilt=15
- field mismatches: 1
    - turn 15 notes: saved=1 rebuilt=0

skipped (no source log): 5
- 2026-10-15_164216-Greybough-8.json: source log is gone
- 2026-10-15_164548-run-na.json: source log is gone
- 2026-10-15_164554-run-na.json: source log is gone
- 2026-10-15_211954-Ambassador-Faelin-8.json: source log is gone
- 2026-10-15_214927-Sewerwock-3.json: source log is gone

---

## After the rebuild (2026-10-17 18:00)

Done on the maintainer's instruction ("rebuild the stale replays and delete the two
that are messed up"), through `settle_up.rebuild` — the same in-place path the
Settle Up **Rebuild** button uses, which keeps the stored id and overwrites the
game instead of stacking a `-2` beside it.

**Deleted — two files that were never games:**

| file | session recorded | content |
| --- | --- | --- |
| `2026-10-15_164548-run-na.json` | `Hearthstone_2026_01_01` | 1176 bytes, no hero, no turns |
| `2026-10-15_164554-run-na.json` | `Power.log` | 1150 bytes, no hero, no turns |

`Hearthstone_2026_01_01` is the synthetic session name `privacy_scan` uses, so both
arrived from a test or tooling run rather than from play. The store went from 16
files to 14.

**Rebuilt — 11 of the 12 remaining**, all with `timeline_error=None`:

- **Two placements corrected**, to the log's own `PLAYER_LEADERBOARD_PLACE`:
  Professor Putricide 7 → **6** (friendly = player 5), Ambassador Faelin 7 → **8**
  (friendly = player 7). The files had been built seconds after their game ended,
  before the log's leaderboard lines were written.
- The rest matched their earlier placement, hero and turn count, and picked up the
  10-16 fixes: the final fight, the last turn's own buy board, and the removed
  "final board not recoverable" note.
- Spot-checked content, not just presence: Alexstrasza's last turn reads
  `winner=them`, peak 2v5, survivors 0v1, 14/14 step boards and **no notes**;
  Putricide's carries one *legitimate* note ("1 minion(s) were played after the
  last buy-phase snapshot"), which is the `lag` disagreement the audit flagged.

**Skipped — 3, source log pruned by Hearthstone:** Greybough (2026-10-15),
Ambassador Faelin (2026-10-15 21:19), Sewerwock (2026-10-15 21:49). They keep the
numbers they were built with; nothing can re-derive them, so they are the oldest
thing in the store and permanently unauditable.

**Open, cosmetic:** the two corrected files still carry the OLD place in their
filename (`...-Professor-Putricide-7.json` holds place 6, `...-Ambassador-Faelin-7.json`
holds 8). Settle Up lists the placement from the file's content, so the page is
right; only the name is stale. Renaming would change the stored id, so it is left
for a decision rather than done silently.
