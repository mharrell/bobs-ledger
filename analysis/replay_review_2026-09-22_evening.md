# Replay review — 2026-09-22 evening (Xyrella 5th, Marin the Manager 6th, Ambassador Faelin 1st)

Session `Hearthstone_2026_09_22`, 3 games, all played on **patch
36.6.1 day one**. Coach = the pre-36.6.1 main that actually played them
(worktree HEAD `1b008b1`; `meta/minions.json` 263 cards, `meta/comps.json`
24 comps). Reviewed from the log; the overlay was not captured live, so every
render below is a reconstruction (§1 says how faithful it is, and where it is
not). Player `Player#1234` (friendly player numbers: game 1/2 `player=7`,
game 3 `player=4`).

Placements: **game 1 Xyrella 5th** (died t11, tier 4, 11 buy phases) ·
**game 2 Marin the Manager 6th** (died t12, tier 6, 12 buy phases) ·
**game 3 Ambassador Faelin 1st** (tier 6 by t15, 20 buy phases, hp 9 from t11
to the end).

---

## 1. Read this first: `replay_review` does not reproduce the coach's scout

`hearth-coach/_evening_review.py` (→ `replay_review.py`) feeds the game from
line 0 and calls `LiveCoach.analyze()` **once, at the advise moment**
(`replay_review._advise_point`). `live.py` calls `analyze()` every poll batch
(~1 s ≈ 166 log lines here), and `analyze()` is what runs `_ensure_meta()`
(which sets `hero_card`/`friendly`/`account`) and `_resolve_boards()`.

`feed()`'s NEXT_OPPONENT_PLAYER_ID handler (live_coach.py:654–668) is guarded
on `hero_card` already being known. Under the harness order it never is, so
every pairing is discarded. Measured on game 1
(`_evening_tmp/pairing.py`):

```
live.py order   (analyze at each MAIN_ACTION):
   line  7048 next_opp 6   pairing {1: 6, 2: 6, 3: 8, 4: 5, 5: 1, 6: 3, 7: 2, 8: 4, 9: 6, 10: 8}
harness order   (one analyze at the end):
   next_opponent=None      pairing {1: None, 2: None, ... 11: None}
```

Both `_opp_boards` and `_lobby_stats` are keyed off `_pairing`, so in harness
order they stay empty and every published forecast falls through to
`baseline_opp`, the **corpus turn-baseline table** (value.py:154 `_baseline_opp`).

Consequence: the numbers in `_evening_tmp/g1.txt`, `g2.txt`, `g3.txt` — *"your
158 vs their ~91"* (g1 t9), *"your 276 vs their ~163"* (g1 t11), *"your 299 vs
their ~248"* (g3 t13), *"ahead on paper — 346 vs ~163"* (g2 t12) — are **harness
artifacts**, not the strings the overlay showed. Reconstructing in live order
(periodic `ensure_meta()` + `_resolve_boards()` during the feed;
`_evening_tmp/liveorder.py`, outputs `g1_live.txt`, `g2_live.txt`,
`g3_live.txt`) gives different, and sometimes opposite, lines:

| phase | harness (baseline anchor) | live order (lobby-median / fresh anchor) |
|---|---|---|
| g1 t9 | `favored — 158 vs ~91` | `favored — 158 vs ~101, seen 1 round ago · they haven't taken damage in 9 rounds` |
| g1 t11 | `ahead on paper — 276 vs ~163` | `ahead on paper — 276 vs ~199, seen 1 round ago · they haven't taken damage in 11 rounds` |
| g2 t12 | `ahead on paper — 346 vs ~163` | `behind — 346 vs ~872, seen 1 round ago; don't take this fight` |
| g3 t20 | `behind — 1047 vs ~1575` | `behind — 1047 vs 3316, seen 2 rounds ago; don't take this fight` |

Game 2 flips from "ahead on paper" (harness) to an honest warning (live). Any
review of this log that quotes the harness scout is quoting a different coach.
**This is a tool bug, not a coach bug** — but every reviewer on this session
is exposed to it, and the `next_opponent` field in the analysis dict is a
third trap: it is the class default `None` (live_coach.py:415) and `analyze()`
never writes it, so `analysis["next_opponent"]` is always `None`.

§3–§5 use the live-order reconstruction throughout, and mark harness-only
numbers where they matter.

## 2. What the coach could and could not name on patch 36.6.1 day one

The patch added the **Aberration** tribe — 24 of the 181 cards in the
log-mined 36.6.1 roster: 23 under `BG36_0xx/1xx/3xx` plus `BGFYM_005`
Harbinger Aph'lass — and rotated **Naga** out (that same roster retains a
single Naga-tagged card, `BG31_330` Ominous Seer).

In the worktree's live DB:

- `meta/minions.json` (263 cards) contains **none** of
  `BG36_097/098/099/101/103/106/108/109/112/113/114/115/116/300/308/311/312/318/320`.
  All were in play — the player's own board in game 3, the opponent's board in
  games 1 and 2. The coach therefore printed raw ids in advice and on board
  tiles all session: *"2. sell BG36_318 (making room)"* (g2 t12),
  *"6. sell BG36_300 (making room)"* (g3 t15), *"4. sell BG36_311 (making
  room)"* (g3 t11). Counted from the resolved reviews: raw `BG36_*` ids appear
  in coach advice in **9 phases** (g2 t10/t12; g3 t10/t11/t13/t14/t15/t16/t17).
- `meta/comps.json` has **no Aberration comp**, and still ships **2 Naga
  comps** whose core cards the patch removed. The t9 hunt line in game 1 was
  *"no hunt — Unbound Tempest, Kelp Keeper (needs tier 6; Tavern Tempest can
  still drop it)"* — neither Kelp Keeper nor Unbound Tempest is in the 36.6.1
  roster; the coach named two cards the shop could no longer produce.
- The 5/5 **ban detector never resolved in any of the three games**:
  `coach._bans_ready == False`, `coach.allowed is None` at the last buy phase
  of games 1, 2 and 3, so the "Banned tribes" strip was empty all session and
  no comp was ever ban-filtered.

None of that is a "the coach should have built an Aberration comp" criticism —
it could not, on day one. The finding is what it did instead: §3–§5.

## 3. Game 1 — Xyrella, 5th (died t11, tier 4, 11 buy phases)

**The player's engine.** Demon self-damage: Malchezaar, Prince of Dance
(BG26_524) + Ashen Corruptor (BG32_873) + Soul Rewinder (BG26_174) + Devout
Hellcaller (BG33_155), later Insatiable Ur'zul (BG21_004) and Imp-lusionist
(BG36_731). At the t11 advise point the coach read the board as
`Turquoise Skitterer 6/6 · Imp-lusionist 4/2 · Forest Rover 5/5 · Malchezaar
30/29 · Ashen Corruptor 16/16 · Soul Rewinder 48/57 · Devout Hellcaller 26/26`
= **276**. This is the coach's own `demons-self-damage` comp
(`comps.json` core includes `BG32_873` Ashen Corruptor).

**Where the coach was right (followed or correctly declined).** t4/t5 level
curve followed; t7 "Buy Careful Investment (spare gold into value)" → bought;
t1 "Buy Wrath Weaver (growth engine)" declined (player took Dune Dweller,
BG31_815) — correct decline, the demon line was the better one. 6 of 11 phases
ended "TAKEN".

**Where the coach was wrong.**

1. **It never held a comp target and then named the wrong one.** `target_comp`
   is empty for t1–t8, then **`Elementals - Unbound Tempest / committing`
   (t9)**, **`Demons - Shop Buff / pivot` (t10)**, **`Elementals - Unbound
   Tempest / pivot` (t11)** — a flip-flop, and the t9/t11 target is an
   Elemental comp whose core card (Unbound Tempest) is not in the 36.6.1
   pool, on a board that was already a demon self-damage board the DB
   itself models.
2. **The t9 "stabilize" premise was stale by a round.** t9 advice: *"2. LEVEL
   next turn (lost 3 straight fights — stabilize first; your 158 vs their ~91
   [live: ~101])"*. Hero HP per phase (coach's own read): 30 at t6, **30 at
   t7**, **28 at t8**, **21 at t9** — two HP-losing fights before t9 (t7 −2,
   t8 −7) — and **the t9 fight itself was a WIN** (HP 21 → 21). The advice
   told the player to stop and stabilize going into the fight he then won.

**The decisive fight (t11) — the forecast was wrong, and not only about
keywords.** The player was at **6 HP** entering t11 (HP 30 → 28 → 21 → 21 →
6 → dead). Live reconstruction: *"ahead on paper — 276 vs ~199, seen 1 round
ago · they haven't taken damage in 11 rounds"*, with *"4. LEVEL next turn
(too fragile to level first; your 276 vs their ~199)"*. The player levelled to
tier 5 anyway, then lost and died.

The opponent's board (fight's own ATTACK blocks + the staged run they belong
to; opponent hero Shudderwock) was seven minions: **Humon'gozz** (BG32_341,
**DIVINE_SHIELD**), Fetid Corroder (BG36_112), Vicious Mindslasher ×2
(BG36_108), golden Brain Rotter (BG36_099_G), Nightmare Corroder (BG36_115),
Parasitic Fleshling (BG36_114). Their end-of-combat stat writes — the game's
own teardown values, which is what they fought with — were:

```
Humon'gozz            ATK 104 / HEALTH 122   (+ DIVINE_SHIELD 1)
Fetid Corroder        ATK  87 / HEALTH 120
Vicious Mindslasher   ATK 108 / HEALTH 192
Vicious Mindslasher   ATK  79 / HEALTH 150
                      --------------------------
                      962 raw stats on four of the seven
```

Against the coach's **"their ~199"** for the whole board, and our 276. Result:
`PLAYSTATE Player#1234 LOSING → LOST`, opponent `WON`; hero DAMAGE 24 → 39;
**placement 5**. Only two of our minions ever attacked (Turquoise Skitterer,
Imp-lusionist); the opponent lost nothing.

**Is this the 09-19 forecast bug?** Partly, and it is the smaller half. The
divine-shield term is real: Humon'gozz carried `DIVINE_SHIELD 1` on the staged
entity and the fight logs its write to `DIVINE_SHIELD 0` at line 190491 — a
whole swing eaten for free, exactly the 09-19 mechanism. But the dominant
error is the **anchor**, not the keyword pricing: `combat_forecast`'s own
docstring (value.py:2233) admits the keyword gap, and here the coach was not
even quoting the right board — "their ~199" was the median of the last three
boards *we had fought* (`lobby_opp`, live_coach.py:1456), against an opponent
that had not taken damage in 11 rounds and brought ~962 stats on four minions.
The divine-shield/raw-stat mispricing was a ~1.5x error on top of a ~5x error.
**Reopening the 09-16/09-19 pricing fix is still correct; it would not have
saved this fight.**

## 4. Game 2 — Marin the Manager, 6th (died t12, tier 6, 12 buy phases)

**The player's engine.** Aberration, from t7: Brain Rotter (BG36_099),
Vicious Mindslasher (BG36_108), Parasitic Fleshling (BG36_114), N'raqi Sapper
(BG36_103), Mindbending Recruiter (BG36_312), N'raqi Frostcaller (BG36_300),
Faceless Converter (BG36_318), The Shadow of Doubt (BG36_109) — every one of
them nameless to the coach (§2).

**Where the coach was right, and the player declined.** Four legitimate
declines, all of them off-build cards the DB could name:
t8 *"2. LEVEL next turn (lost 2 straight fights — stabilize first; your 48 vs
their ~51)"* with top buy **Plaguerunner** → "passed (coach pick:
Plaguerunner)"; t9 top buy **Locked-up Mutineer** → passed; t11 top buy
**Spark Snapper** → passed; t1 pick **Alliance Flag** → passed. Staying on
Aberration was right in principle — the same line wins game 3.

**Where the coach was wrong: it never had a direction at all.**
`target_comp` is **empty for all 12 buy phases** (against game 1's wrong-but-
present Elemental commit). The board was 100% a tribe the DB has no row for,
so the coach had neither a comp to commit to nor a comp to pivot away from —
its only buy advice was generic off-build filler ("surviving until we can
commit", "growth engine").

**Death traced backwards.** HP per phase: 30 through t7 → **24** (t8) → 24
(t9) → 24 (t10) → **16** (t11) → **5** (t12) → dead. The two fights that put
him in the ground were both called too cheap in live order:

- **t10**: *"favored — 195 vs ~106, seen 1 round ago"* → lost, **−8 HP**. The
  opponent that fought us (ATTACK blocks) was a full Aberration mirror — Brain
  Rotter ×3, De-volition-ist, Underrot Spawn, Fetid Corroder, hero King Mukla
  — with a live Brain Rotter at 16/34 and Fetid Corroder at 16/3 peak.
- **t11**: *"close fight — 150 vs ~141, seen 1 round ago"* → lost, **−11 HP**
  (16 → 5). The opponent's golden Vicious Mindslasher (BG36_108_G) peaked at
  **115/304** in that fight; the coach's anchor for their whole board was 141.

So the t12 **eliminating fight** (opponent Mavrik11, hero Kael'thas
Sunstrider) was entered at 5 HP, where any loss is fatal. The coach was
actually right about it in live order — *"behind — 346 vs ~872, seen 1 round
ago; don't take this fight"* — but the harness-order text for that same phase
is *"ahead on paper — 346 vs ~163"*; only the live-order reconstruction shows
the warning. **Implicated earlier line: the t10 "favored" and t11 "close
fight" calls, which cost 19 HP between them and bought no stabilizing advice.**
No coach line is implicated in the t12 board itself — the mirror simply had
goldens (BG36_108_G 115/304) and our golden Faceless Converter
(BG36_318_G, 494/498 in that fight) could not solo it.

## 5. Game 3 — Ambassador Faelin, 1st: the Aberration win the coach called a Beast game

**The player's engine, from the log.** Twenty buy phases, tier 6 by t15, 9 HP
from t11 to the end. Final observed board (the board is the coach's own state
read, so the ids are what the coach printed; the names are resolved from the
log's own `entityName=` brackets):

```
BG36_318  Faceless Converter   164/151  DEATHRATTLE, TAUNT
BG36_318  Faceless Converter    62/63   DEATHRATTLE
BG36_113  Drifting Sacrifice   118/114  DEATHRATTLE, REBORN, TAUNT
BG36_103  N'raqi Sapper         82/79   BATTLECRY, DEATHRATTLE, TAUNT
BG36_320  Mysterious K'Thir     32/32
BG25_354  Titus Rivendare       72/78   (tribe All; the coach's own
                                        beasts-summons entry calls him a
                                        deathrattle doubler)
```

Every Aberration piece grew ~20x over the game (Faceless Converter 8/8 at t9 →
164/151 at t20; Drifting Sacrifice 3/2 → 118/114) — a deathrattle-scaling
board doubling off Titus Rivendare, with Taunt/Reborn carrying the mid-game.
The tribe is confirmed from the log-mined 36.6.1 roster, not assumed.

**The coach never once named it.** `target_comp` is empty t1–t15 and then
**`Beasts - Tasty Lobstah / committing` for t16, t17, t18, t19 and t20** —
the coach committed the player to a Beast comp in the last five buy phases of
an all-Aberration board, and the player declined every Beast pick and won.

The decline ledger for the winning game, exactly:

- **0 of 20 phases ended "TAKEN"** — not one of the coach's ranked buys was
  bought, in the game the session won.
- **10 of 20 phases ended "buy match: passed"** with the coach's top buy being
  an off-build card: t3 Forest Rover, t5 Patient Scout, t7 **Tasty Lobster**
  ("scaling combat engine"), t10 Razorfen Geomancer, t13 Mind Muck, t14 Them
  Apples, t15 **Time Management** ("tempo"), t16 Forest Rover, t17 **Turquoise
  Skitterer** ("growth engine"), t19 Turquoise Skitterer.
- What the player bought instead, every time, was Aberration: Drifting
  Sacrifice + Abyssal Envoy at t10, Faceless Converter (BG36_318) at t13 and
  t16, Faceless Operative (BG36_308) + Energizing Chamber at t14, Unwilling
  Slacker + N'raqi Sapper + **Titus Rivendare** at t15, Brain Rotter +
  Mindbending Recruiter at t19.
- The t20 line closes the loop: *"5. roll — hunting Tasty Lobster, Headhunter
  Gryphon (Them Apples is off-build)"* — telling an Aberration board that a
  card is off-build while hunting two Beasts.

**Where the coach was right, and followed.** This is the honest bright spot,
and it is the hand plan, not the comp:

- t1 *"pass — Ambassador Faelin skips turn 1 (hero power)"* → "pass — as
  advised" (the one phase of the 20 whose match line is "as advised").
  Hero-accurate: Faelin's hero power is the skip.
- The spell/cast ordering was largely followed: t10 *"1. Cast Time
  Management"* → played; t13 *"1. Cast Staff of Enrichment"* → played (×2);
  t14 *"1. Cast Forest's Bounty"* → played; t15 *"1. Cast Defender's Rites"* →
  played; t19 *"1. Cast Forest's Bounty"* → played Forest's Bounty; t20
  *"3. Cast Repair Job"* → played. The *"Hold X (needs <N>g to cast — no gold
  for it)"* branch was correct every time it fired.
- The level curve was right where the player took it: t5 *"1. LEVEL to tier
  3"* → levelled; t7 *"2. LEVEL to tier 4 (you're strong — convert it into a
  tier)"* → levelled.

**Where the coach was wrong — the LEVEL gate, in the opposite direction from
the 09-19 review.** The "too fragile to level first" Q0 gate fired on the
turns that decided the game and the player overrode it twice, correctly:

- t11 (9 HP): *"5. LEVEL next turn (too fragile to level first; your 200 vs
  their ~163 [live: ~201]) — 1 short after the buy; roll meanwhile"* → the
  player levelled to tier 5 **that turn**, and never took damage again.
- t13: *"6. LEVEL next turn (too fragile to level first; your 299 vs their
  ~248)"* → the player levelled to tier 6 at t14, again against the gate.

Two recent reviews found that *declining* a LEVEL line was the winning move;
here the winning move was declining the **anti**-level line. Same rule, other
side: at 9 HP with a scaling board, one tier of tempo is worth more than the
stabilize hold.

**Where the coach was wrong — the endgame forecasts inverted.** From t14 the
live-order forecast turned pessimistic against the *lobby median of fights the
player was winning*, and the player won all of them:

- t14 (9 HP): *"behind — 360 vs ~548, seen 1 round ago; don't take this
  fight"* → player won the fight, HP unchanged.
- t15: *"behind — 473 vs ~1028 … don't take this fight"* → won, unchanged.
- t16: *"behind — 668 vs ~929 … don't take this fight"* → won, unchanged.
- t17: *"behind — 796 vs ~1066 … don't take this fight"* → won, unchanged.
- t19: *"behind — 829 vs ~1702, seen 1 round ago; don't take this fight"* →
  won (opponent License2Phil `LOSING` → `PLAYING`), unchanged.
- t20: *"behind — 1047 vs 3316, seen 2 rounds ago; don't take this fight"* →
  **won the game.**

Six consecutive "don't take this fight" calls in fights the player won is the
mirror image of §3/§4: same anchor, opposite sign. In games 1–2 the `lobby_opp`
median under-read the opponent; in game 3's endgame it over-read it (it is a
median over boards *we* fought, and this player's Aberration board was
out-scaling them). Either way the anchor is the problem, not the ratio.

**The decisive fight (t20).** Opponent <opponent>, an Aberration mirror. Our
attackers: Faceless Converter ×2, Mysterious K'Thir, Harbinger Aph'lass
(BGFYM_005_G), Ambassador Faelin (hero). Theirs: De-volition-ist ×2, Nightmare
Corroder, Mysterious K'Thir, Mindbender Ghur'sha, N'raqi Sapper. Log outcome:
`<opponent> LOSING → LOST`, `Player#1234 WON` — placement **1**, at 9 HP,
after ten consecutive fights without taking damage (HP 9 from t11 through t20).

## 6. Action items

1. **P1 — fix `replay_review`'s feed order before any further review of this
   log.** `_advise_point` must let `_ensure_meta()`/`_resolve_boards()` run
   during the feed (or call `analyze()` periodically), exactly as `live.py`
   does. Until then every scout/forecast string the tool prints for this
   session is wrong, and games 2 and 3 flip sign because of it (§1, table).
   Also drop or fix `analysis["next_opponent"]` — it is a class default that
   `analyze()` never writes, so it reads `None` even when the pairing resolved.
2. **P1 — the forecast anchor (§3, §4, §5).** One root cause, three symptoms:
   `lobby_opp` (median of the last ≤3 boards *we* fought) under-reads opponents
   by ~5x in game 1's t11 (199 vs ~962 on four minions) and over-reads by the
   same mechanism at the end of game 3 (six "don't take this fight" calls in
   fights won). The 09-16/09-19 direction still stands and would still help —
   price the opponent's Divine Shield/Reborn from the staged entities'
   `DIVINE_SHIELD`/`REBORN` tag writes (verified present this session on
   Humon'gozz) — but it is a ~1.5x term on a ~5x error. The anchor itself needs
   a freshness/attribution rule: the announced opponent's board, or an explicit
   "we haven't seen this player" output, instead of a silent median.
3. **P2 — the 5/5 ban detector did not resolve in any of 11 + 12 + 20 buy
   phases** (`_bans_ready False`, `allowed None` at the end of every game).
   The README promises the ban list narrows by ~t3–t5. Either the pool
   estimator's `tribes_seen=4` is too small a sample for this session's lobbies
   or `_refresh_bans` is gated on something that never fired; either way the
   strip was empty all evening.
4. **P2 — day-one patch behaviour, recorded, not blamed.** With no Aberration
   row in `minions.json`/`comps.json`: raw `BG36_*` ids in advice and on board
   tiles in 9 phases, no comp direction at all for 12 straight phases (game 2),
   a Beast comp committed over an Aberration board for the last 5 phases of a
   won game (game 3), and 2 Naga comps plus `Unbound Tempest`/`Kelp Keeper`
   still offered from a pool that no longer contains them (§2). The action is
   the patch pipeline (`patch_notes.py` + pool re-mine), plus one product
   question: when a tribe is unseen in the DB, the coach should say *"a tribe I
   have no data for is in play"* rather than silently advice off-build filler.
5. **P3 (coachable rule the game states, no code):** game 3 is the counter-case
   to the 09-19 §3 finding. Declining *"you're strong — convert it into a
   tier"* won that game; declining *"too fragile to level first"* won this one.
   The distinguishing variable is the same in both — whether the board is
   scaling — and neither review's rule survives without it.
