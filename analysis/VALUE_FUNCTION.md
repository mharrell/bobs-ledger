# Minion Value Function — Design

The coach's decision-making (which card to sell, refresh vs buy, which trinket to
pick) rests on a **minion value function**: scoring any minion in the context of
the current game. This doc captures the design discussion.

## The core idea

**Value is contextual and dynamic, not static.** A card's value depends on the
engine you're building, the turn you're on, the hero power, the two trinkets, and
the opponent across the table. The coach must say "this card is good *right now,
against this opponent, in this engine*" — not "this card is good."

## The value function

```
minion_value(minion, comp, board, hero_power, trinkets, opponent_board) =
    w1·stats
  + w2·comp_synergy
  + w3·role
  + w4·buffs
  + w5·hero_synergy
  + w6·trinket_synergy
  + w7·engine_potential
  + w8·counter_value
```

The weights (`w1..w8`) are the tuning problem — validated against real games
(what did high-MMR players actually do in similar spots?). The inputs are all
computable from what we have: `board_state.py` (buffed stats), `comps.json`
(core/enabler cards), `cards.json`/card DB (tribe, mechanics), `heroes.json`
(hero power), `trinkets.json` (trinket effects).

## The terms

| Term | What it captures |
|------|------------------|
| `stats` | attack + health, weighted by what the comp cares about |
| `comp_synergy` | core card? matches comp tribe? enabler? |
| `role` | scaling engine > buff target > utility > filler |
| `buffs` | buffed stats − base stats (how much you'd lose selling it) |
| `hero_synergy` | does it amplify the hero power? |
| `trinket_synergy` | does it amplify either trinket? |
| `engine_potential` | part of a compounding scaling engine? how far along? |
| `counter_value` | counters the opponent's observed composition? |

## Golden: acquisition value ≠ board value

- **Acquisition** — tripling is valuable: it combines 3 cards' stats + keywords +
  dark gifts, and pays the triple reward. The golden bonus belongs in the *"should
  I buy this third copy?"* decision.
- **Board** — once a golden minion is on the board, it's just a minion; its stats
  already reflect the 3x. The `golden` flag adds **no** separate board value for
  sell decisions.

## The helpers (built on the value function)

- **Sell-value** = *marginal contribution*: compute the board's total value
  without each minion; the one whose removal drops it least is the safest to sell.
  Naturally handles "sell a filler to make room for minions that trigger bonuses."
- **Refresh-EV** = expected value of a reroll vs the known available minion:
  `Σ over pool minions (P(minion)·value(minion)) − value(best available) − refresh_cost`.
  The pool is known (family ban + tavern tier), so the distribution is computable.

## The BG-pool guardrail (critical)

**Only reason over the Battlegrounds minion pool** (`meta/minions.json`, 245
minions) — never the full hearthstonejson DB, which includes Standard cards not in
Battlegrounds. A Standard card like Spellbreaker is noise that would corrupt the
advice. The value function and the coach's reasoning must be constrained to the
BG pool.

## Worked example: Ancestral Automation

The engine: each Ancestral Automation summoned makes all others +3/+2 →
**compounding toward infinity**. The comp is "summon as many AAs as possible."

- **Trinkets**: Automaton Portrait (summons an AA) is the must-pick; Mech
  generators (Scraper Sticker, Reusable Batteries) feed the engine.
- **Minions**: Kangor's Apprentice (resurrects AAs), Prosthetic Hand (Magnetic +
  Reborn onto the AA).
- **Taunt + Reborn loop**: a Reborn AA re-summon triggers the improvement, so you
  *want* it to die and come back. Taunt forces the opponent to attack it → dies →
  comes back → improvement. Taunt is a self-feeding engine.
- **Counter**: Sin'dorei Straight Shot removes Reborn + Taunt (the only BG-pool
  counter; Standard Silence cards don't exist in BG). Venomous also kills it
  regardless of stats. So Taunt+Reborn value is high *until* the opponent has a
  counter — then it flips negative.

## Key lessons

1. **Value is contextual and dynamic** — engine, turn, opponent.
2. **High-tier comps are high-tier because their synergy compounds toward
   infinity** — the "infinite power engine." Value is about engine potential, not
   static stats.
3. **Some cards are tech picks** — more valuable because they counter an observed
   opponent composition (e.g., Sin'dorei Straight Shot vs Mech/Undead).
4. **The coach must reason over the BG pool only**, never Standard cards.
5. **The heuristic doesn't need to be perfect** — its job is to give the LLM good
   numbers to reason over; the LLM handles judgment (uncertainty, sequencing).
