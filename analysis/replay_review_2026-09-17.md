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
behind. The final phase (t11) lasted **7 seconds**: 10 gold, a full
hand with a Tasty Lobster one copy from golden, zero actions, dead
7th. The live coach never advised in that window (no decision record at
t11) — a loop-cadence miss, and the one piece of coach behavior this
review flags as a bug.

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
| t11 | 7 | 7 | 3 → **dead, 7th** | (live never advised — §3.1) |

The t8 fight was against **Snake Eyes** (same hero as the 2026-09-16
evening game, seat p11 staging); per-fight opponent attribution beyond
that is not derivable from hero-tag windows — see §5 (all staged
opponent heroes share the `player=11` slot).

## 3. Findings (ranked)

### 3.1 The live coach went silent for the final phase (t11)

The t11 buy phase started 07:42:08 and ended 07:42:15 — 7 seconds, no
actions, no live decision record. The offline re-analysis plan for that
phase was exactly right: "Play Banana Slamma / Tasty Lobster / Sprightly
Scarab (board is full — sell to make room) …" with the Lobster one copy
from golden. Deploying even partially might not have saved 7th
(3 HP vs a healthy lobby), but it is the difference between 7th and 6th
more often than not. The incremental loop analyzed every other phase
within seconds; the 7-second phase slipped past its cadence. Whatever
the trigger ordering is (shop snapshot → analysis → throttling), a
phase that short must still get one analysis pass.

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
- replay_review's t11 "gold 0" vs turn_forensics t11 "income 10" —
  one of the two phase-start gold models is wrong (forensics shows no
  gold actions in-phase, so phase-start gold should be 10). Resolve
  before scoring any leftover-gold pass (buy-phase-timer rule).
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
| 11 | (offline) deploy full hand — sell for room | 7-second pass, 10 gold | §3.1 — live never advised; not scoreable as player mistake |

## 7. Action items (carrying all six from 2026-09-16 evening + new)

1. (design-first) DYING hard gate on LEVEL — **still open** (§3.3).
2. (bug) gold-gate cast steps in `top_move_steps` — untested today, open.
3. (design-first) forecast honesty (snapshot age, no "favored" at ≤10
   eff HP) — did not recur, still open as designed.
4. (bug, small) comp-flip persistence — no flip observed today, open.
5. (design-first) non-recipe hero-power fuel specs (Snake Eyes last
   night; Reno's power never appeared in advice either) — open.
6. (bug, known) player_actions sell artifact — open.
7. (bug, new) **live loop must analyze a phase-start snapshot however
   short the phase** — t11 (7 s) got zero live advice (§3.1).
8. (tooling, new) per-fight opponent attribution needs lobby.py-style
   grouping, not hero-tag windows (§5).
9. (bug, new) reconcile replay_review vs turn_forensics phase-start
   gold at t11 (§5).
