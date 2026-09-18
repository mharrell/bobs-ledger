# Replay review — 2026-09-18 (Faelin 7th, Buttons 8th, Gallywix 5th, Marin 1st)

Session `Hearthstone_2026_09_18`, 4 games (closed ~11:46).
Live coach ran **1f8492c** in games 1–2 and **099de10** from game 3
(the comp double-count fix, restarted between games). **Game 1:**
Ambassador Faelin, **7th**, 10 phases (t1 skipped by the hero power).
**Game 2:** Buttons, **8th (last)**, 10 phases — died in the t10 fight
after the plan's LEVEL-5-at-14-HP turn. **Game 3:** Trade Prince
Gallywix, **5th** — held tier 3 through t6–t7 against three
LEVEL-to-4 advices, fought back to a golden Tasty Lobster triple, died
t11 behind at "126 vs their ~163". **Game 4:** Marin the Manager,
**1st** — at 4 HP at t16 with a triple-golden Mech core the coach's
label was stuck on "Nagas" (§7), and the spell-buff Nagas (Fauna
Whisperer ×2 + Balinda) carried the fights to the win. BattleTag
redacted.

## 1. TL;DR

Both losses are **tempo/curve losses, not coach failures** — and every
gate landed this week behaved. No gold-0 casts, no phantom magnetic
sells, no one-unit comp flips (Dragons - Battlecries and Beasts - Tasty
Lobstah commits were both real), and the DYING gate never offered LEVEL
at ≤12 effective HP — Buttons' t10 LEVEL-to-5 at **14** HP was legal
under the gate as specified, and that borderline is the session's one
real coach finding (§3.1). The Buttons game was lost from t4: four
straight fights by t7 with a 13-vs-23 board, and the plan's read kept
resetting because the flip ladder keys on the LAST fight only (a
won/tied t9 fight erased a 10-a-round bleed from the loss-streak
signal). Game 1 was lost to player deviations: leveling against
"stabilize first" at t7, then churning the engine at t8.

## 2. Fight timelines (coach hp series, log ground truth)

**Game 1 (Faelin):** 30 → 23 (t6) → 15 (t7) → 5 (t8) → died in t9's
fight, 7th. Board was 106 vs their ~91 at t9 — "close fight" honest,
but the staged-stats optimism (opponent engines under-priced, the
09-16-evening gap) still cost the fight.

**Game 2 (Buttons):** 30 → 24 (t7, "lost 4 straight") → 14 (t8, −10) →
14 (t9, won/tied — streak reset) → 14 at t10's phase → t10 fight −10 →
dead 8th. PREDAMAGE reads pre-armor; the hp series is the truth.

## 3. Findings (ranked)

### 3.1 The 13–16 effective-HP band has no coaching signal

t10, 14 HP, having bled 10 in two of the last three fights: the plan
led with board deploys, then "**LEVEL to tier 5 (standard curve)** — 1
left · no hunt — Titus Rivendare, Tasty Lobster (needs tier 5)". The
player read it as the build being one level from taking off — and died
8th in the fight, 10 gold unspent, holding the pivot. The DYING gate
(≤12) correctly did not fire; the forecast cap ("ahead on paper") fires
at ≤10; the flip ladder saw no loss streak (t9's won/tied fight reset
it) and no last-fight damage (0). Every gate legal, and the plan still
pointed a one-10-hit-from-death board at a tier purchase plus a
tier-5-locked hunt. This is the t16 shape one band higher: comp-driven
LEVEL at "dying next fight" HP.
Design candidates (design-first):
(a) a FRAGILE band (13–16): LEVEL renders only with the fragility
clause ("you die to a 10-hit — the board comes first"), mirroring the
flip text; (b) damage memory: the ladder weighs last-3-fights damage
(sum ≥ 15 ⇒ stabilize-first) instead of streak-resettable signals.

### 3.2 Buttons t2: a phase with no shop and no income, mid-game

Both games have a "no options block" phase — Faelin's is explained
(the skip-power's tier-6/4/2 discover screen); **Buttons' is not**: its
power is turn-8-shaped, yet t2 printed no options and granted no
income (t3's gold 5 means t2's 4 never existed). The player lost a
whole turn's tempo to whatever that was, and the coach had nothing to
say because there was nothing to advise on. Small forensics item:
check whether a reconnect/loading stall or a client glitch produces
MAIN_ACTION flashes without shops in live sessions.

### 3.3 Game 1's loss was player-driven (and honestly coached)

The coach's t7 line was "Buy Might of Stormwind; LEVEL next turn (lost
3 straight — stabilize first)"; the player leveled anyway (−8 that
round). t8 the coach wanted Dead Bellringer (growth); the player sold
the Patient Scout engine + 3 more and rolled 3×. t9 at 5 HP the coach's
deploy was correct and the forecast honest — the fight just wasn't
winnable at 106 vs ~91 against a scaling board. Not scored as coach
misses; the streak of leveling-into-losses is the same player pattern
the 09-15 reviews noted.

## 4. Gates validated (all seven from the 09-16/09-17 work)

- DYING hard gate: never fired wrongly; Buttons t10 at 14 was legal
  (§3.1 is a design gap, not a regression).
- Cast gold gate: no gold-0 cast advice in 20 phases (Chef's Choice at
  g1-t9 was funded and correct).
- Comp flips: Dragons - Battlecries (g1-t8) and Beasts - Tasty Lobstah
  (g2-t9) commits stuck; no single-unit flips.
- Forecast honesty: "~" + age marks rendered (Buttons t5 "13 vs their
  ~23").
- Magnetic sells: t8's five sells in game 2 are all real (two
  Sellementals bought-and-sold same phase); no magnetics recorded.
- Degenerate-phase marker: fired correctly in all three no-shop
  phases (Faelin t1/t2, Buttons t2).
- Opponent attribution: turn_forensics now names the fight opponent
  (used during the live review).

## 5. Tooling notes

- Reviewing a LIVE session mid-game gives shifting headers: final
  placement tags don't exist yet, `PLAYER_LEADERBOARD_PLACE` early
  writes are the seating order, and PREDAMAGE is pre-armor. The
  "placement 3 → 6 → 7 → 8" flake in this review was reading a growing
  file. A guard (refuse/warn when the newest session's mtime is < 60s
  old) would prevent it.
- Buttons (BG32_HERO_002) gets a Greater Trinket choice on turn 8 —
  the coach's pick panel handled trinket discovers already; verify a
  turn-8 Greater Trinket renders when this hero comes up.

## 6. Action items

1. (design-first, new) FRAGILE band 13–16 eff HP: fragility-claused
   LEVEL + last-3-fights damage memory in the flip ladder (§3.1).
2. (small, new) Buttons t2 no-shop anomaly forensics (§3.2).
3. (small, new) replay_review guard against live/growing session
   files (§5).
4. Verify the turn-8 Greater Trinket choice renders for Buttons (§5).

## 7. Postscript — same session, later games (landed live)

Two more bugs were found mid-session and landed between games:

- **One card committed a comp** (099de10): `_core_hits` counted a copy
  BOTH as board presence and as a recent acquisition, so one Tasty
  Lobster bought-and-played read as 2/2 hits (the whole commit
  threshold). A copy in both places now counts once; 2 physical copies
  or 2 distinct cores still commit. Found live in game 4's early
  phases (and retroactively explains the same-phase commits in the
  09-16/09-17 reviews).
- **The DYING flip freeze outlived its evidence** (9203f18): game 4's
  triple-golden Mech core (Utility Drone / Balinda / Glambot, all
  golden, 4/6 board) stayed labeled "Nagas" at 4 HP because the
  09-16 rule blocked ALL cross-tribe flips while dying — and the stuck
  target was damping mech buys as off-comp. The freeze now holds only
  when the new comp isn't better evidenced: strictly-more-hits flips,
  and equal-hits board-dominant takeovers flip (commit corrections,
  not churn).

Mechanics footnote from game 4: Balinda Stonehearth is core in BOTH
Mechs-Magnetics/Spells and Nagas-End-Of-Turn/SpellBuff (five tribes'
comps total — hence her shared-utility exclusion), and Fauna
Whisperer ×2 fed off the same spell package as Glambot. "Mechs with
spells" and "Nagas spell-buff" were one engine with two names; the
Naga half carried the 4-HP fights. The morning's pattern across all
four games was mid-game tier pace (three declined LEVEL advices in
games 2–3); the win came from the player's engine-building bailing
out the tempo deficit.

## 8. Afternoon session — George the Fallen 6th, A. F. Kay 3rd

Session `Hearthstone_2026_09_18`, 2 games (closed 17:07),
reviewed from a snapshot taken 17:09 (the §5 live-file guard, applied
as practice). The live coach ran through the session (decision log
written to 17:06; the rotation artifact `decision_unknown.jsonl`
reappeared at the 16:17 launch, as expected from a05ceba).

**Game 1 — George the Fallen, 6th, 13 phases.** Gates all held. The
13–16 eff-HP band advice (§3.1, action item 1) fired correctly twice
(t5 "lost 2 straight… buy stats first; your 4 vs their ~23"; t9 "lost
3 straight… your 41 vs their ~91") — the player leveled anyway both
times and the 6th is consistent with the warned line: mid-game churn
(t8–t9 sold the Patient Scout/Shell Collector engine pieces; t12 sold
eight) plus tier-5 stall while behind. The coach never committed a
comp direction ("no comp direction yet" at t7, hunt honest: Titus
Rivendare / Headhunter Gryphon "hasn't shown in the tavern").

**Game 2 — A. F. Kay, 3rd, 14 phases.** The Murloc commit ran cleanly
end to end: Q1 pass held (t1 bank with Wrath Weaver alternate), the
coach hunted Papa Mrrglton for three consecutive turns and named the
trap cards BEFORE the player bought them ("Primalfin Lookout is
off-build" t12, "Time Management is off-build" t13 — bought anyway,
recorded as player choice), and the endgame line was the coach's:
board scaled to "your 918 vs their ~577" at t14 with the
too-fragile-to-level clause attached. Third with a scaled board is the
lobby math, not an advisory failure.

**Session findings:**

1. **No new bugs.** No phantom hand, no dead-opponent coaching, no
   stuck-comp mislabels (the 9203f18 freeze never had to arbitrate),
   no double-count commits (099de10 held). Parse clean in both games.
2. **§6.1 (FRAGILE band) gets its live validation** — the clause fired
   with correct numbers three times across the two games and the lost
   fights matched the warnings. Keep as-is; no retuning.
3. **Minor advisory tension (note only):** game 1 t5's single line
   paired "Buy Mechagnome Interpreter (growth engine)" as top pick
   with "buy stats first; your 4 vs their ~23" as pick 2's rationale —
   the FRAGILE clause lives in pick 2 while pick 1 contradicts it.
   Worth a ranking-weight look when the fragile-band design work
   (§6.1) happens; no fix today.
4. **Hunts vs buys:** the coach's roll-for-fuel advice was declined
   four times across both games in favor of buying bodies; in game 2
   the hunt was the winning line. Consistent with the 09-15 finding
   (roll-vs-level dual output): the advice is right; the friction is
   behavioral.

Action items: none new. §6.1 design work absorbs item 3.
