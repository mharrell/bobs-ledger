# Unit-test audit — paradoxes, wrong rules, and goal alignment

2026-09-19 · report-only pass (per Mike: report first, fixes after sign-off) ·
companion file: `test_audit_inventory.md` (per-test index, all 583)

## Method

- **Phase 0 — inventory.** Script-generated index of all 583 tests (36
  files): class, name, LOC, docstring, fixture kind, modules pinned,
  assertion count.
- **Phase 1a — hoop smells.** Date-annotated incident comments and
  scope-guard flags mined per production module; clusters = the "weird
  hoops" (where incident patches accumulate, paradoxes hide).
- **Phase 1b — invariant cross-reference.** Tests collapsed into rule
  domains; each domain's invariants checked pairwise and against the
  canon (CLAUDE.md + memory player rules). Deep-read of every flagged
  family's bodies; the rest triaged via docstrings.
- **Phase 3 — goal alignment.** Every test must answer "what wrong
  advice does this prevent?"; every past live incident must map to a
  guarding test.

Fixture mix: 403 pure-function, 86 synthetic-analysis-dict, 79
synthetic-log-feed, 11 mock, 3 real-log-dependent.

## Hoop hotspots (phase 1a)

Incident-comment density: **value.py 93**, live_coach 42, coach_ui 23,
board_state 20, bans 8 — everyone else ≤ 7. Scope guards: `_bans_ready`
(live_coach), `_zone_shop` (live_coach), `_combat_only_gain` markers
(value).

Verdict: the hoops are **incident-driven and goal-aligned**. Each cluster
we read carries a dated player rule or replay review, pins exceptions to
*a specific card text* (not a blanket), and has tests on both the rule
and its carve-out:

- combat-only gains (15 tests): the marker/override machinery (`Rally`
  is combat-only; Vineweaver's "permanent" wording persists; hand-targeted
  gains persist; self-improving engines are their own class) — consistent,
  each pair pins distinct texts.
- hunt recency (gone-cold at 6 turns vs recent-sighting vs legacy
  untracked callers) — one coherent semantics.
- sticky comp targeting + dying carve-out (09-18 regression) — freeze
  rule with a deliberate dominant-board exception, both sides tested.
- tavern-buff demotion — effect-level rule, cleanly scoped away from
  pricing (verified when the cast gate came out).

The one hoop that encoded a *wrong* rule was the 2026-09-16 cast gold
gate — removed this session (see F0). No other wrong-rule hoop found.

## Findings

### F0 — the pattern case (resolved this session)

`TestCastGoldGate` (old) pinned "hand casts cost their spell price" while
`board_state.py`'s docstring said free. Green suite, mechanically wrong
rule, code carried a demotion hoop for it. Broken by player report + log
forensics (PLAY-from-HAND blocks move no RESOURCES_USED). Tests rewritten
same day. This is exactly the failure class this audit hunts; it took an
outside signal to catch.

### F1 — memory vs test conflict: below-tier cores and the Q1 stay (ASK)

Memory (`hearth-replay-review-2026-09-11`) flags as a defect: "Q1
stay-line still counts below-tier cores as reachable (follow-up)."
`test_lower_tier_core_counts_as_here` (test_live_updates) pins the
opposite as *correct*: a tier-3 core while at tier 4 justifies staying,
"leveling dilutes sub-tier pool shares." The test's rationale is
game-coherent (at t5 a t3 minion is a smaller share of every roll), and
the test postdates the memory — so the likely truth is the memory is
stale and the rule was reconsidered. **Ask Mike** (Q1 below); on
confirmation, update the memory, not the test.

### F2 — rule-vs-game gap: flat-3 absolutism vs price-modifier trinkets (ASK)

`MINION_BUY_PRICE = 3` is pinned absolute by three test families
(`test_minion_costs_flat_three` ×2, `test_golden_priced_flat_three`) and
`_buy_prices` has no modifier input. But the game has real, current
exceptions — both sitting in the trinket DB we curated tonight:
Electrode Attractor ("Magnetic Mechs cost (2)") and Bazaar Sticker ("1
Tavern spell/turn costs Health instead of Gold"). When one is active,
the affordability walk misprices the affected cards (under-prices
nothing; over-prices magnetic mechs at 3g, and health-costs are invisible
to the gold purse). Whether to model this is a design call: a one-trinket
fudge vs a price-modifier hook. **Ask Mike** (Q2 below); the player rule
should read "flat 3 default; text overrides when a trinket says so" if he
wants the hook.

### F3 — designed two-layer tension: fail-open vs fail-closed bans (document only)

`is_banned`/`filter_comps_by_available_tribes` fail OPEN on no ban info
("an unknown ban must not look like all-banned"), while the live
detection window fails CLOSED (advisory list = confirmed-tribe comps
only, 0/5 ⇒ empty). Both are tested, both are intentional, and the
rationale is documented on both sides — but they are opposite responses
to the same input ("no ban info"), and the next refactor can easily
"unify" them wrongly. Disposition: keep both; add a cross-reference
comment at both sites naming the other (no behavior change).

### F4 — docstring drift, same rule (tidy only)

`test_price_drops_per_turn_at_tier` says "tier+5 minus turns at the
tier"; CLAUDE.md says "start at (target+3), drop 1 per round waited."
Same rule, different indexing (tier+5−k ≡ target+3−(k−1)); live button
COST is authoritative anyway. Reword one of the two to the other's
indexing.

### F5 — missing coverage (incidents without guards)

1. **Forecast opponent-scaling / keyword pricing — no test.** The
   09-16-evening death ("favored 895 vs 165 → took 19") and the 09-19
   Marin fix ("opponent keyword pricing promoted in the forecast arc")
   have no guarding test. Highest-value new test: a forecast where the
   opponent's known scaling engine flips the verdict.
2. **Clock-runout scoring — no test.** "Leftover gold/hand at phase end
   may be a clock runout, not a mistake" (player rule 09-11) lives in
   replay_review's scoring with no test.
3. **Never-won ladder turn-2 boundary** — the `turn >= 3` sample gate is
   tested only at turn 5; a turn-2 not-deferring test would pin the
   boundary (at t2 every game is 0-wins; an ungated defer would stall
   every early curve).
4. **Price-modifier trinkets** — becomes a test if Q2 says model them.

### F6 — open items cross-checked (not test gaps)

- Nomi board-contamination data-gate: still deliberately pending
  (`validate_advice.py:120` flips when the extractor fix lands).
- BG36 demon-consume package: meta-content gap (Mike: capped synergy
  layer, not a comp core) — a curation task, not a test.
- Environment-dependent tests (trinket coverage ×6-newest-logs, sanitize
  real-log, integration_real_log, friendly-player real-log): skip
  without local logs — fine on this machine, worth remembering when the
  suite runs anywhere else.

### F7 — no vacuous, orphaned, or dead-design tests found

Every test family traced to a live consumer; no assertion that cannot
fail; no pins to removed designs (the 4-digit trinket id era is pinned
*negatively* — `test_sous_chef_under_log_id` asserts the OLD id is
absent — which is correct). Non-coaching tests (sanitize, corpus,
scrape-diff, art) are pipeline guards by design and labeled as such.

## Goal alignment (phase 3)

Incident → guarding test, spot map (full map lives in the inventory
docstrings): Bream-Counter hand engine → `test_hand_engine`; golden
triple rules → `TestHandPlan`/`TestBuyIntentionTriple`; mid-phase shop
blindness → `test_zone_shop`; phantom hand → `TestBareEntityTagChanges`;
comp-blind naga pivot → `test_hybrid_comp_survives_with_blocked_pieces`;
dead-opponent lock-in → `test_friendly_player`; DYING t16 →
`TestDyingHardGate`; never-won 5k → `TestNeverWonLadder`; Them Apples →
`TestTavernBuffWaste`; locked Thorim hand → `test_locked_hand`; hand
can't sell → `test_sell_row_excludes_hand_minions`; armor one-pool →
`TestArmorFlow`; trinket id drift → `test_trinket_meta`; unranked picks
→ `test_unranked_pick_never_blessed`; discover labels →
`test_discover_labels_key_on_the_displayed_comp`. Unmapped: the two in
F5.1–F5.2.

## Dispositions

| Action | Items |
|---|---|
| Ask player | ~~F1 (below-tier Q1), F2 (flat-3 exceptions)~~ — ANSWERED 2026-09-20, see below |
| New tests | F5.3 t2 boundary (LANDED); F5.1/F5.2 re-scoped — see below |
| Comment cross-refs | F3 (fail-open/fail-closed both sites) — LANDED |
| Wording | F4 (level-cost formula docstring) — LANDED |
| Memory update | F1 outcome — LANDED (ruling: below-tier cores never justify staying) |
| Keep as-is | everything else — no deletions, no rewrites |

## Rulings and what landed (2026-09-20)

**Q1 ruling: below-tier cores do NOT justify staying.** The 09-11
review's objection was right; the `here = this tier or below` test had
enshrined the defect. Landed: `_stay_counts` now buckets `t == tier` as
here and treats `t < tier` as neutral (findable before and after
leveling — justifies neither a stay nor a level). Test rewritten
(`test_lower_tier_core_does_not_hold_the_stay`: at tier 4 a missing tier-3
core no longer freezes the curve). 588 tests green.

**Flat-3 ruling: model the text-stated exceptions.** Landed:
- `_buy_prices` applies Electrode Attractor ("Magnetic Mechs cost (2)")
  to magnetic minions when held (overlay + walk share the layer).
- Bazaar Sticker ("1 Tavern spell/turn costs Health instead of Gold")
  can't live in a flat map: the plan walk discounts the ONE spell it
  would buy, says "costs Health instead of gold (Bazaar Sticker)" in the
  buy line, and refuses the discount while DYING (a health spend at ≤12
  eff HP is how runs end). The overlay's per-card price stays the gold
  figure. Tests: `TestPriceModifiers` (4 cases).

**F5 re-scoped — the two "missing tests" were missing IMPLEMENTATION:**
- F5.1 forecast opponent-scaling: the keyword pricing was a design
  direction in the 09-19 review, never built (`combat_forecast`'s
  docstring admits "the opponent's keywords aren't tracked yet"). A test
  for unbuilt behavior is not writable — this is now the top design
  candidate: lobby scout collects DIVINE_SHIELD/REBORN counts from the
  staged stream (verified available there), prices
  eff = raw + shields×avg-hit + reborn×body, and the forecast says the
  honest line ("their ~163 raw, but 4 shields + 2 reborn — closer to a
  wall than the ratio says"). Test lands with the feature.
- F5.2 clock-runout: also a recorded rule with no code (leftover
  gold/hand at phase end is currently scored nowhere in replay_review —
  nothing to test). If it should be scored automatically, that's a
  detector feature (phase-end + timer-gap detection), design first.
- F5.3 landed: `test_zero_wins_alarm_needs_a_sample` pins the turn-2
  boundary (at t2 every game is 0-wins; the defer must wait for the
  3-turn sample).
