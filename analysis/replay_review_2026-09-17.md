# Replay review — 2026-09-17 morning (Reno Jackson, 7th)

Session `Hearthstone_2026_09_17`, game 1 of 1 (07:20–07:42).
Live coach ran **1f6f968** (current main, decision-log `coach_version`) —
the first game on the freshly re-scraped comps DB (2dd6c82). **Hero:**
Reno Jackson (TB_BaconShop_HERO_41). **Trinket:** Deathly Phylactery.
**Placement: 7th**, 11 buy phases, died in the combat after t11 with
`PREDAMAGE=7` at 3 HP (cumulative DAMAGE 34). BattleTag redacted per
sanitize discipline.

The player pivoted into **Beasts - Tasty Lobstah** at t8–t10 (Headhunter
Gryphon, Tasty Lobster ×2 on board, Sprightly Scarab pair, Lurking
Lionfish, Titus Rivendare) and the coach tracked the commit correctly —
the comp box fired (`analysis.target_cards.name = "Beasts - Tasty
Lobstah"`), making this the fresh DB's first live game and the corpus's
first Tasty Lobstah entry (avg 7.0, replay_stats).

## 1. TL;DR

The coach's early curve and mid-game survival gating were right, and —
unlike the previous evening — the **forecast direction was correct in
every losing round** ("behind" before both −10s; no false "favored").
The DYING gate held at t10 (3 HP, no LEVEL offered), though last
night's t16 bug remains **unfixed-but-latent**: today a committed tier-4
comp simply produced no level pressure. The game was lost in the
t8→t9→t10 stretch (−10, −10) against scaling lobbies while the coach's
"stabilize first" advice was broadly right but under-powered — the
board it helped assemble (≈63 stats at t9, ≈94 by t10) was simply
behind. The apparent final phase (t11) was a **turn-rollover flash
under the death combat** — see §3.1's same-day correction: no shop, no
gold, no player decision ever existed there; the death combat resolved
in the same log second.

## 2. Fight timeline (log ground truth)

Coach-visible hp is raw HEALTH (armor separate). Damage events are
`PREDAMAGE` writes on the friendly hero; armor absorbed most early hits.

| fight after buy | PREDAMAGE | through to hp | hp before → after | coach line (at that buy) |
|---|---|---|---|---|
| t4 | 5 | 0 (armor ate it) | 30 → 30 | buy Oozeling Gladiator |
| t5 | 10 | 3 | 30 → 27 | LEVEL to 3 ✓ taken |
| t6 | 4 | 4 | 27 → 23 | "lost 2 straight — buy stats first, LEVEL next turn" |
| t7 | 0 | 0 | 23 → 23 | play golden Vermin, buy Persistent Poet |
| t8 | 10 | 10 | 23 → 13 | LEVEL to 5 (declined by player — right) |
| t9 | 10 | 10 | 13 → 3 | "took 10 last fight — stabilize first; your 52 vs their ~91" |
| t10 | 0 | 0 | 3 → 3 | "too fragile to level; your 94 vs their ~170" |
| t11 | 7 | 7 | 3 → **dead, 7th** | (no phase existed — §3.1) |

The t8 fight was against **Snake Eyes** (same hero as the 2026-09-16
evening game, seat p11 staging); per-fight opponent attribution beyond
that is not derivable from hero-tag windows — see §5 (all staged
opponent heroes share the `player=11` slot).

## 3. Findings (ranked)

### 3.1 CORRECTION (same day): there was no t11 buy phase

The morning version of this section accused the live coach of going
silent for a "7-second final phase". Ground truth from the raw log
(bounded extract, lines 141693–147913 of the session Power.log): the
`STEP MAIN_ACTION` write at 07:42:15.816 is a **turn-rollover flash
under the death combat** — the 6,220 lines between it and `MAIN_END`
contain NO options block and NO RESOURCES write; they are the kill
combat itself (the fatal `PREDAMAGE=7` lands at 07:42:15.816, the same
timestamp). No shop existed, no gold was granted, and the player never
had a t11 decision to make. The live coach's silence was correct
behavior; this doc's original action item 7 (analyze very short
phases) was void. The "10 gold, full hand" reading came from two tools
carrying t10's state across a degenerate phase — replay_review now
marks such phases "(no shop phase — transition/death turn)" instead of
rendering advice for a decision that never existed. The t11
"deploy your hand" plan the offline re-analysis produced was advice
for a phase that never happened.

The player-fact stands unchanged: they died 7th in the combat right
after t10, at 3 HP, with a full hand and the Lobster one copy from
golden — the regret is real, but it belongs to t10's fight and the
−10s before it, not to a passed turn.

### 3.2 The −10/−10 stretch was priced honestly but coached passively

At t9 and t10 the coach said the correct *direction* (behind, 52 vs 91;
94 vs 170; "stabilize first") — the forecast-honesty gap from the
evening review did not recur. But "stabilize first" never said *what
would actually survive*. The board grew 37 → 63 → 94 stats across
t8–t10 and still bled 10/round; the lobby's tempo was simply faster.
This is the friendly-side version of the opponent-engine gap: the coach
can price "you're behind" but cannot yet answer "behind by enough that
only a triple (Lobster was one copy away) or a wall changes the
outcome." Engine-urgency detection (the t6–t8 ignition gap from the
09-16 morning review) is the same arc.

### 3.3 DYING gate: held today, still unfixed

t10 at 3 HP: no LEVEL offered, plan led with Titus/Sly Raptor/hold +
board buys — correct. But `DYING_HEALTH=12` predates last night's t16
incident (71d2bd0/c8b2c4b); the t16 "LEVEL to tier 6 while DYING" bug
was never patched — today's game just never triggered it (a committed
tier-4 comp wants tier-4 pieces, so no level pressure existed). The
hard-gate action item from last night stays open and stays the top
design item.

### 3.4 The pivot was player-driven and comp-correct

The player declined LEVEL-to-5 at t8 (23 HP) to buy beasts — right
call, the level would have entered the −10 round a tempo behind. The
coach's shop picks t6–t8 (Eternal Knight, Persistent Poet, Forest
Rover) went untaken and the Tasty Lobstah commit at t9 came from the
player's Lobster/Scarab/Lionfish buys, which the comp tracker then
adopted within the same phase. Selling the golden Buzzing Vermin at t10
(07:41:19, 1 gold) was the pivot's real cost — the 8/8 golden body and
its earlier "goldens never combine" hold were the pre-pivot plan; by
t10 the slot was worth more to the Lobstah board. Not scored as a
mistake; worth knowing the coach blessed neither the pivot nor the
sell explicitly.

## 4. What worked (validated)

- Standard curve t3/t5 LEVELs — taken, correct both times.
- "golden body — goldens never combine" t7/t10; "Hold Tasty Lobster
  (1 regular on board; a 3rd copy turns it golden)" t10 — the
  golden-triple rule rendering in live advice exactly when the player
  held copies.
- Forecast direction correct in all four losing rounds ("behind"
  before each −3/−4/−10/−10) — the evening's false-"favored" failure
  did not recur (this lobby's boards staged legibly).
- No gold-0 cast advice all game (the evening's §3.3 family absent).
- Comp box committed Tasty Lobstah and stayed committed — no flip, no
  on-Naga-board nonsense; the fresh comps DB's first live run held up.

## 5. Tooling notes (log forensics)

- **All staged opponent heroes share `player=11`** in the combat
  staging stream — per-fight opponent attribution from hero-tag windows
  is impossible; `lobby.py`'s position-run grouping (or combat-block
  pairing) is the right primitive for review forensics. Hero-tag
  windows do identify *a* participant (07:37:36 → Snake Eyes) only
  because one hero's writes happened to land in-window.
- Early fights: `PREDAMAGE` ≠ pool damage while armor absorbs (−5 with
  15 armor = 0 through). The coach's `hp` field is raw HEALTH; the
  `DYING_HEALTH` comment says "effective (hp+armor)" — verify the live
  path actually adds armor before trusting the DYING threshold.
- RESOLVED (same day): replay_review's t11 "gold 0" vs turn_forensics
  t11 "income 10" — neither model was wrong; the phase was never a
  shopping turn (§3.1). Both numbers were t10 state carried across a
  rollover that granted no RESOURCES and printed no options.
  replay_review now prints "(no shop phase — transition/death turn)"
  for such phases instead of a coach line off a stale purse.
- The decision log carries the comp target in
  `analysis.target_cards.name`; `analysis.comps` is null in 1f6f968
  records — parse the right field.
- Golden skin ids (`BG31_803_G`) and hero skins
  (`TB_BaconShop_HERO_56_SKIN_F` Alexstrasza) resolved to names fine
  this session.

## 6. Coach-vs-player verdict table (per buy phase)

| t | coach (top step) | player did | verdict |
|---|---|---|---|
| 1 | Buy Buzzing Vermin | took it | ✓ both |
| 2 | pass (0 gold) | pass | ✓ both |
| 3 | LEVEL to 2 | leveled | ✓ both |
| 4 | Buy Oozeling Gladiator | Prisonguard + Recruit a Trainee | close (coach #2 taken) |
| 5 | LEVEL to 3; roll leftover | leveled (no roll) | ✓ close |
| 6 | Buy Eternal Knight; "LEVEL next — buy stats first" | leveled anyway | player took the level the coach deferred; −4 anyway |
| 7 | Play golden Vermin ×2; buy Poet | Boon of Beetles + rolls + golden play | ✓ golden handled, pick skipped |
| 8 | LEVEL to 5 | beast buys (Scarab, Sky-hatch) | player right — enter −10 round with board, not tempo |
| 9 | play hand; Buy Tasty Lobster (committing to Beast); "stabilize first" | Lobster + churn (5 sells) | ✓ commit taken; churn partly real juggling |
| 10 | Titus + Sly Raptor; Hold Lobster; "too fragile to level" | 2nd Lobster path, sold golden Vermin, 4 rolls | commit followed; pivot cost §3.4 |
| 11 | (no phase — see §3.1 correction) | died in the rollover combat | not a turn; nothing to score |

## 7. Action items (status as of the 2026-09-17 work session)

1. DYING hard gate on LEVEL — **LANDED** (value.py: the affordable
   deferred branch is gated; see commit "Hard gates from the
   09-16/09-17 reviews").
2. Gold-gate cast steps — **LANDED** (casts spend their spell price,
   demote to a hold when the purse can't cover them after the plan's
   buy; the hand_plan "casts are free" docstring was the root claim and
   is corrected).
3. Forecast honesty — **LANDED** (estimates render "~" + "seen N
   rounds ago"; "favored" caps to "ahead on paper" at ≤10 eff HP).
4. Comp-flip persistence — **LANDED** (no cross-tribe flip while
   DYING; evidence-free flips need >1 tribe unit on board).
5. Non-recipe hero-power fuel specs (Snake Eyes, Reno) — open.
6. Player_actions sell artifact — **LANDED** (magnetic plays excluded
   from the sell backstop; mechanics field was already in minions.json).
7. Live loop short-phase analysis — **VOID**: t11 was not a phase
   (§3.1 correction). The live loop had nothing to advise on.
8. Per-fight opponent attribution — open (tooling).
9. Gold reconciliation — **RESOLVED** (§5): degenerate phase, both
   tools carried t10 state; replay_review now marks it.
