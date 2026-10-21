# Coaching in Settle Up — the agreed plan (2026-10-20)

**STATUS: SPECIFIED, NOT STARTED.** No code, no test and no commit exists for
this feature. This document is the handoff for the next session, and it records
the three decisions the maintainer made and the corrections the first draft
needed before any of it could be honest.

Read alongside: `PIVOT.md` (the state/verdict split this must not break) and
`CLAUDE.md` (the "Where THIS session left off" section added the same day).

---

## 1. The ask

Bring the model-vs-player comparison back into the product:

* **only in Settle Up**, never on the Live page;
* behind a switch that is **off by default**;
* the switch is **display-only** — the comparison is always computed and always
  stored, and the switch only stops it being drawn.

The original draft was handed over as a numbered plan in two blocks ("Coaching
in Settle Up" items 1–7, "Coaching switch" items 1–6). It was reviewed against
the code on 2026-10-20; the sections below are the corrected version. §3 lists
what changed and why, so nobody re-litigates it.

---

## 2. Decisions locked (the maintainer, 2026-10-20)

| # | Decision | Consequence |
|---|---|---|
| 1 | **The switch is display-only.** Coaching is computed at build and stored in the replay as it is today; the switch gates rendering only. | No server round-trip for the toggle, no payload shape depends on it, and flipping it on later works without a Rebuild. |
| 2 | **Nothing is stripped from the share report.** | `session_report.SPEC` is untouched. The draft's item 1 ("no model text in shared/telemetry summaries beyond existing counts") is satisfied by the status quo on the Live side and **dropped** for the share side; the draft's 3.4 payload clause is dropped too. |
| 3 | **The evidence line counts the player's own saved games**, as *difference* counts, never as proof the model was right. | Computed at build time from `saved_replays/`, stored on the replay. No corpus claim, no new corpus read at serve time. |

Decision 2 matters because the share report **already** carries the model's
text: `session_report.SPEC` names `top_move` (line 137) and `top_move_steps`
with each step's `reason` (lines 138–140), plus `hand_step_cards` (line 145).
The draft assumed those were already counts-only. They are not, and the
maintainer chose to keep them — they are what lets a collected corpus grade
plans later.

---

## 3. What changed from the first draft, and why

### 3.1 A contradiction

Draft item 2 said "Default On"; draft item 6 said "off by default". Item 6 wins.

### 3.2 Two false premises

* "no model text in shared/telemetry summaries beyond existing counts" — false,
  see §2. Resolved by decision 2.
* "When Off … omit coaching fields (plans taken/ignored counts) from the shared
  summary" — those fields **do not exist** in the share report. `taken` /
  `ignored` are computed in `settle_up._totals` at review time and never leave
  the machine. Resolved by decision 1: this is a screen rule.

### 3.3 A missing data model

Draft item 5 puts a **dashed outline on the model's card** and names it. The
saved replay's phase rows (`settle_up.py:381–395`) carry `plan` (text), `named`
(a *name*), `lead`, `kind`, `verdict`, `reasons` (prose), `buys` (names) — and
**no card id, no offers, no scores**. So:

* there is no id to draw art from, and
* "options available at that moment" is not recorded anywhere.

§6 adds the keys. **Old saved replays will not have them until Rebuilt** — say
so in the release note, the way the 2026-10-09 and 2026-10-10 sessions did.

### 3.4 The comparison engine already exists

This is the finding that shrinks the job. `outcome_audit.disagreement_rows`
(165–198) is already exactly "the model preferred X over Y", and it already
returns the honest numbers:

```python
{"session", "game", "turn", "gold",
 "coach": card, "coach_score": float,
 "player": card, "player_score": float,
 "delta": float}
```

Its docstring already states the rule the draft was going to invent:

> "Skipped, deliberately, when either card is missing from the ranking: the
> player may have rolled before buying, and a card the coach never priced is
> not evidence of anything." (175–178)

That is **"not comparable"**, decided and documented in the source. And the
affordability data the draft's item 2 needs is on the same row already:
`steps`, `level_cost`, `shop_costs` (`outcome_audit.py:146–149`, "so the
affordability check can be made from the row alone").

So the task is **carry + render**, not build an engine.

### 3.5 Eleven findings that shaped the spec

1. **Priority list ≠ four independent preferences.** `top_move_steps` is ordered
   and contingent; flattening it into rows manufactures differences on steps
   that were never affordable. Needs a **not reached** state.
2. **"Available at that moment" is our reconstruction**, not the player's screen
   (the ban list is not in the log). Needs a **not comparable** state, inherited
   from `disagreement_rows`'s own rule.
3. **Per-step dots repeat the "taken" lesson** (`settle_up.py:224–230`): a turn
   where you took the model's card is not a difference because you also bought a
   second thing. Diffs attach to the **phase and kind**, not to each player step.
4. **Amber is already taken.** `coach_ui.py:2577`: "ONE MEANING PER COLOUR:
   amber (`active`) is *you have set this*", and `--warn` amber (524) is
   fragile/out-of-play. "Differs" gets the **`≠` glyph** and a neutral/dashed
   edge, not a third amber meaning.
5. **"Why: <reason with the number>" would usually be empty** — step reasons are
   prose ("committing to Mech"; median 2 steps over 154 cached lines,
   `value.py:1742`). The number must be the **score margin**.
6. **The four fixed rows can't cover the plan.** `_STEP_KINDS` (`value.py`
   ~1630) has level / pick / buy / sell / roll / cast / play / hold / swap /
   discard / note. Rows are derived from the kinds present.
7. **"Play" means hand minions**; spells are `cast`. The draft's "Play" row must
   read "Play (hand)" — merging them is the domain fact this codebase already
   had to untangle (`settle_up.py:254–281`).
8. **The evidence line had no source.** `replay_stats.py` is a maintainer CLI
   (only `comp_miner` imports it); nothing per-decision ships. Hence decision 3.
9. **The Live seam is `tile()`, not the tavern panel.** `lvCard`
   (`coach_ui.py:2521`) wraps `tile` (2181), and the Settle step-through uses
   `tile()` directly (4826, 4845, 4932, 5110). Decorations must be opts-gated
   with a test that a Live payload renders none.
10. **The callout must reflow.** The tavern panel has a "right side" only above
    1200x900; below that it is a flex column (the round-1 "never stretched
    across" lesson).
11. **The limits line already exists**: `settle_up.CAVEAT` (104–107). Reuse it;
    do not write a second caveat that can drift.

---

## 4. Scope and the wall

* Finished games only. Free: `settle_up.rebuild` only runs on a settled game and
  `live_replay` refuses a log that has not ended.
* **Live carries nothing.** `coach_ui.LIVE_VERDICT_KEYS` (87–99) already drops
  the plan, and `LIVE_UNREAD_KEYS` (151–159) is the second, deliberately
  unmerged list. Do **not** add a third mechanism; extend the existing two and
  their pins (`test_live_view.py`, the three halves, plus the emptied-set
  control at 149–150).
* The string-level control is `test_choices.TestTheFactsNameNoRank`. Any new
  label, tag or note that reaches the Live page must be checked against it —
  the key list cannot see wording.

---

## 5. The feature, surface by surface

### 5.1 One derived artifact, computed on the server

> **BUILT 2026-10-20 — see §12 for the shipped shape.** The schema below is the
> first draft; the module follows it except that `model`/`player` are LISTS (the
> mockups' Buy row) and `margin`/`why`/`reason`/`tier` replace the draft's
> narrower fields. `model_pick`/`offers` were dropped as redundant (§12.3).

`coach_diff`: for each phase, for each **kind present in that phase's plan**:

```python
{
  "kind":        "buy" | "sell" | "play" | "cast" | "level" | "roll" | "pick",
  "model":       {"card": id|None, "name": str, "score": float|None},
  "player":      {"cards": [ids], "score": float|None},
  "state":       "same" | "differs" | "not_reached" | "not_comparable",
  "margin":      float|None,   # model_score - player_score, None if either missing
  "why":         str|None,     # only when a number backs it
}
```

Computed **once**, at build, in the same place the phase rows are built. Every
surface below reads it. Four separate JS comparisons would drift — this project
has been bitten twice (the `shop_rank`/entity dedupe, the two coach cadences).

Rules:

* `not_reached` — the plan never got that far (gold at open, `level_cost`,
  `shop_costs`; the affordability data is already on the row). Grey, no `≠`, no
  dot.
* `not_comparable` — the player's card is not in the model's own ranking. Say
  so; never default to `differs`. Inherit `disagreement_rows`' phrasing.
* `differs` requires a shared scale **and** a margin above the threshold.
* Kinds with no shared score (level, roll) carry **no margin and no confidence
  chip** — which is the honest form of "no clear preference".

### 5.2 The rail: "Model vs you" table

Rows derived from the kinds present (typically Level up / Buy / Sell /
Play (hand) / Cast). Columns **Model | You**. A differing row gets `≠` and a
neutral dashed left edge — never amber (§3.5.4), and never colour alone.

Below the table: `Why: <reason with the number>` (the margin), then the evidence
line, then a confidence chip, then the **limits line** = `settle_up.CAVEAT`
verbatim.

Evidence line, decision 3: `"We differed on 9 level-ups across your 18 saved
games"` — a *difference* count from `saved_replays/`. Implement it as
`replay_store.list()` (line 288) summed over the saved phase rows, **computed at
build time and cached on `count + mtime`** so a rebuild does not rescan.

Measured on this machine 2026-10-20: 18 files, 2,212,492 bytes total (~123 KB
average, largest 263 KB). Cheap once, unacceptable per page-open.

Existing action groups stay, collapsed (the `runLength` grouping and the
"≤5 rows open" rule).

### 5.3 Turn strip and step track

* Turn strip: a mark on turns where the **phase lead** differed — not every turn
  that contained any difference (§3.5.3). Carry a `≠` character, not only a
  colour, and an `aria-label`.
* Step track (`coach_ui.py:4760`): a mark on the tick whose step the model
  differed on; the tooltip appends "(differs from the model)".

### 5.4 Step through

* A "differs from the model" chip beside the caption (`coach_ui.py:4782`).
* In the tavern panel, a callout where there is room: `Model preferred X over Y`
  / `Why: …` / confidence. Must reflow at the <1200x900 flex-column branch.
* The player's card gets a solid outline and the model's a **dashed** one plus a
  text tag ("You bought" / "Model preferred"). Note: the step rows are the
  **player's** steps, so the model's card is usually absent from the list — it
  needs a **ghost tile** (`tile(..., {cls: 'ghost'})` already exists, used for
  passed-through cards at 4853).

### 5.5 The switch

Header row, right side, before the `...` menu (`#settle-more`, 1897).

* `<button role="switch" aria-checked="…">` — a real button, so keyboard
  toggling is free. **`aria-checked` carries the state; the accessible name
  stays "Show coaching".** Do not fold "On/Off" into the name.
* Visible: `Show coaching` + `On`/`Off` + a muted `(work in progress)` read from
  **one constant**.
* Tooltip, verbatim: `Model suggestions for finished games. May be wrong;
  observational, not causal.`
* Default **off**. Persist under the page's convention — `localStorage`, key
  `bl-coaching`, read in a `try/catch` like `bl-tab` (4199/5161), `bl-settle-mode`
  (4276/5193) and `bl-lv-open` (2462/2505). There is no single "view settings"
  store; that phrase in the draft meant "another `bl-*` key".
* **Off renders none of it**: table, Why, confidence chip, dots and legend,
  differs chip, tavern callout/outlines/tags, the observational note. The rail
  returns to the action groups and the layout collapses with no empty gaps
  (check the rail's own collapse rules — a shut group is a header at the top of
  nothing).
* No switch on Live.

### 5.6 Copy rules

* "Model preferred X over Y". Never "mistake", never "wrong", never "error".
* Low confidence / small margin → "no clear preference", or say nothing.
* Hide `Why` when no number backs it.
* Extend `_verdict`'s existing vocabulary ("taken", "shortlist only",
  "not taken", "not graded (…)"), do not invent a parallel one.
* "plans taken / ignored" stays **counts only**.

---

## 6. Data model additions (additive, build-time)

> **BUILT 2026-10-20 — see §12.3.** The keys that shipped are `coach_diff` and
> `confidence` on each phase, and `coach_evidence` on the rep. `model_pick` /
> `offers` / `gold_open` were NOT added: the first two are inside `coach_diff`
> already (and a second copy is the drift trap §5.1 warns about), and the gold is
> the phase's existing `gold`. `board_end` is not duplicated either — the
> Summary's ended board is the turn's own board on screen.

On each phase row in `settle_up.build` (`settle_up.py:381–395`), alongside the
existing keys:

```python
"model_pick":  {"kind": ..., "card": <id>, "name": ..., "score": ...} | None,
"offers":      [{"card": id, "score": float}] (top N, from shop_rank/sell_rank),
"gold_open":   int | None,
"coach_diff":  [...]   # §5.1
```

`coach_diff` itself is derived and redundant with the others — store it anyway:
the JS must not re-derive (drift), and a replay read by an older/newer page
still agrees.

Where the data comes from:

* `shop_rank` is already on the `outcome_audit` row (line 153) with scores.
* `steps`, `level_cost`, `shop_costs` are already there (146–149).
* `player_buys`, `spells_cast`, `plays`, `player_actions.sells` are already
  there (140–145).
* Missing: the model's resolved **card id** per non-buy kind, and `sell_rank`.
  Check what `value.top_move` records (`buy_step_card`, `hand_step_cards`,
  1666–1681) and what the analysis carries for sells before adding a producer —
  `LIVE_VERDICT_KEYS` drops `buy_step_card` from the live payload but it is
  still in the analysis.

`session_report.DROPPED_ON_PURPOSE` needs no change (none of this ships). If any
of it ever does, the whitelist `SPEC` refuses the send until the field is named
— that refusal is the privacy control, not an obstacle.

---

## 7. Build order

Four passes in one worktree, each independently reviewable:

1. **Server artifact** — `coach_diff` + the new phase keys + the saved-games
   evidence count. No UI. Unit-tested against a real saved replay. This is the
   pass the maintainer should look at numbers from.
2. **Rail table** — table, Why, confidence, evidence, `CAVEAT`. Still behind a
   flag that is off; test with an env/debug force so the browser tests can see
   it.
3. **Turn strip, step track, step-through chip.**
4. **Outlines, ghost tile, tavern callout** — the pass with the data-model and
   Live-seam risk. Last for a reason.

---

## 8. Test plan

Unit (`app/tests/`):

* `test_coach_diff.py` (new): `not_reached` when the gold was never there;
  `not_comparable` when the player's card is missing from the ranking;
  `differs` only above the margin threshold; a phase where the player took the
  model's card among two buys is **`same`**; a rebuilt old replay without the
  new keys renders nothing and does not raise.
* `test_settle_up.py`: the new phase keys exist and are additive; `CAVEAT` is
  the one limits line.
* `test_session_report.py`: the report is byte-identical with coaching on and
  off (decision 1 — the switch cannot change the payload).
* `test_live_view.py`: a Live payload with coaching enabled carries **no**
  coaching key (extend both lists' pins, keep the emptied-set control).
* `test_choices.py`: any new string that could reach Live against
  `TestTheFactsNameNoRank`.

Browser (`test_settle_browser.py`, the real pins — a layout claim has to be
measured):

* switch: `role="switch"`, `aria-checked` flips, keyboard toggles, the label
  constant is one string, default off on a fresh profile;
* off → zero coaching nodes and no empty rail gap; on → table with the expected
  row kinds;
* `≠` present on a differing row **and** a text/tag alternative present (never
  colour alone);
* the dots appear on the phase-lead turn only, not on a turn with a second buy;
* the tavern callout is measured in **both** layout branches (wide grid and the
  <1200x900 column) — the round-1 lesson;
* Live: no switch, no coaching nodes.

---

## 9. Traps the next session should not have to re-derive

* `tile()` is shared with Live (§3.5.9). Opts-gate every decoration.
* Amber means selection or fragile already (§3.5.4).
* The plan's steps are a priority list (§3.5.1) and the orders encode intent —
  do not re-sort them for display.
* `choices["ranked"][0]` is the plan's pick (`CLAUDE.md`, hazards) — the new
  comparison must agree with it or the review will contradict itself.
* `_verdict`'s "taken" rule is about the card the model **named**, not the
  shortlist (§3.5.3). `disagreement_rows` is the *broader* signal by design.
* A browser driver value containing `<` truncates the capture; use a comma
  (`CLAUDE.md`).
* Old saved replays lack the new keys until Rebuilt.
* `lru_cache`/per-game caching: the evidence count must be cached on file
  count + mtime, not recomputed per request.

---

## 10. Left open for the next session

> **ITEM 1 IS ANSWERED 2026-10-20 — the number is in §12.4** (1.5 clear / 3.0
> strong), measured over the signed margin, because `disagreement_rows` turns out
> to be structurally empty. Items 2-5 stand.

1. The **margin threshold** that separates "clear preference" from "no clear
   preference" — needs a measured distribution over `disagreement_rows`' `delta`
   on the 18 saved games, not a guess. Do this in pass 1 and write the number
   down.
2. Whether `level`/`roll` should carry a *mechanical* confidence (exact gold
   arithmetic, e.g. "the upgrade cost 10, you had 6") instead of no chip. Cheap
   and honest if the gold numbers are exact; skip if not.
3. Whether the ghost tile shows the model's card **art** or a plain outline with
   the name (art needs `img_cache`; a missing image must not leave a hole).
4. The callout's exact micro-layout in the narrow branch.
5. Whether "differs from the model" should also appear in the Saved-replay list
   rows (not requested; answer no unless asked).

---

## 11. Process

* Worktree: `.claude/worktrees/coaching`, branched from **fresh** `main`.
  (Two leftovers exist as of 2026-10-20: `.claude/worktrees/live-replay`, merged
  but not removed, and `.claude/worktrees/settle-up-round3`, which still holds
  5 uncommitted files — leave both alone unless asked.)
* Never commit `CLAUDE.md` or the design notes; they are excluded in both places.
* End the session with `python app/sync.py`, or report "branch X, N commits,
  NOT merged".
* `CLAUDE.md` was at 55,694 bytes of its 65,536 budget on 2026-10-20, so the
  new section in it is a pointer, not a copy of this file.
* Suite baseline before this work: 2053 tests, OK, 109 skipped (Chromium
  available in some sandboxes and not others — a browser that cannot START is a
  SKIP, not a failure).

---

## 12. The mockups, the decisions they settled, and what pass 1 measured
(2026-10-20, later the same day)

### 12.1 Two mockups arrived

The maintainer handed over two screenshots of the Settle Up page with coaching
switched ON:

* **Summary, turn 7** — header `Show coaching: On (work in progress)` as an amber
  switch before `…`; round strip 1–15 with a corner dot on turns 5, 8 and a
  `≠ differs from the model · Observational, not causal` legend; the rail's
  existing `TURN 7 · 14 ACTIONS` header and chips, then a **Model vs you** card
  (confidence chip in its header, `MODEL | YOU` columns, Level up `Yes · tier
  4 → 5` / `No`, Buy `[A], [B]` / `[A], [C]`, Sell `—` / `[D]`, Play `[A]` /
  `[A]`, a solid amber left bar on the three differing rows), then `Why: …`,
  `[stat] · [n] games`, the CAVEAT, and `All 14 actions ▸ collapsed`.
* **Step through, step 12** — `Bought [Minion C]` + a `differs from the model`
  chip; the existing letter step track with the current tick amber and small
  dots on two later ticks; in the Tavern row the bought offer solid-outlined +
  `You bought`, the model's card **in its own offer slot**, dashed +
  `Model preferred`; the callout `Model preferred [E] over [C]` / `Why: …` /
  `confidence: medium · [stat] · [n] games · Observational, not causal`.

The parts that already existed (and the mockups therefore only dressed): the
rail header and its chips, the letter step track and its selected tick, the
Tavern/Board/Hand panels, the `Summary | Step through` header toggle. The parts
that are new are the table, the callout, the tags, the switch, and the dots.

### 12.2 Three decisions the mockups settled, two the plan keeps

1. **Default OFF** — confirmed. The mockups are drawn switched on to show the
   feature.
2. **Amber IS the "differs" colour** — a deliberate exception to §3.5.4, taken
   as an experiment: the table's left bar, the turn-chip dots and the step-track
   dots all ride ONE CSS token (`--tdiff`), so reversing it later is a variable
   change, not a refactor. **Flagged for a potential refactor** in the CSS where
   the token is declared: amber still means "you have set this" (the selected
   turn chip, `Play`, `You bought`), and two meanings under one colour is the
   thing §3.5.4 was protecting against.
3. **Summary = lists, judged against the end-of-phase board; Step through =
   per step.** The summary's Buy row is therefore every card the plan named
   against every card the player bought, with the turn's ENDED board as the
   yardstick beside it (not a re-derivation: that board is already on screen).
   The Step-through callout compares one card to one card, at the step.
4. **`Play (hand)` stays** (§3.5.7) — the mockups' plain `Play` would merge the
   hand-minion and cast vocabularies again.
5. **`CAVEAT` verbatim stays** (§3.5.11) — the callout's shortened
   `… · Observational, not causal` is a second limits line; the callout gets the
   one sentence, or points at the rail's.

### 12.3 What pass 1 built (server artifact only, no page changes)

* **`app/coach_diff.py`** (new): `for_phase(audit_row)` -> the rows;
  `confidence(rows)` -> high/medium/None; `saved_evidence(root=None)` and
  `evidence_line(ev, kind)` -> the difference counts.
* **`settle_up.build`**: `SCHEMA` 2; each phase gains `coach_diff` (list) and
  `confidence`; the rep gains `coach_evidence`. The console report prints one
  `coaching:` line per phase, `same` rows omitted — that line is how pass 1's
  numbers were eyeballed.
* **The row** is
  `{kind, state, model:{asked,cards}, player:{did,cards}, margin, why, reason, tier}`.
  Kinds in display order (level, buy, sell, play, cast, roll, pick); a row exists
  when either side has something to say.
* **States.** `same` = the plan's ask is covered by the player's action (for a
  buy: every named card was bought — the `taken` lesson, so an extra second buy
  is NOT a difference). `differs` = not covered. `not_reached` = the plan's own
  priority list could not pay for the step (a conservative walk: level costs
  `level_cost`, a buy costs the flat 3 unless the cost map prices it at most
  that, a roll 1, everything else 0 — never `shop_costs`' stale minion tags).
  `not_comparable` = nothing to match: a sell step (no id), a pick, a buy/cast
  step whose card did not resolve.
* **The evidence** counts differences per kind across `saved_replays/`, cached on
  the store's file count + mtime + byte size. Two vintages: a rebuilt save
  contributes one count per differing kind; an old save contributes its
  un-taken phase lead. So the figure is a FLOOR — it rises when old saves are
  Rebuilt — and the wording says "differed", never that the model was right.
  On this machine it reads **77 differing moves across 18 games** (buy 38,
  level 29, cast 10), all from the old saves' lead rule until they are Rebuilt.
* **A found trap, and the rule that closes it.** The first cut emitted a row for
  every kind either side had something to say about, and a real game showed
  `play differs` (model `[]`, player 2) on ALMOST EVERY PHASE: `plays` fires
  when an entity moves HAND -> PLAY, which a BOUGHT minion does on its way to
  the board, so the row double-counted the buy. `spells_cast` is broader still —
  the parser counts any id that is not a known minion, so hero powers and triple
  rewards ride it (`TB_BaconShop_HP_046`, `TB_BaconShop_Triples_01`). **A `play`
  or `cast` row now exists only where the PLAN named one**; level/buy/sell/roll
  keep their player-only rows, because those four action records are exact
  (`upgrades`, `player_buys`, `sells`, `refreshes`).
* **Tests**: 35 in `test_coach_diff.py` (states, margin/why, tier, order,
  confidence, evidence caching, the player-only play/cast rule, and a source
  guard that the three live-path modules never import the module), 3 added to
  `test_settle_up.py` (the keys, the console line, an old save rendering
  unchanged).

### 12.4 The measurement (plan §10.1, answered)

Ten of the 18 saved games still have their source log; 112 advised phases across
them.

* **`disagreement_rows` reports ZERO rows, and that is structural.** Its
  `delta > 0` asks whether the player bought a card the coach ranked ABOVE the
  card it recommended — and the plan's buy card is the top of that same ranking,
  so the delta is never positive. §3.4's "the comparison engine already exists"
  was wrong about which engine: the rule survives (a shared scale, skip when
  either side is unpriced), but the *signal* had to be generalised to the signed
  margin `score(model card) - score(best card bought)`.
* **66 phases have a buy step; only 20 are scorable**, and the other 46 bought
  after a roll, so the bought card is not on the ranking the coach settled with.
  This is why the row's STATE comes from the lists (always available) and the
  margin is an enrichment, not the arbiter.
* On the 20: median **+2.8**, 55% at or above 1.5, 40% at or above 3.0, max
  +10.5; the six 0.0s are the phases where the player bought the named card.
* Thresholds: **`MARGIN_CLEAR = 1.5`** (the distribution has a gap between 1.0
  and 2.5) and **`MARGIN_STRONG = 3.0`**. Negative margins are possible in
  principle; only a positive one raises `confidence`, and the plan step's own
  prose reason rides the row for exactly that case.

### 12.5 Open for pass 2 and later

* **Where the graded `Plan — taken` line goes.** It is the only place the
  verdict is currently shown, and the mockup's rail has no verdict line. Do not
  drop the grading to make room for the table: the ledger's point is whether the
  plan was followed, and the table is a different question.
* **`All 14 actions ▸ collapsed`** is a master collapse the current rail does
  not have (groups collapse individually). Decide whether it also folds the
  table (probably not) and whether it replaces the per-group headers.
* **The confidence chip's word.** It is derived from the ranking gap, not from
  any model confidence, so "confidence: medium" is a UI shorthand with a precise
  meaning that the caveat has to survive.
* **Step-through alignment** (pass 4): the k-th player buy step pairs with the
  k-th card in the buy row's `model.cards` — in the plan's order, never re-sorted
  (§9). When the plan's cards run out, the step has no comparison.
* **Old saves**: no keys until Rebuilt; the page must render today's rail
  unchanged (it already does, and `test_settle_up` now pins the report doing
  the same).

---

## 13. Pass 2 as built: the box and the switch (2026-10-20)

The maintainer's shape, verbatim: *"the coaching should probably be in a new box,
below the actions box, that can be collapsed or opened ... a summary above the
collapsed section, with each item in the collapsible section."* That is what the
page does now.

**Placement.** The switch is in the Settle Up header row, right side, before the
`…` menu (`#coach-switch`). The box (`coachBox`) is the rail's **sibling of the
action groups**, appended after them and before the `Plan` details — so folding
an action group cannot hide it, and the plan's grading stays the rail's last
section (the verdict did NOT move; the mockup's rail simply had no verdict line).

**The fold.** Collapsed by default: the header button carries `▸ Model vs you ·
3 differ` plus the confidence chip, and `aria-expanded` says which state it is
in. Opening shows one row per kind and persists under `bl-coach-open` — a view
setting like `bl-settle-mode`, separate from the switch's own `bl-coaching`
key. `≠` and an amber left edge (`--tdiff`, the flagged exception) mark a
differing row; `not_reached` and `not_comparable` are muted, carry no glyph, and
explain themselves on hover; one legend line says what the greys mean.

**Off builds nothing.** `if (_coachOn)` guards the append, so a player who never
touches the switch gets exactly the rail they had — no header, no gap.

**Two states that are easy to get wrong, both closed:**
* a save that predates the comparison (no `coach_diff` anywhere) gets a one-line
  note pointing at **Rebuild** — an empty box would read as broken;
* a turn in a NEW save that has no advised phase draws **no box at all**
  (`hasCoach` is the rep-level question, decided in `renderTavernGame`), rather
  than reusing the old-save note.

**The caveat is NOT repeated in the box.** The page already prints `CAVEAT`
verbatim at the bottom (`ts-caveat`), and a second identical sentence on one
screen is the duplication the rail exists to remove. The box carries the
evidence count instead ("we differed on 77 moves across your 18 saved games"),
which is a difference count and not a causal claim. If the maintainer wants the
limits line inside the box too, it should MOVE from the footnote, not be copied.
**OPEN, for the maintainer to call.**

**Tests.** Node: the wording helpers (`coachRows`/`coachSummary`/`coachCell`/
`coachWhy`/`coachEvidence`) and the DOM assembly against a minimal shim
(`coachBox`: row count, classes, the glyph count, the no-rows and old-save
branches). Source pins: the switch's role/aria/default, the one `COACH_WIP`
constant, the append guard, the box's position between the groups and the plan.
Browser (`test_settle_browser.TestTheCoachingBoxInABrowser`): off leaves zero
nodes, the fold is a real `display:none`, the amber edge is read off the computed
style, the old-save note, and the switch is absent from the live tab. **The
browser class SKIPS in this sandbox** (Chromium cannot start — the documented
case), so those five are UNVERIFIED here and must be run before release.

**Not built, deliberately:** the mockup's master `All 14 actions ▸ collapsed`
(the box is a sibling, so the actions can gain their own master fold later
without touching it); the Step-through callout and the turn/step marks (passes
3-4).

---

## Appendix A — the original draft, verbatim

Preserved as it was handed over, so the next session can check the spec against
what was actually asked rather than against a summary of it. **Where it
conflicts with §2 or §3, the decisions and corrections win** — the four known
conflicts are the default (item 2 vs item 6), the "shared summary" clause
(switch item 4), the "no model text beyond counts" clause (coaching item 1), and
the amber vocabulary (coaching items 3 and 5).

> **Coaching in Settle Up (Summary + Step through only):**
>
> 1. Render model-vs-player comparisons only for finished games. Never in Live;
>    no model text in shared/telemetry summaries beyond existing counts.
> 2. Per phase, compare only options that were available at that moment
>    (tavern offers, board, hand, gold). Show only differences.
> 3. Summary: in the rail, a "Model vs you" table: rows Level up, Buy, Sell,
>    Play; columns Model / You; differing rows get "≠" and an amber left
>    edge (never color alone). Below: "Why: <reason with the number>", the
>    evidence line ("<stat> · <n> games"), a confidence chip, and the limits
>    line. Existing action groups stay, collapsed.
> 4. Turn strip: amber dot on turns where the player differed from the model.
>    Step track: dot on ticks where they differed; tooltip appends "(differs
>    from the model)".
> 5. Step through: when the current step differs, show a "differs from the
>    model" chip next to the caption, and in the Tavern panel's empty right
>    side a callout: "Model preferred X over Y / Why: ... / confidence ...".
>    Mark the player's card with a solid amber outline and the model's with a
>    dashed one, plus a text tag ("You bought" / "Model preferred").
> 6. Copy: "Model preferred ... over ...", never "mistake". If confidence is
>    low, show "no clear preference" or nothing. Hide Why when there is no
>    number behind it.
> 7. Keep "plans taken / ignored" as counts only.
>
> **Coaching switch (Settle Up only):**
>
> 1. Header row, right side, before the "..." menu: a switch labeled
>    "Show coaching: On/Off" with a muted "(work in progress)" (from one
>    constant). role="switch", aria-checked, keyboard-togglable. Tooltip:
>    "Model suggestions for finished games. May be wrong; observational,
>    not causal."
> 2. State persists with the other view settings. Default On.
> 3. When Off: render none of the coaching UI (Model vs you table, Why,
>    confidence chip, turn/step dots and legend, "differs from the model"
>    chip, Tavern callout/outlines/tags, the Observational note). The rail
>    returns to the action groups. Layout collapses with no empty gaps.
> 4. When Off: do not call the model, and omit coaching fields (plans
>    taken/ignored counts) from the shared summary.
> 5. Not on Live: no switch and no model output there.
> 6. Also, it should be switched to "off" by default.

