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
- [x] Parse `Power.log` into a structured, queryable game-state model —
      `board_state.py` reconstructs the friendly final board (minions + buffed
      stats) + hand + hero tier/gold/armor. See `analysis/BG_LOG_STRUCTURE.md`
      for the three log quirks it handles (empty-CardID blocks, end-of-game
      cleanup, snapshot + final-stats lookup).
- [ ] Decide: live from Power.log (authoritative) vs. screen OCR for live play.
- [ ] Add verification of the parsed state (breakoutBot discipline).

## Phase 3 — Meta reference (done)
- [x] Build the structured meta DB in `meta/`: comps (20), cards (89), trinkets
      (121), dark gifts (43), heroes (115), minions (245, with full card details),
      tavern spells (72, by tier). See DESIGN.md section 6.
- [x] Scrapers/parsers: `scrape_comps.py` (hsreplay comps), `parse_trinkets.py`,
      `parse_minions.py`; Cloudflare-gated data (minions/heroes/dark-gifts) via
      manual paste; tavern-spell tier from the wiki.
- [x] Family-ban extraction: `bans.py` (5 allowed / 5 banned per game from a
      Power.log) + comp filter.
- [ ] (optional) Verify the vision model reads any future image-based meta
      correctly before trusting it (breakoutBot discipline).

## Phase 4 — Coach agent
- [x] Lock model choice: **`deepseek-v4-flash`** (1M context), pinned in
      `coach_llm.py` with prefix-cache discipline (FIXED_BLOCK meta + VARIABLE
      tail). See DESIGN.md "Model, context & cache strategy".
- [ ] Wire `DEEPSEEK_API_KEY` (env) and smoke-test `coach_llm.py` against the
      hosted API; confirm `prompt_cache_hit_tokens` climbs on repeat calls.
- [ ] Build the coach loop: parse board state (`board_state.py`) + family ban
      (`bans.py`) → filter comps → assemble the FIXED_BLOCK meta + VARIABLE
      board-state tail → call `coach_llm.py` → emit advice.
- [x] **Respect the family ban:** exactly 5 tribes allowed / 5 banned per game.
      `bans.py` extracts the 5 allowed tribes from a Power.log (pure-tribe pool
      minions) and `filter_comps_by_available_tribes` filters comps (every core
      card must have ≥1 allowed tribe; `All`/`Neutral` never-banned; compound
      cards playable if either tribe is allowed). See memory `hearth-family-ban`.
- [ ] Emit dynamic, board-specific, explainable advice.

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
- Meta references: **structured JSON DB** in `meta/` (comps, cards, trinkets,
  dark gifts, heroes, minions, tavern spells), refreshed on patches.
- Competitive angle: **reasoning over data volume**; lead with dynamic,
  board-specific, explainable advice; use HSReplay stats (if any) as supplement.
- Hybrid architecture: live board parse + structured meta + family-ban filter +
  optional stats + reasoning.
- **Model: `deepseek-v4-flash`** (1M context) with prefix-cache discipline —
  see DESIGN.md "Model, context & cache strategy" and `coach_llm.py`.
- **Family ban:** exactly 5 tribes allowed / 5 banned per game; comps filtered by
  core-card tribes (`bans.py`).

## Open decisions
- Live board source: Power.log vs screen OCR.
- Vision model: hosted API (if images accepted) vs local vision-capable model
  (text reasoning is locked to `deepseek-v4-flash`; vision is a separate input
  path to confirm).
- Latency/cost budget per decision.
- Evaluation protocol (sham-control).

## Dependencies / blockers
- Network to PyPI (for `hslog` deps) — currently down from working environment.
- `DEEPSEEK_API_KEY` for headless harness runs — not yet wired.
- Vision model availability for the coach agent.
