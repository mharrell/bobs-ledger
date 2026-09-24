# Replay review — 2026-09-23 evening (Drest'agath, **1st**)

Session `Hearthstone_2026_09_23`, 1 game. Hero **Drest'agath**, placement
**1st**, 19 buy phases of which 15 rendered a coach line. Live coach ran the build
from this session (provisional Aberration comp, the swap arbiter, the fragility
band). BattleTag redacted.

## 1. Coach-vs-player summary

| # | hero | place | phases | taken | passed | n/a |
|---|---|---|---|---|---|---|
| 1 | Drest'agath | **1** | 15 | 8/15 (53%) | 2 | 5 |

**53% is the highest adherence measured in this corpus** (previous best 31–46%,
corpus mean ~46% of ranked buys). It is not evidence of better advice by itself —
but combined with §2 it is the first game where the coach had a real build to
aim at, and the player took it.

Phases with no plan (5) are the transition/death turns plus the two "buy match:
plan said level only" phases below, which are the interesting kind.

## 2. What the new work did in a live winning game

- **The provisional Aberration comp coached a real build, and the player followed
  it.** t10: *"3. Buy N'raqi Sapper (committing to Aberration…)"* — TAKEN.
  t12/t13/t15/t16/t18/t19 all carry *"no hunt — Faceless Converter (hasn't shown
  in the tavern)"*, i.e. the coach is hunting the mined core. This is the first
  game in the corpus where the winning build was not invisible to the coach.
- **The swap arbiter fired on every full-board phase and never blessed a losing
  trade.** t16 *"don't buy Banana Slamma — it would cost the Mindbender Ghur'sha
  (4.9 vs 90.1)"*, t18 *"…Mangled Bandit … (23.9 vs 248.8)"*, t19 *"…Drifting
  Sacrifice … (7.8 vs 379.1)"*, t15 *"…Patient Scout … (2.7 vs 49.9)"*. Without
  it, the plan would have named an off-build Beast card (Banana Slamma) as the
  buy on an Aberration board — the exact failure the 09-23 morning review caught.
- **Fragility never triggered** — Drest'agath was never in the 13–16 band — so
  this game neither tests nor contradicts it.

## 3. Findings, ranked

### 3.1 The review harness cannot see the mid-turn re-advice (measurement gap)

t15 is the game's turning point: the player held 1 Mindbender Ghur'sha on board
and rolled 3×, found a second, and played **BG36_097_G (golden)**. The coach's
line for t15, as captured, is the *phase-start* plan for a junk shop
(`Patient Scout 2.7 · Treasure Parrot −1.0 · Trench Fighter −2.4 · Sanguine
Refiner −2.7`).

The live coach re-advises on every shop change (the 2026-09-01 mid-turn loop), so
it very likely did advise the Ghur'sha buy after the roll — and **the review
harness cannot tell**: `_advise_at` returns the first stable shop of the phase,
and the review text stores one line per phase. Every adherence number in this
corpus inherits that blind spot, and "passed" verdicts may be plans the player
never saw.

*Fix direction:* capture each distinct plan the live loop emits per phase (a
fingerprint-tagged list) into the review text, so a phase shows the plan at each
decision point and adherence is scored against the advice the player actually
had. This is the same capture the in-overlay verdict toggle would give.

**Adding to that blind spot (2026-09-23, from the discard work below): the
reconstruction also cannot reproduce ACTIVATION advice.** `activations` ride the
live settled-shop state (`live_coach` line 1062), and driving a game with
`replay_review._advise_at` yields `activations == []` for every phase — including
the two phases in the cache that DID advise an activation (09-22 evening g3
*"Activate Brain Rotter (discard a card to give your deity +2/+2)"*, 09-23 morning
g1 *"Activate Mindbending Recruiter (discard a card to get a random aberration)"*).
So a fix to activation advice can be unit-tested but not re-measured against the
corpus until the capture exists. Worth pinning first: whatever fills
`_pending_activations` is not reached by the review harness's window.

### 3.2 A vetoed buy must become actionable advice

The t15/t16 shops scored 2.7 / 4.9 at the top, the plan named that card as the
buy, and the arbiter then vetoed it. The player was left with "don't buy X" and
nothing to do with the gold.

*Fixed in this review:* the rewrite now reads
`roll instead — Patient Scout (2.7) isn't worth losing the Mindbender Ghur'sha
(49.9)`.

### 3.3 Stage 1's currency is asymmetric, and this game shows the shape of it

The arbiter compares a **fresh card's** score against a **developed body's**
score. Late-game that is a mismatch: `minion_value` for a board minion includes
its accumulated stats, so the outgoing side reached **379.1** at t19 while every
shop card was under 8. The vetoes were correct in direction and trivially so —
of course a 379-stat body beats a fresh minion — which means stage 1's *take*
verdicts carry the real information and its late-game vetoes mostly restate "do
not trade your board for junk".

This is exactly what stages 2–3 in `analysis/board_swap.md` exist to fix: compare
what the incoming card *becomes* (simulated growth) and what the board *loses*
(combat strength now), rather than two different kinds of number.

### 3.4 Two ids rendered raw in the coach's own advice

`BG26_350` (Bassgill) and `BG_EX1_170` (Emperor Cobra) were missing from
`minions.json`, so the coach said both as raw ids.

*Fixed:* Bassgill via `extend_pool.py`; Emperor Cobra exposed a **tool bug** —
the tool's `BG<nn>_<num>` shape filter cannot see a BG **reprint** that keeps its
original set-coded id (`BG_EX1_170` is Blackrock Mountain). Widening the filter to
"the card cache says MINION with a techLevel" pulled in **15 rows of junk**
(summoned tokens like `BG28_603t` Beetle, buddies like
`TB_BaconShop_HERO_33_Buddy`, warp variants like `BG34_Giant_*`) — so the fix is a
narrow second family, `BG_<SET>_<num>`, with a test pinning both the reprint and
the junk it must not match.

### 3.5 The t1 filler is still there

t1: *"1. Buy Southsea Busker (surviving until we can commit)"* — the
no-comp-direction placeholder on turn 1, where no comp can exist yet. Honest but
useless; it is the same class of text as the 27 `surviving until we can commit`
lines measured earlier. A turn-1 plan should be about tempo and curve, not about
committing.

### 3.6 The trinket DB keeps falling behind the live game

This game's session produced two more trinkets absent from the DB
(`BG30_MagicItem_943` Surveyor Portrait, `BG32_MagicItem_301` Bassgill Portrait),
the third such round today (Reinvigorating Light and Weighted Gauntlet earlier,
The Eye of Sargeras before that). The log-coverage gates catch every one — that
part works — but the *fix* is a manual ritual each time.

*Fix direction:* a report-only `--gaps` mode over the trinket caches (the
`extend_pool` pattern: scan recent logs, name the missing ids with their cache
text, write nothing), so the list is one command and the curation is the only
human step. Both trinkets added here with curated reads and art.

## 4. Gates

- 19 phases; 5 with no rendered plan (transition/death turns), 8 taken, 2 passed.
- Four "plan said level only — player bought …" phases (t15/16/18/19): the buy
  section produced nothing while the player bought 2–5 cards. Two of those shops
  are junk (§3.2); t19's included **Faceless Converter**, the comp core the coach
  was hunting — the player found it and bought it. Whether the coach advised it at
  that moment is exactly what §3.1 says we cannot see.
- No coach advice was *wrong* in this game in a way the numbers can prove. The
  measurable failures are elsewhere: unnamed-slot phases (fixed this morning),
  the junk-shop buy (fixed here), and the harness blind spot (§3.1).

## 5. What changed as a result of this review

| finding | action |
|---|---|
| raw ids in advice (§3.4) | Bassgill + Emperor Cobra added; `extend_pool` reprint family + tests |
| vetoed buy left no action (§3.2) | the rewrite is now actionable roll advice + test |
| trinket DB behind the live game (§3.6) | Surveyor + Bassgill Portrait added with reads and art; a report-only gap scan is the recorded next step |
| harness blind to mid-turn re-advice (§3.1) | **not fixed** — recorded as the next measurement task |
| asymmetric currency (§3.3) | **not fixed** — stages 2–3 of `board_swap.md` |
| t1 filler (§3.5) | **not fixed** — small, needs a turn-1 curve plan |
