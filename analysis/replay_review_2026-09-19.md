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
