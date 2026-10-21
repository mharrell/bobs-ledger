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

