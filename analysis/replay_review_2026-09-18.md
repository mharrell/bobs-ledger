# Replay review — 2026-09-18 (Faelin 7th, Buttons 8th)

Session `Hearthstone_2026_09_18`, 2 games (07:20 session file
closed ~10:48). Live coach ran **1f8492c** (current main — every gate
from the 09-16/09-17 reviews live). **Game 1:** Ambassador Faelin,
**7th**, 10 phases (t1 skipped by the hero power). **Game 2:** Buttons,
**8th (last)**, 10 phases — died in the t10 fight after the plan's
LEVEL-5-at-14-HP turn. BattleTag redacted.

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
