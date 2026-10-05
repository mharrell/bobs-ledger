# Learning from Replays — the measurement loop

**Status:** plan only, nothing implemented. Rewritten 2026-10-04, main `f7562a5`.

Supersedes the first version of this document, which was organized around
re-tuning the existing `forecast` thresholds. That approach was abandoned (§1).

The question this answers: replays are about to arrive in volume. How do we turn
them into a *continually improving* algorithm, rather than a folder of logs and a
pile of opinions?

---

## 1. The reshape (decided)

The original plan was to calibrate the existing forecast: a scalar stat ratio,
`board_stats / opp_stats`, thresholded at 1.3 ("favored") and 0.8 ("close").
**That structure is being replaced, not tuned.**

Why: divine shield, venomous, reborn and attack order are precisely the effects
that let a smaller board beat a larger one, and a scalar total cannot see any of
them. The forecast is not under-tuned — it is the wrong shape. `combat_forecast`
already knows this and names shields and venom in its output text while the ratio
that decides the verdict ignores them.

Two further problems with the old target, both settled:

- **"Favored" cannot be promised.** The opponent is usually unknown; the code's
  own freshness rule (`live_coach.py:822`, opponent board usable only if seen
  within 2 rounds) is the standing admission. `lobby_opp` is a median of at most
  three fresh boards — a median of three is not a forecast.
- **The three-way verdict is the wrong output.** A probability over outcomes
  cannot be wrong the way a label can, and it degrades honestly as information
  runs out.

**The replacement:** a combat simulator producing a probability distribution over
fight outcomes, against a *distribution* of plausible opponent boards rather than
a point estimate.

### The target distribution

```
P(win)      — we take their board. Zero damage. THE number that matters.
P(tie)      — both boards die. Also zero damage (rule confirmed by the
              maintainer 2026-10-04; the code agrees — live_coach.py:1436-1437,
              "the winner takes 0; ties take 0").
P(loss)     — we take damage: their tavern tier + surviving minions, capped per
              round by damage_cap (2/5/10/15 observed).
```

Read as bands: **P(win)**, **P(win or tie)** ("at least tie"), **P(damage < cap)**
("at least not full damage"). These are three projections of one joint table, so
publish the table and let the advice layer read whichever projection the situation
calls for — at 6 HP with a 15 cap, P(damage = 0) is what matters; at 30 HP you can
take a risk. That replaces `FAVOR_HP_CEILING = 10` as a crude stand-in.

### What the log already contains (the load-bearing finding)

**The training set for the simulator already exists, and the coach discards it.**

- `live_coach.py:721-726` snapshots minions as `(player, atk+health)` — a
  projection applied to `board_state.snapshots`, which carry the **full minion
  dict**. Per that code's own comment, during combat **both** boards sit in the
  snapshot with a disambiguating `player` field.
- So `(our board, their board, outcome)` is recoverable from logs already on
  disk: the loss is a projection, not missing data.
- `board_state.KEYWORDS` already tracks taunt / divine shield / reborn /
  windfury / poisonous / venomous / stealth / lifesteal / deathrattle, so the
  keyword layer is parsed.

No new data collection, no cloud access, no SPEC change, no privacy surface.

---

## 2. Data inventory (measured)

| Source | Content | Limitation |
|---|---|---|
| `app/decision_logs/` | 2 sessions, 331 advisory records | 2 games; builds `38b9aef` and `ef2a33f` (both pre-fix) |
| HS `Power.log` archives | 6 games, **68 buy phases** | 1 is a 2-phase fragment; placements 1/3/4/5/6 + one `None` |
| Cloud KV `sessions/…` | 4 real games, 527 distinct advisories | duplicate ids; no outcome fields; pre-fix builds |

**Grain matters more than volume.** One session's 212 advisory records are *one
game*. Buy phases are the unit: 68 locally. Any analysis treating records as
independent inflates n roughly 10x and every p-value with it.

**Label counts at the phase grain:** ~38 of 68 phases carry an observable
next-fight label (measured 19 explicit loss labels plus 11 HP-delta observations
in a crude first probe; the exact figure needs a careful pass in Phase 0).

### What the log can and cannot label

- **Loss:** `PREDAMAGE > 0` on the friendly hero. Clean and unambiguous.
- **Win vs tie: NOT distinguishable.** Neither writes hero damage. The
  win/tie split is invisible in the label; the damage bands come from the HP
  delta series instead. This is a known limit, not a defect.
- **Damage taken:** `HEALTH - DAMAGE` carried forward per turn
  (`board_state.py:349-369`) — the series `live_coach._combat_damage` uses.
- **Final placement:** `extract_game.py:222`, offline only (§4 item 4).
- **Opponent identity:** by **seat**, the stable per-player key (`lobby.py`).

---

## 3. The opponent model — three tiers of quality

Rather than predicting one opponent, compute **what we have to beat**. Every
fight is against *someone* in the lobby, so the requirement is a single threshold
— a percentile of lobby strength at this turn — sharpened when the next opponent
is known. The code already falls back through a three-tier ladder; this
strengthens each rung.

| Tier | Source | Quality |
|---|---|---|
| 1. Specific opponent, projected | their own sighting history (below) | best; needs 2 sightings, or 1 + an identified engine |
| 2. Lobby percentile, this turn | observed boards pooled across the lobby | good; improves with corpus size |
| 3. Corpus prior | `baseline_opp` (median opponent stat total per turn) | crude; already exists |

### Growth-rate projection (the maintainer's idea, made concrete)

Tribe tells you **shape, not level**: a Deathrattle player at turn 10 might be at
180 or 800 depending on luck, draws and investment. But the *rate* is measurable:

1. **Observed rate.** The same seat seen at two turns gives `Δstats / Δturns`.
   Measured, not inferred — it embodies their actual play and luck.
2. **Analytic rate.** If their board matches one of the 15 engines in
   `meta/engines.json`, `simulate_growth.simulate_growth(board, scenario, engine)`
   computes the per-turn gain directly — **and lets you project from one sighting
   instead of two.** This is what the "Unbound Tempest at turn 10" intuition was
   reaching for. Its output includes a `deity` block that is deliberately excluded
   from `gain`; respect that.

The analytic route is also better-behaved than naive extrapolation, because the
engine model respects mechanics (a shop-eat engine's growth compounds), where a
straight line does not.

**Three traps, all handled:**
- **Sells make stats fall.** A rate read across a rebuild can be negative. Clamp,
  and fall back to the lobby prior rather than extrapolating backwards.
- **Comp switches.** A large composition change resets the rate; a Beast player
  who pivots to Mechs has no carry-over growth.
- **`blended` snapshots.** `resolve_completed` already flags these and excludes
  them from composition previews. They must also be excluded from *rate*
  estimation — the counter is an upper bound on holdings, so a blended sighting
  inflates the delta.

**Extrapolation discipline:** from turn 10 to 13 an exponential projection can be
badly wrong in both directions. Cap the horizon, widen the band per turn, and
show a range — never a single number.

### Measured: the trajectories exist, and they are noisy (2026-10-04)

A probe substituted a recording `LobbyScout` into a real `LiveCoach` (so the
phase tracking and pairing are production code, with only the resolve step
keeping history instead of overwriting) and ran it over the 5 non-fragment
archived logs. Results:

```
seats per game:           [7, 6, 7, 7, 7]
seats with 2+ sightings:  3, 3, 4, 4, 6
example:  seat 3: t6:9 -> t12:25     seat 7: t5:11 -> t11:19
          seat 8: t2:10 -> t9:38 -> t10:28
consecutive-sighting deltas: n=25
  mean +5.1   median +7.0   stdev 9.2
  positive 18 (72%)   negative 5 (20%)   zero 2 (8%)
```

Three findings, one of them decisive:

1. **Trajectories are real.** Every substantive game yields 2+ sightings for
   3-6 seats, and one seat per game gets 3. So "where were they X turns ago"
   is a question the data can answer — **with 2-3 points, not a curve.**
2. **The signal is noisy, and the noise is the interesting part.** 20% of
   consecutive sightings show a *weaker* board, and the spread (stdev 9.2)
   exceeds the median gain (+7.0). That is the maintainer's observation
   ("much more than expected, but also much less") showing up as variance
   rather than as trend — which is an argument for reporting **direction and
   rate with a widening band**, never a point projection.
3. **The absolute level is wrong**, so this needs a fix before use — see the
   three blockers below.

### Three blockers found by building it

1. **`META_TAGS` has no ATK/HEALTH.** Verified: `tag=ATK` appears **only** as
   bare-entity `TAG_CHANGE` writes (2662 in one game) and **never** in indented
   block form (0). That is the exact shape `lobby._WRITE` already matches, so
   listing the two tags is the whole change — no new parsing.
2. **The scout is dormant unless `analyze()` is called.** `_scout.open_round`
   is gated on `live_coach.friendly` (`live_coach.py:511`), and `friendly` is
   set only by `analyze()` → `_ensure_meta()`. Feeding a whole log without
   periodic `analyze()` left the scout **completely empty** (0 seats, 0
   rounds). This is the hazard `replay_review` documents for opponent pairing,
   and it applies to the entire scout. **Every offline replay that wants scout
   data must call `analyze()` on a cadence**, or it will silently measure
   nothing.
3. **Base stats, not live stats.** `resolve_completed` stores card **counts**;
   joining those to the card DB gives *base* stats, understating a buffed
   board by a wide margin (the probe's totals were ~10x low). The fix is to
   keep the staged entity's live ATK/HEALTH at resolve time, not to join ids
   later — which is why blocker 1 and this one are the same piece of work.

A fourth, inherent limit: combat snapshots capture a board **mid-fight** as
deaths empty it. `_resolve_boards` already picks "the snapshot with the most
opponent presence" for exactly this reason, and any stat series inherits the
resulting wobble. Expect it in the noise above.

### What follows for the projection

The rate is worth having, but the honest output at this sample size is a
**direction with a range**, not a number: "seat 3 was 9 on turn 6 and 25 on turn
12 — gaining steadily" is supportable; "seat 3 will be 41 on turn 15" is not,
because the spread across sightings is larger than the median gain. Report the
observation, mark it with its round, and let the band widen — the same discipline
as §3.

### The self-validating property

The projection is testable **for free**: the next time we meet that seat, compare
what we predicted against what we saw. So the check gets built in from the start,
producing a real error distribution instead of an opinion — and the noise
measured above is exactly what that check would quantify.



The projection is testable **for free**: the next time we meet that seat, compare
what we predicted against what we saw. So the check gets built in from the start,
producing a real error distribution instead of an opinion.

---

## 4. The scouting tracker (maintainer's proposal)

**The panel already exists.** `coach_ui.py:1218-1238` renders a "Next opponent"
box: hero, name, composition tiles, "as of round N" — and the panel comments say
"exact when their board staged, **aged since**". A scout strip already shows
"you N stats · …". So this is not a new panel; it is adding **memory** to a panel
that currently holds one snapshot.

**What already exists:** `lobby.py::resolve_completed` builds
`seats[seat] = {cards, turn, goldens, hero, name, blended}`, keyed by seat.
`fresh_seats(cur_turn, max_age)` already answers "whose snapshot is still fresh".
It simply **overwrites** each seat rather than accumulating.

**The one real gap, found while checking:** `lobby.py:49` is

```python
META_TAGS = ("CONTROLLER", "CARDTYPE", "CREATOR", "PREMIUM", "ZONE_POSITION")
```

— **no ATK or HEALTH.** So the scout tracks *which* minions a seat has, never
*how big* they are, and `merged_holdings()` is a copy-count counter for the pool
ledger, **not** a strength measure. A stat history cannot be derived from what is
stored today. This is the tracker's actual cost: capture ATK/HEALTH for staged
entities in the same combat burst `lobby.py` already parses.

**Composition (tribe/what they are building) needs no new capture** — `cards` is
already a base-cid counter, and `committed(tribe, min_copies, matches)` already
resolves "this seat is on that tribe", with membership delegated to the tribe DB
(compounds, Amalgams) rather than string equality.

### The scout leaks across games (found while checking, 2026-10-04 — FIXED, main `5bf2bc0`)

`live_coach._reset()` runs on every `CREATE_GAME` and rebuilds `gs` and `actions`
— but **never recreated or cleared `self._scout`**. `LobbyScout` had no reset
method (`lobby.py`), and `seats` is instance state. Verified by probe: a seat
resolved at turn 10 of one game was still in `seats` during the *next* game.

Its freshness test then reads it as **fresh**, because the age goes negative and
the check is `<= max_age`:

```
during game 2, at turn 2:  fresh_seats(2, max_age=2) -> {7}
  seat 7: cur_turn 2 - rec turn 10 = -8   (<= 2 -> FRESH)
  merged_holdings(2) -> {'BG31_843': 2}   # last game's cards
```

Consequences, all of them visible to the player:

- **`coach_ui` "Next opponent"** renders the *previous* game's composition for
  that seat — a stranger's board presented as the announced opponent's. This is
  precisely the panel §4 is meant to make trustworthy.
- **`tribe_pressure`** counts the stale seat, so the comps panel's tribe pressure
  is wrong early in a new game.
- **`merged_holdings`** feeds our own pool ledger, so "pool left" is polluted by
  a previous game's cards.

The seat ids line up (`next_opponent` is a seat), which is exactly why the stale
record is accepted rather than failing loudly. Every existing `test_lobby.py`
case stays inside one game, so the boundary is untested.

**Fix:** recreate the scout on `_reset()` (or give it a `reset()` clearing
`seats`, `_names`, `_rounds`, `_resolved`, `_meta`), **and** harden the freshness
comparison to reject a negative age, so the class of bug cannot return silently.
A test must feed two consecutive `CREATE_GAME`s and assert the seats are gone.

This is a precondition for the tracker (§5): adding a history list to a record
that survives a game boundary would carry **another player's trajectory** into the
projection, which is worse than carrying their board.

### Two steps, and step 1 is nearly free

- **Step 1 — memory without prediction.** Show what we have actually seen:
  "t4: 95 · t7: 180" for the same seat, with composition. Zero inference, so no
  risk of a confidently wrong number, and useful on its own — it is information
  the player cannot get in-game. It also proves the plumbing, seat identity, and
  the blended-exclusion rule.
- **Step 2 — projection, only if the backtest earns it.** Add the forward
  estimate once measured error is small enough to be worth showing.

**This feature does not depend on the combat simulator.** The two share the
opponent-model slot but ship independently: step 1 is information display, not
outcome prediction. Given how heavy the other threads are, that separability
matters.

---

## 5. Preconditions — data plumbing before any modelling

Each of these silently corrupts the loop if skipped. **Items 2 and 9 are DONE**
(main `5bf2bc0`, 2026-10-04); the rest are open.

1. **Stop discarding combat detail.** `live_coach.py:721-726` keeps only
   `(player, atk+health)`; retain card, atk, health and keywords per minion. This
   is the simulator's entire training set.
2. **Capture seat stats — DONE** (`lobby.py`, main `5bf2bc0`). ATK/HEALTH are in
   `META_TAGS`, and each seat record now carries `stats` (Σ atk+hp of the
   opponent's minions in the winning position run, frozen at the combat window's
   CLOSE) and `stats_n` (that minion count). Both are `None` when nothing staged
   a readable pair, and forced `None` on a `blended` record — the counter there
   is an upper bound, so a total over it would be one too.

   Two facts worth keeping:

   * **The snapshot must be taken at `close_round()`, not at resolve time.**
     ATK/HEALTH are written several times per entity — staged values, then
     combat wear, then a zeroed/reset pair at teardown. Reading later records a
     corpse (measured: a "board" of 1253), and reading the max records
     combat-only buffs, which are explicitly non-persistent (CLAUDE.md).
   * **The first attempt re-derived the board subset and was wrong.** A naive
     "staged entities minus our controller" filter admitted entities that were
     never on the board (14 entities, 1253 stats). The fix routes the stats
     through `_opp_board`'s existing winner-run selection, so the number
     describes exactly the entities the composition counter does. `lobby._meta`
     tracks no ZONE, so nothing weaker could have disambiguated it.
3. **Call `analyze()` on a cadence in every offline replay.** The scout only
   populates when `friendly` is known, and `friendly` comes from `analyze()` →
   `_ensure_meta()`. A whole-log feed with no `analyze()` yields **zero** scout
   data — measured, twice. Any harness that wants scout/opponent data must
   reproduce the live cadence or it will silently measure nothing. This is the
   same hazard `replay_review` documents for opponent pairing, generalised to
   the whole scout.
4. **`top_move_steps[].card` is `None`** even when `action` names the card
   ("Play Tasty Lobster x2"). Anything keying off `step['card']` — including
   `outcome_audit._plan_shape`'s `pick` branch — sees nothing. Blocks rung 4.
5. **A final-placement label does not exist in the analysis dict.** Only the live
   `current_place`, and nothing re-runs `analyze()` after death, so the game-over
   card inherits the last pre-death standing.
6. **`gold` is `None` for all 212 records** of the 10-03 session (both levels)
   while 10-02 has it on 152/154. Confirm the claimed account-map fix against the
   current build; a `None` purse is a label bug, not a missing value.
7. **`damage_last` is written twice** (`live_coach.py:1510` and `:1632`).
   Redundant today; a future edit to one site will diverge from the other.
8. **`opp_age` can be non-null while `opp_stats` is `None`** — the age then
   describes the *lobby* anchor, not the preview the forecast used. Any
   fresh-vs-stale slice inherits this.
9. **The scout carries a previous game's seats into the next game — DONE**
   (main `5bf2bc0`). `LobbyScout.reset()` clears every per-game field,
   `live_coach._reset()` calls it on `CREATE_GAME`, and `fresh_seats` now
   rejects a NEGATIVE age — the arithmetic that made the leak silent, since
   `cur_turn - rec["turn"] <= max_age` is true for any record from a future
   turn. `test_lobby.TestGameBoundary` owns the boundary; three of those cases
   are the ones that would have caught it.

---

## 6. Methodology rules (not optional)

**Parameter budget.** With ~38 labelled fights and 6 independent games, at most
**2-3 constants may be re-tuned**, and every candidate is reported under
leave-one-game-out validation. Anyone fitting 35 weights against 38 labels is
overfitting; the plan makes that mechanically hard rather than merely discouraged.
This bites hardest on the simulator, which could easily grow a large parameter set
— so the simulator's free parameters must be few and named.

**Graders read outcomes from the log, never from the coach.**
`outcome_audit._summarize` compares *coach-recorded* HP at phase N to
*coach-recorded* HP at phase N+1 — the same parser on both sides, so a health
parse bug moves both and the delta looks perfect. That is circular, and it is
exactly the class of failure this project keeps finding.

**No change without a case.** Either the change flips a named
`validate_advice.py` case (and that edit is the acceptance test) or it adds one.
Silent behaviour changes are this repo's recurring failure mode.

**Build-stamp everything.** A change is only measurable against games played
after it. A game coached across an update is **unusable**, not partially usable —
extend `session_report.build`'s existing refusal-to-name-one-version to the lab.

**Observational honesty.** Calibration improves the coach's *self-consistency*. It
does not prove better player outcomes, and any report must say so.

---

## 7. Baseline checks — the gates before any live-path change

Both are cheap, both are offline, and both are the difference between a hypothesis
and a finding. Neither has been run.

**Check A — how good is what we have?** Grade the current stat-ratio rule against
the ~38 labelled fights. This number is the baseline any simulator must beat, and
establishing it costs almost nothing. Most projects skip this step and cannot
answer "was the new thing better?"

**Check B — does the growth projection work?** Replay the archived logs with the
extended seat capture and ask: for seats seen twice, how well does `Δstats/Δturn`
predict the next sighting? If it is good, the projection earns its place in the
feed. If it is poor, we have spent a week instead of a quarter — and Step 2 of the
tracker is cancelled on evidence rather than on taste.

The probe already gives this a pessimistic prior (§3): with 2-3 sightings per seat
and a spread larger than the median gain, a curve cannot be fitted — only a
direction. Check B is therefore **not** "is the extrapolation accurate" but "is
the *sign* of the change informative", and it should be phrased that way before
it runs, or it will be judged against a standard the data cannot meet.

---

## 8. Phases

### Phase 0 — Lab (no modelling)

Keep full combat detail (§5.1); capture seat stats (§5.2); build `corpus.py`, one
canonical read path over cloud reports / `decision_logs` / `Power.log`, emitting
one row per (session, game, buy phase) with identity (build, game, turn), state,
advice, the player's action, and the outcome — **outcome derived from the log,
independently of the coach**.

**Exit:** a baseline report of per-claim label counts and builds; the `gold` bug
resolved; **Check A's number** recorded. No tuning.

### Phase 1 — Fight table and baseline

Build the fight table from the retained combat detail: every fight as (our board,
their board, damage taken, loss?) — the labelled dataset the simulator trains
against.

**Exit:** the fight table, plus Check A's baseline expressed against it.

### Phase 2 — Crude simulator, graded

A deliberately crude combat model: stats, divine shield, venomous, attack order.
**No deathrattles, no exotic keywords.** Graded against the same labels.

**Exit:** simulator error vs Check A's baseline. If it does not beat the ratio,
stop and report that — the full simulator is not justified.

### Phase 3 — Full simulator, only if Phase 2 earns it

Add deathrattles, reborn, cleave and the rest, one keyword at a time, each with
its own measured delta.

**Exit:** a calibrated `P(win) / P(tie) / P(loss)` on held-out fights.

### Phase 4 — Opponent distribution

The three-tier ladder (§3) and Check B. Projection enabled only for tiers whose
backtest error is acceptable.

**Exit:** Check B's error distribution; tier 1 enabled only if it passes.

### Phase 5 — Surface it

Expose the probability table and the scouting tracker in the overlay (Step 1 of
§4 can ship earlier — it has no dependency on Phases 1-4).

**Exit:** the overlay shows a probability, not a verdict, and observed history is
labelled with its observation round.

### Phase 6 — Widen the report, deliberately

Only once Phases 1-5 show which outcomes predict anything. Expected to be small —
most likely a final-placement field and a per-advisory outcome delta — never a
bulk dump. It is the privacy-control change: own review, own `SPEC` edit, own
consent-scope reading.

---

## 9. What we cannot measure, and should stop implying

- **Placement effect of coaching.** 6 games can only return noise, and it is
  confounded — followed advice correlates with easy spots, so followed-bad and
  ignored-good are *suspected rules*, never proof. `outcome_audit` says this
  itself. Rung 5 stays out of the objective until the corpus is orders larger.
- **Build-to-build win-rate comparisons.** Needs hundreds of games *and* a clean
  per-build slice, which the cloud corpus cannot currently provide.
- **Minion prices from `shop_costs`.** Stale legacy tier tags; flat 3 gold.
- **Opponent buys and sells.** Not recoverable — opponents share the spectator
  player number (`ROADMAP.md`).
- **Win vs tie, per fight.** Not in the log; see §2.

---

## 10. Open decisions

1. **Where do the tools live?** Proposal: `corpus.py` / `calibrate.py` /
   `flips.py` / the simulator in `app/` (they import `live_coach`, `value`,
   `extract_game`); reports to `analysis/`. Neither ships either way, but `app/`
   keeps the imports honest.
2. **Is `HEARTH_TELEMETRY_KEY` set on this machine?** If so, `fetch_sessions.py
   --stats` confirms the cloud corpus size. The plan does not depend on it.
3. **Simulator fidelity budget.** Which keywords are in the crude version, and
   which are deferred? Phase 2's exit depends on this being fixed *before* the
   work, or "crude" quietly becomes "whatever was easiest".
4. **How is a seat's history scoped?** Answered: it must reset per game, and
   today it does not (§4). The tracker's history list inherits that leak, so the
   reset fix is a precondition rather than a follow-up.
5. **Does Step 1 ship alone?** It is the cheapest useful thing here and is
   independent of every other phase. Shipping it early also produces the
   re-sighting data Check B needs.
