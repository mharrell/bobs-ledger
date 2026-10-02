# Tempo mode, finished: bleed-aware ranking everywhere

**Status:** design candidate — no code yet (design-before-implementing,
per `analysis/engine_coaching.md`).
**Date:** 2026-10-02. **Evidence base:** outcome_audit 2026-09-25, the
2026-09-26 E.T.C. spiral, and the 2026-09-18 FRAGILE-band loss.

## The problem

The 09-25 outcome audit's first signal: turns where the player FOLLOWED
the coach's LEVEL advice bled −4.6 HP by the next fight vs −2.0 when they
ignored it — followed advice did *worse* than gut play. The E.T.C. game
that spawned `tempo_emergency` showed the same shape one level down: a
"growth engine" headlined the shop for three straight turns of a dying
board while the level clause said "buy stats first" — the shop ranking
never saw the bleed.

Root cause is now precise, not vague: **pace reaches gates and one
scorer, but not the whole scorer.** The coach computes a bleed number and
then spends it in a few places; the future-growth terms elsewhere still
price a turn-10 payout the same at 100 HP and at 15.

## What exists today (inventory)

| Piece | Where | What it does |
|---|---|---|
| `tempo_emergency(armor_hist, turn)` → 0 / 0.6 / 1.0 | value.py:739 | bleed = max(last hit, recent-3 sum, 4×streak); ≥12 full tempo, ≥8 half, else 0 |
| emergency in `minion_value` | value.py:837-845 | growth term ×(1−0.6·e); current stats get +W_STATS·e. Comp bonuses untouched |
| emergency in offer/discover ranking | value.py:1233, live_coach.py:1313-1319 | same shape, offers only |
| fragility bands (dying ≤12, fragile 13-16) | `fragility`, value.py:1803 | text + the flip ladder's DYING hard gate |
| LEVEL demotion | value.py:2552 | t≥3 and recent3 ≥ FRAGILE_BLEED(15) → "too fragile to level first" |
| stabilized read + mortality ladder | value.py:2125-2170 | "next buy should win a fight" vs "scaling is safe" |

## The remaining gap (what is still pace-blind)

1. **Spell ranking** — `_spell_score` has no emergency input.
   `W_SPELL_FUEL` / `W_DISCARD_FUEL` literally price *future* engine
   growth; in a bleed they should collapse, while one-shot board buffs
   (immediate power) deserve full or boosted credit — they are the
   "win a fight now" buys the mortality ladder asks for.
2. **Engine-sim and recipe terms in minion/offer scoring** —
   `W_ENGINE_SIM` (simulated growth), `W_RECIPE_FUEL`,
   `W_ENGINE_MULT` price future magnitudes and bypass the growth-term
   discount (only the `growth_potential` term sees `emergency`).
3. **Plan-level tie-breaks** — the audited −4.6 was a LEVEL decision;
   the t≥3 demotion exists, but plan assembly and roll-vs-level still
   have no general pace input when two plans score within noise.
4. **Validation** — nothing has ever measured tempo mode's effect.
   The audit flagged the problem; no harness run shows the flag fixed.

## Design

**Pace stays one number.** `tempo_emergency` remains the only source of
truth; every plan below is a new *consumer* of it, not a new signal.
Kill switch: `HEARTH_TEMPO=0` forces e=0 (byte-identical to today).

### Plan 1 — pace into spell scoring
`_spell_score(…, emergency=e)`:
- fuel bonuses (`W_SPELL_FUEL`, `W_DISCARD_FUEL`) × (1 − 0.6·e);
- immediate stat effects keep full credit — at e=1.0 a flat
  +X/+X-to-board spell is exactly the "buy stats first" line, so add
  `+0.3·e` per point of immediate board stats (mirrors the minion
  W_STATS boost);
- shop-buff spells (per `_is_shop_turn_buff`) stay demoted: a buff that
  dies with the shop is neither scaling nor a fight-winner unless a
  minion is bought with it (rule from 2026-09-08, unchanged).

### Plan 2 — pace into the future-magnitude terms
In `minion_value` / offer ranking: `W_ENGINE_SIM`, `W_RECIPE_FUEL`,
`W_ENGINE_MULT` terms × (1 − 0.6·e). Same discount curve as the growth
term — one mental model. Immediate terms (W_STATS, W_BUFFS, W_CORE)
untouched: a missing core is still the build, even while bleeding.

### Plan 3 — pace into plan tie-breaks
When the top two plans land within the existing noise band (the
`_plan_shape` epsilon), prefer the one with higher **immediate board
power delta** (same-shop terms only: stats + buffs + deployments), and
say so in the reason string ("bleeding — picks the body over the
engine"). LEVEL/reroll advice keeps its existing dedicated gates; this
covers everything else.

### Plan 4 — validation harness (the discipline part)
- Extend `outcome_audit.py` to bucket turns by emergency (0 / 0.6 / 1.0)
  and report followed-vs-ignored HP deltas per bucket.
- **Sham control:** replay the same corpus with `HEARTH_TEMPO=0`.
  Contract: e=0 turns are byte-identical advice (regression test);
  the control run reproduces today's numbers by construction.
- **Success:** in e≥0.6 turns, followed advice's HP delta improves
  toward the ignored baseline (−4.6 → ≥ −2.0-ish is the directional
  target, not a promise); steady-turn advice unchanged; no new
  sell-the-engine regressions (sell floors untouched by design).
- Rollout: replay harness first (`validate_advice.py` style), then live
  with `replay_review` on the next 3 sessions, then outcome_audit weekly.

## Explicitly unchanged
- DYING hard gate and FRAGILE text (they are the loudest voice and stay
  last-word).
- Combat-only gains stay non-persistent (2026-09-11 rule).
- Sell floors and comp glue protection (bleeding is not a license to
  dismantle the build).
- Lobby-pace anchors in roll-vs-level (already shipped, Plan 3 respects
  them).

## Out of scope (separate gaps, noted so they don't get lost)
- **Buddies season is unmodeled** in the meta DB — a meta-content gap,
  not a scoring one.
- Opponent-scaling forecasts (2026-09-16-evening finding) — belongs to
  the forecast workstream, though Plan 4's bucketed audit will also
  surface it if it's still live.
