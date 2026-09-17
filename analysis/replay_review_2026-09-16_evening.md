# Replay review — 2026-09-16 evening (Snake Eyes, 3rd)

Session `Hearthstone_2026_09_16`, game 1. Live coach ran
**a51c015** (current main, fresh restart after the trinket re-key — see
decision-log `coach_version`), records 22:13–22:38. One game reviewed;
more games were queued into the same Power.log afterwards, so every
parser must bound itself to the target `CREATE_GAME` (§7).

**Hero:** Snake Eyes (BG28_HERO_400) — hero power: roll a die, gain that
much Gold, locked that many turns after. **Trinket:** Ominous Stone
(one-shot Tier-4 discover of most-common type). **Placement: 3rd**, 16
buy phases, died in the combat after buy t16 at 8 HP (took 19;
`BACON_WON_LAST_COMBAT=0`, `PREDAMAGE=19`, cumulative DAMAGE 41 vs a
30+8 pool).

## 1. TL;DR

The coach's **engine coaching was the best part of the game**: it caught
the Glambot/Repair Job cast-engine at ignition (t8), fed it every turn
after (t13–t16 "Cast Repair Job — each cast feeds your cast engine"),
and the player rode a 16-HP tier-4 board at t10 to a 1,137-stat board by
t16. The game was lost to the two things the coach **structurally
cannot see**: (a) opponent scaling engines — the forecast said "favored
— 895 vs 165" one minute before a fight that dealt 19 to us; the
opponent ran a self-damage Demon engine (Malchezaar refresh-costs-Health
→ Ashen Corruptor rewinds damage into tavern buffs → Eredar Escapist
turns 4-damage ticks into Corrupted Cupcakes; the Escapist was 2056/4140
two rounds later); and (b) its own survival gate — at 8 HP, DYING for
four straight rounds, the t16 plan pushed "LEVEL to tier 6" (the player
followed and died), contradicting the coach's own t13/t15 rule "too
fragile to level first — buy board now".

## 2. Fight timeline (log ground truth)

| fight after buy | health after | coach forecast (at that buy) | outcome |
|---|---|---|---|
| t4→t5 | 30 | behind, don't take this fight | no damage (pairing luck) |
| t5→t6 | 28 (armor gone) | behind — 10 vs 13 | −2 |
| t6→t7 | 20 | behind — 14 vs 24, "lost 2 straight" | −8 |
| t7→t8 | 16 | behind — 23 vs 35, "lost 3 straight" | −4 |
| t11→t12 | 16 | favored — 324 vs 123 | 0 |
| t12→t13 | **8** | **favored — 349 vs 125** | **−8** ← forecast miss #1 |
| t13→t14 | 8 | favored — 421 vs 236 | 0 |
| t14→t15 | 8 | (pass, gold 0) | 0 |
| t15→t16 | 8 | favored — 679 vs ~54 | 0 (their staged ≈ 50 stats ✓) |
| t16→end | **dead, 3rd** | **favored — 895 vs 165** | **−19** ← forecast miss #2 |

Health values from the live decision log; damage verified against
`PREDAMAGE`/`DAMAGE` tag writes on the hero entity. The t15 forecast was
accurate, so the machinery works when the opponent is static.

## 3. Findings (ranked)

### 3.1 The forecast cannot price opponent scaling engines (both kills)

t12→t13: "favored — 349 vs 125" → lost 8. t16→end: "favored — 895 vs
165" → took 19 and died. The second opponent's staged board *in the
log* reads as near-base stats (Eredar Escapist 6/8, ~78 total), while
its true strength was vastly higher (Escapist 2056/4140 by game end).
The forecast prices static snapshots; a lobby running reactive engines
(self-damage Demons, end-of-turn Naga scales, reaction Cupcakes) is
systematically under-priced. Compounding it: the forecast line carries
**no confidence/age signal**, so "favored" reads as a guarantee to the
player — and at 8 HP the player bet the game on it (with the coach's
encouragement, see 3.2).

Design direction (design-first): carry seat-snapshot age into the
forecast ("their ~165, seen 2 rounds ago"), and clamp — never print
"favored" when effective HP ≤ 10. Longer term, opponent
engine-becoming detection is the mirror of the friendly-side gap from
the 09-16 morning review.

### 3.2 t16: LEVEL-to-6 at 8 HP contradicted the coach's own DYING rule

t13 and t15 the coach said the right thing: "LEVEL **next** turn (too
fragile to level first) … roll meanwhile" under the "DYING at 8 — buy
board now" banner. At t16, same 8 HP, same fragility, the plan's step 3
became "LEVEL to tier 6 — 1 left after" with no fragility clause — the
only thing that changed was the comp flip (§3.5) making tier-6 pieces
look reachable. The player followed the plan (leveled, spent the turn)
and died 3rd. Whatever the fight outcome, spending a DYING turn's gold
on a tier violates the coach's own rule; the gate must be **hard** —
under `DYING`, LEVEL is notofferable no matter what the comp wants.

### 3.3 Gold-0 cast advice (t9, t14) — third occurrence across games

t9 (gold 0): the plan's ONLY step was "Cast Tavern Coin". t14 (gold 0):
"Cast Repair Job". Both times the player passed with zero gold. Same
family as the Reno game's t10 "Cast Misplaced Tea Set at gold 0". The
affordability walk gates BUYS against live gold; the cast steps in
`top_move_steps` are not gold-gated. Note the gate must be "castable
**now**", not "never suggest casts" — t16's "Cast Repair Job ×3" was
correct and the player cast all three.

### 3.4 t7: the plan contradicted itself within four steps

Step 1–3: Play Glambot, Cast Tavern Coin, **Buy Mechagnome Interpreter
(growth engine)** — committing ~6 gold to a buy. Step 4: "LEVEL next
turn (lost 3 straight and your board is behind — **buy stats first**)
… roll meanwhile". Both instructions were live in the same plan. The
player resolved the conflict by taking the LEVEL and skipping the buy —
defensible at 20 HP vs a scaling lobby — but the step order recommended
the opposite. Under a survival threat the plan needs one dominant move;
the "buy stats first" clause should suppress engine-buy suggestions the
same way it suppresses LEVEL.

### 3.5 t16 comp flip (Mechs → Nagas) on a one-Naga board

Through t15 the comp was "Mechs - Magnetics/Spells", committing. At
t16 — the final phase — `target_comp` flipped to "Nagas - End Of
Turn/Spell Buff". The board's only Naga is Fauna Whisperer (1 unit).
The flip is a comp-pivot-tracking artifact (Naga core hit via Fauna +
tribe density), but it fed the LEVEL-6 rationale ("the comp's next
pieces live there") and swapped the overlay's Comp box identity in the
last 60 seconds. Rule: no comp flip inside the DYING gate; and a flip
should require more than one tribe unit on board.

### 3.6 Snake Eyes' hero power is invisible to the plan

The hero power (die roll → that much gold, then locked that many turns)
never appears in any advice all game — not its timing, not its gold
spike, not its interaction with LEVEL vs roll affordability. The
hero-power integration is recipe-shaped (`hero_powers.json`) and Snake
Eyes is not recipe-shaped. A fuel-spec entry ("gold spike on turn X"
into the roll-vs-level walk) is the natural home.

## 4. What worked (validated again)

- **Engine ignition (t8):** comp committed to "Mechs - Magnetics/Spells"
  at 2/2 hits and the "each cast feeds your cast engine" line appeared
  exactly as the Glambot loop went live. Every later "Cast Repair Job"
  step was engine-correct (Glambot magnetizes a 4/4 Satellite per spell
  cast on a Mech; Drone Duplicator doubles it; Rescue Bots feed Repair
  Jobs).
- **The final board is the coaching made real:** from a 16-HP tier-4
  board at t10 — Rescue Bot 93/100 (taunt) and 108/109 (taunt+reborn),
  Drone Duplicator 250/230 (DS+reborn+taunt), golden Glambot 104/88,
  golden Cord Puller 29/13, Fauna Whisperer. 1,137 stats.
- **Them Apples conditional hold (t12):** "Hold Them Apples (cast it
  the turn you buy shop minions — the buff dies with this shop)" — the
  player bought four shop minions and cast it. The conditional
  rendered, the player read it right.
- **Lobby-pace anchor numbers** rendered every phase ("your 679 vs
  their ~54"), and the t15 estimate was dead-on.
- t5 "roll the leftover anyway, gold doesn't carry" — followed.

## 5. Player deviations worth noting

- t6–t12 the player consistently preferred board-building over the
  coach's shop picks (Mechagnome Interpreter t7 skipped; Might of
  Stormwind t8 skipped in favor of a magnetic flip; Chef's Choice +
  Weapons Forge t10; mass mech buy t12 over "LEVEL to tier 6"). On this
  board, the player was right each time — the engine assembled because
  of those buys.
- t13's buy/sell flip-flop and t8's "buy 2 → sell 4 → play 3" are
  partly player_actions artifacts (§7), partly real magnetic juggling;
  don't score them as mistakes without forensics.

## 6. Coach-vs-player verdict table (per buy phase)

| t | coach plan (top steps) | player did | verdict |
|---|---|---|---|
| 1 | Buy Cord Puller | took it | ✓ both |
| 3 | LEVEL to 2 (standard curve) | leveled | ✓ both |
| 4 | Buy Patient Scout (growth engine) | took it + more | ✓ coach #1 taken |
| 5 | Cast Tavern Coin; LEVEL to 3; roll leftover | leveled + rolled, didn't cast | ✓ close |
| 6 | Cast Coin; Buy Mind Muck; "level next turn — buy stats first" | bought Cord Puller + Thaumaturgist, rolled | player ok, plan split |
| 7 | Play Glambot; **Buy Mechagnome**; "lost 3 straight — buy stats first" | LEVEL + Glambot only | player resolved §3.4 correctly |
| 8 | Cast Coin; **Buy Might of Stormwind**; comp committed Mechs 2/2 | magnetic flip (Prosthetic Hand/AoM), played Drone Duplicator | player built the engine; coach's tempo pick miss |
| 9 | "Cast Tavern Coin" at **gold 0** | pass | §3.3 |
| 10 | Cast Coin; LEVEL to 5; Buy Tavern Dish Banana | Chef's Choice + Weapons Forge, sold Patient Scout | player right (engine fuel) |
| 11 | LEVEL to 5 ("you're strong — convert it into a tier") | leveled | ✓ both |
| 12 | Cast Overconfidence; **Hold Them Apples (conditional)**; LEVEL to 6 | bought 4 mechs, cast both, no level | player right; LEVEL-6 at 16 HP was pushy |
| 13 | Cast Repair Job; Buy Tea Set; "too fragile to level — buy board" | Repair Job cast + buys | ✓ coach rule right |
| 14 | "Cast Repair Job" at **gold 0** | pass | §3.3 |
| 15 | Cast Repair Job; Buy Planar Telescope; "too fragile to level" | took Telescope + buys | ✓ coach #2 taken |
| 16 | Cast Repair Job ×3; **LEVEL to tier 6** | followed all of it | ✗ §3.2 — died |

## 7. Tooling notes (log forensics)

- The session Power.log now contains **4 `CREATE_GAME`s** (games queued
  after the review target). Any ad-hoc script that "parses the newest
  session" without bounding to the target game silently mixes games —
  mine did until bounded; `replay_review` was already correct.
- Hero damage lives in `PREDAMAGE`/`DAMAGE` tag writes on the hero
  entity ( GameState stream), not `HEALTH` writes — `board_state`'s
  `dmg`/`hero_stat_log` already model this; don't re-derive it.
- Staged combat copies can read as near-base stats at create time (the
  opponent's Escapist staged "6/8"); live scaled stats arrive via later
  tag writes. Staged-stat totals are a floor, not the fight — relevant
  to anyone re-using `lobby.py` runs for forecast numbers.
- player_actions' plays-recorded-as-sells artifact shows as t8 "buy
  Prosthetic Hand + Annoy-o-Module; sell both; play both" and t13
  "sell Repair Job" (a spell). Known family (2026-09-15 note); still
  pollutes review + corpus ground truth.
- Card-id drift continues into the new season's skins: `TB_BaconUps_*`
  (golden-skin ids) resolve to no DB name; opponent-board display will
  show raw ids until the DB learns them or the name fallback does.

## 8. Action items

1. (design-first) DYING hard gate: under DYING, LEVEL is not
   offerable; "buy board now" wins the plan.
2. (bug) gold-gate cast steps in `top_move_steps` ("castable now").
3. (design-first) forecast honesty: snapshot age in the line + no
   "favored" at ≤10 effective HP; opponent engine-becoming as the
   longer arc.
4. (bug, small) comp-flip persistence: no flip while DYING; require
   >1 tribe unit.
5. (design-first) hero-power gold timing for non-recipe heroes
   (Snake Eyes fuel-spec entry).
6. (bug, known) player_actions sell artifact — magnetics/hand copies.
