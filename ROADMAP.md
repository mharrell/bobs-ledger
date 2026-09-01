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
- [x] **Live source leaning: Power.log tailing** (authoritative, no OCR). The
      parsers work on partial games; `live.py` tails the active Power.log and
      runs the coach analysis each buy phase. **First live test: a real game the
      user won (1st)**. Exposed open issues: engine pieces rank too low (Nomi),
      combat-time scaling is invisible (Flaming Enforcer), and it over-advises
      on unchanged boards (needs per-board dedup). See memory `hearth-live-coach`.
- [x] **Incremental live coach** (`live_coach.py`): feeds lines into a persistent
      GameState + action tracker as they arrive, so each buy-phase analysis is
      ~0.002s (was ~2s re-parsing the whole log). Caches per-game data (heroes,
      bans, comps); auto-switches to a new session; handles end-of-game gracefully.
- [x] **Verification of the parsed state (breakoutBot discipline) — started**:
      a stdlib-unittest golden-test suite in `tests/` (hand-built log excerpts
      reproducing the real session log's quirks, plus a skip-if-absent
      integration test on the newest real Power.log). Run
      `python -m unittest discover -s tests` from `hearth-coach/`.
- [x] **Hardening pass 1 (2026-08-31)**, after a full-project review:
      - Tribe canonicalization: `tribes.py` is now the single vocabulary
        (canonical singular display names; see "Key decisions"). `comps.json`
        / `minions.json` / `cards.json` migrated (all-tribe/neutral -> null);
        every tribe comparison in `value.py` / `live_coach.py` /
        `player_actions.py` normalizes through it. This fixed three silent
        bugs: the W_TRIBE bonus never fired, the banned-tribe penalty applied
        to EVERY minion in every game, and `_best_comp` always returned the
        first comp in the file.
      - `check_meta.py`: validator asserting one canonical tribe vocabulary
        (comp-vs-minion vocabulary intersection) + comps schema + duplicate
        names in meta JSON.
      - Parser fixes: `FULL_ENTITY - Updating` blocks (PowerTaskList
        re-renders) now retarget the current entity instead of corrupting the
        previous Creating entity; PowerTaskList `tag=STEP` duplicates no
        longer spawn spurious turns (~60% turn-count inflation, live coach
        reported 16 turns for ~10 buy phases); the first `MAIN_ACTION` is a
        real buy phase (turn-1 buys no longer dropped); golden minions no
        longer filtered as noise in `extract_board.py`.
      - Live-loop fixes: advise fires only after the shop offers are parsed
        (was: always an empty shop on the first advise of each turn); missing
        ban seed fails OPEN (`allowed=None` -> all comps playable, no
        banned-tribe penalty, overlay shows no banned tribes) instead of
        "all tribes banned"; None-safe board fingerprint; the friendly hero
        power (text from `meta/heroes.json` via `meta.hero_power`) now feeds
        the W_HERO synergy term in sell/shop rankings.

## Phase 3 — Meta reference (done)
- [x] Build the structured meta DB in `meta/`: comps (20), cards (89), trinkets
      (121), dark gifts (43), heroes (115), minions (245, with full card details),
      tavern spells (72, by tier). See DESIGN.md section 6.
- [x] Scrapers/parsers: `scrape_comps.py` (hsreplay comps), `parse_trinkets.py`,
      `parse_minions.py`; Cloudflare-gated data (minions/heroes/dark-gifts) via
      manual paste; tavern-spell tier from the wiki.
- [x] Family-ban extraction: `bans.py` (5 allowed / 5 banned per game from a
      Power.log) + comp filter.
- [x] Patch-notes updater: `patch_notes.py <url>` fetches official patch notes,
      LLM-extracts before/after changes, and (with `--apply`) writes them into
      `meta/`. Dry-runs by default; new cards flagged for manual entry.
- [x] Automated check (review-first): `check_patch_notes.py` discovers the
      latest patch from the Blizzard news page, writes a reviewable report to
      `patch_reports/`, and toasts — it never edits the meta DB. Register as a
      weekly Windows Task Scheduler task with `register_patch_check.ps1`.
- [ ] (optional) Verify the vision model reads any future image-based meta
      correctly before trusting it (breakoutBot discipline).

## Phase 4 — Coach agent
- [ ] **Choose the coach's advice model** (open decision): hosted API vs local
      vision-capable model. `coach_llm.py` (a DeepSeek v4 flash client) exists
      but is NOT the intended advice engine at this time. (The deepseek-v4-flash
      config in `~/.claude/settings.json` is for the Claude Code session, not the
      coach.)
- [ ] Build the coach loop: parse board state (`board_state.py`) + family ban
      (`bans.py`) → filter comps → assemble the meta FIXED_BLOCK + board-state
      VARIABLE tail → call the chosen advice model → emit advice.
- [x] **Respect the family ban:** exactly 5 tribes allowed / 5 banned per game.
      `bans.py` extracts the 5 allowed tribes from a Power.log (pure-tribe pool
      minions) and `filter_comps_by_available_tribes` filters comps (every core
      card must have ≥1 allowed tribe; `All`/`Neutral` never-banned; compound
      cards playable if either tribe is allowed). See memory `hearth-family-ban`.
- [ ] Emit dynamic, board-specific, explainable advice.

## Phase 4a — Value function & growth simulator (done)
The "reasoning layer" the coach reasons over — how good each minion/comp is.
- [x] **Value function** (`value.py`): scores a board minion by stats, buffs, comp
      synergy (core/addon/tribe), role, engine recognition, and simulated growth.
      Loads card text from the **BG pool** (`meta/minions.json`), not the
      Standard-only DB — so it reads real BG abilities (fixed a blindness bug
      where Ravaging Scorpid's Beetle-scaling was invisible).
- [x] **Growth simulator** (`simulate_growth.py`): deterministically models a
      comp's trigger chain (cast spell / play tribe / end of turn / discover /
      attack) and sums the stat gain. Machine-readable engine model in
      `meta/engines.json` — **13 engines** (Glambot, Spark Snapper, Mana Surge,
      Groundbreaker, Ruiner, Tasty Lobster, Painter, Unbound/Nomi, Felboar,
      Ravaging Scorpid, Hooktusk, Devilish Distractor, Vigilant Bristlemane).
      Handles golden pieces (2x), compounding shop-eat, and tribe-scaling.
- [x] **Wired into the coach**: `sell_recommendation` (safe-to-sell → keep),
      `shop_ranking` (tavern buy ranking), `top_move` (one decision line).
- [x] **Comp-targeting layer** (`comp_target`): identifies the best comp to build
      toward — commit if you're deep into one (≥2 core cards), else pivot to the
      highest-tier playable comp. The buy ranking scores shop cards against the
      TARGET comp (with a bonus for its core/addon cards), so the buy
      recommendation guides the build rather than just matching the current board.
- [x] **Intentions (the "why")**: the top-move states why behind each move —
      "committing to <tribe>", "part of growth cycle", "surviving until we can
      commit", "making room", "leveling for access". Plus "wait for end of turn"
      when the board is full with end-of-turn scaling, and a late-game fallback
      ("hold — look for <target> core cards") so the advice doesn't go stale.
- [x] **Validated against real games** (`validate_growth.py`): the simulator
      consistently UNDERESTIMATES actual growth by ~1.6–2x (single-turn model,
      no multi-turn compounding) — conservative but in the right ballpark.
- [ ] Tune the simulator's parameters (tavern_base, eat_every, W_*) against the
      growing replay corpus to close the underestimation.

## Phase 4b — Spell buy advice (done)
Most of the player's actual buys are tavern SPELLS, which shop advice ignored
entirely (replay review labelled spell-only turns as such). The spell data was
already in `meta/tavern_spells.json` (72 spells, tier/cost/text); the live shop
parse already captured spell options (their ids match the minion-option regex,
tavern-owned) — shop_ranking just silently dropped them.
- [x] **Spell scoring** (`value.py`): `_load_spell_db()` + `_spell_score()` —
      direct effect per gold from card text (stat grants; Choose One takes the
      best branch, not the sum; whole-board scope scales by board size; utility
      effects get flat points), plus a **cast-spell engine fuel** term:
      `_spell_fuel_bonus()` runs the growth simulator at the current per-turn
      cast count and +1, and credits the spell with the delta — the marginal
      growth one bought spell buys on a running Glambot/Nomi/Felboar engine.
      `W_SPELL_FUEL = 0.3` (tunable, like every other weight).
- [x] **Wired into the coach**: `shop_ranking` ranks minions AND spells in one
      list (spells scored per-gold, not by the minion value function);
      `top_move` affordability uses the spell cost; buy intentions say why
      ("part of growth cycle" / "utility" / "tempo" / "spare gold into value");
      the live loop passes the real per-turn trigger scenario in, so the fuel
      term reflects actual cast counts. Display names resolve through
      `_load_bg_names` (now includes spells) for the UI and replay review.
- [x] replay_review: spell buys now compare against the ranked picks (which
      include spells) instead of always reporting "coach doesn't cover spells".

## Phase 5 — Overlay / delivery
- [x] **V1 coaching UI overlay** (`coach_ui.py`): a local stdlib HTTP server +
      static HTML page that polls the analysis and renders widgets — top-move
      headline (with intentions), target comp (pivot to / committing to), state
      strip, level/roll, per-turn triggers, board (golden marks), sell ranking,
      tavern buy ranking ("Buy this"), comps, banned tribes.
      Run `python live.py` → open `http://127.0.0.1:8747/`.
- [x] **Mid-turn updates** (2026-09-01): the monitor used to advise exactly once
      per buy phase and go stale for the rest of the turn. `LiveCoach.
      state_fingerprint()` (gold, tier, board, tavern offers) + a fingerprint
      re-advise loop in `live.py`: while in a buy phase, any decision-state
      change (buy, roll, play, sell — gold and offers shift) re-advises within
      one poll (~1s, ~6ms per analyze), instead of once per phase. The empty-shop
      gap right after a buy can't fire (`tavern_offers()` empty until the game
      re-prints options); the console dedups on the same fingerprint and now
      leads with the top move (`describe` includes it).
- [ ] Post-game replay review UI.
- [ ] Selection ranker (hero/trinket/discover/dark-gift picks).
- [ ] Persist live game data so a log rotation / coach restart doesn't lose the
      tail of a game (surfaced when the A. F. Kay game was lost to rotation).

## Phase 6 — Evaluation rigor
- Sham-coach control (a sham coach gives plausible-but-random advice; if players
  feel it "helps," the signal is not evidence of real help).
- Controlled protocol for "does coaching improve placement."
- Bucketing + outcome tables on the opponent data.

## Phase 7 — (optional) data flywheel
- [x] **Replay-analysis pipeline** (`replay_stats.py`): deterministically
      aggregates outcome data (comp/engine/hero placement, card value, board
      strength) across a corpus of Power.logs — zero LLM tokens per game. Saves
      to `meta/corpus_stats.json` (`python replay_stats.py --save ...`). This is
      the foundation for tuning the simulator and weighting comps by actual
      success. Corpus ~17 games and growing.
- [x] **Corpus wired into the value function** (2026-08-31): `comp_target`
      pivots by meta tier + sample-shrunk placement strength
      (`(4.5 - avg_place) * n/(n+3)`) from `meta/corpus_stats.json` — a comp
      placing 1.0 on a large personal sample is S-tier-equivalent; n=1 can't
      flip a tier decision.
- [x] **replay_stats rigor** (2026-08-31): rows below n=3 marked `[low]`
      (descriptive, not a signal); comp/engine tables sorted by the same shrunk
      statistic; games deduped across rotated logs by GAME_SEED; the card table
      states its confound (final-board placement, no tenure weighting).
- [x] **Replay review** (`replay_review.py`, 2026-08-31): reconstructs each buy
      phase through the exact live path and prints recommendation vs actual
      actions — the per-turn coach-vs-player diff that feeds honing. First
      finding: the coach buried the (correct) tempo-level line under a generic
      buy pick that was never taken; top_move now leads with an affordable
      level.
- [ ] Opt-in replay upload loop to build the corpus over time.
- [ ] Phase 6 sham-control: matched advice-vs-sham-coach games (the only
      causal test that coaching helps placement).

---

## Key decisions locked so far
- **Canonical tribe representation (2026-08-31):** singular display names
  ("Elemental", "Mech", ...) owned by `tribes.py`; meta JSON and code compare
  through `tribes.normalize()`; All/Neutral tribe fields are `null`. Enforced
  by `check_meta.py`.
- Meta references: **structured JSON DB** in `meta/` (comps, cards, trinkets,
  dark gifts, heroes, minions, tavern spells), refreshed on patches.
- Competitive angle: **reasoning over data volume**; lead with dynamic,
  board-specific, explainable advice; use HSReplay stats (if any) as supplement.
- Hybrid architecture: live board parse + structured meta + family-ban filter +
  optional stats + reasoning.
- **Claude Code session model:** `deepseek-v4-flash` (1M context) with
  prefix-cache discipline — the harness config for the tool building the coach,
  NOT the coach's advice model. See DESIGN.md "Model & cache strategy".
- **Family ban:** exactly 5 tribes allowed / 5 banned per game; comps filtered by
  core-card tribes (`bans.py`).

## Open decisions
- Live board source: Power.log vs screen OCR.
- **Coach's advice model:** hosted API vs local vision-capable model (undecided;
  `coach_llm.py` is parked, not the intended engine).
- Latency/cost budget per decision.
- Evaluation protocol (sham-control).

## Dependencies / blockers
- Network to PyPI (for `hslog` deps) — currently down from working environment.
- `DEEPSEEK_API_KEY` for headless harness runs — not yet wired.
- Vision model availability for the coach agent.
