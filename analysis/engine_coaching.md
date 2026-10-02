# Engine-aware coaching: synergy, reachability, roll-vs-level

Design agreed 2026-09-15 from the four-game session review
(`Hearthstone_2026_09_15`: Tras'tath 6th, Voone 7th, Buttons 4th,
Shudderwock **1st**) plus the 09-14 morning session. Three related upgrades,
built in order 1 → 2 → 3 — each consumes the previous. **Core principle
throughout: population stats stay the base of every pick; synergy only ever
adds bounded, card-text-derived (`mechanical`) adjustments on top. Never let
a synergy term override a dominant statistical favorite.**

## Evidence base (log-verified)

Game 4 (Shudderwock 1st, 20 turns) — the positive case:

- Build key: **Tavern Tempest** (t4 Elemental, "Battlecry: Get a random
  Elemental") fired by Shudderwock's battlecry hero power + **Sous Chef
  Sticker** (log id `BG35_MagicItem_801`, DB id 8012: extra hero-power use,
  +1 Gold per use). Player refused to level until Tempest was online; held
  tier 5 t13–t19 while the coach said "LEVEL to tier 6 — you're strong"
  seven times. Won.
- **Unbound Tempest obtained via discover at tier 5** while the coach's hunt
  line said "needs tier 6" (`_hunt_check` tier gate).
- Engine needed **Elemental bodies** (Unbound Tempest: per-play; Meteorite
  Crasher: per-sell, +4/+4; Mana Surge: per-play) — every gold-to-Elemental
  conversion was right regardless of which Elemental came out. Final board:
  golden Unbound 6035/5848, golden Flaming Enforcer 4006/3927, golden
  Meteorite Crasher 1785/1150.
- Coach never surfaced Tavern Tempest as the build key; its shop advice
  ranked by generic value only.

Morning 09-15 games (same session, `Hearthstone_2026_09_15`) —
the regression cases:

- Game 1 (Tras'tath, 6th): t9/t12 "LEVEL — you're strong" while the board
  was behind the lobby (23 vs ~51 the prior turn) — strength read vs next
  opponent only; leveled into the death.
- Game 2 (Voone, 7th): coach LEVEL advice at t6/t7 was correct (player
  under-leveled) — must not regress.
- Player-stated leak to coach against: **rolling gold away with no target**
  (over-rolling when the comp is far from set). The anti-roll mode below
  exists for this.

## Plan 1 — Hero-power × trinket engine modeling

### Current behavior

- Engines are minion-defined: `meta/engines.json` (14 entries) →
  `simulate_growth` + `W_ENGINE*` weights in `value.py`. Trinkets flow into
  analysis (`live_coach.py` ~1039–1054: `scenario["trinkets"]`,
  `trinket_recs` from `meta/trinket_effects.json` → `W_TRINKET`), and the
  simulator has `requires_trinket` steps. Hero power is a text lookup only
  (`meta.hero_power`).
- Picks (`choices.py rank_choices`): heroes = pure `pick_rate/10` (stats
  first — stays untouched); trinkets = `pick_rate/10 + (4.5 −
  avg_placement)` + a bounded board-tribe synergy term; discovers already
  rank against the comp target with honest per-option labels.

### Design

1. **Curated recipe table** `meta/engine_recipes.json`. First entry:
   Shudderwock × Sous Chef Sticker × battlecry-fuel. Each entry carries
   `confidence: mechanical | observed` — only `mechanical` (quoted card
   text, Butchering-fix pattern) activates anything; `observed` entries sit
   inert until corpus data justifies them. Requires structured hero-power
   semantics: `{trigger: battlecry|spell|..., extra_uses, gold_per_use}` —
   encoded from card text.
2. **Play-time recognition (loud):** a small detector in
   `live_coach`/`value.py` — recipe active → shop ranking multiplies
   battlecry-fuel minions ("part of your hero-power engine"); advice names
   the engine ("your hero power + Sous Chef Sticker make Tavern Tempest the
   build key").
3. **Pick-time synergy (quiet, capped):** extend the trinket ranker's
   existing synergy layer with two bounded terms — hero-power synergy (the
   recipe flags vs the offered hero's structured power) and comp-direction
   synergy (trinket mechanic tags vs comp_target/comp_progress leader, not
   just current board tribes). Hero pick ranking does NOT change.
4. **Reverse edge:** a held trinket gives the comp meter/comp_target a
   small nudge (trinket ↔ comp is two-way).

### Guardrails

- Recipes modulate, never originate: no comp targets, no hunt overrides, no
  solo level-gate flips.
- Synergy contribution **capped ~1.5** on the trinket scale (pick-rate
  0–10, placement ~3.5): can flip a near-tie, never beat a dominant
  favorite.
- Every edge traces to card text; pick-panel why-labels show the term when
  it applies (same precedent as discover-pick labels).
- Sized against the existing `W_ENGINE` family — no new dominant weight
  (avoid the old Lobster-engine mistune).
- Pick-time synergy measurement gate (PARKED): before any future
  stats-override at pick time, measure against the decision-log corpus +
  trinket.json pick_rate/avg_placement baselines; report honestly if n is
  too thin.

### Validation

Replay-regression harness (built alongside this plan; see Harness below):
game 4 t11/t13 asserts Tavern Tempest surfaced; morning games assert zero
pick-time changes and no false engine activations.

## Plan 2 — Reachability and body hunger

### Current behavior

`value.py _hunt_check` (three gates): TIER (hard "needs tier N" block),
POOL (own-side ledger "pool dry"), RECENCY (`HUNT_SEEN_WINDOW=4`,
shop_seen tracking). Separately, the Q1 stay gate (~1411–1428) vetoes any
stay when a missing piece exists above the current tier — so a payoff core
at tier 6 forces LEVEL even when a discover path reaches it from tier 5.
`W_SPELL_FUEL` exists ("per stat of marginal engine growth one spell cast
buys") but only values spells, and only as a scoring nudge, not advice.

### Design — two layers, one asymmetry

**RNG identity matters for specific hunts; it does not matter for fuel.**
Discover menus are tier-limited (trustworthy); random generation is
pool-weighted (weak for a named card, but deterministic-enough when any
body of the tribe satisfies the need).

**Layer A — specific-piece reachability:**
- Curated reachability table: each discover/generator source →
  `{kind: discover|random_generate, tier_cap, persistence: hand|per_turn}`.
  Discover sources are trusted above-tier paths; `random_generate` is a
  weak mention only, never a gate. Discover paths bypass the POOL gate too
  (a discover does not roll the shared pool).
- `_hunt_check` gains a fourth path: TIER gate passes when a live discover
  source reaches the piece → "Unbound Tempest — reachable via your
  discover sources."
- Q1's above-veto gets the same exception: a piece above vetoes the stay
  only if unreachable from here.

**Layer B — body hunger (fuel):**
- Curated **fuel spec** per engine (extends `engine_recipes.json` /
  trinket annotations): `{fuel_tribe, trigger: play|sell|summon,
  payoff: quality_independent}` — mechanically derived (Unbound Tempest
  pays out the *tavern's* stats, so cheap bodies are fine; quantity beats
  quality).
- When the engine is live and gold is idle → explicit advice line naming
  conversions ranked by bodies-per-gold: "feed the engine — cast Chef's
  Choice / buy the Tempest battlecry / hero power." Generalizes
  `W_SPELL_FUEL` from spells to battlecries, hero-power uses, and summons,
  and promotes it from scoring nudge to advice.
- Fuel-line floor (agreed): only when the engine piece is on board AND
  past the early tempo window (tier ≥ 4). The line never displaces a real
  buy — gold-idle only.

### Guardrails

- `mechanical` confidence only; fuel lines are spend recommendations inside
  the committed build — never a comp-target override.
- Layer A must not resurrect hunt-every-turn: recency gate still applies to
  specific pieces (Morchie regression).

### Validation

Game 4 t12: hunt/stay line instead of "needs tier 6" + LEVEL. Morning
game 1: no fuel line with no engine live. Morchie Gem Rat case stays
blocked.

## Plan 3 — Roll-vs-level as one valued comparison

### Current behavior

Gate ladder in `value.py` (~2541–2611, re-checked 2026-10-02): flip gates
(too fragile to level first; 0 wins so far; bled ≥ 15 over the last 3 fights
— the 2026-09-18 damage memory; tier ≥ 2 + 2
losses + board < 0.7× the next seat; tier ≥ 3 + 2 losses; tier ≥ 3 + took
≥ 10 last fight; tier ≥ 4 + board < 0.7× the LOBBY pace, which is this
plan's own anchor) →
Q1 stay → LEVEL with "the comp's next pieces live there" / "you're strong
— convert it into a tier" (`board_stats ≥ 1.5× next opponent`) / "standard
curve". Rolls appear only as filler ("roll meanwhile"). History of
special-case patches (09-08 Loh, 09-10 tie, 09-11 Morchie) = the ladder is
out of room.

**Status (2026-10-02):** items 2–4 of the design below LANDED — the
lobby-pace anchor (`value.py:2575`), the three roll modes (roll-for-fuel
`value.py:2324`/`2639`, pieces mode and the spoken anti-roll state
`value.py:2828`), and the dual "consider rerolling for X" + "next priority:
Y" output (`value.py:2645`, `2972`). **Item 1 did NOT:** there is no
`level_value` or `roll_value` function anywhere in the repo — the
comparison stayed inside `top_move`'s gate ladder, which is the "another
elif" this plan was written to replace.

### Design

1. **One decision function, not another elif (NOT built — neither name
   exists in the code):** `level_value` (unlocked pieces × Plan-2
   reachability + flip-gate penalties as inputs) vs
   `roll_value` (live engine recipe (P1) × gold income × fuel at current
   tier (P2-B) × board cushion). Existing gates become inputs.
2. **Strength re-anchored to lobby pace** — lobby.py seat snapshots, not
   next seat alone (game-1 failure).
3. **Three roll modes (agreed dials):**
   - **Roll for pieces**: comp committed OR ≤ 2 missing AND those pieces
     on the current tier (or Plan-2 reachable). Promotes the existing hunt
     (which already names missing cores and carries the feasibility gates)
     to a first-class option competing with LEVEL.
   - **Roll for fuel**: comp complete + live engine needs bodies
     (P2-B). Rolling joins casting/battlecries as encouraged spend.
   - **Anti-roll**: neither condition → the coach actively discourages
     ("no reroll target — comp is 3 pieces short on tier 5 · next
     priority: buy board stats"). State-based, aimed at the player's
     self-identified over-rolling leak.
4. **Dual coaching output (agreed):** when a roll line wins, the advice
   carries both lines — "consider rerolling for [X]" AND "next priority:
   [Y]" — as separate numbered steps with whys. Fits the existing
   `top_move_steps` structure (kinds play/cast/buy/level/roll/note); the
   overlay and decision log need no structural change. Both lines logged
   → uptake measurable (did the roll line or the priority line get taken?).

### Guardrails

- Roll-lead gated to recognized engines / near-complete comps per mode
  definitions — start conservative, expand later only on evidence.
- Never the full APM churn (sell-everything, roll to zero): one notch more
  conservative than the player's actual game-4 play. Sell-timing is
  mid-turn judgment the coach can't see; the buy-phase clock can eat long
  APM plans.

### Validation

Harness assertions: game 4 t13–t19 → roll-lead with exit condition
("level after the triple / when the shop stops producing"); morning game 1
t9 → buy-stats, no level; morning game 2 t6/t7 → LEVEL stands.

## The harness (built alongside Plan 1)

A replay-regression runner in the `validate_growth.py` spirit: given the
session Power.log + expected advice at (game, turn) moments, run the
advisory path offline (replay_review's machinery) and diff against the
expectations table. Cases at birth: game 4 t11/t13/t12/t13–t19 (positive),
morning 09-14 games 1 (t8/t9) and 2 (t6/t7) (regression), Morchie over-hunt
block. This is also the before/after measurement story for "does the
coaching help" — coach-vs-player diffs on the same logs, pre and post.

## Build order

1. Harness + `engine_recipes.json` + hero-power semantics + play-time
   detector (P1).
2. Reachability table + `_hunt_check` path + Q1 exception (P2-A); fuel
   specs + feed-the-engine line (P2-B).
3. roll_value/level_value comparison + three roll modes + dual coaching
   output (P3).

## Plan 4 candidate — non-recipe hero-power gold timing (designed 2026-09-17, not built)

From the 2026-09-16 evening (Snake Eyes) and 09-17 (Reno) reviews: heroes
whose power mints gold never appear in the roll-vs-level walk — the walk
only knows the coin purse and the lobby pace. The log ground truth (both
sessions verified):

- Hero powers live on their OWN entity (`BG28_HERO_400p` "Lucky Roll",
  `TB_BaconShop_HP_046` "Gonna Be Rich!"), player-owned in PLAY.
- **No countdown/lock tag exists** on the power entity: the visible tags
  are `HEROPOWER_ACTIVATIONS_THIS_TURN`, `NUM_TURNS_IN_PLAY` (global
  mirror), and statics. Snake Eyes' "locked N turns" state must be
  MODELED, not read.
- What IS readable: the activation (a PLAY/hero-power block on the power
  entity) and the gold it minted (`TEMP_RESOURCES` writes on the friendly
  player immediately after — Snake Eyes' die roll shows as the temp-gold
  delta; Reno's Gonna Be Rich similarly).

Proposed model (curated per hero, `meta/hero_powers.json` gains fields):

    "Snake Eyes": {"trigger": "hero_power",
                   "text": "<verbatim heroes.json>",
                   "gold_die": [1, 6],
                   "lock": "die_value",
                   "confidence": "mechanical"}

- The coach tracks `last_activation_turn` + `last_gold` from the log and
  derives `unlock_turn = last_activation_turn + lock(last_gold)`.
- The roll-vs-level walk consumes it `_fuel_roll_mode`-style: when the
  power unlocks NEXT turn, the plan says so — "hero power unlocks next
  turn (rolled 4 -> locked 4): a gold spike is coming; don't spend down
  to zero if a level is close". A level the CURRENT purse can't afford
  but the spike can is a "save, don't roll" line — the Snake Eyes game's
  t5/t9 shape exactly.
- Validation: replay the 09-16 evening Snake Eyes session; the walk
  should flag the spike ahead and NOT change any advice in the Reno
  09-17 session (no spike — regression).

Deliberately NOT built yet: per breakoutBot discipline the lock model is
a behavior guess until validated against a session where the player
actually played around the spike.

## Plan 5 candidate — top-4 conversion at 5k+ (framed 2026-09-20)

The player crossed 5,000 MMR (2026-09-19). The session ledger since:
4th, 7th, 8th, then **1st, 1st** on the fixed coach, then 5th, 5th,
5th (the last: Mister Clocksworth, 13 phases, tier 5, the never-won
alarm never armed — a game won-or-tied throughout, lost in the
endgame). The survival phase is solved enough that its remaining 5ths
are LATE 5ths: contested top-5 at t13, dead in the last 3-4 turns.
The player's framing, agreed as the next phase of coaching: **getting
to 4th+ after 5k.**

Levers, ranked by evidence and cost:

1. **Standing-aware risk posture** (cheap, new signal). Current
   placement is IN THE LOG mid-game (`PLAYER_LEADERBOARD_PLACE` writes
   on our hero entity — final placements are the last of them). The
   situation line should carry it: "5th of 7 alive" changes the correct
   play more than HP does — at 5th-6th alive the spike is mandatory,
   at 1st-2nd preservation beats greed. Consumed by the situation line
   first; the roll-vs-level dial second.
2. **Growth-aware forecast** (cheap, all inputs exist). board_stats per
   phase is already recorded; the lobby median per round too. The
   forecast compares LEVELS ("602 vs 163") but the endgame question is
   SLOPES: "you gain ~+40/round, the lobby ~+70/round — you lose that
   race; this fight is your window" vs "you out-scale — level safely."
   A two-phase delta on existing data.
3. **Opponent keyword pricing** (filed 2026-09-19 evening; the
   Deflect-o-Bot game). board_state's staged-hero entity registration
   drops most copies' card ids — fix that and the DIVINE_SHIELD/REBORN
   counts flow into the forecast's opponent line.
4. **Opponent engine-becoming** (the 09-16 morning gap, mirrored):
   the friendly side has recipes/fuel; the opponent side is still stat
   totals. Their staged boards + the bleed record (already collected
   for the streak read) hint at comp identity — v2.
5. **Positioning** (deferred): taunt/attack-order coaching vs poison
   and divine shields is the real endgame skill but the biggest scope;
   revisit after 1-3.

Evidence base: analysis/endgame_transcript_digest.md (2026-09-20) —
the existing 136-transcript corpus mined for endgame advice; strongest
single source yhult8FLYM4 (Shadybunny, "five skills to 8k"). The corpus's
own advice already states lever 1's hole (no placement+HP-keyed swing
rule exists in human guides either) and lever 2's core ("just barely over
the bar" — GeuRrFYtsZo).

Validation: the 5th-place corpus is accumulating (five 5ths across
09-19/09-20); outcome_audit scores advice vs the NEXT fight's damage
and can be sliced to endgame phases (t10+) for before/after.
