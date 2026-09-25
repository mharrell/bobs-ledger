# Replay review — 2026-09-24 evening (Forest Lord Cenarius)

**Result: 1st.** Session `Hearthstone_2026_09_24` game 1 (snapshot
reviewed, not the live file). 15 buy phases, advice taken 3/15 (20%),
passed 8, not-applicable 4. This is also the first game on the reworked
overlay (300 ms poll, ETag/304, kind-chipped plan, two panes) — the
player's verdict on the tool was "refreshes super fast."

## The headline: a win coached on a PROVISIONAL comp

The build drifted into **Aberrations Deity-feed** — the comp `comp_miner.py`
mined from the player's own corpus on 09-23 (`provisional: true`, 4 games of
evidence). The coach tracked it the whole way: from t12 to t19 the plan
carried "no hunt → N'raqi Sapper (hasn't shown in the tavern)" and "stay on
tier 5 — your comp's missing cores are on this tier or below." That is the
hunt-feasibility language and the comp_target doctrine operating on a comp
that no published source lists. The 09-23 provisional-comp work paid for
itself one day later.

## The three new features, live in one game

- **Discard advice (t12):** "Discard Unbound Tempest (via Mindbending
  Recruiter — least useful card in hand)". The player sold the Tempest
  instead — same card gone, no Deity trigger — and won anyway. Worth a
  glance in the next Deity game: the discard step is new vocabulary.
- **Swap arbiter (t13, t14):** "Swap: play Drifting Sacrifice, sell
  De-volition-ist (5.3 vs 4.6 — marginal)" and "Swap: play Mysterious
  K'Thir, sell Mindbending Recruiter (44.1 vs 18.0 — clearly better)."
  Calibrated language, marginal vs clearly-better, exactly as designed.
- **Level restraint:** the plan stayed "stay on tier 5" for eight straight
  phases while the lobby leveled; at t20 it finally said "LEVEL to tier 6
  (you're strong — convert it into a tier)" — the player stayed 5 and won
  anyway. Both lines were legal; the restraint did not cost the game.

## Adherence, read honestly

20% taken is not the story. The "passed" buys were almost all
sidegrade shopping while the player rolled hard (x7, x7, x5 in the late
phases) hunting the N'raqi pieces the coach's own hunt line named. Where
the plan's #1 was structural (LEVEL at t4/t9/t10, the t12 stay), the
player took it. The coach's specific buy picks (Staff of Enrichment,
Prosthetic Hand, Mechagnome Interpreter, Amber Guardian, Snow Baller) were
passed every time — "growth engine" picks did not survive contact with an
Aberration shop. Signal for the value function: its generic growth-engine
picks are still weaker than its comp-tracking.

## Fixed in passing (found by this review)

- Golden/board-variant ids printed raw in the review's actual-action lines
  (`BG36_318_G`, `BG36_320_G`, `BGFYM_002t`). replay_review now resolves
  `_G`/`t` variants to the base card's name (same convention as the
  overlay's CARDS map), falling back to the original id when unknown.
- `BGFYM_002t` **Aberrant Tentacle** carried in minions.json (0-cost
  Aberration taunt token; the log prints no ATK for it) and moved from
  `seen_not_carried` to the resolved registry — it sits on boards and gets
  sold, so the Sell row must name it.
- **Shark Cannon** (`BG32_MagicItem_232`, "After you spend 10 Gold, give
  your Pirates +1/+1 and improve this") offered in this very game and
  absent from trinkets.json — added with carddef text, a curated guide,
  and its trinket_effects read (Pirates-gated growth engine, base_value 5).
  Its Cannonfire enchantment rides the own-enchantment exemption.

## Data notes

- 6 of 21 turns print "no shop phase — transition/death turn": the combat
  transitions around each fight. Consistent with the known phase-shape
  artifact family; nothing this game contradicts it.
- The preflight's variant strip over-stripped golden-of-token ids
  (`BGFYM_002t_G` → `BGFYM_002`, nonexistent): `_plausible_card` now
  accepts any intermediate strip being known.
