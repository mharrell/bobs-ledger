# Advisory-vs-outcome audit — first corpus-loop run

2026-09-20 · tool: `outcome_audit.py` · scope: 10 local session games,
97 advised buy phases (1 game yielded no phases — reconnect shape)

## Method

One incremental replay of the CURRENT coach per game (deliberately
auditing today's rules, unlike decision_log's version-pinned advice);
per advised buy phase: the structured plan (`top_move_steps`), the
player's actual actions that phase (`parse_actions`), and the outcome —
effective-HP (health+armor, the coach's own true-HP series) delta across
the FOLLOWING combat, taken as the delta to the next advised phase.
Buy-phase armor gains are accepted v1 noise; the last phase has no
following fight.

**Caveat (sham-control discipline):** this is observational. Players
follow advice in easy spots and ignore it in scary ones, so
followed-vs-ignored means are NOT causal. The loop's job is ranking
SUSPECT RULES for review, and — at scale — quantifying whether the
coach's marginal advice correlates with better placements.

## Results (n=97 phases, 9 games)

| class | n | mean ΔHP next fight | median |
|---|---|---|---|
| buy-followed | 19 | −1.7 | 0.0 |
| buy-ignored | 5 | −3.4 | −5.0 |
| **level-followed** | **36** | **−4.6** | **−4.0** |
| level-ignored | 3 | −2.0 | −3.0 |

Buy advice looks healthy (following it bleeds less than ignoring it —
within noise, but the right sign). **The level ladder is the suspect:**
followed levels preceded a mean −4.6 HP loss, and the worst rows are the
classic mid-curve stall:

```
g2 t11 tier 4 at 30 HP -> -15   (A.F. Kay, placed 3)
g1 t11 tier 4 at 22 HP -> -14   (Marin,  placed 4 — died to that fight's followup)
g2 t10 tier 4 at 29 HP -> -10   (Galewing, placed 5)
g2 t8  tier 3 at 25 HP -> -10   (Tavish, placed 7 — the 'levels 4-5-6 chasing pieces' game)
g1 t7  tier 3 at 32 HP -> -10   (Guff, placed 1 — and still WON)
```

Honest read: this does NOT say leveling is wrong — Guff took a −10 on a
level at t7 and finished 1st; curving is how the game is won. It says
the coach currently advises levels with no stated PRICE, and the player
can't tell a free curve level from a −14 stall at 22 HP (the t16
"LEVEL to tier 6 — 1 left after" death and the 09-19 "you're strong —
convert it into a tier" declines were the same disagreement, from the
other side). The candidate improvement: price the level in the plan
("LEVEL to tier 5 — you'll likely take ~8 next fight; board is 2 pieces
short") and let the stall-risk gates (never-won, DYING, loss streak)
speak with that number. Design first; the harness now measures whether
it works.

## Harness validation

The tool independently rediscovers the two known deaths from the replay
reviews (Marin t11 22 HP −14 → died 4th; Tavish t8 25 HP −10 → the 7th)
— the join is sane.

## Limitations / next steps

1. **Scale**: 9 games is a vibe, not a verdict. The telemetry repo
   (mharrell/hearth-telemetry) holds the sessions this tool can consume
   unchanged (same Power.log shapes) — clone + bulk-run for real n.
2. **Beyond next-fight**: level advice pays back over 2-3 turns, not 1 —
   add game-level placement correlation (level-adherence vs placement)
   once n is meaningful.
3. **A 09-18 10:21 session (5 games) didn't parse rows** — check whether
   its logs rotated; the harness skipped nothing silently (it never ran:
   the file list had changed).
4. No unit test yet — the harness is validated by rediscoving the
   reviewed deaths; a fixture-based smoke test can come with the scale-up.
