# Replay review — 2026-09-21 afternoon (Sir Finley Mrrgglton 3rd — a 29k Demon wall the forecast priced at 2.9k)

Session `Hearthstone_2026_09_21`, **1 game** (12:14–12:47), live
coach on **54416c1** (the version stamped on every advisory in
`decision_logs/decision_Power.log.jsonl`); the quotes below are the overlay's
own text. Reviewed from branch `worktree-replays-0921-0922`. **Sir Finley
Mrrgglton** (`TB_BaconShop_HERO_40`), **3rd**, 17 buy phases, final tier 5.
Patch **36.6** card knowledge only (36.6.1 landed 09-22, out of scope).
Bans (`bans.py` pool inference, 3-card gate — five pure-tribe pools at 13–19
distinct minions: Elemental 19, Naga 18, Undead 15, Demon 15, Dragon 13; two
1-card leaks, Prosthetic Hand/MECH and Felboar/QUILBOAR):
**Demon · Dragon · Elemental · Naga · Undead allowed.**

## 1. The build and its engine

The player opened on the Elemental shop-buff package and never left it:

| piece | when | text (36.6) |
|---|---|---|
| Meteorite Crasher | t7 | After you **sell** an Elemental, gain +4/+4 |
| **Nomi, Kitchen Nightmare** | **t8** | After you **play** an Elemental, give Elementals in the Tavern +4/+4 this game |
| Flourishing Frostling | t8 (golden t12) | +2/+1 for each Elemental you played this game |
| Glowing Cinder | t10 | Deathrattle: your Elementals give an extra +2 Health this game |
| Titus Rivendare | t10 | Your Deathrattles trigger an extra time |
| Fauna Whisperer ×2 | t11 / t15 | End of turn: cast Natural Blessing on adjacent minions |
| Flaming Enforcer ×2 | t11 / t12 (golden t14) | End of turn: consume the highest-Health minion in the Tavern |
| **Unleashed Mana Surge** | **t13** | After you play an Elemental, give your Elementals +2/+3 |
| Gatekeeper Amalgam | t14 | Whenever you cast a spell on this, it casts Misplaced Tea Set |

Plus the Baller cycle as fuel: Fire Baller (t6/t11/t16), Snow Baller, Air Baller
— "when you sell this, give your minions +1 Attack / +1 Health / +2/+2", and
Sellemental / Molten Rock / Patient Scout / Refreshing Anomaly / Waveling /
En-Djinn Blazer / Tavern Tempest as cheap Elemental bodies to play and re-sell.
Board stat total by phase close: `t8 105 → t10 399 → t11 631 → t12 1381 →
t13 2654 → t14 4618 → t15 6498 → t16 9175`, and 14,346 after the t16 shop
plays — 2,654 → 14,346 across turns 13–16, all of it Elemental-side.

## 2. The game in two halves

**Half one — five straight losses.** HP ground truth (friendly hero entity
116): 30 HP + 15 armor. ARMOR 15→11 (12:21:15), →8 (12:22:13), →0 (12:23:55);
then DAMAGE 0→10 (12:25:26) and →16 (12:27:28). 15 armor + 16 HP gone inside
seven rounds, leaving **14 HP**, and the coach's own situation line agrees:
t8 — "lost 5 straight". Its stabilization advice was right and the player took
it: t5 "LEVEL next turn (lost 2 straight and your board is behind — buy stats
first; your 8 vs their ~23)", t7 "LEVEL next turn (lost 4 straight fights —
stabilize first; your 29 vs their ~35)", t10 "LEVEL next turn (your board is
behind the lobby pace — buy stats first; your 105 vs their ~170)".

**Half two — nine clean fights, then one hit.** From 12:27:28 to 12:46:18 the
hero takes zero damage (one armor *gain*: ARMOR 0→5 at 12:41:36), while the
board goes 70 → 14,346. Then, at the end of the turn-16 shop, the whole board
is destroyed in one combat.

**The decisive phase is the turn-16 shop and the fight after it.** The player
entered the last fight at 14 HP + 5 armor with a 14,346-stat board and left it
dead; the clean run through turns 8–15 (no hero damage at all) only decided
which places were already taken. The coach's plan for that last
shop was "LEVEL to tier 6 (you're strong — convert it into a tier) — 2 left ·
Buy Natural Blessing (tempo) · no hunt — Drakkari Enchanter, Felfire Conjurer
(hasn't shown in the tavern)", with the forecast priced at a tenth of the real
board (§3).

## 3. The last fight: 29,012 against a forecast of ~2,862

The fatal combat is conclusive in the snapshot stream (player `2` = us, player
`10` = the opponent): our board enters at **14,537** and is annihilated to 0
(14,537 → 14,221 → 13,691 → 9,878 → 9,542 → 5,100 → gone) while the opponent's
board sits at **29,012 with 6 minions** and ends at 248. The hero's
ARMOR/DAMAGE writes land immediately after (12:46:18, lines 310754/310758):
**ARMOR 0, DAMAGE 16 → 40 — 29 damage, dead, 3rd.** The board that killed him:

> golden **Devilish Distractor 9737/9707**, **Soul Rewinder 3430/3645**,
> Laboratory Assistant 429/430, golden **Malchezaar, Prince of Dance**
> 401/399, **Eredar Escapist 292/294**, golden Balinda Stonehearth 124/124

— a pure Demon board (Demon is allowed this game), led by a single 9.7k/9.7k
Demon. The player was on 14 HP + 5 armor.

The coach's forecast for that round (live, 12:44:02):

> `favored — 8434 vs ~2862, seen 1 round ago (yours: 1 divine shield) · they
> haven't taken damage in 16 rounds`

**~2,862 against an actual 29,012 — a 10× under-price on the killing blow**,
with the opponent's 16-round win streak printed in the same string. Note there
were three different numbers in play for that one opponent and none of them was
the truth: the anchor used was the two-round lobby median of *staged* boards
(seat 4's 2,870 at t15 and 2,855 at t14 → 2,862.5), the coach's own committed
record for the seat it was actually paired with was `_opp_boards[5] = {stats:
774, n: 5, turn: 16}`, and the board that showed up was 29,012. Same defect as
the morning session's game 1 (`replay_review_2026-09-21.md` §4.1): the fallback
anchor is a lobby aggregate, so a seat the coach has never seen a real board
from reads as average right up to the round it kills you — and here the seat
record it *did* hold (774) was wrong too.

`FAVOR_HP_CEILING = 10` did not cap this one: 14 HP + 5 armor = 19 effective,
so the label stayed "favored" instead of "ahead on paper".

## 4. Where the coach was right, where the player declined, where it was wrong

**Right, and engine-shaped from the start.** This game is the opposite of the
morning: the coach named the *loop*, not just the cards, and the player
followed it. t10 — "roll — **feed the engine**: elemental bodies (every
Elemental sold feeds Meteorite Crasher)"; t11 — "feed the engine — buy Fire
Baller (3g), **every Elemental sold feeds Meteorite Crasher** (quantity beats
quality)" → TAKEN (Fire Baller); t14 — "feed the engine — buy Fire Baller
(3g), **every Elemental played feeds Unleashed Mana Surge** (quantity beats
quality)". The per-minion trigger is read correctly in each line (sell- vs
play-triggered), and the player ran exactly that loop — the t16 shop's
Elemental buys (Sellemental, Snow Baller, En-Djinn Blazer, Fire Baller) hitting
the coach's ranked list (TAKEN on Snow Baller). The early level ladder was right
too: t12/t13 "LEVEL to tier 5 (you're strong — convert it into a tier)" —
declined at t12, taken at t13.

**Declines, all legitimate:**
- **t14, t15, t16 — "LEVEL to tier 6 (you're strong — convert it into a
  tier)" declined three times**, at 14 HP (eff 14 at t14, eff 19 at t15/t16);
  the player stayed tier 5 and put all ten gold into board every turn. The
  board's 6,498 → 9,175 → 14,346 growth is the argument, and 10 gold of stats
  was the only thing that could have beaten a 29k board — a tier-6 level would
  not have. Correct decline.
- **The comp label.** t14 the target was "Elementals - Unbound Tempest"
  (1 hit — Nomi); at t15 it flipped to "**Nagas - End Of Turn/Spell Buff**"
  (2 hits) and stayed there through t16 (sticky), with the live situation line
  reading "Nagas build — scaling". The two hits were two *copies* of one card
  (Fauna Whisperer ×2) while the rest of the board was Elemental: t15's seven
  slots were 4 Elementals (golden Flourishing Frostling, golden Flaming
  Enforcer, Unleashed Mana Surge, Nomi) + the All-tribe Gatekeeper Amalgam +
  2 Fauna Whisperers, and t16's were 5 Elementals (Fire Baller) + Gatekeeper
  Amalgam + 1 Fauna Whisperer. The player ignored the flip and kept buying
  Elementals — t15 Tavern Tempest, En-Djinn Blazer ×2, Refreshing Anomaly,
  Waveling, Fire Baller; t16 Sellemental, Snow Baller, En-Djinn Blazer,
  Fire Baller — and the board doubled twice. Legal under the flip rules
  (2 hits > 1) but substantively a mislabel, and the sticky rule then locked it
  in for the endgame.

**Wrong — the hero-power pick is unranked and the power is never re-read.**
Sir Finley's entire kit is the start-of-game hero-power Discover, and the
coach rendered (live, 12:19:41):

> `choice = {"kind": "unknown", "source": "Adventure!", "ranked": [["Friendly
> Wager", "TB_BaconShop_HP_081", null, ""], ["Embrace the Elements",
> "BG22_HERO_001p", null, ""], ["King of Duality", "BG35_HERO_001p", null,
> ""]]}` → **`no data on these options — your call`**

All three options scored `null` with empty text; the player took **King of
Duality** (`BG35_HERO_001p` — the only one of the three that ends the game in
`zone=PLAY` for player 2; the other two are GRAVEYARD/SETASIDE only).
Worse than the missed ranking: `live_coach.analyze` sets
`hero_power = _hero_power_text(self.hero_name)` — the *hero card's* static text
from `heroes.json` — and nothing anywhere in the coach reads the power entity
that is actually in play. For this whole game `hero_power` was therefore
`"At the start of the game, Discover a Hero Power."`, which (a) feeds
`minion_value`'s `W_HERO` keyword matching with a string that has no keywords,
and (b) means the skip-turn guard and every hero-power synergy term were keyed
on a placeholder. `meta/hero_powers.json` holds exactly one real entry
(Shudderwock).

**Minor:** the degenerate-phase marker fired correctly on the two zero-length
no-shop transitions (t2, t9) — both benign, and t2 coincides with the
first-combat rollover.

## Action items

1. (bug, medium) **Carry the seat's own board into the forecast whatever its
   age, and re-key it by seat.** Same item as the morning review §4.1, and the
   second instance in one day of the same session pair (14× under-price on the
   fight that cost 9 HP, 10× on the one that cost 29 and the game). The
   recorded 774 against the actual 29,012 also shows the pairing key and the
   staged-entity player id are not the same numbering space — the seat record
   needs to be corroborated before it is trusted as "this seat's board".
2. (bug, small–medium) **Read the in-play hero power.** The log prints it
   (`FULL_ENTITY … zone=PLAY … cardId=BG35_HERO_001p player=2`); prefer that
   card over `heroes.json`'s hero-card text whenever it exists, and use it for
   the `hero_power` analysis field, `W_HERO`, and the skip-turn guard. Sir
   Finley ran a whole game on a placeholder (see §4).
3. (small) **Rank the hero-power Discover.** `choices.py` has no path for
   `kind=unknown / source="Adventure!"`; three real options rendered as "no
   data on these options — your call". At minimum fall back to
   `choices.hero_power` text if the power ids ever land in
   `meta/hero_powers.json`/`heroes.json` — currently none of the three is in
   either file.
4. (design-first, carried) **A duplicated card should not flip the comp label
   past a board that is 5/7 one tribe.** Two Fauna Whisperers took the label
   from Elementals to Nagas (§4) and the sticky rule held it. The 09-18
   `099de10` fix stopped one card counting twice *across board and recent
   stream*; two physical copies still count as two hits by design — this game
   is the first evidence that "two copies of one card" is a weak commit signal
   when the competing comp has a larger share of the board.
5. (design, carried) **FRAGILE band.** 19 effective HP with the opponent on a
   16-round win streak still rendered "favored" and a LEVEL plan; 14 HP
   rendered a bare "LEVEL to tier 5 (you're strong…)". `FAVOR_HP_CEILING = 10`
   and the DYING gate at 12 leave the 13–19 band uncovered — the open 09-18
   §3.1 item, now with a session where the band's own advice pointed at a tier.
