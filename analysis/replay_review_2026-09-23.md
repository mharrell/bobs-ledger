# Replay review — 2026-09-23 morning (A. F. Kay 7th, Heistbaron Togwaggle **1st**)

Session `Hearthstone_2026_09_23`, 2 games, reviewed with the new
toolkit (`review_kit.py` skeleton + `--show`, `logquery.py`, `doctor.py`) rather
than by hand — see the test-drive notes at the end for what that exposed.

| # | hero | place | phases | taken | passed | n/a |
|---|---|---|---|---|---|---|
| 1 | A. F. Kay | **7** | 12 | 1/10 (10%) | 2 | 5 |
| 2 | Heistbaron Togwaggle | **1** | 18 | 5/16 (31%) | 6 | 5 |

The adherence columns are low in **both** games, including the win — the same
pattern as 09-22: you are playing a build the coach does not have, and doing it
successfully.

## 1. The win: a golden Aberration stat board, not the Beast package

Final board at t18, from the log: Faceless Converter 26/26 **and 149/153** (one
golden), Nightmare Corroder 159/155 (golden), Mysterious K'Thir 254/255,
Titus Rivendare 139/146, Balinda Stonehearth 60/60. At t13 it was already three
goldens: Faceless Converter 44/48, Nightmare Corroder 48/42, Unwilling Slacker
47/45, plus De-volition-ist 34/38, Mindbender Ghur'sha 9/15, Mysterious K'Thir
50/50 and Titus.

**The coach never once named the build.** Over the whole game it pushed a Beast
package — `Buy Banana Slamma (surviving until we can commit)` at t10 and t13,
then `no hunt — Tasty Lobster, Headhunter Gryphon`, and `roll — hunting Tasty
Lobster, Headhunter Gryphon (Weapons Forge is off-build)` at t18, delivered to an
all-Aberration board. It also labelled the direction "surviving until we can
commit" while the board was already the strongest thing in the lobby.

**You declined all six of the win's mismatches and won anyway.** What actually
built the board was heavy churn plus tier-6 access: t10 sold five minions,
levelled, rolled 5×; t13 bought five (Eyes of the Earth Mother, De-volition-ist,
Lost Staff of Hamuul, Mysterious K'Thir, Mindbender Ghur'sha) and sold Balinda;
t18 rolled 9×.

Worth knowing for the next Aberration game: **you had the two discard outlets and
sold both at t10** (Brain Rotter, Abyssal Envoy). The discard engine's own
numbers on your t13 board say that was fine — with no outlets the engine still
banked **+24/+24 a turn from Mysterious K'Thir's own end-of-turn discard**
(`fuel=42`), which is the piece that mattered, and Mysterious K'Thir finished at
254/255.

## 2. The loss: churn without a direction

A. F. Kay, 12 phases, 7th. The level gate behaved (t1 correctly passed —
`pass — A. F. Kay skips turn 1 (hero power)`, the fix landed yesterday showing up
live), and armor absorbed the early game (10 → 6 → 0 by t8).

What the phase table shows is a board rebuilt every turn with no comp committed:

- t10: `Play Holy Vanguard · Play Wandering Willbreaker (board is full — sell to
  make room) · Buy Shiny Ring (tempo) · sell Zoatroid`. Actual: bought Abyssal
  Envoy, **sold six** (two Zoatroids, BGFYM_002t ×2, Joyous, Brain Rotter),
  levelled, replayed three.
- t12: `Cast Energizing Chamber · Play Nightmare Corroder · Play Fetid Corroder ·
  LEVEL to tier 6`. Actual: **sold six**, levelled, replayed three.

Five of the ten phases had no buy step at all in the plan (`n/a`), which is the
comp-blindness again: without a target, the plan degrades into "play what is in
hand" and the coach's only repeatable advice is about board space.

## 3. Coach bugs and gaps this review found

1. **Still no Aberration comp** (`meta/comps.json`). This is now three sessions
   running where the winning build was invisible to the coach. The engine work
   lets it *value* the pieces; it still has no comp to aim at, so `comp_target`
   falls back to Beasts.
2. **`logquery.py stats` could not read the loss's death curve.** For A. F. Kay
   the hero's HP sits at 30 for the whole game while armor drains — so the tool
   reports damage-absorbed-by-armor and nothing about the actual deaths. The fix
   is to use `board_state`'s parser (done for the base series) and to check what
   spelling the *lethal* writes take; until then treat the `hp` column as base
   health, not current health. Flagged rather than papered over.
3. **Three real tavern spells are missing from `meta/tavern_spells.json`**, found
   by the pre-flight across two sessions: `BG35_910` **Conflagration** (tier 4,
   cost 2, "+4/+4, improved by each Elemental you played this turn"),
   `BG35_911` **Arcane Absorption** (tier 4, cost 1, "give a friendly Elemental
   half the stats of the highest-Health minion in the Tavern") and `BG31_893`
   **Gem Day** (cost 0, Choose One: Blood Gems give +1 Attack or +1 Health this
   game — **no tier** in the cache, which is why it was not added). Two of the
   three have a tier and could be added immediately.

## 4. Test-drive notes on the new tools

**Worked well:** `doctor.py` opened the session in 9 lines and its newest-log
check named the hero and the two unknown ids before anything else ran.
`review_kit.py` gave a 10-line entry point plus the turns worth opening, and the
warm cache made re-reads instant. `logquery games` found all three missing spells
— a class of gap neither `check_patch_db.py` (change-list only) nor the trinket
test could see.

**Bugs the drive found, all fixed:**

| bug | cause |
|---|---|
| `stats` returned `hp: None` for every turn | my own regex; a hero's base health comes from its FULL_ENTITY block, where tag lines carry **no** card id. Now uses `board_state.hero_stat_log` |
| `board` returned 0 rows | `GameState.board` is a **method**, needs the **friendly player**, and returns a **(friendly, opponents) tuple** — I got all three wrong |
| no way to open the turns the skeleton named | added `review_kit --show 5,13` |
| `--summary` divided by the wrong denominator | `phases` counts only rows that rendered a coach line; now reports `phases` (real count) and `taken/N` (verdicts) separately |

That is five API/assumption bugs across two tools, every one caught within a
minute of running them on real data — which is the argument for the test drive
rather than more unit tests.
