# Hearthstone Battlegrounds AI Coach — Project Design

**Project:** An AI-assisted gaming tool that coaches a human player in real time
during Hearthstone Battlegrounds. Competes with HSReplay/Firestone stat overlays
on *reasoning and dynamic, board-specific, explainable advice* rather than raw
aggregate data volume.

**Status:** Design & bootstrap phase. No live coach yet.

---

## 1. Vision / One-line Pitch

A real-time Battlegrounds coaching overlay that reads the live board and gives
**dynamic, explainable advice** — competing with HSReplay/Firestone stat overlays
on *reasoning*, not raw data volume. Where stat overlays say "this comp wins X% at
your rating," the coach says "you have a triple pair and 8 gold — here's the best
move *for this exact board*, and why."

## 2. What the player gets

- **Live coaching overlay** during a match (dynamic, board-specific, explainable).
- **Post-game replay analysis** — full opponent purchase/move reconstruction from
  the player's own replay logs.
- **Meta reference** — curated screenshots (comp tier lists, hero/Champion
  rankings) the agent consults when advising.

## 3. Why Battlegrounds (vs. Breakout)

Battlegrounds is the **structural opposite** of the reflex game (Breakout) — and
that's exactly what an LLM-based coach wants:

| | Breakout (past work) | Battlegrounds |
|---|---|---|
| Tempo | Real-time reflex | Turn-based, decision-timed |
| State | Continuous frame stream | One readable board screenshot per decision |
| Good play | Mechanical tracking | Strategic, verbal reasoning |
| Coaching output | "Move right now" | "Buy this, level next, pivot to X" |

No reflex/latency pressure. Coaching is *linguistic* — an LLM strength.

---

## 4. Target Architecture (hybrid)

```
                    +-----------------------------------------------+
                    |                COACH AGENT (LLM)             |
                    |  reasoning over (state + meta + stats)       |
                    +------+------------------+--------------------+
                           |                  |
              board state |            meta/context |
                           v                  v
      +----------------+          +-----------------------+
      | LIVE BOARD      |          |  REFERENCE-IMAGE       |
      | PARSER          |          |  LIBRARY (curated      |
      | (from Power.log |          |  screenshots: comp     |
      |  or screen OCR) |          |  tiers, hero ranks)    |
      +----------------+          +-----------------------+
                           ^
                           | optional
              +-----------------------+
              |  HSReplay public API   |
              |  (aggregate stats, if  |
              |  accessible)           |
              +-----------------------+
```

**Two context layers:**
1. **Live board state** (the "specific situation"): tier, gold, board, rolls,
   hero, opponents' visible board/tier.
2. **Meta knowledge (the "general knowledge"):** curated reference screenshots
   (comp meta, hero rankings), plus optionally live HSReplay aggregate stats.

The coach reasons over both simultaneously.

### Design decision — meta reference source (LOCKED)
**Curated screenshots the user takes**, refreshed manually on patches. The coach
fetches only the *relevant subset* per decision (e.g., hero-rank sheet only on
hero-select turn). Self-owned; no dependence on HSReplay's API.

### Model, context & cache strategy (LOCKED)
- **Model: `deepseek-v4-flash`** (1M-token context). Pinned in `coach_llm.py`;
  use the id directly, not the deprecated `deepseek-chat`/`deepseek-reasoner`
  aliases (they route to v4-flash but share its cache and are deprecated).
- **Context: exploit the full 1M window.** The *entire* static meta reference
  (all comps + cards, ~7.5k tokens) fits trivially. No per-decision subsetting
  for size — load it all into the cached prefix.
- **Cache: prefix-cache discipline** (see `.claude/skills/cache-in-flight/`).
  Every request = byte-stable FIXED_BLOCK (system prompt + full meta reference)
  + per-decision VARIABLE tail (live board state + question). A cache hit is
  ~50x cheaper input tokens; the per-decision cost collapses to just the small
  board-state tail. **Never** interleave live state into the fixed block or
  regenerate the system prompt per call — either busts the whole prefix.
- **Verify, don't assume:** read `prompt_cache_hit_tokens` vs
  `prompt_cache_miss_tokens` from each response; if hits are ~0, find the
  prefix drift before scaling up.
- **Client:** `coach_llm.py` (uses `requests`, already in the venv; reads
  `DEEPSEEK_API_KEY` from env). No SDK install needed.

### Domain constraint — family ban (LOCKED)
Each Battlegrounds game allows **exactly 5 tribes** and bans the other 5
(verified across the user's recent replays). A comp is playable only if **every
core card has at least one tribe in the allowed set** — so filter by each core
card's full tribe set, not the comp's `tribe` field (a Demon deck with a Pirate
core card is unavailable when Pirates are banned). `All`/`Neutral` cards are
never-banned; compound cards (e.g. `Demon/Quilboar`) are playable if *either*
tribe is allowed. Detection: the 5 allowed tribes are the **pure single-tribe
minions** in the tavern pool (`BACON_POOL_MINION`); compound minions appear if
any tribe is active, so they can't reveal bans. Implemented in `bans.py`
(`bans_from_log`, `filter_comps_by_available_tribes`). See memory
`hearth-family-ban`.

---

## 4. The Data Asset: Opponent Observation from Own Replays

### Thesis
Each Hearthstone `Power.log` game contains the **full move stream of all 8
players** (hero, purchases, sells, tiers, placement). So each game you play
yields **~8 decision trajectories**, not just your own.

### Why it's valuable
- **8x per-game yield.** Each replay contains the complete decisions of you +
  7 opponents.
- **More than HDT persists.** HDT's own local cache (`BgsLastGames.xml`) stores
  only *your own* final board + placement — **no opponent data**. Your raw
  `Power.log` is richer than the tracker's cache.
- **Not exposed by HSReplay's API.** HSReplay only surfaces aggregate stats; raw
  replays are their proprietary asset. So your own logs are the only way to get
  opponent-level detail.

### What it enables
- MMR-localized coaching (your opponents are near your rating).
- Opponent-modeling as a feature (common patterns at your MMR band).
- A full-time-stream training set (state buckets -> outcome win-tables).

### Honest caveats (breakoutBot discipline)
- **Volume still scales with games played.** Per-game efficiency is 8x, but raw
  volume depends on install base / games played.
- **Observational, not causal.** Placement is confounded by 7 players + shop
  randomness. "Players who took X placed better" is a correlation. Needs
  bucketing + outcome tables, and sham-control on any "advice improves placement"
  claim (the same dead-model-calibration habit from the breakoutBot project).

### Where the data lives
- Hearthstone session logs: `C:\Program Files (x86)\Hearthstone\Logs\`
  `Hearthstone_<timestamp>\Power.log` (or `Power_old.log` after rotation).
- Format: standard Power.log with `CREATE_GAME`, `GAME_SEED`, `BACON_*` tags,
  `TAG_PLAYSTATE`, `SHOW_ENTITY`/`CardID`, `TECH_LEVEL`.
- Parser: **`python-hslog`** (official HearthSim, MIT, Python) — the same parser
  HDT uses. Cloned into `python-hslog/`.

### Validation task (parked / to-do)
Split one `Power.log` into games and extract per-player move stream (hero,
placement, purchases, tiers). Confirms the opponent-data thesis. See
`parse_bg.py` (smoke test) and `analysis/OPPONENT_DATA.md`.

---

## 5. Market / Competitor Landscape

### How HSReplay & Vicious Syndicate get their data
**Crowdsourced from opt-in users, not mined from Blizzard.**
- HSReplay (HearthSim): users install Hearthstone Deck Tracker / Firestone and
  opt in to "replay upload." HDT reads Hearthstone's own logs from the game
  install folder and uploads anonymized replays to HSReplay.net. HearthSim
  processes/aggregates millions of games. Sources:
  - https://hearthsim.info/blog/how-we-process-replays/
  - https://github.com/HearthSim/legal/blob/.../PRIVACY.md
- Vicious Syndicate: same model via their app; they pay a small group of
  high-MMR "contributors" for a ranked, high-skill sample.

### What the app stores locally vs. what it fetches live
Inspected the installed HDT app (`AppData\Roaming\HearthstoneDeckTracker`):
- **Live from API (not stored):** win-rates, tier lists, meta stats. Tiny
  transient cache (`hsreplay_winrates.cache` ~667 bytes with `ServerTimeStamp`).
- **Stored locally:** `BgsLastGames.xml` (own recent BG games, final board only,
  **no opponent data**), `Replays/` (constructed `.hdtreplay` files, own games),
  `hsreplay.cache` (account token), `Images/` (card art), auth tokens.

### Can we get their data?
- **Aggregate stats:** HSReplay has a public API (aggregated stats only). BG-specific
  coverage in the *public* API is uncertain — verify against their api-docs.
- **Raw replays:** not available from either. Own opt-in upload loop is the only
  way to build your own corpus.

### The moat and how we position
- We can't out-compete them on raw aggregate volume (years of contributed replays).
- **We can win on reasoning, dynamic board adaptation, and explainability** — they
  don't do that at all.

---

## 6. Reference-Image Layer (Meta Screenshots) — LOCKED

**Source:** curated screenshots the user takes.
**Refresh:** manual on patches.
**Per-decision fetch:** only the relevant subset (e.g., hero-rank sheet only on
hero-select turn).

### Honest design notes
- **Staleness:** screenshots are point-in-time. Treat as refreshable assets, not
  live data.
- **Legibility is the real risk.** Meta sheets are dense with small text. A vision
  model can misread fine print. Mitigation: scale/crop dense text, and pair each
  image with a short text caption (fallback) so the agent has a reliable signal if
  the pixels are ambiguous. (breakoutBot discipline: *verify what the model
  actually reads.*)
- **Token/cost + latency:** each image eats context. Keep a library on disk; fetch
  only the relevant subset per decision.
- **Complements, not replaces** the live board reasoning.

### Model vision limitation (current)
The current agent model (deepseek-v4-flash:cloud) **does not accept images yet**.
The eventual coach agent may use a vision-capable model or the hosted DeepSeek
API (verify whether the hosted API accepts `image_url` in `content`). See
`analysis/DEEPSEEK_VISION.md` for what we know.

---

## 8. DeepSeek Vision / Model capability (current knowledge)

- Open-source vision model: [DeepSeek-VL](https://github.com/deepseek-ai/deepseek-vl)
  (and paper https://arxiv.org/html/2403.05525v2). Current V-series line includes
  vision-capable variants (e.g., a "DeepSeek V4 Flash Vision" build — third-party
  source). Official [DeepSeek-V3.1](https://huggingface.co/deepseek-ai/DeepSeek-V3.1)
  has multimodal variants.
- **Hosted API image-input is the thing to confirm** against authoritative
  https://api-docs.deepseek.com/api/create-chat-completion and the change log.
  Historically the July 2025 API upgrade covered text tools (JSON output, function
  calling, FIM); vision support has been rolling out around/after that.
- **Recommendation:** verify whether the hosted API accepts an `image_url`
  `content` part before committing architecture.

---

## 9. Setup & Infrastructure Status

- Working dir: `<user dir>\PycharmProjects\visual-game-coach`
  (repo project folder: `hearth-coach/`).
- Cloned `python-hslog/` (official HearthSim parser).
- `parse_bg.py` (smoke-test parser) — reads a Power.log, splits into games, prints
  per-player hero/name/placement. Syntax-validated.
- `.venv` created.
- **BLOCKED:** installing `hslog` deps (`aniso8601`, `hearthstone`) from PyPI —
  network to pypi.org / api.github.com is currently unreachable from the working
  environment. The venv currently only contains `pip`.

### Network situation
- PyPI and GitHub have been intermittently unreachable from the agent's pwsh tool
  (earlier `git clone` succeeded; subsequent direct HTTPS requests to pypi.org,
  files.pythonhosted.org, api.github.com time out). This is a host network/TLS
  issue, not harness-specific.
- To install, either wait for network, or run the install from the user's own
  terminal once connectivity returns.

### Harness / headless notes
- `dsh --profile headless` is how to run a fresh agent from the CLI.
- Headless needs a `DEEPSEEK_API_KEY` in its launching environment (it does NOT
  inherit the GUI's key). The GUI Models page is the credentials service. Not yet
  wired for headless runs.
- The GUI model does not accept images.

---

## 10. Known Pitfalls / Decisions to Respect (from breakoutBot experience)

1. **Verify what a vision model actually reads** before trusting image-derived
   advice (dead-model/confound discipline).
2. **Don't attribute an outcome to one variable** without listing others.
3. **Observational data is not causal** — bucket + control before claiming
   coaching improves placement.
4. **Design decisions before implementation** (project habit).
5. **NoopResetEnv-style timing confounds** — for BG the analog is matching hidden
   game state (opponents' shops) which the game intentionally hides.

---

## 11. Open Questions

- Can we get a public-API / aggregator cleanly, or rely on screenshots + own data?
- Does the hosted DeepSeek API accept images? If not, use a vision-capable model.
- How to do the live board parse: from Power.log (authoritative) vs. screen OCR.
- How to measure coaching effectiveness rigorously (sham-control design).
- Latency/cost budget per decision point.

## 12. Next Steps (see ROADMAP.md)
