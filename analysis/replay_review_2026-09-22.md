# Replay review — 2026-09-22 morning (Master Nguyen 7th, Thorim 4th, Mutanus 4th, Captain Eudora 7th)

Session `Hearthstone_2026_09_22`, 4 games (player `Player#1234`),
reviewed on the `replays-0921-0922` worktree (main @ `603cbc1`). Patch **36.6**
— 36.6.1 (Aberration type added, Naga rotated out) landed later the same day
and is not applied here. Every card call below is 36.6 pool: game 1's ban set
read `['Dragon', 'Mech', 'Murloc', 'Pirate', 'Undead']` with the Naga comps
still listed playable, which is exactly right for 36.6. Bare `tN` = the 1-based
buy phase `replay_review.py` prints; the coach's own `NUM_TURNS_IN_PLAY` agrees
with it in this session.

Method note: `replay_review.py` cannot see the pairings (its `_advise_point`
stops feeding at the settled shop, so every `NEXT_OPPONENT_PLAYER_ID`
announcement is missed — §9, the same defect reported on 09-21 evening), so its
printed anchors are all `baseline_opp`. The advice quoted as *what the player
saw* below is reconstructed with `analyze()` on every ~120-line poll batch
(`live.py`'s cadence) — verified against `replay_review.py`'s action list, which
is identical.

| game | hero | placement | buy phases | final tier | fatal fight | HP in | board in |
|---|---|---|---|---|---|---|---|
| 1 | Master Nguyen (`BG20_HERO_202`) | **7** | 9 | 4 | t9 vs Tess Greymane | 7 | 143 stats / 7 |
| 2 | Thorim, Stormlord (`BG27_HERO_801`) | 4 | 13 | 5 | t13 vs seat 8 (Edwin VanCleef) | 15 | 177 stats / 6 |
| 3 | Mutanus the Devourer (`BG20_HERO_301`) | 4 | 16 | 6 | t16 vs Nightmare Lord Xavius | 2 | 3040 stats / 7 |
| 4 | Captain Eudora (`TB_BaconShop_HERO_64`) | **7** | 10 | 4 | t10 vs Sindragosa | 14 | 1204 stats / 7 |

## 1. How each game died

**Game 1 — Master Nguyen, 7th, tier 4.** Nine fights, seven of them costing
health (armor included): 2, 0, 3, 6, 0, 5, 10 (t7), 7 (t8), and then the lethal
one entered at 7 HP in t9. The board entering that last
fight was the 36.6 demon tavern-consume pile the 09-19 review called "not a comp
— a capped synergy layer": Imp-lusionist 6/2, golden Trapped Clapper 5/5, Devout
Hellcaller 16/14, golden Flaming Enforcer 18/23, golden Ashen Corruptor 13/13,
Balinda Stonehearth 6/6, Deft Deserter 8/8 — 143 stats, three goldens, **no
scaling engine and no self-damage source**. The coach's read at the death turn
was correct and blunt: t9 settled, `behind — 100 vs ~166, seen 1 round ago;
don't take this fight (yours: venomous) · they haven't taken damage in 9 rounds`.
It was right, and the trend behind it was already four rounds old: the board grew
22 → 37 → 63 → 100 (t5-t9) while the anchor it was measured against grew
30.5 → 36 → 74 → 114.5 → 166. The player's board never closed the gap.

**Game 2 — Thorim, 4th, tier 5.** The player was **unbeaten through t10** (30 HP
+ 8 armor intact, ten wins) with a Beast Leviathan/Slamma board. Then: t11 cost
11 HP, t12 cost 12, t13 lethal from 15. Board entering t13: Turquoise Skitterer
20/5, Sewer Lord 6/12, Deathstrider 14/12, golden Banana Slamma 14/14, Lurking
Leviathan 3/9, Stalwart Kodo 36/32 — 177 stats against a 380-stat anchor. This
one is *not* a low-tier death: the curve was honest (tier 5 at t9 on the coach's
"the comp's next pieces live there") and the loss was a board that never
finished assembling (§5, §6).

**Game 3 — Mutanus, 4th, tier 6.** The best-built game of the four: a Pirate
bounty/end-of-turn engine (Proud Privateer, Enterprising Escapee, Sky Admiral
Rogers, golden Hooktusk Master Marauder, Drakkari Enchanter) at 3040 stats by
t16. It died because the last two fights went the wrong way at 24 and then 2 HP:
t14 cost 10, **t15 cost 22 in a single fight** (24 → 2), t16 lethal. The coach's
own honesty mark worked here — at 2 HP the label was capped to
`ahead on paper — 2816 vs ~2118` instead of "favored" — but the mortality clock
that should have screamed a round earlier never fired (§2, §3, §4).

**Game 4 — Captain Eudora, 7th, tier 4.** A real comp for once: Quilboar
Bristlemane, committed by the coach at t5 ("scale Quilboar - Bristlemane — buy
its scalers, cast everything, sell nothing that grows"), 1204 stats by t10 with
Vigilant Bristlemane 199/310 and Felboar 175/253. It died at 14 HP with a 13:1
stat ratio on the board. The damage trail (HP read at each buy phase):
30 → 22 (t6 fight cost 10) → **won** t7 → 14 (t8 fight cost 8) → **won** t9 →
dead from 14 in t10; the two costliest losses of the game came with the bigger
board (`close fight — 57 vs ~46` and `close fight — 89 vs ~69`), and the death
turn's line was `favored — 1204 vs ~93, seen 1 round ago (yours: 2 divine
shields) · they haven't taken damage in 10 rounds` plus a level recommendation
(§2, §4).

## 2. The two tier-4, 7th-place deaths: the level/roll gates, verdict per game

Neither death is a *missed-curve* death — both players were on the coach's own
curve (tier 4 at t7/t8 is where `standard curve` put them). The level
*instruction* failed in opposite ways, and the roll/commit gates are where the
real losses are.

**Game 1 — level gate RIGHT, roll/plan gate wrong, commit gate missed.**
- Levels: t2, t4, t7 to tier 4, each on the coach's line (`LEVEL to tier 3
  (standard curve) — 1 left`, `LEVEL to tier 4 (standard curve) — 2 left`). Tier 5
  was never advised, and *shouldn't* have been: at t8 (14 eff HP, 10 taken last
  fight) no step in the plan even offered a tier — the settled move list was
  just `1. Cast Methodical Madness` — and at t9 (7 eff HP ≤ DYING_HEALTH) the
  level rendered in the deferred, non-actionable form quoted by
  `replay_review.py`: `4. LEVEL next turn (too fragile to level first; your 100
  vs their ~91) — 2 short after the buy; roll meanwhile` (the `~91` is that
  tool's baseline anchor; live that line read `~166` — §9). Refusing a 9-gold
  tier at 7 HP was correct.
- Roll gate: the death-turn plan ended `no reroll target — comp is 4 pieces
  short on tier 4 · roll the leftover anyway, gold doesn't carry`, though the
  player did not roll at t9 at all (`turn_forensics.py`: three buys, three sells,
  no reroll). The rolls that hurt were earlier: `roll x5` at t8 with 14 HP and a
  63-stat board, hunting inside a comp that did not exist yet.
- **Commit gate: missed.** `comp_progress` was empty at every phase through t7
  (t8's first candidate was `Demons - Shop Buff`, hits 1, `ready: False`);
  the player's t3–t8 coach picks were tribe-less generics (`Buy Patient Scout
  (growth engine)`, `Buy Staff of Enrichment (part of growth cycle)`, `Buy Motley
  Phalanx (growth engine)`), and the first and only `target_comp` —
  `Demons - Self Damage`, `committing` — arrived at t9, the turn they died. Eight
  buy phases with no lane is the game-1 diagnosis, and it is visible in the
  coach's own data (§6).

**Game 4 — level gate WRONG (the opposite failure), roll gate misaimed.**
- At 14 eff HP, gold 10, level cost 9, the death-turn advice read
  `1. Play Fearless Foodie (board is full — sell to make room) · 2. Play Bramble
  Tunneler (board is full — sell to make room) · 3. LEVEL to tier 5 (you're
  strong — convert it into a tier) — 1 left`, under the headline
  `Quilboar build — scaling · strong (1204 vs ~93)`. Spending the last purse on
  a tier on the turn one lost fight ends the game is the wrong instruction even
  though the board was genuinely strong; the `strong` branch of the flip
  (`board_stats >= 1.5 * their`, `value.py:1630`) has **no effective-HP guard**,
  while the `dying` branch above it does.
- The player declined the level — a *legitimate* decline — and then burned the
  same purse on `roll x4` plus four buys (BG28_583, Tricky Trousers, Razorfen
  Geomancer, Gem Confiscation), which is not. Neither side of the table had a
  "buy the biggest body / stabilize" step: the plan's own step was
  `roll — hunting Trench Fighter`.
- Roll/commit gate otherwise right: Bristlemane was the right target and the
  coach named it from t5, including `Buy Trench Fighter (committing to Quilboar)`
  at t10. This game's bar was high enough to survive; it lost the fight anyway.

## 3. BUG (b): the per-combat damage cap is frozen at 2, so the mortality clock almost never fires

`BACON_COMBAT_DAMAGE_CAP` escalates during the game, but the coach reads only
the opening value. Ground truth from the log (game 1 chunk, GameState lines):

```
235   TAG_CHANGE Entity=7          tag=BACON_COMBAT_DAMAGE_CAP value=2
2190  TAG_CHANGE Entity=GameEntity tag=BACON_COMBAT_DAMAGE_CAP value=5
22395 TAG_CHANGE Entity=GameEntity tag=BACON_COMBAT_DAMAGE_CAP value=10
88944 TAG_CHANGE Entity=GameEntity tag=BACON_COMBAT_DAMAGE_CAP value=15
```

The coach's `damage_cap` in every analyzed state of all four games (t1→t9/t10/t13/t16):
`{1: 2, 2: 2, ... 16: 2}` — frozen at 2. Reproduced in isolation:

```
after numeric  Entity=7 value=2          -> 2
after named    Entity=GameEntity value=5 -> 2   (ignored)
after named    Entity=GameEntity value=15-> 2   (ignored)
after numeric  Entity=1 value=15         -> 15
```

`board_state.py:322-325` claims the opposite of what the log does — "only PTL's
echo uses the named `Entity=GameEntity` form" — and `test_damage_cap_on_numeric_gameentity`
only covers the bare-numeric spelling. Consequence: the ladder branch that says
"one bad fight ends it" (`eff <= cap`) can only ever fire at **≤2 HP**. Per-fight
damage taken in this session (from the HP series, armor included): 2 and 2 in the
two turn-1 fights, then 3, 3, 5, 6, 7, 7, 8, 8, 10, 10, 10, 11, 12 and a single
**22** — nothing after turn 1 cost as little as the cap the coach printed.

## 4. BUG (b): the death clause is computed and then truncated away

`value.py:1388` returns `" · ".join(bits[:3])`, and the mortality clause is
appended **last** (`value.py:1366-1385`). Whenever build/strength/streak already
fill three slots, the one line that matters is dropped:

- Game 1 t9: 7 HP, lobby 166 — the `eff <= 12` branch (`value.py:1377`) fires and
  appends `DYING at 7 — buy board now`, but it lands as the fourth bit and
  `bits[:3]` drops it. Rendered headline for the whole death turn:
  `Demons build — scaling · behind (100 vs ~166) · lost 3 straight`.
  The player died in that fight.
- Game 3 t16 shows the line surviving only because it had a free slot:
  `Pirates build — scaling · lost 2 straight · 2 HP vs a 2 damage cap — one bad
  fight ends it, buy board now`. Note it is quoting the frozen cap of 2.
- Game 4 t10 got neither, for the second reason: `lobby >= 100` gates the
  sub-30-HP clauses (`value.py:1374, 1380`), and the lobby median that turn was
  **93.5**. Headline: `Quilboar build — scaling · strong (1204 vs ~93)`. One
  lost fight later the player was dead.

So in the two 7th places the coach had the information and did not say it:
either it was truncated (§4, game 1) or the HP gate was gated on a stale lobby
number (§4, game 4).

## 5. BUG (b): a 10:1 "favored" off a one-round-old three-minion preview

Game 2 t11, 30 HP + 8 armor, board 208, and the forecast the player read for the
whole shop phase:

```
favored — 208 vs 21, seen 1 round ago · they haven't taken damage in 11 rounds
```

`opp_stats=21` — presented as the fresh preview, no `~` estimate mark — is the
same opponent's (seat 5) turn-10 board of **3 minions**. That fight cost **11
HP**, the player's first loss all game (30+8 → 27+0), and the anchor went 21 →
167 (t12) → 380 (t13). The advice steps that turn were `1. Play Stalwart Kodo ·
2. Play Banana Slamma · 3. Hold Lurking Lionfish` — nothing in the box said that
a 3-body 21-stat read, one round old in a lobby that had just doubled twice, was
not a fight to shop through casually. This is the 09-19 §5 class again (stat
totals are not combat power, and the anchor lags a doubling lobby), with the
aggravating factor that the estimate mark is absent precisely when the
fresh-preview path is a stale mini-board.

## 6. BUG (b): comp commit on half an engine

Game 1 t9 `comp_progress`:

```
{'name': 'Demons - Self Damage', 'tribe': 'Demon', 'meta_tier': 'S',
 'hits': 2, 'ready': True,
 'needs': ['BG35_883', 'BG36_733', 'BG36_762', 'BG_LOE_077'],
 'trinket_fit': False, 'tribe_hits': 3}
```

`ready: True` and `target_state: committing` from two Ashen Corruptors alone.
The coach's own meta entry for that comp says
`when_to_commit: 'Ashen Corruptor + self damage (Wrath Weaver or Malchezaar,
Prince of Dance) + payoff (Tichondrius or Eredar Escapist)'` — the player had
**no self-damage source on board or in hand** at any point in the game
(`own_pool` at t9: Devout Hellcaller, Imp-lusionist, Trapped Clapper ×2, Patient
Scout, Laboratory Assistant, Ashen Corruptor ×2, Methodical Madness; Balinda
arrived later that turn). The situation line then advertised the half-engine as
`Demons build — scaling`, and the death-turn plan spent the last purse inside it
(`3. Buy Flaming Enforcer (growth engine)`), i.e. the 09-19 §2 "piecewise, never
engine-shaped" finding with the enabler half missing entirely.

## 7. (a) Coach advice that was RIGHT and the player declined

- **Game 2 t12 — the comp's core was sold, not played.** With 15 HP and a
  101-stat board, the coach's steps were `1. Play Stalwart Kodo · 2. Hold Lurking
  Leviathan (hold — 1 regular on board; a 3rd copy turns it golden) · 3. Play
  Lurking Lionfish`, the level line was `LEVEL next turn (took 11 last fight —
  stabilize first; ...)`, its only sell was `sell Hooktusk, Master Marauder
  (making room)`, and the comp line since t8 was `scale Beasts - Leviathan — buy
  its scalers, cast everything, sell nothing that grows`. The action list for
  that turn reads `sell Hooktusk, Master Marauder, Banana Slamma, Goldrinn, the
  Great Wolf, Forest Rover, Lurking Lionfish`; **Goldrinn** (the comp's own
  scaling core, `BGS_018`) and **Lurking Lionfish** are absent from the t12
  end-of-turn board, so both left for good. The `Sewer Lord` buy in the same turn
  was the right one. The Beast board six turns of play had assembled was
  liquidated on the turn the player fell to 15.
- **Game 1 t9 — `don't take this fight` was unavoidable, but the plan was
  greed.** At 7 HP with 10 gold the recommended order was `1. Hold Trapped
  Clapper (hold — 1 regular on board; a 3rd copy turns it golden) · 2. Cast
  Methodical Madness`, then `3. Buy Flaming Enforcer (growth engine)`. A hold
  and a keyword spell are not 7 HP worth of stats. The player at least bought
  bodies that turn (Ashen Corruptor and Trapped Clapper, both completing goldens)
  but left the two cards the coach's own hand steps kept ranking — `Play Brann
  Bronzebeard · Play Leeroy the Reckless` — in hand with the board full, paying
  neither the sell nor the play.
- **Game 3 — the level ladder and the honesty mark were right.** `LEVEL to tier 5
  (you're strong — convert it into a tier) — 3 left` (t9) and `LEVEL to tier 6
  (you're strong — convert it into a tier)` (declined at t12, taken at t13) were
  the right conversions for a 583→949-stat board; at 2 HP the forecast correctly
  refused to say "favored" (`ahead on paper — 2816 vs ~2118`).
  The player's decline worth flagging is the *plan*, not the tier: at 2 HP the
  steps were `1. Play Blade Collector x2 · 2. Buy Costume Enthusiast (surviving
  until we can commit)` / `2. Buy Tavern Dish Banana (tempo)` — nothing bought a
  wall for a 2-HP hero while the headline said `one bad fight ends it, buy board
  now`.
- **Game 4 — the comp read was right for ten turns.** `scale Quilboar -
  Bristlemane — buy its scalers, cast everything, sell nothing that grows`
  (t5/t6) and `Buy Trench Fighter (committing to Quilboar)` (t10) are the reason
  the board reached 1204 stats. Declining the t10 tier-5 level was reasonable;
  the 4-roll hunt that replaced it was not.

## 8. (c) Player leaks no advice line ever addressed

- **Game 1: eight buy phases with no direction.** The coach never said "you have
  no comp at t5-t8 with four straight losses — either commit to the demons in
  front of you or buy stats". It offered generics instead, and the first
  direction statement came on the death turn (§2).
- **Game 2 t11: 10 gold never spent on the turn that cost 11 HP.**
  `turn_forensics.py`'s gold timeline for t11 has no buy, sell, roll or level
  event at all (`t11 tier 5 income 10`), while the coach's steps were all
  "board is full — sell to make room" plays
  (`1. Play Stalwart Kodo (board is full — sell to make room) · 2. Play Banana
  Slamma (board is full — sell to make room) · 3. Hold Lurking Lionfish`). The
  first lost fight of an otherwise perfect game was fought with 10 unspent gold
  on the table.
- **Game 4: the stat edge was never converted into wins, and nothing asked why.**
  The two costliest losses (t6 -10, t8 -8) came with the stat edge already in
  hand (`close fight — 57 vs ~46`, `close fight — 89 vs ~69`), then 4 rolls at
  the death line bought nothing. `loss_streak` reset on the single t9 win and
  `never_won` was false all game, so "you keep losing with the bigger board"
  never existed as a signal.
- **Game 3: gold burned on tempo at the death line.** `Buy Tavern Dish Banana
  (tempo)`, `Buy Wave of Gold (tempo)`, `Cast Gem Confiscation` all appear at
  2 HP; the coach ranked them, so this one is as much a coach gap as a leak.
- Cross-game roll counts: `roll x5` at 14 HP (game 1 t8), `roll x6/x4` at 15 HP
  (game 2 t12/t13), `roll x7/x5/x9` in game 3's last three turns, `roll x4` at
  14 HP (game 4 t10). The roll step stays in the plan at every HP total because
  nothing in `top_move` distinguishes "spare gold" from "last turn".

## 9. Recurrence, not new: the review tool sees no scout at all

`replay_review.py`'s per-phase advice here shows `opp_stats: None`,
`lobby_opp: None` for **every** phase of all four games (`baseline_opp` supplies
"their"), while the same log fed at `live.py`'s cadence yields
`pairing {1: 1, 2: 4, ... 9: 2}` and a populated `_lobby_stats` (7 records in
game 1, 9-15 in the longer games). The mechanism is the one documented on 09-21
evening §1 (`next_opponent` is set inside `feed()` behind a guard that needs
`hero_card`, which only `analyze()` assigns). Reproduce:

```
single analyze at the settled shop: pairing {0: None, ... 8: None}  lobby_stats []
analyze every 120 lines:           pairing {1: 1, 2: 4, ... 9: 2}   lobby_stats [7 recs]
```

Two consequences for this review: the house tool's printed anchors are all
corpus baselines (so its "your 100 vs their ~91" at game 1 t9 is **not** what
the player saw — live said `~166`), and any live hiccup that delays the first
`analyze()` past t1 leaves the overlay equally blind.

## Action items

1. `board_state.py` — accept the named `Entity=GameEntity` form for
   `BACON_COMBAT_DAMAGE_CAP` (the writes the game actually escalates with) and
   delete the false "only PTL's echo" comment at 322-325; add a regression test
   using the real line form (`TAG_CHANGE Entity=GameEntity
   tag=BACON_COMBAT_DAMAGE_CAP value=5`, GameState stream). Until then the
   mortality clock's first branch is unreachable above 2 HP in every game.
2. `value.situation_line` — never let the 3-clause cap (`bits[:3]`) eat the
   mortality clause: reserve the slot, or emit mortality first. Instance: game 1
   t9 (`DYING at 7 — buy board now` computed, dropped, player died in that
   fight).
3. `value.situation_line` — drop the `lobby >= 100` precondition on the sub-30-HP
   clauses; key fragility on effective HP against observed per-fight damage (this
   session: 2-22, versus a printed cap of 2), not on a lobby median. Instance:
   game 4 t10, 14 eff HP, lobby 93.5, no clause at all, dead one fight later.
4. `value` level flip — the `strong` (≥1.5×) branch needs the same effective-HP
   ceiling the `dying` branch has. Instance: game 4 t10,
   `LEVEL to tier 5 (you're strong — convert it into a tier) — 1 left` at 14 eff
   HP, one fight from death.
5. `value.combat_forecast` + `lobby_opp` — (i) never print a fresh-preview anchor
   without the `~` mark when it is older than the current round and thin (game 2
   t11 `favored — 208 vs 21` from a 3-minion t10 board, 11 HP lost); (ii) carry
   the 09-19 §5 keyword pricing (opponent divine shield / reborn / venomous) —
   game 4 lost 2 of its last 4 fights, one of them lethal, with a 1.3-13× stat
   edge.
6. `comp_progress` — require a comp's `when_to_commit` enabler before declaring
   `ready`/`committing`: game 1 t9 committed `Demons - Self Damage` (hits 2,
   ready True) with no self-damage source on board or in hand.
7. Carry-over from 09-21 evening §1, unchanged: make the scout's pairing capture
   independent of `analyze()` cadence, so the house review tool reports the
   anchors the overlay actually had (and so a slow first `analyze()` cannot leave
   the live coach blind for a whole game).
