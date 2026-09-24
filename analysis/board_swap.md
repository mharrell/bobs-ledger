# Board swaps — naming the card you sell, and proving it is worth it

**Status: stage 1 IMPLEMENTED (2026-09-23).** Stages 2 (combat "now" term) and 3
(simulator "future" term) are designed below and not built. `value.slot_swaps`,
the guards, the plan wiring and `tests/test_board_swap.py` are the stage-1
deliverable.

### Stage-1 result, measured across all local sessions (44 full-board phases)

| | |
|---|---|
| full-board phases with a comparable incoming card | **17** |
| best candidate **take** (Δ ≥ 3) | 8 |
| best candidate **close** (0 ≤ Δ < 3) | 1 |
| best candidate **veto** (Δ < 0 — the card is not worth the slot) | **8** |
| plans that now **name** the trade with its numbers | 9 |
| invariant *"never advise a take with a negative delta"* | **holds** |

Roughly half of the phases where the coach wanted a card on a full board were
swaps the numbers do not support, and it used to advise them anyway. The veto
examples now read:

```
don't buy Boom-in-a-Box — it would cost the Imp-lusionist (6.5 vs 6.6)
don't buy Vicious Mindslasher — it would cost the N'raqi Frostcaller (11.4 vs 28.8)
Hold Drifting Sacrifice (hold — 5.3 vs the 5.6 Fetid Corroder it would cost)
Swap: play Parasitic Fleshling, sell Fetid Corroder (34.5 vs 5.6 — clearly better)
```

The 27 phases that stay silent are ones with nothing to compare (a spell buy
needs no slot; no sell candidate survived the guards) — silence there is the
honest answer, and the old unmatched "sell to make room" wording still stands for
the filler-only case.

---

## 1. The problem, measured

The player's report, verbatim:

> The coach will frequently say that a card should be played, and something else
> must be sold to make room for it. But it doesn't say *which* card, or state
> if/how the value of the new card will be greater than the one you'll need to
> sell to play it.

Measured over the 154 cached coach lines (4 sessions, 12 games):

| | count |
|---|---|
| phases with a **full board** (7 minions) | **37 / 154 (24%)** |
| ...that also told the player to play or buy | **34** |
| ...that mentioned a sell at all | 28 |
| ...that **named** the card to sell | 18 |
| ...that told the player to make room **without saying what to cut** | **16 / 34 (47%)** |

And the advice is not always value-positive. Taking every full-board phase from the
two newest sessions, pairing the plan's best incoming card (hand play or shop buy)
against the cheapest-to-sell board minion — both scored by `value.minion_value` —
12 of 12 phases had a live swap decision:

| verdict | count |
|---|---|
| incoming clearly better (Δ ≥ 3) | 8 |
| marginal (0 ≤ Δ < 3) | 2 |
| **incoming worth LESS than the card it displaces** | **2** |

The two negative ones are the same decision twice: `hand Faceless Converter`
(16.0) against a board minion scored **20.2** (Δ **−4.2**), both taken while the
player was in the FRAGILE band. The coach advised the swap; the numbers it
already computes say not to.

## 2. What already exists (the work is smaller than it looks)

This is not a missing simulator. Every ingredient is in the repo:

| piece | what it gives |
|---|---|
| `value.minion_value(minion, card, comp, hero_power, trinkets, board_scaling, dominant_tribe, engine_bonus)` | the **common currency**: one "keep score" for a board minion (stats × `W_STATS`, multiplier glue `W_MULT`, board engine `W_ENGINE`, combat-scaling terms, comp fit) |
| `value.sell_recommendation(...)` | a full **ascending** sell ranking: banned-tribe penalty (−2), comp-glue floor `W_SELL_FLOOR = 16` for cores/addons/multipliers/Spellcraft, engine growth attributed through the simulator (`_engine_growth_bonus`) |
| `value._hand_plan` | hand cards scored with the **same** `minion_value`, plus the play/hold logic (triple completion, hand-charge kits, pool gate) |
| `value.shop_ranking` | shop candidates in the same units |
| `simulate_growth.py` | a deterministic engine model (14 engines) — the "future" term |
| `combat_forecast`, `board_stats`, `damage_last`, `damage_cap` | the "now" term and the survival read |
| `value.fragility` (this session) | the FRAGILE band (13–16 effective HP) as a first-class signal |
| `_top_move_text` step 4 | a partial naming path: it emits `sell X (making room)` **only** when the worst sell scores below `SELL_FILLER_SCORE = 15`, and only for a *buy*, never for a hand play |

So the money quote from the live session:

```
plan     : 1. Play Thorned Trailblazer (golden body — goldens never combine — sell to make room)
           2. Play Drifting Sacrifice (board is full — sell to make room) · 3. Cast Tricky Trousers
hand     : BG31_327 play 6.6   ·  BG36_113 play 5.3
sell_rank: BG36_112 5.6  ·  BG36_311 14.9 (held — golden hunt)  ·  BG36_099 15.7
```

Two cards competing for one slot, and the answers are already in the analysis:
Trailblazer (6.6) beats the 5.6 card by **+1.0** (marginal), Drifting Sacrifice
(5.3) **loses 0.3**. The plan says "make room" three times and ranks none of it.

## 3. The contract (what the coach must say)

Per full-board phase, the plan must produce **one** slot decision, not a
suggestion per step:

1. **Name the outgoing card.** `play Thorned Trailblazer, sell Glowscale (6.6 vs
   5.6)`.
2. **State the comparison**, in the same units, and say when it is close:
   `+1.0 — marginal, either is fine` versus `+11 — clearly better`.
3. **Veto the swap when it loses**: `hold Drifting Sacrifice — 5.3 against the
   5.6 you'd have to sell`. A card that is worse than the slot it costs is not
   play, it is a hold, and saying so is the coaching.
4. **Never trade down while fragile.** In the FRAGILE/DYING bands, a swap that
   lowers the *now* term is vetoed regardless of growth. The −4.2 Faceless
   Converter case is exactly this: it was advised at 13–16 HP.
5. **One slot, one queue.** With two hand plays and a shop buy competing, the
   plan should rank the queue by Δ and mark the losers as holds, instead of
   emitting three "make room" steps that cannot all happen.

## 4. Design

### 4.1 The arbiter

```
slot_swaps(analysis) -> [(incoming, outgoing, delta, verdict, why), ...]
```

- **Incoming candidates**: hand cards whose verb is play/cast (scored already), the
  shop's ranked candidates (`shop_ranking` minus the 3-gold price check), and the
  plan's resolved `buy_step_card`.
- **Outgoing candidates**: `sell_rank` ascending, filtered by the guard list
  (§4.3) — the first survivor is the cheapest to lose.
- **Δ** for a candidate pair = `incoming_score − outgoing_score`, plus a
  structural term (§4.2).
- **Verdict**: `take` (Δ ≥ `SWAP_TAKE = 3`), `close` (0 ≤ Δ < 3), `veto`
  (Δ < 0), `veto (fragile)` (Δ < 0 *or* the now-term drops, in the FRAGILE/DYING
  bands).

The thresholds are starting values to calibrate, not truth: the point is that the
coach becomes *decidable* and says which side of the line it is on.

### 4.2 Three terms, introduced in stages

`minion_value` is a keep-score dominated by raw stats (`W_STATS × (atk+hp)`), which
is the right first approximation and wrong in two specific ways: it cannot see
what a body does *in combat* (Venomous, Divine Shield, Taunt, Cleave, Reborn) and
it discounts future growth to a per-card bonus. So:

| stage | term | source | what it fixes |
|---|---|---|---|
| **1** | **shared keep-score** (what exists today) | `minion_value` / `sell_recommendation` | names the sell, states Δ, vetoes the negative swap. Cheap, immediate, fixes 47% of full-board phases and the −4.2 case |
| **2** | **now** — combat consequence | board stats + keyword terms, vs the lobby/next seat; fragility band from this session | stops trading a Venomous/Divine-Shield body for a bigger vanilla one, and hard-vetoes trading down while fragile |
| **3** | **future** — projected growth | `simulate_growth` run with and without the swap, K turns | catches the "worse now, much better in 3 turns" case (engines, scaling comps) which stage 1 will wrongly veto |

Stage 3 is where the real simulation the player expected lives. It should be
*added to* the stage-1 arbiter, not replace it: a simulator fed a 7-minion board
still cannot see the slot, the triple, or the comp glue — those stay structural.

### 4.3 Guards — cards that are not sellable

Some already exist in `sell_recommendation` (comp glue floor, multipliers,
Spellcraft). The arbiter must not hand back a guard as the outgoing card:

- comp **core/addon** (floor exists) and any card in the live target's shopping list;
- a **multiplier/enabler** (Brann, Drakkari, Titus-class) — its value is what it
  amplifies, and `_engine_growth_bonus` already measures part of that;
- a **golden-hunt hold** (the plan says "hold — a 3rd copy turns it golden": the
  same panel must not also sell it — this guard exists and is tested);
- **golden/triple components** that would break a completed golden;
- a **token/summon body** — nearly free to lose, and usually the right answer;
- the **Deity carrier** / permanent-accrued-stat bodies (one-time effects that
  cannot be re-bought);
- **position-dependent** minions (left-most/adjacent effects) whose value depends
  on neighbours the score cannot see.

### 4.4 Output

Extend `top_move_steps` (already structured by this session's `split_step`) with a
new step kind `swap`, and keep the plan to ONE of them:

```
1. Play Thorned Trailblazer, sell Glowscale (6.6 vs 5.6 — marginal)
2. Hold Drifting Sacrifice (5.3 against the 5.6 it would cost)
```

The Buy box and the overlay's Sell panel read the same verdict, so the three
surfaces cannot disagree (the 2026-09-01 rule that the Buy box mirrors the plan).

## 5. Tests and validation

**Unit fixtures** (`tests/test_board_swap.py`, stage 1 — 14 tests): a winning
swap is named with its numbers; a marginal one says so; a losing one is vetoed
and the hand entry demoted to a hold with the comparison that decided it; two
plays and one slot choose one and hold the other; the comp's core, a multiplier
on the board, and anything the plan HOLDS are never the outgoing card; spells do
not compete for a slot; a board with space asks no swap question; nothing
sellable means no sell advice; a losing shop buy is argued against and flagged
for the overlay; a marginal swap is vetoed at DYING but merely "close" at
FRAGILE (that band is stage 2's).

**The corpus counterfactual, run** (all local sessions, 44 full-board phases):
the invariant `never emit a take with a negative delta` **holds**, and the
verdict split (8 take / 1 close / 8 veto) is in the header above. Re-run it with
`value.slot_swaps` over `replay_review._advise_at` per phase.

**Still to check against the labelled human cases** (09-04 Balinda, 09-16 Reno):
the verdicts must agree with the reviews' judgement, or the currency is wrong and
stages 2/3 change order. Not yet done — it needs the reviews' per-phase tables
mapped onto phases programmatically.

### What would falsify the design

If the arbiter's verdicts disagree with the hand-written reviews' cases where a
human judged the sold card wrong, the currency is wrong and stage 2/3 order
changes.

## 6. Open questions

1. **Is `minion_value` the right currency, or should the swap use board stats?**
   A big vanilla body scores high and does little; a 3/3 Venomous scores low and
   wins fights. Stage 2 answers this; stage 1 accepts the limitation explicitly.
2. **How should the 8th-slot triple interaction read?** Playing a card that
   completes a golden *and* needs a slot is two decisions at once.
3. **Do we model the sell's gold return?** Selling returns 1 gold (3 for a golden
   in some rules) — small, but it is a real term when the plan is gold-starved.
4. **Calibration**: `SWAP_TAKE = 3` and `SELL_FILLER_SCORE = 15` are inherited
   guesses. They can be fitted against the corpus only once the metric work
   (verdict capture) exists — until then they are stated assumptions.
