# Roadmap — Hearthstone Battlegrounds AI Coach

Priorities and concrete next steps.

## Phase 0 — Bootstrap (done)
- [x] Create project folder `hearth-coach/`
- [x] Clone official `python-hslog` parser
- [x] Write `parse_bg.py` smoke-test parser
- [x] Document design (DESIGN.md), competitors (COMPETITORS.md), opponent-data
      thesis (OPPONENT_DATA.md), DeepSeek vision status (DEEPSEEK_VISION.md)
- [x] Install `hslog` deps from PyPI (network restored).

## Phase 1 — Validate the opponent-data thesis (done)
1. [x] Get `hslog` installed.
2. [x] Run `parse_bg.py` against a real `Power.log`.
3. [x] Confirm per-player hero/placement extraction works.
4. [x] Build the full opponent-move extractor — `extract_game.py` (stdlib-only;
       `hslog` mangles BG's 8-player structure, so we parse the raw log).
5. [x] Print a first-place vs last-place comparison (`--compare`).

Findings: `analysis/BG_LOG_STRUCTURE.md`. Key caveat — opponents' individual
buys/sells are not recoverable (they share the spectator player number); tier
timing is the one clean per-player signal, and it does not always separate
winner from loser.

## Phase 2 — Board-state parser (live + replay)
- Parse `Power.log` into a structured, queryable game-state model.
- Decide: live from Power.log (authoritative) vs. screen OCR for live play.
- Add verification of the parsed state (breakoutBot discipline).

## Phase 3 — Reference-image library
- Curate meta screenshots (comp tier lists, hero/Champion rankings).
- Legibility step: scale/crop dense text; pair images with text captions.
- Verify the vision model reads them correctly before trusting advice.
- Per-decision fetch (only the relevant subset).

## Phase 4 — Coach agent
- Resolve model choice: vision-capable model or hosted API (confirm image input).
- Reason over (board state + meta images [+ optional HSReplay stats]).
- Emit dynamic, board-specific, explainable advice.

## Phase 5 — Overlay / delivery
- Overlay UI (text / arrow / audio) with a per-decision latency/cost budget.
- Post-game replay review UI.

## Phase 6 — Evaluation rigor
- Sham-coach control (a sham coach gives plausible-but-random advice; if players
  feel it "helps," the signal is not evidence of real help).
- Controlled protocol for "does coaching improve placement."
- Bucketing + outcome tables on the opponent data.

## Phase 7 — (optional) data flywheel
- Opt-in replay upload loop to build our own outcome corpus over time.

---

## Key decisions locked so far
- Meta references: **curated screenshots** the user takes, refreshed on patches.
- Competitive angle: **reasoning over data volume**; lead with dynamic,
  board-specific, explainable advice; use HSReplay stats (if any) as supplement.
- Hybrid architecture: live board parse + meta images + optional stats + reasoning.

## Open decisions
- Live board source: Power.log vs screen OCR.
- Vision model: hosted API (if images accepted) vs local vision-capable model.
- Latency/cost budget per decision.
- Evaluation protocol (sham-control).

## Dependencies / blockers
- Network to PyPI (for `hslog` deps) — currently down from working environment.
- `DEEPSEEK_API_KEY` for headless harness runs — not yet wired.
- Vision model availability for the coach agent.
