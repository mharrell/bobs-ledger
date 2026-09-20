# Replay review — 2026-09-19 (Guff Runetotem, 1st — first Demon game)

Session `Hearthstone_2026_09_19`, 1 game (live coach on
68c5c5f; reviewed from a snapshot). **Placement 1.** All-demon board
with three goldens by t15 (golden 887/912, golden 642/651, golden
564/566), won at 22 HP.

## 1. The player's engine and what the coach saw

The player's intended line (their report): **Deft Deserter**
(BG36_621, "Activate (1): Give all minions in the Tavern +8/+8 and
Taunt, Divine Shield, or Windfury") keywording the tavern so that
**Methodical Madness** (BG36_880, t4 spell, via **Imp-lusionist's**
deathrattle) consumes keyworded tavern minions — "gain their stats and
Bonus Keywords" — i.e. a Windfury/Divine-Shield-stacking finisher on
top of the demon stat engine. The player assembled it late (Deserter
×2 t12–13, Ashen Corruptor ×2 t13, Imp-lusionist t14) and the game
ended before it bloomed ("over too soon").

Coach coverage: the pieces surfaced generically — Deft Deserter in
advice 62× (t12–14), Imp-lusionist 32×, Mind Muck 34×, Ashen
Corruptor 7× — but **Methodical Madness: 0 mentions**, and
`meta/engine_recipes.json` has **no BG36 tavern-consume entries at
all** (Imp-lusionist / Deft Deserter / Soulkeeping Jailer / Mind Muck /
Flaming Enforcer / Ashen Corruptor). The advice was piecewise
("buy this demon"), never engine-shaped.

## 2. Design verdict (Mike's call, agreed): NOT a comp — a capped
synergy layer

Board space (7 slots) caps the package: the consume demons + Deserter
+ Imp-lusionist eat slots the scaled demons need. The right encoding
is the Plan-1 **capped pick-time synergy modifier** on an already-
committed demon comp, not a new comp core:

- when a demon comp is committed and board-dominant, rank **Deft
  Deserter** and **Methodical Madness** (when Imp-lusionist is
  on-board/hand) up as the finisher line — "cherry on top";
- never advise sacrificing board slots for engine pieces when the comp
  is dominant (board-space cap written into the modifier);
- **utility-vs-triple clause**: consume demons (Mind Muck, Flaming
  Enforcer, Soulkeeping Jailer) should not get the hold-for-golden
  advice while their consume utility is live — game 1's t9 "Hold Mind
  Muck (hold — 1 regular on board; a 3rd copy turns it golden)" was
  the wrong frame for this card; the player sold them and consumed.

## 3. Gates and fixes

No new bugs. Golden-hold, board-full sell-for-room, off-build hunt
traps, and the tier-5 stay (comp pieces "on this tier or below") all
behaved; the player stayed tier 5 at 22 HP against repeated "you're
strong — convert it into a tier" LEVEL advices and won — a legitimate
decline, the board was already the argument.

## 4. Action items

1. (design-first, small P1 extension) The capped demon synergy
   modifier above + the consume-utility-vs-triple clause (§2). The
   Methodical Madness / tavern-keyword mechanic itself lives in
   spell_effects/minion text already curated; only the engine *shape*
   is missing.

## 5. Evening session (`Hearthstone_2026_09_19`): Marin 4th — died to divine shields at "602 vs ~163"

Game 1 of the 17:15 session (game 2, Tavish, live at review time; live
coach on current main). 13 buy phases, clean curve, heavy honest churn,
t13 LEVEL-6 taken. Died 4th in the t13 fight.

**The fight that killed us** (opponent staged board at the losing line,
log ground truth): a **Deflect-o-Bot mech board carrying 4 DIVINE
SHIELDs and 2 Reborns** (Deflect-o-Bot itself shielded — the card that
gains stats as shields pop). The t12 forecast had said "**your 602 vs
their ~163**" — a 4x raw-stat edge that lost.

This is the third opponent-side forecast mispricing in a week (09-16
evening: "895 vs 165" took 19; 09-19 morning games; now this), and the
first where the mechanism is precisely identifiable: **the forecast
prices stat totals; divine shields and reborn are stat multipliers the
opponent gets for free.** The forecast's own docstring admits it ("the
opponent's keywords aren't tracked yet — their board reaches us as
stat totals"). The player's takeaway after the game — "Reborn and/or
Divine Shield might be more important than I've previously given it
credit for, or having truly massive stats" — is the same conclusion
the data forces.

Design direction (promotes the 09-16 §3.1 arc): the lobby scout
already reads staged boards — the DIVINE_SHIELD/REBORN tags are in the
same stream as the stats it collects (verified by hand this session:
the keyword counts above came from the staged entities' tag writes).
Pricing: eff = raw + shields x (a wasted hit ~= our average attack)
+ reborn x body. The forecast then owes the player the honest line:
"their ~163 raw, but 4 shields + 2 reborn — closer to a wall than the
ratio says", and at 4th-place stakes "602 vs 163" stops reading as
unbeatable.

## 6. Evening game 2 (Tavish, 7th): the three-way split and the late pivot

The player's own read — "great position for Beasts or Elementals, tried
to switch too late" — checks out against the comp-target trajectory:
no direction t1-t7 (three tribes at ~1 core hit each: Beast pieces,
Elemental pieces, and Lurking Lionfish/Kelp Keeper — which are NAGAS,
the tribe mirage), Elementals commit t9 (Unbound Tempest at 2 hits,
payoff at TIER 6 — the plan printed "needs tier 6" at t8 and t9 while
the board was tier 3-4 at 25 HP), a flip to Nagas at t10 when the naga
buys landed, then levels 4-5-6 chasing pieces to death at t13, 8 HP,
7th. The box followed the pivot in real time; it did not resist.

Coachable rule the game states: **commit to what you can reach at your
current tier** — a comp whose cores live two tiers up is a lottery
ticket, and a three-way split bleeds against a 5k-MMR lobby.

Design candidate (pick-a-lane fork): when the box is committed and the
shop's high-rankers point at a DIFFERENT tribe, name the fork in the
plan — "the elemental commit needs tier 6 (two levels away at 25 HP),
or the naga pieces in front of you are live now." The comp-flip gates
(09-16/09-18) govern the label; this governs the PLAYER'S decision,
which is the thing that actually died here.
