# Pivot — the live overlay stops advising; the verdict moves after the game

**Decided 2026-10-06.** The live path ships *state*. The prescriptive engine —
`value.top_move`, the numbered plan, the pick verdict, the sell verdict — keeps
running and keeps being recorded, and is shown **only once the decision it
describes can no longer be acted on**. Phase 3 (a mid-combat retrospective on
the phase that just closed) is deliberately NOT in v1.

This file is maintainer-only and never ships (it is named in
`publish_release.EXCLUDE_FILES` alongside `DESIGN.md` / `ROADMAP.md`).

---

## 1. Why — and what is actually true

The trigger was an AI-written summary of Blizzard policy asserting that
"providing decision-making … is highly likely to be classified as a violation",
that Warden detects such tools and bans automatically and without warning, and
that a "pencil and paper" rule makes real-time advice a breach. Three parts of
that are wrong. The plan is shaped by the corrections, not by the claim:

1. **Warden is not this app's risk vector, and no pivot changes that.** Warden
   targets memory, packet and input manipulation. This app reads a text file the
   game writes to the player's own disk. Verified by grep on 2026-10-06, before
   this document was written: `SendInput|SetCursorPos|mouse_event|keybd_event|
   pyautogui|OpenProcess|ReadProcessMemory|WriteProcessMemory|
   CreateRemoteThread` is **zero matches** across `app/`. (`CLAUDE.md` item 3
   wants that property test-locked — the code side *and* the README claim that
   depends on it. Still open.)
2. **"Decision-making is highly likely a ToS violation" is not a Blizzard
   sentence.** No Blizzard document draws that line. The clause actually in play
   (EULA 1.C) prohibits software that "facilitates the gameplay" and grants "an
   advantage over other players not using such methods" — and a *pure statistics
   overlay grants that advantage too*. The clause does not name verdicts. So
   descriptive-vs-prescriptive is a **risk dial, not a safe/unsafe switch**: read
   strictly, "your opponent has a 4/4" is as exposed as "kill the 4/4".
3. **The precedent for prescriptive overlay advice is public and long.** HSReplay's
   *Bob's Buddy* rated every minion in the tavern and flagged the buy; HearthArena
   has named a best pick for every Arena card since 2014; Firestone ships BG hero
   tier lists and per-minion ratings today. Log-reading trackers have never been
   the enforcement target — input automation has.

What survives those corrections is a **real but different risk: discretionary and
reputational.** Blizzard may reread its own words whenever it likes, and what
invites that is *attention* — a stream, a viral post, tournament use, or a
download page advertising "tells you what to buy". That is worth engineering
against, and it is why this pivot optimises for **defensibility and attention
profile** rather than for a verb blacklist. (Not legal advice; nobody here is a
lawyer.)

The second reason is product, not risk. README already concedes that the
recommendations "have not yet been checked against outcomes" and that the
leveling calls "may be wrong". A live oracle making unvalidated calls is the
weakest use of this asset. A review whose headline number is **the model's own
track record** is the strongest — and it is the one thing no stat overlay has.

## 2. The prescriptive surface leaving the live path

Ground truth, read out of
`app/decision_logs/decision_Hearthstone_2026_10_03_14_46_54.jsonl` — this is what
a player actually saw:

```
1. Cast Them Apples (buff dies with this shop · buy the buffed minions this turn)
 · 2. Swap: play Bronze Warden, sell Flittering Bat (3.3 vs -1.2 · clearly better)
 · 3. LEVEL (access to tier 4) · 4. Buy Bronze Warden (surviving until we can commit)
```

and `1. PICK Diremuck Forager (best available)`.

| Site | Says today | Becomes |
|---|---|---|
| `coach_ui.py:1151` | panel headed **"Do this now"** | a situation panel |
| `coach_ui.py:1155-1251` | numbered steps, `act` verbs, the `hero` step, `if locked, pick Y` | gone from the live render |
| `coach_ui.py:987` `KIND_CHIP` | `LV/PICK/BUY/SELL/ROLL/CAST/PLAY/HOLD/SWAP/DISC` | review renderer only |
| `value._top_move_text` / `top_move` | the numbered plan | unchanged — a review-only producer |
| `choices.py` | `PICK X (best available)` / `(pick 18%, avg #4.77)` | option tiles with per-option facts, no "best" |
| `live.py::_advise_pick` | `PICK X` | descriptive |
| `value.sell_recommendation` | `Safe to sell \| do not sell` | each minion's own number, no verdict |
| `shop_rank` / `buy_this` | an ordering plus a named headline buy | facts per offer; no headline |
| `target_comp` / `hunt_targets` | "what you're hunting" | owned vs missing comp pieces |

The prescriptive part is **one panel plus a handful of payload fields**. This is
not a rewrite.

## 3. What does not change

`board_state.py` reconstruction, `pool`/`bans`/`lobby`, the curated meta DB and
the comp guides, `simulate_growth`, `fight_model` / `combat_forecast`, the damage
model, `tribes`, `config`, the whole privacy architecture (`sanitize_log`,
`privacy_scan`, `share` consent scope, the `session_report` whitelist), the
decision log and telemetry corpus, and **`value.py` in full**. The live screen
keeps: state strip, situation line, DANGER/fragility band, next opponent's comp,
hand, TARGET COMP tiles, COMP DIRECTION meter, LOBBY PRESSURE, TAVERN row,
PLAYABLE COMPS, level price.

What the live screen loses is the answer. It becomes a very good instrument and
stops being an oracle.

## 4. Plan

**Phase 0 — pin the posture (first, small).** Write the contract into `DESIGN.md`:
what ships live (state), what ships after the fact (verdict), and the property
that must never regress (no process/memory/input access). Add the two controls
`CLAUDE.md` item 3 asks for: a test asserting README's no-process/no-input claims
*and* that those API names stay absent from `app/`, and a **live-payload contract
test** asserting the coach's live output carries no verdict fields — that is what
stops this pivot from silently reverting.

**Phase 1 — the live overlay becomes descriptive.** `coach_ui.py`, `live.py`,
`choices.py` per the table in §2; `live_coach.py::analyze` stops emitting
`top_move`, `top_move_steps`, `buy_this`, the `choice.ranked` order and
instruction-shaped `target_comp` — while still **computing and logging** them, so
the review keeps its input. Drift guard for the kind/chip sets, like the existing
`KIND_CHIP` ↔ `_STEP_KINDS` one.

**Phase 2 — promote the review to the product. DONE (2026-10-06).** Shipped as
`app/settle_up.py`, reachable three ways: the end-of-game card's "Settle up" link,
the overlay server's `/review` route (`coach_ui._review_response`, built
off-thread by `live._settle_up_in_background` so the monitor's tick keeps
answering the log), and `python app/settle_up.py --latest` for any game still in
the log.

It is built on `outcome_audit.audit_game` — the per-phase join that already
existed for the audit tooling (plan, the player's actual actions, the HP delta
across the following fight), at the one-row-per-buy-phase grain. That is what
this plan predicted: the pieces were already there, and the work was assembling
them and giving them a face.

**One deliberate deviation from this plan.** It was to be rendered by the
existing page. It is not: the overlay page is a 300ms-polling JS app driven by
`/analysis`, and a review should be something a player can keep and read without
a process running, so `render_html` writes a standalone page. The cost is a
second small stylesheet; the benefit is a report with no state and no server.

**What it cannot grade — measured, and mostly CLOSED (2026-10-06).** When the
review first shipped, a phase whose plan led with a `cast` (or a swap, a play, a
pick) read **not graded**: 8 of the 16 advised phases in the 10-06 game, because
`value.top_move` left `card` as None on a cast step and `player_actions` counted
spells instead of naming them.

That is fixed at the source rather than worked around: `_top_move_text` now
records which card each hand step is about (while it still holds the ids), and
`player_actions` records `spell_ids`. The same game now reports **1 ungraded**
(a swap-led plan), with the rest judged. Two limits stayed, and the review prints
both: a swap needs the sell AND its replacement as a pair, which the row does not
carry; and a cast-led `taken` is weaker evidence than a buy-led one, because a
turn that casts several spells can satisfy "Cast X" incidentally.

**Phase 3 — excluded from v1, kept on the table.** The half-step: during combat,
show the phase that just **closed** — that exact shop, the model's line, what the
player did. Strong teaching, and defensible because the decision is over and the
shop is gone. Its guard is testable: a retrospective is keyed to a closed phase
and **never** carries live shop state (the `MAIN_ACTION`/settle seam that
`replay_review._advise_point` already uses). Do not ship this until Phase 1+2 have
stood on their own.

**Phase 4 — docs, packaging, naming.** README's "Is this allowed?" currently says
*"It reads the board you actually have and tells you what to buy, every buy
phase"* — after Phase 1 that sentence is false and must be rewritten to the new
factual posture and test-locked. `publish_release.py` already carries
`EXCLUDE_FILES`/`EXCLUDE_PATHS`, so "the prescriptive build stays with the
maintainer" is a packaging change, not a fork. And because attention is the
actual risk, the word "coach" in the UI, the repo description and the release
notes is a deliberate decision, not a leftover.

## 5. Hazards specific to this change

- **`session_report.SPEC` has teeth** and `source_problems()` reads the SOURCE: a
  new analysis field, or a new key inside `scenario` / `choice` / `comp_progress`,
  **refuses the upload** until it is named in `SPEC` or listed in
  `DROPPED_FROM_ANALYSIS`. Removing fields from the live payload is the same
  class of change — do it as a decision, not as a side effect.
- **`publish_release.py` walks the WORKING TREE, not git.** This file is
  maintainer-only for that reason and is excluded by basename; a new root-level
  doc that is not added to `EXCLUDE_FILES` would ship to players on the next
  release. The reproducibility gate catches untracked entries, not unwanted ones.
- **The overlay is the product's face.** A review product that still greets the
  player with a verdict-shaped panel on the live path has not pivoted, however
  the docs read. The Phase 0 contract test is what makes the difference real.

## 6. Decisions

**Still open:**

1. Does the maintainer keep a live-coach build for personal use, excluded from
   the release? (Cheap via `EXCLUDE_FILES`; it moves the risk to whoever opts in.)

**Settled since this list was written (2026-10-06), kept here so they are not
reopened by accident:**

2. ~~Naming and attention profile: keep "coach" in the UI, or move the product's
   language to the ledger/review framing?~~ **The name stays "Bob's Ledger".**
   It was already the pun — Bob runs the tavern, a ledger is the tavernkeeper's
   book — and the pivot made the existing name *more* accurate rather than less.
   A rename would also cost ~26 files including both launcher filenames, the
   workers.dev subdomain every installed copy's updater points at, and shortcuts
   already on players' machines. The bar-tab language went into the review's own
   name instead: **Settle up**. (See CLAUDE.md.)
3. ~~Whether the review's first screen leads with the model's line or with the
   player's own decisions, scored.~~ **Answered by building it:** the first
   screen is neither — it is the TURN BY TURN board section (what you went in
   with, what they brought, what you kept), and the model's line follows in the
   phase-by-phase view. The question assumed a single choice between two scored
   framings, and the thing that turned out to be worth leading with was the
   reconstruction the game itself cannot show.
4. ~~The review is deliberately a standalone page, not part of the overlay
   (§4 Phase 2's one deviation). Does the tab work (2026-10-07) undo that?~~
   **No — it extends it.** The overlay page grew a Settle Up TAB, but the tab
   is a browser over SAVED games served from `/review/*` endpoints and a
   per-user store (`app/replay_store.py`, release-excluded); the standalone
   page remains exactly what it was, for the same reason (a keepsake with no
   process behind it). The contract is re-pinned, not rewritten: `/analysis`
   still carries no verdict fields (`test_live_view.py`), and
   `test_settle_tab.py::TestTheWall` pins the new surface to the same rule —
   settle data reaches the page only through `/review/*`, and only for games
   that are over.
