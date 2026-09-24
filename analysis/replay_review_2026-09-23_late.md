# Replay review — 2026-09-23 late (Galakrond 4th, Dinotamer Brann 3rd)

Session `Hearthstone_2026_09_23`, 2 games. BattleTag redacted. Live coach
ran the post-discard build (provisional Aberration comp, swap arbiter, fragility
band, discard loop).

## 1. Coach-vs-player summary

| # | hero | place | phases | taken | passed | n/a |
|---|---|---|---|---|---|---|
| 1 | Galakrond | 4 | 14 | 3/14 (21%) | 6 | 4 |
| 2 | Dinotamer Brann | 3 | 14 | 3/14 (21%) | 5 | 6 |

21% is the lowest of the corpus so far (the 09-23 win was 53%), and the two games
fail for **different** reasons — which is the useful part.

## 2. What the new work did

- **The Aberration provisional comp carried game 2 end to end**: target
  "Aberrations - Deity Feed" from t6 to t15 on a board that reached 7/7
  Aberrations. The player built exactly it (Faceless Converter, N'raqi Sapper,
  Mysterious K'Thir, Titus, Mindbender Ghur'sha).
- **The swap arbiter and its vetoes are now the plan's normal voice**:
  t10 *"roll instead — Snow Baller (9.7) isn't worth losing the Mindbending
  Recruiter"*, t12 *"Hold Drifting Sacrifice (hold — 5.3 vs the 20.7 Mindbending
  Recruiter it would cost)"*, t15 *"roll instead — Parasitic Fleshling (34.5)
  isn't worth losing the …"*.
- **The damage-memory gate fired** in game 1: t10 *"LEVEL next turn (bled 23 over
  the last 3 fights — buy stats first; your …)"*, and the DYING gate at t15
  (*"too fragile to level first; your 318 vs their ~616"*).
- **The discard loop did not appear** — the overlay had not been restarted with
  it (committed mid-session), so these games predate it. Nothing to score.

## 3. Findings, ranked

### 3.1 Game 1: the coach's build direction was wrong for most of the game (FIXED)

Traced per phase, the board was Aberration-majority from t6 (3 of 6) to t15 (3 of
5), and `comp_gap` said **"Aberration" in every one of those phases** — yet the
target comp flip-flopped:

| turn | board | tribes | target |
|---|---|---|---|
| 9 | 6 | Aberration 3 | Aberrations - Deity Feed |
| 10 | 6 | Aberration 4 | **Demons - Shop Buff** |
| 11 | 6 | Aberration 5 | Aberrations - Deity Feed |
| 12 | 6 | Aberration 4 | **Mechs - Deathrattle** |
| 14 | 6 | Aberration 4 | **Beasts - Tasty Lobstah** |
| 15 | 5 | Aberration 3 | **Beasts - Tasty Lobstah** |

So the plan hunted Tasty Lobster at a player who was building Aberrations — the
same shape as the morning's Faelin case, and no wonder adherence was 21%.

**Cause (mine, from the morning's own fix).** `comp_target` skips provisional
comps in the ≥2-hit commit path, so a *published* comp matching two incidental
cores on the board won by default, and the gap branch never got reached.

**Fixed**: the gap branch now runs *after* the recent-acquisition check but
*before* the committed return, and only yields to a published commit that is
being **actively built** (≥2 of its cores bought this turn):

```
Galakrond shape (4 Aberrations + an incidental Beast pair) -> Aberrations - Deity Feed
the same board, 2 Beast cores bought THIS TURN             -> Beasts - Tasty Lobstah   (pivot kept)
Beast-dominant board                                       -> Beasts - Tasty Lobstah   (unchanged)
no mined comp for the gap tribe                            -> Beasts - Tasty Lobstah   (old rule unchanged)
```

Tests pin all four in `tests/test_board_swap.py`.

### 3.2 …but the LIVE value still disagrees: `_sticky_target` holds the stale comp (OPEN)

Reproduction at t12 of that game, with the fix in place:

```
value.comp_target(a["board"], a["playable_comps"], recent_cards=a["recent_cards"])
    -> "Aberrations - Deity Feed"        (correct)
a["target_comp"]                          -> "Mechs - Deathrattle"   (what the player saw)
```

`playable_comps` in that analysis *does* contain `aberrations-deity-feed`, and
`comp_gap` says Aberration, so the pure function is right and something stateful
in `live_coach` is holding the old direction. The candidate is the sticky chain
(`self._sticky_target`, updated on **every** `analyze()` pass — and the review
harness re-advises many times per phase): t10 would have locked "Demons - Shop
Buff" while the ban filter was still fail-open, and each later pass then compared
against that.

**Next step (not this session)**: log `prev`, `new`, `prev_hits`, `new_hits` and
`_board_tribe_units` on the branch that returns `prev`, and check whether the
cross-tribe guard is counting the provisional comp's evidence at all. Until that
is settled, fix 3.1 is correct in the pure function and **not** yet visible live.

### 3.3 Game 2: the plan says "roll (hunt)" while the player buys the board

Five phases ended *"plan said roll (hunt) — player bought (…)"*, and the player's
buys were repeatedly the *right* ones: t13 bought **Faceless Converter, N'raqi
Sapper, Mysterious K'Thir** (the mined core and an addon) while the coach's pick
was "Brain Rotter (growth engine)".

The coach's own snapshot explains the pick and not the failure: at t13 its shop
held only Brain Rotter 3.4, Natural Blessing 1.5, Bilgewater Breakout 1.0,
Prodigious Tusker 0.7, Gem Rat −2.2, Blue Whelp −3.4 — junk. The player then
rolled 5× into the comp. So this is the **mid-turn capture gap again** (evening
review §3.1): the review sees the phase-start shop, the player saw five
generations of it. The coach very likely advised those buys live; nothing in this
harness can show it.

### 3.4 The arbiter's one-slot model against a churning player

Game 2's vetoes fired (t10, t12, t15) while the player sold 3–5 cards a turn and
bought 4–5. The arbiter assumes **one** outgoing card (the cheapest to lose) for
**one** incoming card; a player rebuilding their board pays for several buys with
several cuts. That is stage 1.5 of `board_swap.md`: evaluate a queue (N junk
slots → up to N buys, each against the next-worst cut) instead of a single swap.

### 3.5 One unresolved id

`BGFYM_002t` / `BGFYM_002t_G` = **"Aberrant Tentacle"** — a summoned token (the
Tentacle Zoatroid sells for, per the patch article's own text "get a 0/2 Tentacle
with Taunt"), with no card data in any local cache. It has no base card in the DB,
so the pre-flight reports it on every game that summons one. Treated like the
other token-in-a-minion-shape (`BG30_MagicItem_442t` Blood Golem) — see §5.

## 4. Gates

- Both games: 6 and 5 "passed" verdicts — the player churns and rolls far more
  than the plan's named single buy, so a binary taken/passed verdict understates
  the coach. Read the verdict column as "did the player do the plan's *first*
  action", not "was the plan wrong".
- No phase in either game advised something impossible (the two impossible-discard
  classes are gated now, and no activation advice appeared at all in these games).

## 5. What changed as a result of this review

| finding | action |
|---|---|
| direction flip-flop on a tribe-majority board (§3.1) | **fixed** — gap branch reordered, active-pivot guard, 4 tests |
| live value still holds a stale comp (§3.2) | **open** — reproduction recorded; needs the sticky inputs logged |
| junk-snapshot / post-roll buys (§3.3) | **open** — the capture work from the evening review |
| one-slot arbiter vs a churning player (§3.4) | **open** — stage 1.5 of `board_swap.md` |
| `BGFYM_002t` Aberrant Tentacle (§3.5) | recorded as a known token in `meta/patch_gaps.json` |
