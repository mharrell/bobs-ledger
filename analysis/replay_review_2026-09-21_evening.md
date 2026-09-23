# Replay review — 2026-09-21 evening (Yogg-Saron 8th, Tras'tath 6th, Sylvanas 3rd)

Session `Hearthstone_2026_09_21`, 3 games (player `Player#1234`),
reviewed with `replay_review.py` on the `replays-0921-0922` worktree (main
@ `1b008b1`). Patch **36.6** — 36.6.1 (2026-09-22, Aberration type, Naga
rotated out) is AFTER these games and is not applied here; every card call
below is 36.6 pool. Bare `tN` = the 1-based buy phase `replay_review.py`
prints; the coach's own `NUM_TURNS_IN_PLAY` is given where it matters (the
player's shop phases are the odd values — 2, 4, 6 …).

| game | hero | placement | buy phases | final tier | board entering the last fight |
|---|---|---|---|---|---|
| 1 | Yogg-Saron, Hope's End (`TB_BaconShop_HERO_35`) | 8 | 12 | 5 | 282 stats / 6 minions |
| 2 | Tras'tath, Soul Parasite (`BG36_HERO_101`) | 6 | 11 | 5 | 234 stats / 6 minions |
| 3 | Sylvanas Windrunner (`BG23_HERO_306`) | 3 | 16 | 5 (stayed) | 1963 stats / 5 minions |

## 1. The session's one shared cause: no opponent information, ever

All three games read the enemy through the same broken comparison. The coach's
own per-phase state (`None` = the coach never had a value):

| game | `opp_stats` | `lobby_opp` | `last_opp_stats` | `baseline_opp` used as "their" |
|---|---|---|---|---|
| 1 | None (t2-t12) | None | None | 5→163 (t2-t12) |
| 2 | None (t2-t11) | None | None | 5→163 (t2-t11) |
| 3 | None (t2-t16) | None until t13 (248.5) | None | 5→616.5 (t2-t16) |

`opp_stats` and `lobby_opp` are the two inputs of the level-vs-board rule's
`their` (`value.py:1622-1628`: `their = max(preview, lobby)`, falling back to
`analysis.get("baseline_opp")`). `baseline_opp` is `meta/turn_baseline.json`'s
`opp` median — **a 9-game corpus** (`"n": 9` at every turn, `"11": {"med":
163, "n": 9}`, and no entry at all past turn 12) — i.e. the median board of
nine games the coach has seen, NOT the board in front of the player. Every
"favored" in this session is `board_stats` vs that constant.

The scout is not merely stale, it is empty, and the emptiness reproduces
exactly. Feeding the log through `LiveCoach` the way `replay_review.py` does
(one `analyze()` per buy phase) leaves, for all three games:

```
game 1 hero_card TB_BaconShop_HERO_35 next_opponent None opp_boards {} lobby [] seats {}
game 2 hero_card BG36_HERO_101        next_opponent None opp_boards {} lobby [] seats {}
game 3 hero_card BG23_HERO_306        next_opponent None opp_boards {} lobby [] seats {}
```

`next_opponent` is set in `feed()` behind a guard that requires the friendly
hero to already be parsed (`live_coach.py:658-663`):

```
if m and ((m.group(1) is not None and m.group(1) == self.hero_card)
          or (m.group(2) is not None
              and m.group(2) == str(self.friendly))
          or (m.group(3) is not None
              and m.group(3) == self.account)):
    self.next_opponent = int(m.group(4)) or None
```

and `self.hero_card` is only ever assigned inside `_ensure_meta()`, which is
called from `analyze()` (`live_coach.py:1060`) — never from `feed()`. All 18/20/28
`NEXT_OPPONENT_PLAYER_ID` announcements in these three logs therefore arrive
with `hero_card is None` and are discarded. Feeding the same log with
`analyze()` every 1500 lines instead (i.e. what live.py's ~1s poll does)
produces a populated scout (`pairing {1: 3, 2: 5, ...}`, 10 `_lobby_stats`
records). So this is **not** "the live coach was blind" — it is "the coach's
scout is entirely a function of how often `analyze()` runs, and the one code
path that reconstructs a buy phase for review (and any live hiccup that delays
the first `analyze()`) gets nothing." The review tool cannot see what the
overlay saw, and the coach has no honesty line for "I have no idea what I'm
facing."

## 2. Game 1 — Yogg-Saron (8th): 12 buy phases, four straight losses inside a board that was rebuilt from scratch every turn

**Build and engine.** Yogg-Saron (hero power: cast a random Tavern spell at the
start of your turn). The player landed on **Elementals** late: Molten Rock
(`BGS_127`, +1 Health per Elemental played), Waveling (`BG34_856`), Wildfire
Elemental (`BGS_126`), Tavern Tempest (`BGS_123`, "Battlecry: Get a random
Elemental"), En-Djinn Blazer (`BG34_865`), Kelp Keeper (`BG36_701` = Murloc
type, "Activate (1): Trigger a friendly minion's Battlecry"), and — the real
payoff the player stumbled into at t11 — **Flaming Enforcer** (`BG34_500`,
Demon/Elemental, "At the end of your turn, consume the highest-Health minion in
the Tavern to gain its stats"). The coach agreed with the label: *"comp:
Elementals - Unbound Tempest hits 3"* and *"Elementals - Stat scaling hits 3"*
from t9 to t12. The comp's own tier-6 payoffs (`Unbound Tempest` `BG36_352`,
`Unleashed Mana Surge` `BG32_846`) were **never owned** — `comp_progress` never
lists them as hits.

**Where the coach was right and the player declined.** Almost everything the
coach said about the *board* was right, and the player overrode it:

- t1 *"Buy Crackling Cyclone"* → taken, and it was the right tier-1 body.
- t2/t5 *"LEVEL to tier 2/3 (standard curve)"* → taken, and the curve itself was
  correct (the coach's flip only arms from tier 4 up).
- t8 *"1. Play Wolf Pup (board is full — sell to make room) · 2. Play Devout
  Hellcaller ... · 6. sell Decoy Conjurer (making room)"* → the player **sold
  Wolf Pup and Devout Hellcaller** and churned both Decoy Conjurers plus
  Crackling Cyclone, Papa Mrrglton, Refreshing Anomaly and a freshly bought
  Sellemental. Eight sells, one buy, two rolls in one phase.
- t9/t10 *"1. Hold Tavern Tempest (hold — 1 regular on board; a 3rd copy turns
  it golden)"* → declined; the player sold engine pieces instead (see below).
  The line is also internally wrong at t10: the coach's own board that phase
  lists **two** Tavern Tempests (3/3 and 5/5) with a third in hand — the triple
  was already live, and the coach was still describing one regular.- t10 *"3. LEVEL next turn (your board is behind the lobby pace — buy stats
  first; your 111 vs their ~170)"* → the player leveled to tier 5 in the same
  phase and sold four minions. A legitimate decline only if the level bought
  power; it bought En-Djinn Blazer (5/5).
- t11, at 7 HP, *"3. Buy Nightmare Par-tea Guest (surviving until we can
  commit)"* → declined; that phase (20:54:51→20:56:37) is ten sells, three
  rolls, and two buys (Flaming Enforcer, Kelp Keeper) — including
  `SELL Kelp Keeper` at 20:56:21 on a Kelp Keeper bought at 20:55:57.

**Where the coach was outright wrong (bug).** The plan abandons the comp at the
exact moment it should commit, in both losing games, with the same formula —
t8: *"5. no hunt — Unbound Tempest, Kelp Keeper (needs tier 6; Tavern Tempest
can still drop it)"*, t10: *"4. no hunt — Unbound Tempest, Brann Bronzebeard
(needs tier 6; Tavern Tempest can still drop it)"*. The gate reads the comp's
missing cores as two tiers up and therefore "not worth hunting", while listing
Tavern Tempest (`BGS_123`, "Get a **random** Elemental", tier 4) as a
`reach_sources` entry — the coach's own tier-uncapped random-generator escape
hatch. So the coach (a) never advised the tier that held the payoffs, and (b)
simultaneously suppressed the roll that would have found the mid-tier cores.
Game 2's t9 repeats it verbatim: *"4. no hunt — Unbound Tempest, Nomi, Kitchen
Nightmare (needs tier 6)"*.

**The decisive phase.** t11 → t12. Entering t11 the player is at **7 HP**
(`DAMAGE 23` on the hero entity at 20:54:05, HEALTH 30) with a 106-stat board;
the coach's read is *"behind — 106 vs ~163; don't take this fight."* The t11
board (coach's own list) still had the pieces: Molten Rock 27/17, Kelp Keeper
7/7, Decoy Conjurer 7/7, two Tavern Tempests 5/5 and 2/2, Waveling 7/3,
En-Djinn Blazer 5/5. The player then sold ten of them. At t12 (20:56:39,
`NUM_TURNS_IN_PLAY=19`) the board is 282 stats (Waveling 22/6, Molten Rock
56/27, **Flaming Enforcer 54/35**, Kelp Keeper 22/10, Tavern Tempest 20/8,
Tavern Tempest 17/5) — the Flaming Enforcer + En-Djinn Blazer tavern-scaling
turned the panic churn into raw stats — **but the player passed the turn**. The
coach's last line of the game is *"1. Play Tavern Tempest (triples golden!)"*
and it is the right line: a third Tavern Tempest was in hand at t12, on a board
holding two. Third copy → golden → double the Battlecry engine (and Kelp Keeper
was on board to re-trigger it). No play.

The fight (20:56:39, one second after the phase opened) put **36 total damage**
on the hero (`TAG_CHANGE ... Yogg-Saron, Hope's End id=100 ... tag=DAMAGE
value=36`), up from 23, i.e. 13 more than 30 HP allowed: dead 8th. The opposing
board (staged entities in that combat window) was an **Elemental/Murloc-lord
board** — Bile Spitter (`BG33_318`, "Venomous Rally"), Very Hungry Winterfinner,
Diremuck Forager (`BG27_556`), Gearfin, and the `BG34_854pe` hero-power buff at
35/27; the player's board dealt back 3.

The death is therefore not one decision. It is a 15-HP-to-7-HP bleed from four
straight losses (t7 *"close fight — 37 vs ~35"* → −6; t8 *"favored — 71 vs
~51"* → −10; t11 *"behind — 106 vs ~163"* → −8) against a board that was
liquidated and re-bought every turn, with the two most valuable lines — "level
to reach the Elemental payoffs" and "hold the Tavern Tempest triple" — never
taken. The coach's level/roll calls were individually defensible; its two
silences were not.

## 3. Game 2 — Tras'tath (6th): the opening pass, then one board sale at 7 HP

**Build and engine.** Tras'tath, Soul Parasite. The player held **zero minions
through t1-t4** (no buy block at all before 20:59:46 — the first two buy phases
are passes at 3 gold each) and never committed: the mid-game board is a
Naga/Demon grab-bag (Fleeing Fugitive `BG36_921`, Soul Rewinder `BG26_174`,
Ominous Seer `BG31_330`, Seafloor Recruiter `BG34_925`, Soulkeeping Jailer
`BG36_503`), with **Brann Bronzebeard** (`BG_LOE_077`, double Battlecries) at
t8 and a late Elemental detour (two Tavern Tempests). The coach's own comp
tracking shows the drift: *"Demons - Self Damage hits 1"*, *"Elementals -
Unbound Tempest hits 1"*, *"Elementals - Stat scaling hits 1"* at t9 → Elementals
hits 3 at t10/t11 with Demons still at 1.

**Where the coach was right and the player declined.**

- t9 *"1. Hold Ominous Seer (hold — 1 regular on board; a 3rd copy turns it
  golden)"* → declined: the player sold **both** Ominous Seers at 21:09:37 and
  21:09:44, and had also bought-and-sold a Refreshing Anomaly inside four
  seconds (21:09:01 → 21:09:05).
- t9 *"3. LEVEL next turn (took 10 last fight — stabilize first; your 116 vs
  their ~91)"* → the player leveled at t10's first action anyway (21:11:07).
- t11 at 7 HP *"1. Play Waveling · 2. Hold Trapped Clapper"* → declined: Waveling
  was **sold** at 21:13:54, Trapped Clapper sold at 21:13:23 and again at
  21:14:42, and both Tavern Tempests (4/4 and 6/6 — the board's best tempo) sold
  at 21:13:45 and 21:13:51.
- t11 *"3. Buy Titus Rivendare (growth engine)"* → taken (21:14:03), one turn
  before death, onto a 7-HP board. Buying a tier-5 engine at 7 HP is not a
  play; the coach offered it and the player took it.

**Where the coach was outright wrong (bug).** Same no-hunt formula as game 1
(*"no hunt — Unbound Tempest, Nomi, Kitchen Nightmare (needs tier 6)"*). Plus
one arithmetic check the coach never made: at t2-t4 it forecast *"behind — 0 vs
~5 / ~7 / ~11; don't take this fight"* on a **0-stat board** while the player
was in fact winning those fights (the opponent bled 2 and 3 — the fight after
t3 and the fight after t4 both cost the opponent HP). The `baseline_opp` curve
says an empty board is "behind"; nothing in the advice says "you have no board
at all — buy anything", which is the only true thing about t1-t4.

**The decisive phase.** t11, 7 HP, 21:12:40 (`NUM_TURNS_IN_PLAY=20`), 10 gold.
The board the player sold from was the session's biggest single asset — 234
stats (Tavern Tempest 4/4, Trapped Clapper 29/33, Soulkeeping Jailer 15/26,
Soul Rewinder 26/37, Tavern Tempest 6/6, Brann Bronzebeard 22/26). From it the
player removed Trapped Clapper, both Tavern Tempests, Waveling, Soul Rewinder
and a second Trapped Clapper, bought Ashen Corruptor / Titus Rivendare /
Devilish Distractor, rolled twice, and went into the lethal fight with 6
minions, 198 stats. The 30-damage `Soulkeeping Jailer` in the fight's attacker
list is the **opponent's** (the same card in the player's list is 15/26), i.e.
the board that killed them was the demon/jailer board the player had just
dismantled their own copy of. Lethal: `TAG_CHANGE ... Tras'tath, Soul Parasite
id=107 ... tag=DAMAGE value=38` at 21:15:07 (up from 23; the player dealt 3
back), `PLAYSTATE LOSING`. The killer is `perrin` (Y'Shaarj), whose staged board
carried **two golden Flaming Enforcers 8/10** with a golden Imp-lusionist
(`BG36_731_G` — Deathrattle: get a Methodical Madness). 6th place.

## 4. Game 3 — Sylvanas (3rd): the recoverable one, and what it did right

**Build and engine.** Sylvanas Windrunner (`BG23_HERO_306`). The player built a
**Quilboar Blood-Gem board and never left it**: Bramble Tunneler (`BG36_331`,
t4 Quilboar, "Rally: Get a random Choose One card"), Vigilant Bristlemane
(`BG36_510`, t5, "Whenever you cast a spell on this, it plays a Blood Gem on
adjacent minions"), Snare Trapper (`BG36_332`), Trench Fighter (`BG34_684`,
"At the end of your turn, get a Gem Confiscation"), Gem Rat (`BG31_326`, "At the
end of your turn, get a Gem Day"), Sanguine Refiner (`BG33_885`, "Rally: Your
Blood Gems give an extra +1/+2 this game"), Turbo Hogrider (`BG31_323`,
"After you play a Choose One card, this plays a Blood Gem on all your other
Quilboar"), with Highkeeper Ra (`BG34_319`) and Balinda Stonehearth
(`BG35_883`, spells cast twice) as support. The scaling is in the log: Bramble
Tunneler 9/12 (t7) → 32/38 (t9) → 140/173 (t12) → 338/399 (t13) → 514/605
(t15); Vigilant Bristlemane 7/9 → 19/21 → 154/186 → 229/254 → **347/379**;
board stat total 54 → 245 → 1140 → 1963 (coach's `board_stats`).

**The four things it did right (all player-side, none of them coach-led).**

1. **It committed at tier 4-5 and stopped rolling for direction.** The player
   held a Quilboar board from t7 on (Bramble Tunneler + two Thorned
   Trailblazers at t7, Vigilant Bristlemane added at t8) and bought nothing
   off-tribe after t8 except Highkeeper Ra and Balinda Stonehearth (both
   tribe-agnostic). The coach's `comp_progress` only reached *"Quilboar -
   Bristlemane hits 1"* at t8 and *"hits 4"* at t13, i.e. it lagged the player's
   own commitment by several turns, and its comp advice was retrospective —
   *"Buy Gem Rat (committing to Quilboar)"* at t11 and *"Buy Sanguine Refiner
   (committing to Quilboar)"* at t13 both label buys the player had already
   decided. The four hits it eventually counted are Bramble Tunneler + Vigilant
   Bristlemane + Sanguine Refiner + Trench Fighter (`meta/comps.json`
   `Quilboar - Bristlemane` core) — every one of them a player find.
2. **It stayed at tier 5 on purpose.** Two explicit offers to level were
   declined: t9 *"6. stay on tier 5 — your comp's missing cores are on this
   tier or below; leveling would lower the odds"* (followed — correct) and t12
   *"5. LEVEL to tier 6 (you're strong — convert it into a tier) — 3 left"*
   (declined — also correct: the engine was already compounding and every point
   of gold went to spells and Blood Gem pieces). This is the level-vs-board
   rule's best moment in the session.
3. **It ignored the no-hunt gate and found the core anyway.** t9's plan was
   *"5. roll — hunting Trench Fighter (Felboar is off-build)"*; the player
   bought `Crater Miner`, `Crater Miner`, `Felboar`, `Alliance Flag` — including
   **Felboar** (`BG28_633`, Demon/Quilboar, "After you cast 3 spells, consume a
   minion in the Tavern to gain its stats"), which the coach had explicitly
   labelled off-build, and which is a Quilboar-hybrid spell-payoff in exactly
   this build.
4. **It kept the board and worked the shop instead of the board.** The high
   action counts are all *fodder* cycling, not board churn: t11 is 7 sells
   (Snare Trapper, Fearless Foodie, Gatekeeper Amalgam, Felboar, Crater Miner,
   Sly Infiltrator, Veteran Brigand), t13 is 10 sells, t14 is 14 sells — and in
   every one of them the six stat carriers (Bramble Tunneler, Vigilant
   Bristlemane, Highkeeper Ra) are still there at the end of the phase, while
   the Sly Infiltrators / Fearless Foodies / Snare Trappers go round and round.
   Compare game 1's t8/t11 and game 2's t11, where the same churn reflex hit the
   *board*: the difference between 3rd and 8th in this session is which set of
   cards the sell cursor was pointed at.

**The decisive phase.** t14 → t15 → the end. The hero's cumulative `DAMAGE` is
`12` (21:26:02) → `24` (21:38:33, the fight resolved at the top of t14, i.e. the
player entered it at "hp=18" and left at 6) → `40` (21:43:18, the last
combat). The coach read 18 HP at t14 correctly, then said *"ahead on paper —
1568 vs ~577"* — and the player lost 12. The final board was 1963 stats, the
coach's read *"ahead on paper — 1963 vs ~616"*, and the last combat killed the
player behind **Greybough** (`TB_BaconShop_HERO_95_SKIN_C`, 2nd) after
**Galewing** took 1st — the player is `PLAYER_LEADERBOARD_PLACE value=3`
against their 2/1. The killer is not a bigger stat board: it is a **Reborn /
Taunt / re-summon board** — `BG25_008_G` 8/4 Reborn+Taunt, `BG25_014` 9/6,
`BG32_324_G` 4/14, `BG25_009` Eternal Summoner 8/1 Reborn+Taunt, `BG31_835`
Deathly Striker 8/8 Reborn, `BG28_300` Harmless Bonehead Reborn, plus
`Drustfallen Butcher` (the unit that dealt 397 to the player's Timewarped Lil'
Quilboar, above). That is the same mechanism as the 09-19 review's
divine-shield finding, one patch later: the forecast prices stat totals, and
re-summons are a stat multiplier the opponent gets for free, so "1963 vs ~616"
was never the 3x edge it printed. Raw stats were not the losing variable in game
3 — HP was: the 12-damage t14 fight is what took an 18-HP player to 6 and made a
1963-stat board irrelevant.

## 5. Coach bugs, quoted

1. **the whole scout is empty in the review path** — `opp_stats` / `lobby_opp` /
   `last_opp_stats` are `None` for every phase of all three games, so every
   forecast compared the player's board to `baseline_opp`, the 9-game
   `meta/turn_baseline.json` median. Quoted advice that depends on it: game 1 t8
   *"forecast: favored — 71 vs ~51 (yours: 1 divine shield)"* → the player lost
   10 HP; game 2 t9 *"close fight — 116 vs ~91"* → −10; game 3 t13 *"favored —
   1078 vs ~248"* → −12. Root cause of the reproduction above: `_NEXT_OPP`
   parsing sits behind a `self.hero_card` guard in `feed()`, but `hero_card` is
   only assigned in `_ensure_meta()` from `analyze()` — the coach's situational
   awareness is a function of `analyze()` cadence, and there is no "no scout
   data" honesty line in the advice text.
2. **"no hunt" is a dead end, quoted verbatim** — game 1 t8: *"5. no hunt —
   Unbound Tempest, Kelp Keeper (needs tier 6; Tavern Tempest can still drop
   it)"*; game 1 t10: *"4. no hunt — Unbound Tempest, Brann Bronzebeard (needs
   tier 6; Tavern Tempest can still drop it)"*; game 2 t9: *"4. no hunt —
   Unbound Tempest, Nomi, Kitchen Nightmare (needs tier 6)"*. One line
   (`BGS_123`, *"Get a random Elemental"*) is the only mechanism the coach
   credits for a comp whose core sits two tiers away, so it neither advises the
   tier nor the roll.
3. **`BG34_Giant_608` (Timewarped Lil' Quilboar) is invisible.** It is on the
   player's board in game 3 from 21:29:06 on: `FULL_ENTITY - Creating ID=8045
   CardID=BG34_Giant_608` with its entity lines carrying `zone=HAND zonePos=1
   cardId=BG34_Giant_608 player=5` (`Entities[0]=[entityName=Timewarped Lil'
   Quilboar id=8045 zone=SETASIDE zonePos=0 cardId=BG34_Giant_608 player=5]`),
   `SETASIDE → HAND` at line 486627 (21:29:18, the tail of buy 9),
   `HAND → PLAY` at 518919 (buy 10), and 11 more copies through the game, the
   last still on the board in the final fight. It attacks as *"ATTACK
   Timewarped Lil' Quilboar BG34_Giant_608 player 5 line 770767"*, and it is
   **not in `meta/minions.json`** (`meta.minions()` lookup for
   `BG34_Giant_608` and its `BG34_Giant_015` sibling → `None`). `MINION_ID`
   (`extract_game.py:71-72`) is
   `^(?:BG\d+_\d+|BG\d+_[A-Z]+_\d+|BGS_\d+|BG_[A-Z]+_\d+|BG\d+_GS\d+)(_G)?$`
   — `_Giant_` is mixed-case, so this real Quilboar is rejected by
   `board_state.MINION_ONLY` at every board build (`board_state.py:275, 284,
   428, 460, 550`). It appears in **0 of 16** `replay_review` boards for game 3
   while its sibling engine pieces do. A Blood-Gem-scaling Quilboar off the
   coach's board is the coach mis-scoring exactly the comp the player won with.
4. **The triples-golden call is right and cost nothing — but only because the
   player passed.** Game 1 t12's *"1. Play Tavern Tempest (triples golden!)"* is
   the session's best single line (third copy in hand, two on board, Kelp Keeper
   on board to re-trigger the Battlecry) and was not taken. Recording it here
   because it is the counter-example to §5.2: the coach *can* see the engine
   when the pieces are already in hand.

## 6. Action items

1. **(P1, correctness) Make the scout's absence visible, then fix its
   cadence.** Two parts, both small: (a) stamp `opp_stats`-is-a-baseline in the
   forecast text — "their ~163 (corpus median; no scout data)" instead of an
   unqualified "~" (the `approx` flag at `value.py:1629` already knows this and
   only gates a tilde); (b) hoist `_ensure_meta()` (or at least the
   hero/friendly/account assignment) out of `analyze()` so `feed()`'s
   `_NEXT_OPP` guard can fire — as written, the coach's whole opponent model is
   a side effect of poll frequency, which makes `replay_review.py` structurally
   blind to what the overlay showed.
2. **(P1, advice) Kill the "no hunt" dead end or give it teeth.** When the
   target comp's missing cores are above the current tier, the plan must name
   the choice: either level toward them (and say the tier and the cost) or hunt
   the mid-tier enablers — never "no reroll target, roll the leftover anyway"
   while a tier-4 `reach_sources` generator sits in hand. Both losing games
   spent every phase after t8 in that hole.
3. **(P2, meta coverage) `BG34_Giant_*` is a real Battlegrounds minion family
   the coach cannot see.** Add `BG\d+_[A-Za-z]+_\d+` to `MINION_ID` (with the
   cardtype filter doing the minion/trinket split, as the comment there already
   promises) and curate `BG34_Giant_608` / `BG34_Giant_015` into
   `meta/minions.json`. 6,000 log lines of a card the coach drops from its own
   board, 12 lines after a regex whose stated job is "a real board minion id".
4. **(P2, coaching) The churn reflex has no advice surface.** Games 1 and 2 both
   die of it (game 1 t11: ten board sells at 7 HP; game 2 t11: six board sells
   at 7 HP, including a golden pair in waiting) and the coach never said "stop
   selling your board". The sell ranking exists (`sell_rank`) and the "board is
   full — sell to make room" line is *permissive*; what is missing is the
   inverse gate: at ≤10 HP, a sell that removes a scaling piece should be
   flagged by name before the buy advice.
5. **(P3, baseline) `meta/turn_baseline.json` runs out at turn 12** (`n=9` to
   turn 11, `n=6` at 13, no entry past 18) while this session's boards reach
   1963 stats. Until the corpus grows, late-game forecasts should say the
   baseline is out of range rather than print it as "~616".
