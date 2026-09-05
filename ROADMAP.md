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

- [x] **Advice consistency pass** (2026-09-01, from the Master Nguyen game):
      one-shot battlecries/deathrattles had their +N/+N magnitude counted as
      compounding growth (a +10/+10 one-shot scored 27 and beat real comp
      engines) — `growth_potential` now discounts one-shot magnitude 4x and
      fixes the "end of YOUR turn" substring gap; a committed comp (≥2 core on
      board) damps off-tribe shop minions (`W_OFF_COMP = -2.0`); replay_review
      settles the options block before ranking (was: one-card rankings from
      firing on the first option line).
- [x] **Affordability + priority UX** (2026-09-01 evening, from the
      Heistbaron Togwaggle game): top_move priced buys at the card's mana
      `cost` — but a BG minion's buy price is its TIER, and the 18
      auto-added pool minions had neither, so the affordability check was
      skipped entirely (unaffordable suggestions). Fixes: `extend_pool.py`
      heals tier from hearthstonejson `techLevel` (backfilled all 18);
      `top_move` prices minions at tier / spells at cost; when leveling
      leads, buys are budgeted from the LEFTOVER gold; the line is now
      NUMBERED priority steps (1. LEVEL → 2. PICK → 3. Buy → 4. sell), the
      overlay's buy box reads "Then buy (after leveling)" when a level leads,
      the live poll dropped to 0.3s (advice is ~5ms — the 1s poll was the
      perceived slowness), and output is cp1252-safe (Unicode arrows crash
      Windows consoles).
- [x] **Real upgrade prices + spending-aware gold** (2026-09-03, from the
      Voone game): two "coach doesn't understand gold" bugs. (1) The
      level-cost model was tier+1, but BG upgrade prices start at
      (target+3) gold and DROP 1 at the start of each round you wait — the
      coach now reads the TechUp button's live COST tag from the log
      (teardown-write-proof), with the wiki-rule formula as fallback.
      Turn-1 leveling at 3 gold is genuinely impossible (the button costs
      5). (2) `board_state` stored only RESOURCES (the turn's purse) and
      never RESOURCES_USED — after a buy the coach still showed the full
      purse. Gold is now RESOURCES + TEMP_RESOURCES − RESOURCES_USED, and
      the fingerprint notices spending.
- [x] **Level-vs-board rule** (2026-09-03 evening, from the replay review:
      level advice overridden 5x in 2 games): the friendly hero's HEALTH tag
      is now parsed alongside armor, and `top_move` flips to BUY-first when
      the level and the shop's top card can't both be afforded AND either
      effective health (HP+armor) ≤ 12 (dying) or the shop's top card is a
      core piece of the target comp; the level then trails the buy. The
      state strip shows HP, red when dying.
- [x] **Cast-generating spells** (2026-09-03 evening, from the Naga
      losing-game report): Spitescale Special (Get 3 random Spellcraft
      spells) triggered the per-cast buff 4 times, not 1 — `_extra_casts()`
      parses cast generation from text and `_spell_fuel_bonus` measures the
      marginal growth at n + 1 + k casts, so spellcraft spells rank by their
      real multiplied engine value.
- [x] **Empty-board buy-phase window** (2026-09-03): after a full-board
      turn, the log tears the tavern board down at combat end and re-adds it
      only AFTER the next shop print — the coach advised one phase per game
      on board 0. `analyze()` now estimates from the last board snapshot
      until the real board lands.
- [x] **Ban gate** (2026-09-03): `bans_from_log` derives allowed tribes
      from pool minions seen so far, and a partial reveal once froze 9
      banned tribes in the UI for a whole game. Only a complete
      5-allowed set is accepted; incomplete sets fail open and retry.
- [x] **Target-comp pivot override** (2026-09-04, from the Varden replay):
      the tracker committed from board overlap alone — backward-looking, so
      "LEVEL to tier 6" was pushed for five consecutive phases while the
      player pivoted. `comp_target(board, comps, recent_cards)` now
      overrides the board commit when the last turn or two of acquisitions
      contain ≥2 core hits of a DIFFERENT comp (copies count — a pivot is
      often 3x one core).
- [x] **Level decision gates 1+2** (2026-09-04, from the Guff replay + the
      Jeef/Shadybunny leveling transcripts — model in
      `analysis/LEVELING_MODEL.md`): the coach leveled while it was losing —
      the Guff game took 4 straight combat losses absorbed by armor
      (12→0) while HP stayed 30, invisible to the static HP+armor rule.
      (1) **Armor flow**: `GameState.hero_stat_log` records every hero
      ARMOR/HP write; `LiveCoach` stamps each with its turn (first/last per
      turn — combat damage = first minus last, quiet turns carry forward),
      exposing `damage_last` and `loss_streak` (real loss = ≥3, 1-2 is a
      close fight). Two straight losses or one ≥10 hit at tier ≥3 defer the
      level behind the buy: "LEVEL next turn (lost 2 straight fights —
      stabilize first)". Early-game losses (tiers 1-2) don't gate levels —
      that part of the game is shop-driven, not board-driven.
      (2) **Shopping-list tier filter** (Q1): `_comp_needs_by_tier` splits
      the target comp's unowned pieces by which tavern tier holds them.
      Pieces at tier+1 → the level states its payoff ("the comp's next
      pieces live there"); pieces ONLY on the current tier → the level is
      declined on purpose ("stay on tier N — your comp's missing pieces
      are on this tier; leveling would lower the odds"), and the buy comes
      from the full purse. Every level step now carries its reason.
      Remaining gates (curve baseline, opponent estimate) tracked in the
      spec.
- [x] **Level decision gates 3+4** (2026-09-04, same model — the scout):
      (3) **Turn baseline**: `build_baseline.py` mines the local corpus
      (14 games at build time) into `meta/turn_baseline.json` — the
      median friendly-board and fought-opponent-board stat totals per
      turn, the "what does a board at turn N look like" prior. Re-run
      it as the corpus grows. (4) **Opponent estimate**: the log carries
      `NEXT_OPPONENT_PLAYER_ID` (announced each buy phase on the friendly
      hero/account entity), and every combat we fight logs the
      opponent-side board under a fixed id (real per-player ids are not
      recoverable from combat entities — they share the opponent-side
      container). The pairing maps each fought board to its announced
      opponent, so the announced next opponent's LAST-KNOWN board is
      exactly the buy-phase preview the player sees. Analysis exposes
      `board_stats` / `opp_stats` (exact) / `lobby_opp` (median of every
      board we've fought) / `baseline_opp` (corpus prior); the state
      strip shows "you X stats · ~Y theirs" and the level gates' reasons
      carry the comparison ("your 7 vs their ~16"). Shadybunny's Q0 is
      now data-grounded: ≥1.5x their board and not losing → the level
      reason says "you're strong — convert it into a tier". Next:
      a real combat forecast (positioning/keywords) to ground gate 5.
- [x] **Early-game realism fixes** (2026-09-04, from the Murloc Holmes
      live session — decision-log forensics pinned all three):
      (1) **Turns 1-2 buy a minion** when one is affordable — the ranked
      spell over an affordable minion was wrong while the board is being
      born ("turn 1 recommended a spell over a minion... no").
      (2) **The Buy box goes quiet when the plan has no buy step** — it
      used to show the raw shop #1 under "Then buy (after leveling)"
      when the level consumed the whole purse, reading as "level then
      buy" (a move the player can't make). (3) **A target comp requires
      evidence**: `comp_target` no longer picks the "best meta comp"
      from nothing — no board commit and no recent core buys → None
      ("no direction yet"; the checklist-comp-from-turn-1 anti-pattern
      Shadybunny warns against). Board copies now count toward a commit
      (2x one core commits, same as a pivot).
- [x] **Scout + pick + ban fixes** (2026-09-04, from the Guff live session —
      the coach recommended leveling through a losing streak and the overlay
      froze on a picked trinket; log forensics pinned five bugs):
      (1) **The scout resolver marked turns before their fight existed** —
      each turn got marked resolved during its own buy phase, often from the
      previous fight's teardown remnants (a phantom 6-stat "opponent board"),
      so every real fight board was skipped; now only completed turns
      resolve, from combat-phase snapshots only. (2) **Pairings reset each
      turn** — but NEXT_OPPONENT_PLAYER_ID only logs on CHANGE, so same-
      player rematches never re-announced and their boards were dropped; the
      announced value now persists and the pairing is captured when the buy
      phase closes. (3) **A None==None guard hole** let unbracketed
      announcements match before the hero parsed. (4) **The pick freeze** —
      `state_fingerprint` didn't include the choice or scout, so resolving a
      trinket pick (which changes no gold/board/shop) never re-advised; the
      overlay sat on the pick panel until a refresh. (5) **`_banned(None)`
      displayed all 10 tribes as banned** on fail-open (its own docstring
      promised the opposite), and `_refresh_bans` never re-ran once the hero
      parsed first — ban-blind games. Plus: **any hero damage counts as a
      loss** (a won combat never drops health+armor — the Guff game lost
      every fight by 1-5 and the old ≥3 rule read it as no streak); close
      losses are flagged in the reason, not discounted.
- [x] **Hand coaching + the endgame scale (2026-09-04, "it would have just
      had me leave 5 spells in my hand that 10x my stats" / "we committed,
      we have it, now we scale it to kingdom come")**:
      (1) **The hand is now parsed** (board_state.hand: minions AND tavern
      spells, each typed; casting from hand is free, a stuck minion plays
      free — every hand card is pure profit the coach can't leave on the
      table). (2) **`value.hand_plan`** ranks casts (direct effect + cast-
      engine fuel — end-of-turn compounding counts casts made THIS turn)
      and plays (free minion value; "board is full — sell to make room"
      when applicable); generated spell entities without a real id are
      skipped. (3) **The hand leads top_move's numbered plan** (free actions
      execute first; copies group "x2", beyond three kinds the rest
      summarize so the level/buy steps stay visible), and the full-board
      "wait for end of turn" pass lists the casts before it. (4) **The
      fingerprint includes the hand** — buying a spell into hand or casting
      one out re-advises without touching gold/board/shop. (5) **The
      overlay** gets a "Your hand" tile row (cast/play + score) under the
      instruction panel. (6) **Endgame framing**: once committed
      (target_state == "committing"), the stale/roll fallbacks say "scale
      <comp> — buy its scalers, cast everything, sell nothing that grows"
      / "roll — hunt more <comp> to scale it" instead of "hold — look for
      core cards". Validated on the live Guff game: t2 casts the Banana
      alone, t9 lists Spitescale Special + Tavern Coins, t13-14 show stuck
      comp pieces with make-room notes; UI smoke-tested against the real
      payload.
- [x] **Multiplier sell protection + one comp target** (2026-09-04, from the
      1st-place Guff replay — "sell Balinda Stonehearth (making room)" fired
      three phases in a row; t9 headlined Banana Slamma, a Beast, in a Naga
      game): (1) **Comp glue is never safest to sell** — sell_recommendation
      floors multipliers (Balinda "cast twice" was invisible to the old
      "trigger twice" patterns), the fit comp's core/addon pieces, and
      Spellcraft generators (Rimescale-class, now a scaling marker) above
      the 15-point filler threshold shared with top_move and the UI.
      (2) **ONE evidence-based comp target feeds sell + buy + display** —
      shop_ranking used to fall back to an arbitrary dict-order comp
      (+10 to its core) when there was no evidence, and
      sell_recommendation keyed its glue floor on a crude tribe-overlap
      comp that could be the wrong Naga comp (protecting Balinda while
      listing "sell Fauna Whisperer" — the comp's own payoff). Both now
      take the target live_coach computes from board + recent acquisitions;
      no evidence means no comp bonus, cards score on their own merits.
      Verified on the replay: every wrong sell and the t9 mis-blessing are
      gone; 172/172 tests.

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
- [x] **Comp-cards box** (2026-09-01): the analysis carries `target_cards`
      (`value.comp_cards`) — the target comp's core/addon cards with display
      names and an owned flag — so the player doesn't open comps.json to see
      what belongs to the comp. Console `describe` renders a TARGET COMP
      shopping list ("[have]" markers), tags shop entries CORE/addon/spell,
      and restructured the whole output into compact labeled sections; the
      overlay's Target comp widget lists the cards as owned/missing chips.
- [ ] Post-game replay review UI.
- [x] **Selection ranker** (`choices.py`, 2026-09-01): the coach now advises on
      the picks it could only count before — hero (1 of 4), trinkets (Lesser/
      Greater), and minion discovers. Parses `DebugPrintEntityChoices` blocks
      (GameState only — PowerTaskList re-prints; options deduped for the
      hero-selection screen re-print), classified hero/trinket/discover/
      unknown. Ranking: heroes and trinkets by NAME against meta/heroes.json
      and meta/trinkets.json (log ids are patch-drifted; names match 100%) —
      hsreplay pick_rate + avg_placement + board-tribe synergy for trinkets;
      minion discovers rank through `shop_ranking` (comp-targeted). Tracked
      incrementally in `live_coach` (SendChoices resolves; lines fall through
      so discover trigger counts are unaffected), surfaces as a "Pick this"
      overlay box, a PICK lead in `top_move`, and a console section. Hero-power
      shift choices (17/game with Master Nguyen) remain unranked — no data.
      Locked heroes (season pass): the log doesn't expose ownership, so the
      top pick carries an "if locked, <next-best>" fallback.
- [ ] Persist live game data so a log rotation / coach restart doesn't lose the
      tail of a game (surfaced when the A. F. Kay game was lost to rotation).
- [x] **Overlay real-estate rework** (2026-09-03/04, from the overlay
      screenshots): full-width three-column layout — DECIDE (Choose 1, Top
      move, Buy, Level/Roll), BUILD (Target comp, Board, triggers), MARKET
      (Tavern shop, Sell ranking, Playable comps) — with the state strip
      (hero/gold/tier/turn/HP/banned) across the top; responsive (3/2/1
      columns). 44px art with hover zoom; art placeholders (initial letter,
      fixed slot) keep every row aligned with or without art. The Buy box
      mirrors the top move's actual buy (buy_step_card written by top_move) —
      they used to disagree (shop #1 vs the plan's affordable card). Shop
      rows show each card's tavern price. Playable comps (was permanently
      "—" on a key mismatch), stacked comp rows, duplicate sell entries
      grouped with ×N badges.
- [x] **Card art: 100% coverage** (2026-09-03): HearthstoneJSON renders lag
      the patch and skip trinkets entirely, and the wiki is Cloudflare-blocked
      — so `hearth_art_extract.py` reads the local client's Unity bundles:
      carddef objects map card id -> portrait GUID (asset names differ between
      content generations, so GUIDs are the stable address), then every
      Data/Win bundle is container-scanned for those GUIDs and the texture
      exported at 256px (+497 art files: 91 trinkets, 92 heroes, 382
      current-season). `/img/<id>.png` also fetches renders on demand (1h
      negative cache, ThreadingHTTPServer so a fetch can't stall /analysis).

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
- [x] **Beta corpus pipeline** (2026-09-03/04): HSReplay confirmed they do
      NOT make replay data available, so we gather our own. `decision_log.py`
      records every advisory alongside the Power.log (log basename + byte
      offset join keys, coach git version — advice is only re-derivable from
      a log under the exact code that produced it); `sanitize_log.py` redacts
      BattleTags (the log's ONLY personal data — a ~1M-line pattern scan
      found no IPs, emails, paths, or account IDs); `package_corpus.py` emits
      one ~5MB gzipped bundle per session (sanitized log + decisions +
      manifest); `upload_corpus.py` PUTs it to the private repo
      **mharrell/hearth-telemetry** (gh keyring or a repo-scoped
      GH_TELEMETRY_TOKEN). Verified end-to-end.
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
- `DEEPSEEK_API_KEY` for the patch-notes LLM extraction pass and headless
  harness runs — set in the user's normal terminal environment.
- Vision model availability for the coach agent (open decision).
