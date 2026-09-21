# Design candidate: price the LEVEL in the plan

2026-09-20 · status: DRAFT for Mike's sign-off · author: the corpus loop
(`outcome_audit.py`, `analysis/advisory_outcomes_2026-09-20.md`)

## Problem

The plan says "LEVEL to tier 5 (standard curve)" with no stated cost.
The corpus loop's first run: followed levels preceded a mean −4.6 HP
loss (n=36); the worst rows are mid-curve stalls of −9..−15 at t5-t11.
The player cannot tell a free curve level from a −14 stall at 22 HP —
and the review history keeps tripping on exactly this (t16 LEVEL at 8 HP
died; the 09-19 declines of "you're strong — convert it into a tier"
were correct AND looked like disobedience; Tavish's 4-5-6 chase to 7th).

The goal is NOT to level less. Guff took −10 on a t7 level and won;
Silas Darkmoon followed 3/3 levels, bled −5.3/fight, placed 1st. The
goal is that every level advice carries its price, so the ladder's
expensive rungs are visible BEFORE the fight, not in the replay review.

## Proposal (v1)

When a LEVEL step leads the plan (or trails it), append a **price
clause** computed from signals the analysis already carries:

1. **Lobby gap (primary):** our board stats vs the turn-matched lobby
   (`lobby_opp` / `baseline_opp` — the forecast's anchors). A level
   spends one buy turn on the board; being behind the lobby's boards
   makes that turn expensive:
   - ahead of lobby: "cheap — you're ahead on boards"
   - within ±25%: no clause (the normal curve needs no warning)
   - behind by ≥25%: "prices high — you're behind the lobby's boards
     (~40 vs ~90) and the fight after a level is the one you skip"
2. **Comp distance (secondary):** a committing comp 2+ pieces short adds
   "the comp is N pieces short — leveling halves your odds of them"
   (this is the Q1/stay machinery's knowledge, said as a price instead
   of only as a stay veto).
3. **Recent damage (calibration):** state the last fight's damage as the
   floor ("took 8 last fight; the lobby scales up from here") when ≥5.

v1 informs only — it never demotes the level. The existing hard gates
(DYING, never-won, loss-streak) stay the only things that defer.

## What would change, concretely

- `top_move`: the LEVEL lead/trail lines gain the clause (one line, no
  new steps). The comps panel / Build column are untouched.
- No gate changes. A "prices high" level is still advice 1 — v2 can ask
  whether it should sometimes yield to the best buy (that is a behavior
  change and gets its own round-trip).

## Validation

Re-run `outcome_audit.py` after a few sessions with the clause live:
- the followed-level mean ΔHP should move toward the ignored mean;
- placements should NOT drop (level adherence vs placement is now in
  the report — Silas's 1st on 3/3 followed levels is the counterexample
  guard);
- eyeball the worst followed-level rows: the clause should be present on
  every one that was foreseeable.

## Open questions for Mike

1. Always show the price (even "cheap"), or only when prices high /
   comp is short?
2. v1 informs only — right call? Or should a "prices high" level ever
   yield to the shop's best buy (a behavior change, v2)?
3. Wording: "prices high" / "costs ~N next fight" / something else?
