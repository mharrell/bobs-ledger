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

## 5. Follow-up the same day: the three DB gaps above, closed

Item 3 of §3 named three missing tavern spells. Working through them showed the
gap was never really about the spells:

- **`BG35_910` Conflagration** (tier 4, cost 2) and **`BG35_911` Arcane
  Absorption** (tier 4, cost 1) are now in `meta/tavern_spells.json` with curated
  reads in `spell_effects.json` and art in the cache. Both are real tavern spells
  the client data carries (`spellSchool TAVERN`, `techLevel 4`) that the patch
  notes never listed — the change list's three new spells are the discard batch
  (`BG36_301t`/`303`/`371`), all long since in the DB. They arrive in hand
  **generated**, not bought: the log shows Arcane Absorption spawned by Leyline
  Surfacer (`BG35_881`) via `SUB_SPELL_START`, and Conflagration created in
  SETASIDE and cast for free. That is why `isBattlegroundsPoolSpell` is false for
  both — and why the flag is not a usable filter (it is also false for Seafood
  Stew, a *returning* spell that is in the pool).
- **`BG31_893` Gem Day** is recorded in `meta/patch_gaps.json`
  (`seen_not_carried`) rather than added: no tier exists in the client data, and
  in all 1580 log lines naming it, across 5 sessions, it is created in
  `zone=SETASIDE` for a non-friendly player and never reaches a hand or a shop.
  `logquery` now consults that registry, so the pre-flight stops re-reporting an
  answered question.
- The pre-flight itself was also lying by omission: `BG36_330_Gt`/`_Gt2` (a
  golden triple's tokens, declared `CARDTYPE=SPELL` by the game) were reported as
  unknown cards while only a bare `_G` suffix was being stripped. Fixed, and the
  newest game's pre-flight is now **empty** — which is what a clean game should
  look like.

The same sweep found and fixed a much larger gap of the same shape: **13 trinkets
that appeared in the last six sessions were absent from `meta/trinkets.json`**,
including the seven "unsourceable" discard trinkets §2.2 of
`discard_mechanic.md` listed with `—` ids. They were never unsourceable — the log
prints `entityName=Evil Experiment ... cardId=BG36_MagicItem_416` on the same
line, and the coverage test only looked at *offered* trinkets (a choice list),
not at granted ones. Eleven rows and their curated reads were added
(`404`, `416`, `430`, `602`, `417t`, `914t`, `988t`, `712`, `732`, `754`, `924`,
`204`, `402`, `408`), the offered-only test now also checks every trinket-shaped
id seen in a log, and the one genuinely unsourced name (**Writhing Tentacles**)
fails that test the day it is offered, so it will not be missed again.

Two more finds from the same pass, both pinned by id now:
**C'Thun is `BGFYM_000`** (the `patch_gaps.json` entry claimed no id existed
anywhere on this machine — the id was in 1913 log lines; only the
cache/name-based search could not see it) and **Hungering Abomination
`BG25_014`** was missing from the minion DB altogether, which `extend_pool.py`
found and healed after that tool was corrected to write `cost: 3` (the flat
minion price) instead of hearthstonejson's mana cost `0`.

## 6. The Aberration comp: mined, promoted, and what it moved

Item 1 of §3 ("still no Aberration comp") is now closed in the only honest way
available — the source has nothing, so we measured our own boards.

**Scale of the hole first.** Across the 12 games in the local corpus, **4 ended
on an Aberration-dominant final board** (`comp_miner.scan()`: Aberration 4, Demon
3, Quilboar 2, Elemental 1, Beast 1, Pirate 1), and counting the "no target comp"
placeholders in the cached reviews — `surviving until we can commit`,
`no comp direction yet`, `no reroll target` — they run **36–60% of the coach's
lines in a typical game**. Those games are also *structurally unmeasurable*: a
player cannot follow a direction that does not exist, which is why a blended
adherence figure was misleading.

**What the corpus actually supports** (n=4, top4=2, floor 3): core **Faceless
Converter** (3/4, avg place 2.67) and **N'raqi Sapper** (3/4, avg 4.67), with
Titus Rivendare, Mysterious K'Thir, The Shadow of Doubt, Nightmare Corroder,
Parasitic Fleshling and Balinda Stonehearth at 2/4. That reads as a **Deity-fuel
package** — Converter and Sapper both pay the Deity on Deathrattle (Sapper hands
over Energizing Chambers, +7/+7 each, twice if discarded), Titus doubles those
triggers, and K'Thir / Shadow of Doubt / Fleshling are the discard and hand-add
payoffs — which is what the promoted entry says, in its own words, rather than a
marketing name.

Promoted as **`aberrations-deity-feed`** ("Aberrations - Deity Feed"), marked
`provisional` with its evidence attached, second class in every ranking path,
labelled everywhere it can reach the player (see `DESIGN.md` §"Provisional
comps").

**Measured effect on the win it was mined from** (09-23 game 2, re-run with
`review_kit --refresh`): buy-plan **taken 5/16 (31%) → 7/16 (44%)**, no-plan
phases **5 → 4**. The plan line that changed is exactly the one this feature
exists for:

```
6. no reroll target — Aberrations - Deity Feed (provisional — 4 of our games)
   is the only package for this tribe; hunt its pieces · roll the leftover anyway
```

One game is not evidence of better advice; it is evidence that the placeholder
was replaced by a labelled direction, which is the precondition for measuring
these games at all.


