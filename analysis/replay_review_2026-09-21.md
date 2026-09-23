# Replay review — 2026-09-21 (A. F. Kay 1st — the Elemental tavern-pump; Inge 3rd)

Session `Hearthstone_2026_09_21`, 2 games (10:33–11:07), live coach
on **54416c1** — the version stamped on every advisory of the session in
`decision_logs/decision_Power.log.jsonl` (747 renders for 2026-09-21), so the
live quotes below are what the overlay actually showed. Reviewed from branch
`worktree-replays-0921-0922`. **Game 1:** A. F. Kay (`TB_BaconShop_HERO_16`),
**1st**, 18 buy phases, final tier 6. **Game 2:** Inge, the Iron Hymn
(`BG26_HERO_102`), **3rd**, 14 phases, final tier 6. Judged on patch **36.6**
card knowledge only (36.6.1 landed 09-22 and is out of scope). Per-game bans
by `bans.py` pool inference (3-card gate; game 1 shows exactly five pure-tribe
pools at 16–21 distinct minions plus three 1-card leaks — Prosthetic Hand/MECH,
Captain Cookie/MURLOC and Flaming Enforcer/DEMON, the leak class `bans.py`
documents):

- **g1 allowed** Beast · Dragon · **Elemental** · Pirate · Undead
- **g2 allowed** Beast · Mech · Murloc · **Naga** · Quilboar

## 1. Game 1 — the build and its engine (A. F. Kay, 1st)

A. F. Kay's power in 36.6 is "Skip your first two turns, then Discover a
minion from Tier 3 and Tier 4" (`meta/heroes.json`). The player passed t1–t3
and opened at t4 with 5 gold and 3 minions (Waveling, Humon'gozz, Enchanted
Lasso) — the hero-power discovers. From there the whole game is one build:

**An Elemental tavern-pump feeding Unbound Tempest.**

| piece | first on board | text (36.6) |
|---|---|---|
| Waveling | t4 (hero-power Discover) | Deathrattle: after the Tavern is Refreshed this game, give a random minion in it +4/+4 |
| Sand Swirler | t6 (golden t9) | Battlecry: your Elementals give an extra **+2 Attack this game** |
| En-Djinn Blazer | t8 | Battlecry: after the Tavern is Refreshed this game, give a random minion in it +10/+10 |
| Living Prison | t9 (2 copies) | Activate (1): gain the stats of the next minion you buy this turn |
| **Dancing Barnstormer** | **t9** (2nd copy bought t11 → golden t14) | Battlecry **and** Deathrattle: Elementals in the Tavern +8/+8 this game |
| Flaming Enforcer | t10 (golden t15) | End of turn: consume the highest-Health minion in the Tavern |
| Glowing Cinder | t10 (2nd copy t13) | Deathrattle: your Elementals give an extra **+2 Health this game** |
| Flourishing Frostling | t13 (golden t15) | +2/+1 for each Elemental you played this game |
| Balinda Stonehearth | t14 (2nd copy t15) | Your spells that target friendly minions cast twice |
| **Unbound Tempest** | **t16** | After you play 3 Elementals, gain the stats of the highest-Health minion in the Tavern |
| **Unleashed Mana Surge** | **t16** | After you play an Elemental, give your Elementals +2/+3 |

The loop is multiplicative, not additive: Barnstormer/Blazer/Waveling pump the
*tavern* with permanent "this game" stats, Sand Swirler + Glowing Cinder widen
the pump itself, Flaming Enforcer eats the pumped tavern minion at end of turn,
and **Unbound Tempest converts the pumped tavern into permanent board stats
every three Elementals**. Board stat total at each phase close:

`t11 917 → t12 1484 → t13 1708 → t14 2762 → t15 3991 → t16 8342 → t17 13447 →
t18 20149 (23,941 mid-fight)`

The two biggest jumps are the two turns *after* Unbound Tempest landed (t16).
That is the win: a 20k-stat Elemental board at tier 6, on 26 effective HP.

## 2. Game 1 — the fight that decided it

HP ground truth (friendly hero entity 97, `GameState` ARMOR/DAMAGE writes):
30 HP + 15 armor. Four fights lost all game: armor 15→13 at 10:36:47, →10 at
10:37:28, →5 at 10:43:11, then **11:02:16 ARMOR=0 + DAMAGE=4** — the turn-16
fight, −9 (5 armor + 4 HP). Final 26 effective HP; after the turn-7 loss the
hero takes no damage at all until 11:02:16 and none afterwards, so **every
fight from turn 8 to the end of the game was won or tied except the turn-16
one**.

The turn-16 fight is the one that hurt, and it is the one the coach
mispriced. Staged-board ground truth from the combat window (fullest opponent
snapshot, 6 minions, total **15,438**): Snow Baller 319/394, Air Revenant
399/443, golden Meteorite Crasher 1069/1348, Living Prison 1335/1811,
**golden Living Prison 2847/3814**, Flourishing Frostling 640/1019 — an
Elemental mirror with two Activate-fed Living Prisons. Our board at that
advice was 8,342.

The coach said (live, 10:59:53):

> `favored — 6147 vs ~1108, seen 1 round ago (yours: 1 divine shield) · they
> haven't taken damage in 7 rounds`

**~1108 against an actual 15,438: a 14× under-price, on the only fight the
player lost after turn 7.** The mechanism is in `_fresh_opp_stats`:
`opp_stats` requires `_opp_boards[next_opponent]` no older than `turn - 2`, and
seat 7's last committed board was a 46-stat turn-8 board, so the anchor fell
through to `_lobby_stats` — the median of the last two rounds' fights
(1289/928 → 1108.5). The seat was *known* and *silent for 7 rounds*, and the
forecast printed that fact in the same string while calling the fight
"favored".

One turn later the same engine got it right — because the loss had just
committed seat 7's board (11:02:17):

> `behind — 10670 vs 15438, seen 1 round ago; don't take this fight (yours: 1
> divine shield) · they haven't taken damage in 8 rounds`

We won that one (t17: 13,447 vs 15,438), and 11:04:29:

> `close fight — 16357 vs 15438, seen 1 round ago …`

— which was accurate (20,149 → 23,941 vs 15,623, our board ending at 1,912 and
one minion; Buttons dies at 11:06:34, DAMAGE=41). So the fresh-anchor path is
sound; the fallback path is the bug (§4.1).

Eliminations (`DAMAGE` writes): Farseer Nobundo 8th 10:39:40 · Inge 7th
10:49:56 · Loh 6th 10:52:28 · Heistbaron 5th and The Curator 4th 10:57:25
(same round) · Galakrond 3rd 10:59:52 · Buttons 2nd 11:06:34.

## 3. Game 1 — coverage without a shape: the coach was comp-blind for 16 of 18 phases

`comp_progress` was **empty for every phase from t1 to t16** and
`target_comp=None` throughout; the label only appears at t17 ("Elementals -
Unbound Tempest", 1/2 hits, after Unbound Tempest was bought) and t18
("Elementals - Stat scaling", 2/2). The live plans say it in the coach's own
words: t14 — "**no reroll target — no comp direction yet**" with a 2,762-stat
all-Elemental board; t15 — "**no comp direction yet**".

At the same time the coach named the player's pieces constantly. Counting
`top_move` renders across the session the overlay actually wrote
(266 renders in game 1): Glowing Cinder 52×, Sand Swirler 46×, Living Prison
46×, Flourishing Frostling 41×, Unbound Tempest 37×, Waveling 26×, Balinda
21×, Unleashed Mana Surge 14×, Dancing Barnstormer 9×, Flaming Enforcer 8×,
En-Djinn Blazer 3×. **Zero mentions of the comp's own core**: Brann
Bronzebeard, Nomi, Kelp Keeper, Tavern Tempest — 0 renders in the whole game.

The reason is the meta DB, not the ban filter (Elemental is allowed).
`elementals-unbound-tempest` core = Unbound Tempest, Kelp Keeper, Brann,
Nomi, Tavern Tempest; `elementals-stat-scaling` core = Unleashed Mana Surge,
Moat Custodian, Kelp Keeper, Brann, Tavern Tempest. Only two of the eleven
cards the player actually won with (Unbound Tempest, Unleashed Mana Surge)
appear in either core; the pieces that made the board 20k — Dancing
Barnstormer, Flourishing Frostling, Waveling, En-Djinn Blazer, Living Prison,
Sand Swirler, Glowing Cinder — are in **neither core nor addons** of any of
the 24 comps. So `_core_hits` read 0 and `comp_target` stayed None, and the
plan's #1/step-3 filler defaulted to off-build cards:

| phase | coach's buy step (live) | tribe | player did |
|---|---|---|---|
| t8 | Persistent Poet (surviving until we can commit) | Dragon | bought 4 instead (TAKEN on Leaf Through the Pages) |
| t10 | Harmless Bonehead (surviving until we can commit) | Undead t1 | bought Crackling Cyclone + **Glowing Cinder** (TAKEN) |
| t11 | Maw Caster (surviving until we can commit) | Undead t4 | **bought Dancing Barnstormer** — the engine (declined) |
| t15 | Eternal Knight (surviving until we can commit) | Undead t2 | declined (board 3,991) |
| t17 | Fire-forged Evoker (surviving until we can commit) | Dragon t6 | declined (board 13,447) |

t11 is the cleanest coach-wrong/player-right moment of the session: the plan's
third step pointed at an off-build Undead while the shop held **Dancing
Barnstormer** — the card that pumps the tavern the rest of the build consumes
(the player bought the second copy there; the pair went golden at t14). The
board went 917 → 20,149 over the next seven turns.

**Right, and taken** (the coach's procedural spine plus the two picks that
happened to be engine pieces): t4 "Buy Enchanted Lasso (utility)" TAKEN;
t8 "Buy Leaf Through the Pages" TAKEN; t10 "Buy Crackling Cyclone" TAKEN;
t11 "LEVEL to tier 5 (you're strong — convert it into a tier)" taken → tier 5;
t13 "LEVEL to tier 6 (you're strong…)" taken → tier 6; t16 "Buy **Unleashed
Mana Surge** (part of growth cycle)" TAKEN — the +2/+3-per-Elemental team pump;
t18 "Buy **Glowing Cinder** (growth engine)" TAKEN and the game's only
engine-shaped line, "feed the engine — cast Chef's Choice (2g), every Elemental
played feeds Unbound Tempest (quantity beats quality)".

The same phase-frame also produced a mislabelled sell line: t10's "4. **sell
Living Prison** (making room)" went out while the board held *two* Living
Prisons — 4/5 (sell score 0.9) **and 60/48** (score 32.6, one Activate-fed
body) — and the step text names neither. The player sold both.

**Verdict on the win — carried by the player.** The advisory record credits the
coach with three things: the level ladder (t11 "LEVEL to tier 5 (you're strong
— convert it into a tier)", taken; t13 "LEVEL to tier 6", taken), two ranked
shop picks that happened to be engine pieces (t16 Unleashed Mana Surge, t18
Glowing Cinder, both TAKEN), and the t17/t18 forecasts, which were honest once
the fresh seat board existed. Everything that turned 2,762 stats into 20,149 —
the tavern pump (Waveling / Sand Swirler / En-Djinn Blazer / Dancing Barnstormer
/ Glowing Cinder) plus the two cards that convert it (Unbound Tempest, Flaming
Enforcer) — reached the board while `target_comp` was `None` and the plan's buy
step pointed at Persistent Poet / Harmless Bonehead / Maw Caster / Eternal
Knight / Fire-forged Evoker, off-build in every sampled phase. The one advisory
that could have changed a fight's outcome (the t16 forecast) called the losing
fight "favored" by 14×. Nothing in the record explains the curve except the
player's own read of the shop; the coach carried the curve, not the build.

## 4. Bugs

### 4.1 The forecast's fallback anchor drops the known seat

`opp_stats` (the seat's own board) is gated on freshness; when it is stale the
chain is `opp_stats or lobby_opp or baseline_opp` and the *seat's own last-known
board* is discarded outright rather than rendered as "unknown / 8 rounds ago".
In game 1 that is the difference between "favored — 6147 vs ~1108" and the
actual 15,438 (§2). The 09-19 evening review filed the sibling problem
(stat totals vs shields/reborn, "602 vs ~163"); this is a different and more
mechanical defect: **the anchor selection, not the pricing.** The seat-level
record exists at the moment of the advice (`_opp_boards[7]` = a 46-stat turn-8
board) and is simply not used.

### 4.2 The skip-turn guard never fires for A. F. Kay — it is a substring miss

`value.py:1555`:

```python
hp = analysis.get("hero_power") or ""
if (analysis.get("turn") or 0) == 1 and "skip your first turn" in hp.lower():
    return (f"pass — {analysis.get('hero') or 'this hero'} skips turn 1 "
            f"(hero power)")
```

A. F. Kay's curated text is `"Skip your first two turns, then Discover a
minion from Tier 3 and Tier 4."` — **"skip your first two turns" does not
contain "skip your first turn"**, so the guard is dead for exactly the hero it
most obviously exists for. The live log for this session:

```
[2026-09-21T10:36:08] t1  TOP: 1. LEVEL (access to tier 2) · 2. Buy Buzzing Vermin (surviving until we can commit)
[2026-09-21T10:36:47] t3  TOP: 1. LEVEL (access to tier 2) · 2. Buy Glim Guardian (surviving until we can commit)
```

Two phases of unexecutable advice (gold is `None` — a skipped turn writes no
RESOURCES tag; the player passed both, and passed t3 as well). The guard's
docstring names this exact failure mode ("the old planner read 'LEVEL (access
to tier 2) / Buy Flighty Scout' for a turn that doesn't exist"), and the
`== 1` term would not cover the *second* skipped turn even after a substring
fix. Cross-checked against the 09-18 session in the same decision log — that
game's A. F. Kay also rendered `1. LEVEL (access to tier 2) · 2. Buy Wrath
Weaver` at t1 (2026-09-18T16:42:24), so the "Q1 pass held" note in
`replay_review_2026-09-18.md` §8 is contradicted by the log: the guard has
been dead for this hero all along, at least since the 36.6 wording.

## 5. Game 2 — the build, and the two fights that took 3rd (Inge, the Iron Hymn, 3rd)

Bans allow **Naga**, and the player built the spell-buff half of it. Curve:
Ominous Seer (t1) → Fleeing Fugitive ×2 (t3) → Cagey Conjurer (t4, Activate
(1): cast 2 random Tavern spells) → Tranquil Meditative (t7, 2 copies by t8,
golden by t11; Spellcraft: your Tavern spells give an extra +1/+1 this game) →
Fauna Whisperer ×2 (t11/t14; end of turn, cast Natural Blessing on adjacent
minions) →
Gatekeeper Amalgam (t11; whenever you cast a spell on this it casts Misplaced
Tea Set) → **Groundbreaker** (t12 ×2, golden t13; after you play a Naga gain
+1/+1, improved by every 3 spells cast this game) → Balinda Stonehearth (t13;
spells that target friendly minions cast twice) → Torrential Ruiner (t14;
whenever you cast a spell on a Naga, give your minions +2/+3). Fuel is bought
spells, cast free from hand (the 09-19 player rule): Misplaced Tea Set, Lost
Staff of Hamuul, Shifting Tide, Azerite Empowerment, Eonar's Favor, Might of
Stormwind, Natural Blessing, Boundless Potential, Winner's Bread, Planar
Telescope, Alliance Flag. Board: `t8 214 → t11 803 → t12 1487 → t13 3144 →
t14 4436`.

The coach's label here was **right, and on time**: `target_comp` = "Nagas -
End Of Turn/Spell Buff" (2 hits) from t12, and the situation line read
"Nagas build — scaling · strong". t7–t10 it briefly showed "Murlocs -
Family 1/2" (one Kelp Keeper) — no harm.

HP ground truth: 30 HP + 10 armor. Losses: 11:24:41 armor →5; 11:26:00 armor
→0 + DAMAGE=10 (that fight −15); **11:33:30 DAMAGE=22** (the turn-13 fight,
−12); **11:36:06 DAMAGE=40** — dead, 3rd.

Both late losses were fights the ratio called comfortable:

- **t13** (hp 20→8, −12), live 11:31:03 — `favored — 1917 vs ~529, seen 1
  round ago · they haven't taken damage in 9 rounds`. The staged board in that
  combat window was **2,801** (6 minions) and it was a **Murloc** board, not
  Nagas: Twilight Tidehunter 472/168, golden Deepwater Chieftain 460/139,
  golden Captain Cookie 439/116, Shamanic Tidecaller 424/103, Bile Spitter
  390/70, Brann Bronzebeard 12/8.
- **t14** (hp 8 → dead, −18), live 11:33:31 — `ahead on paper — 3896 vs ~1602,
  seen 1 round ago · they haven't taken damage in 5 rounds`. Our board went
  6,684 → 4,300 → 0 across the window while the fullest staged opponent board
  was **2,581** (7 minions), a **Mech** board: Falling Sky Golem 535/344 +
  517/323, Glambot 135/119 + 55/55, golden Metallic Hunter 115/122, Rescue Bot
  84/102, Scrap Scraper 43/32.

Note the honesty mark did its job — `FAVOR_HP_CEILING = 10` capped "favored"
to "ahead on paper" at 8 effective HP — but at **20** HP the t13 fight was
labeled "favored" and cost 12. The 12-damage band is invisible to a ≤10 cap;
that is the 09-18 §3.1 FRAGILE-band gap showing up one band higher.

**Gates that held:** `DYING_HEALTH = 12` never rendered a LEVEL at ≤12 eff
(t14 was 8 and the plan led with board plays); the `never-won` clause rendered
correctly early ("0 wins so far — every fight has cost you HP" at t4); the
forecast's `~`/age marks and the "they haven't taken damage in N rounds"
streak read both fired; no gold-0 casts; comp label stayed Nagas through three
consecutive phases once it committed.

**Declines (all legitimate):** t8 "LEVEL to tier 6 (you're strong)" declined
for two spell buys + a roll (the player leveled at t11 instead); t10 "Buy Tasty
Lobster (scaling combat engine)" — a Beast, legal but off-build — declined; t11
"Buy Metallic Hunter (surviving until we can commit)" (Mech) declined; t12
"Buy Mechagnome Interpreter (growth engine)" (Mech) declined for a spell-only
phase. The coach's off-build filler advice is the same §3 shape as game 1, one
tribe over.

## Action items

1. (bug, small) **Fix the skip-turn substring and make it general.** Match the
   hero power for a skip *count* rather than a fixed phrase — e.g. a regex
   `skip your first (\w+) turns?` mapping word→1/2 — and render the pass
   positionally for the skipped turns, not only `turn == 1`. Two dead phases
   per A. F. Kay game, and it is the guard's own stated purpose (§4.2).
2. (bug, small–medium) **Keep the seat in the forecast fallback chain.** When
   `_opp_boards[next_opponent]` is stale, render the seat's own last-known
   board with its age ("they were 46 eight rounds ago — unknown") instead of
   silently substituting the lobby median; and suppress the "favored" label
   when the seat has bled nothing for ≥5 rounds *and* the anchor is not fresh
   (§4.1, §2).
3. (design-first, medium) **The Elemental comp entries do not describe the
   Elemental build that wins.** `elementals-unbound-tempest` /
   `elementals-stat-scaling` cores are a Brann/Nomi/Kelp-Keeper APM package;
   the tavern-pump engine (Dancing Barnstormer, Flourishing Frostling,
   Waveling, En-Djinn Blazer, Living Prison, Sand Swirler, Glowing Cinder →
   Unbound Tempest) appears in no core or addon in `meta/comps.json`, so
   `comp_progress` read 0 hits for a 16-phase all-Elemental board and the plan
   offered "no comp direction yet" at 2,762 stats (§3). The repair is the
   09-19 Plan-1 shape — a second Elemental comp entry (or an engine recipe)
   whose core *is* the pump package — not a new gate.
4. (small) **Disambiguate same-card sell steps.** "sell Living Prison (making
   room)" when the board holds a 4/5 (score 0.9) and a 60/48 (score 32.6) of
   the same card needs the stat line (or a position) in the step text (§3).
5. (design, carried) **FRAGILE band above 10.** `FAVOR_HP_CEILING = 10` did
   not cover a 20-HP board that took 12 (g2 t13) or a 19-eff board that took
   29 (session B t16, see the afternoon review). Fold this into the open
   09-18 §3.1 item rather than opening a new one.
6. (note, no fix) The degenerate no-shop phase marker fired correctly on all
   three zero-length transitions (g1 t2 and t12, g2 t9); g1's t12 sits exactly
   at Inge's death write. The 09-18 §3.2 forensics item stays open but gained
   no new evidence here.
