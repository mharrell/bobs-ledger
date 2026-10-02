# Hearthstone Battlegrounds AI Coach — Project Design

**Project:** An AI-assisted gaming tool that coaches a human player in real time
during Hearthstone Battlegrounds. Competes with HSReplay/Firestone stat overlays
on *reasoning and dynamic, board-specific, explainable advice* rather than raw
aggregate data volume.

**Status:** Live coach running (Phase 5 V1 overlay; see ROADMAP.md for phase
status). The advice model is still a deterministic value function; the LLM
reasoning layer (Phase 4) is the open build.

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
- **Meta reference** — a structured JSON DB (comps, cards, trinkets, dark gifts,
  heroes, minions, tavern spells) the agent consults when advising. See
  `meta/` and the "Meta reference" section below.

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
      | LIVE BOARD      |          |  META REFERENCE        |
      | PARSER          |          |  (structured JSON DB:  |
      | (from Power.log |          |  comps, cards, trinkets,|
      |  or screen OCR) |          |  dark gifts, heroes,   |
      +----------------+          |  minions, tavern spells)|
                           ^       +-----------------------+
                           | optional
              +-----------------------+
              |  HSReplay public API   |
              |  (aggregate stats, if  |
              |  accessible)           |
              +-----------------------+
```

**Two context layers:**
1. **Live board state** (the "specific situation"): tier, gold, board, rolls,
   hero, opponents' visible board/tier, and the per-game family ban.
2. **Meta knowledge (the "general knowledge"):** the structured meta reference
   (comp meta, card details, trinket/hero/minion/spell data), plus optionally
   live HSReplay aggregate stats.

The coach reasons over both simultaneously.

### Design decision — meta reference source (LOCKED)
**A structured JSON DB** in `meta/` (comps, cards, trinkets, dark gifts, heroes,
minions, tavern spells), built from hsreplay pages + the hearthstonejson card DB
+ the wiki.gg tavern-spell page. Refreshed manually on patches. The coach loads
the relevant subset per decision. Self-owned; no dependence on HSReplay's API
(which is Cloudflare-protected for minions/heroes/dark-gifts — those are captured
via manual paste).

### Model & cache strategy — two distinct things
**1. The Claude Code session (the tool building the coach) runs on
`deepseek-v4-flash`** (1M context) with prefix-cache discipline. That's the
harness config in `~/.claude/settings.json` — it powers *this* agent, not the
coach's runtime. Cache discipline: byte-stable FIXED_BLOCK + per-decision
VARIABLE tail; verify via `prompt_cache_hit_tokens` vs `prompt_cache_miss_tokens`.

**2. The coach's advice model is a separate, OPEN decision** (see ROADMAP
"Open decisions"). It was never locked. `coach_llm.py` is a GLM 5.3 flash
client (`DEFAULT_PROVIDER = "glm"`, provider-agnostic) that exists in the
repo (kept) but is **not** the intended advice engine
at this time. The coach's reasoning model — hosted API vs local vision-capable
model — is still to be chosen.

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

## 5. The Data Asset: Opponent Observation from Own Replays

### Thesis
Each Hearthstone `Power.log` game contains the **full per-player record of
all 8 players** (hero, hero name, tavern-tier timing, final placement). So
each game you play yields **~8 tier trajectories**, not just your own — but
not 8 complete decision streams: opponents' individual buys and sells are
**not** recoverable, because they share the spectator player number (Phase 1
finding, `analysis/OPPONENT_DATA.md`; the friendly side's buys/sells do
parse). Tier timing is the one clean per-player decision signal.

### Why it's valuable
- **8x per-game yield.** Each replay contains the tier/placement record of
  you + 7 opponents.
- **More than HDT persists.** HDT's own local cache (`BgsLastGames.xml`) stores
  only *your own* final board + placement — **no opponent data**. Your raw
  `Power.log` is richer than the tracker's cache.
- **Not exposed by HSReplay's API.** HSReplay only surfaces aggregate stats; raw
  replays are their proprietary asset. So your own logs are the only way to get
  opponent-level detail.

### What it enables
- MMR-localized coaching (your opponents are near your rating).
- Opponent-modeling as a feature (common patterns at your MMR band).
- A per-player tier-timing + outcome training set (state buckets -> outcome
  win-tables).

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
- Parser: **stdlib only, no `hslog`** — `extract_game.py` parses the raw log
  directly (verified: `hslog`'s `EntityTreeExporter` is built for constructed
  2-player games and mangles Battlegrounds' 8-player structure, collapsing all
  7 opponents into the "spectator" player). `python-hslog` (official HearthSim,
  MIT) is vendored into `python-hslog/` and used only by the `parse_bg.py`
  smoke test, not on the BG data path.

### Validation task — DONE (2026-08-24/25, ROADMAP Phase 1)
`extract_game.py` splits one `Power.log` into games and extracts the
per-player record (hero, hero name, account name, placement, tier) plus the
move stream: tier timing for all 8, buys/sells for the friendly side only.
Confirms the opponent-data thesis with the buy/sell caveat above. See
`analysis/OPPONENT_DATA.md`.

---

## 5b. Market / Competitor Landscape

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

## 6. Meta Reference (structured DB) — LOCKED

**Source:** a structured JSON DB in `meta/`, built from hsreplay pages + the
hearthstonejson card DB + the wiki.gg tavern-spell page.
**Refresh:** manual on patches (re-run the scrapers / re-paste Cloudflare-gated
data). Balance changes can be applied from official patch notes with
`patch_notes.py <url>` (fetches the page, LLM-extracts before/after changes,
dry-runs by default; `--apply` writes them). New cards still need manual entry
(patch notes don't carry internal card IDs).
**Automated check (review-first):** `check_patch_notes.py` discovers the latest
patch from the Blizzard news page, writes a reviewable report to
`patch_reports/`, and toasts — it never edits the meta DB. Register it as a
weekly Windows Task Scheduler task with `register_patch_check.ps1`. A human
reviews the report and applies with `patch_notes.py <url> --apply`.
**Per-decision fetch:** the coach loads the relevant subset per decision (e.g.,
comps filtered by the family ban; the hero-rank list on hero-select).

### Provisional comps — mined from our own corpus (added 2026-09-23) — LOCKED

The comp list comes from a scraped source, and that source does not cover every
tribe in play. When this section was written (2026-09-23) it had **26 comps
across the ten original tribes and none for Aberration**, which 36.6.1 added.
Measured consequence (2026-09-23, 12 games in the local corpus): **4 games
ended on an Aberration-dominant board**, and in a typical game **36–60% of the
coach's lines were the "no target comp" placeholder**. Those games are also
structurally unmeasurable — a player cannot follow advice that does not
exist — so the gap corrupts the adherence metric as well as the coaching.

**Resolved since (2026-09-26):** the source now publishes Aberration comps —
`meta/comps.json` holds **35 comps, 4 of them Aberration**
(`aberrations-deathrattle-spells`, `aberrations-apm-deity`, `aberrations-sludge`
scraped; `aberrations-deity-feed` promoted from our own corpus) — and **no entry
carries `provisional: true` today**. The mechanism below is kept because it is
the standing path for the next tribe the source misses.

**`comp_miner.py --promote`** fills it and the entry carries its own caveat:

- **Marked.** `provisional: true`, `source`, and an `evidence` block (games,
  top-4 count, floor, build date, per-card share and average placement). A
  provisional comp is labelled everywhere it can reach the player, in the plan
  ("provisional — 4 of our games"), the overlay's comp box, the comp-direction
  rows and the Playable-comps panel (grouped under "Provisional", sorted last).
- **Second class by construction.** It never enters the ≥2-hit commit, the
  recent-acquisition pivot, or the tribe-level signal (`value._is_provisional`),
  so a published comp always outranks it. It is reachable through exactly ONE
  path: `comp_target`'s gap branch, for a board whose dominant tribe has no
  published comp at all.
- **No invented tier.** `meta_tier`/`difficulty` stay null: nobody published
  this comp, so there is no tier to quote, and a fabricated "A" would let it sort
  among real comps and win pick ranking it never earned.
- **The gap stays visible.** `comp_gap` still reports the tribe (it is about the
  *published* source), so the honest "no comp published for X yet" message and
  the cohort split in measurement both keep working.
- **The scraper cannot delete it.** `scrape_comps.py --prune` drops only what the
  source used to list; a provisional entry is kept and reported, and
  `--promote`/`shadowed_provisional` reports the intended end state — a
  provisional comp whose tribe the source has since published — for a human to
  retire.

First entry: **`aberrations-deity-feed`** ("Aberrations - Deity Feed", n=4,
top4=2), core Faceless Converter + N'raqi Sapper. It was **promoted to a
first-class comp on 2026-09-26** (player decision: the published
`aberrations-deathrattle-spells` shares Converter/Titus/Sapper/Corroder/Shadow
of Doubt, but this is the distinct deity-pool spell-scaling build the player
actually plays), so `comp_miner.py --promote` now refuses to touch it — a
non-provisional row is never overwritten.

### The current pool and out-of-play (added 2026-09-22) — LOCKED

The snapshot above has no concept of a card *leaving*, which is why a removed
card stayed recommendable forever. Patch 36.6.1 (a new minion type, Aberrations;
Naga rotated out) forced the issue, and two data layers now answer it:

- **`meta/pool_roster.json`** — the **current pool**, mined from the machine's
  own Power.logs by `pool_roster.py`. The game dumps its pool at game start
  (every in-pool minion as a `FULL_ENTITY` with `TECH_LEVEL`, `ATK`/`HEALTH`,
  `CARDRACE`, `IS_BACON_POOL_MINION`), so this is authoritative, offline and
  patch-proof where the paste is a hand-refreshed snapshot. Sessions group into
  content **epochs**; the boundary is read from content, not `BuildNumber`
  (which did not change across 36.6.1).
- **`meta/out_of_play.json`** — the **registry** of what is not in play
  (rotated tribes, removed cards), each with reason/patch/date and a `history`
  block. Enforced by **`playable.py`**, which is also the review gate:
  `validate()` cross-checks the official removal lists against the mined pool
  and reports disagreements rather than hiding them. `HEARTH_OUT_OF_PLAY=0`
  disables enforcement so a historical replay review is judged under the rules
  it was played with.

Design, evidence and the remaining gaps: `analysis/pool_and_out_of_play.md`.

### The assets (`meta/`)
| File | Contents |
|------|----------|
| `comps.json` | 35 comps (tier, difficulty, core/addon cards, how-to-play, when-to-commit) |
| `cards.json` | 89 curated cards (name, tier, tribe, atk/health) |
| `trinkets.json` | 220 trinket rows (Lesser/Greater/variants; pick rate, avg placement, distribution, guide) |
| `dark_gifts.json` | 43 dark gifts (name, description; not ranked — see `choices.py`) |
| `heroes.json` | 117 heroes (hero power, pick rate) |
| `minions.json` | 334 minions by tavern tier, with full card details |
| `tavern_spells.json` | 86 tavern spells by tier, with cost + text |
| `engines.json` | 14 growth engines (machine-readable trigger chain) |
| `guides/` | comp guides mined from commentary transcripts |

### Honest design notes
- **Staleness:** the meta is point-in-time. Treat as refreshable assets, not live
  data. The comps tier list updates frequently (the newest tier change was ~22h
  old when last checked); rescrape when the meta moves.
- **Source access:** hsreplay embeds comps/trinkets data in HTML (scrapable), but
  minions/heroes/dark-gifts load via a **Cloudflare-protected API** — those are
  captured via manual paste. The wiki.gg tavern-spell page is accessible and
  supplies the spell tier grouping.
- **Token/cost + latency:** the full meta is small (~tens of KB), so it fits in
  the cached prefix; per-decision subsetting is for relevance, not size.
- **Complements, not replaces** the live board reasoning.

### Model vision limitation (current)
The current agent model (deepseek-v4-flash:cloud) **does not accept images yet**.
The eventual coach agent may use a vision-capable model or the hosted DeepSeek
API (verify whether the hosted API accepts `image_url` in `content`). See
`analysis/DEEPSEEK_VISION.md` for what we know.

---

## 7. DeepSeek Vision / Model capability (current knowledge)

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

## 8b. Setup & Infrastructure Status

- Working dir: `<repo root> Pangolin\PycharmProjects\visual-game-coach`
  (repo project folder: `hearth-coach/`).
- Cloned `python-hslog/` (official HearthSim parser).
- `.venv` created; `requests` available (no SDK install needed for the LLM client).
- **Tools built:**
  - `parse_bg.py` / `extract_game.py` — Power.log → per-game player/hero/placement.
  - `board_state.py` — Power.log → friendly final board + hand + hero state
    (spending-aware gold).
  - `bans.py` — Power.log → per-game 5 allowed / 5 banned tribes; comp filter
    (partial pool reveals fail open and retry).
  - `scrape_comps.py` — hsreplay comp pages → `comps.json` (`--top N`, `--prune`).
  - `coach_llm.py` — GLM 5.3 flash client (`DEFAULT_PROVIDER = "glm"`;
    DeepSeek is a switchable second provider) with prefix-cache discipline.
  - `parse_trinkets.py` / `parse_minions.py` — meta raw pastes → JSON.
  - `value.py` — minion value function (sell ranking, shop ranking, top move;
    real upgrade button prices, level-vs-board rule, comp-pivot tracking).
  - `choices.py` — hero / trinket / discover pick ranking.
  - `simulate_growth.py` — deterministic growth simulator (engine model in
    `meta/engines.json`; golden, compounding, tribe-scaling).
  - `live_coach.py` — incremental live coach (fast per-buy-phase analysis).
  - `live.py` — live monitor + overlay server.
  - `coach_ui.py` — overlay (two-pane Decide/Reference on wide windows, prices,
    card art).
  - `validate_growth.py` — simulator validation against real games.
  - `replay_stats.py` — deterministic replay-analysis pipeline (corpus stats).
  - `replay_review.py` — per-phase coach-recommendation vs player-actions diff.
  - `hearth_art_extract.py` — UnityPy card-art extraction from the local
    client (GUID-addressed; 100% coverage).
  - `sanitize_log.py` / `decision_log.py` / `package_corpus.py` /
    `upload_corpus.py` — the beta corpus loop → private repo
    `mharrell/hearth-telemetry`.
  - `privacy_scan.py` — the independent checker behind every privacy claim
    (see "Privacy & sharing" below).
  - **Automation toolkit (2026-09-23).** Output tokens are the expensive
    side, so every entry point is bounded to a few lines and takes `--json`:
    `patch_day.py` (detect patch → fetch notes → canary the parsers →
    report; `--apply` refreshes), `doctor.py` (one-shot pre-flight verdict:
    patch, coverage, gates, art, trinket coverage, newest log),
    `logquery.py` (eight bounded Power.log queries), `review_kit.py`
    (per-game review skeleton + turn drill-down, cached), `comp_miner.py`
    (mine OUR corpus for comps the scraped source lacks; proposes, and
    `--promote` writes a PROVISIONAL entry marked as such), `pool.py` /
    `lobby.py` / `pool_roster.py` (own-side pool ledger, seat-level
    opponent snapshots, log-mined pool roster), `outcome_audit.py` and
    `turn_forensics.py` (advice-vs-outcome and log-mechanics forensics).
  - Root `sync.py` — commit + merge into main + push, in one command.
- **Meta reference:** complete in `meta/` (see section 6).

### Privacy & sharing (2026-10-02)

The coach reads logs, so its privacy claims have to be measured, not
asserted. Three mechanisms, in order of who they protect:

1. `sanitize_log.py` redacts every player identity a Power.log carries —
   BattleTags, the bare opponent handles Battlegrounds writes for most
   opponents (no discriminator at all), and `GameAccountId` pairs, whose
   `lo` half is stable per account and so links a player's uploads. Each
   becomes a stable `P1, P2, …` placeholder, which is what keeps the
   sanitized log analysable: it produces identical advice.
2. `privacy_scan.py` verifies, using deliberately DIFFERENT code from the
   redactor. The first version of this check called the sanitizer on its own
   output, and certified a bundle clean that shipped fifteen opponent
   handles; a check that asks the cleaner whether it cleaned is not a check.
   It is what `package_corpus --inspect` runs, and what `publish_release.py`
   gates on.
3. `publish_release.py` refuses to publish unless two gates pass: PRIVACY
   (no shipped text file carries personal data) and REPRODUCIBILITY (the zip
   matches HEAD, with no uncommitted edits and no stray untracked entries —
   the zip is built from the working tree, so a scratch directory once
   inflated a release from 236 entries to 472). Both have explicit
   overrides so an exception is a decision, not an accident.

### Distribution & first run

`publish_release.py` builds the zip (code + `meta/` + user docs; never
`analysis/`, `telemetry/`, `CLAUDE.md`, the caches, local data, or any
`.lnk`), stamps `VERSION` and `.update_state.json`, and PUTs it plus a
manifest to the collector's KV namespace. Users get it from
`GET /release/latest.json` → `GET /release/<zip>`, or by `git clone`.

A released zip keeps itself current because the stamp it carries is the
other half of the update join: direction is decided by the manifest's
publish timestamp against that stamp, and without a stamped state a fresh
install could only ever answer "unknown", which is why the update offer
never fired until 2026-10-02.

First run is `Start Bob's Ledger.cmd` at the zip root: it finds Python
(venv → `py -3` → `python`), asks before installing the one dependency,
reports the log folder without writing to it, offers a Desktop shortcut
with `bobs-ledger.ico` on it, and starts the coach with the overlay open.
Windows never draws an icon on a `.cmd`, so the shortcut is the only
clickable thing that can wear the icon; it is created on the user's machine
because a `.lnk` embeds absolute paths.

### Network situation
- hsreplay's minions/heroes/dark-gifts APIs are Cloudflare-protected (403) —
  those meta assets come from manual paste; the comps/trinkets pages are
  scrapable. The wiki (hearthstone.wiki.gg) is now Cloudflare-blocked too
  (2026-09-03) — card art comes from the local client via `hearth_art_extract.py`
  instead.

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

- Does the hosted DeepSeek API accept images? If not, use a vision-capable model.
- (Resolved) Live board source: **Power.log tailing** (authoritative, no OCR) —
  implemented and validated in `live.py` / `live_coach.py`.
- How to measure coaching effectiveness rigorously (sham-control design;
  Phase 6 — `replay_review.py` is the first data-collection tool).
- Latency/cost budget per decision point.
- Coach's advice model: hosted API vs local vision-capable model (the
  deterministic value function is the interim advice layer).
- (Resolved) Meta source: structured JSON DB in `meta/`; hsreplay's
  minions/heroes/dark-gifts APIs are Cloudflare-protected, so those come from
  manual paste; the wiki supplies the tavern-spell tier grouping.

## 12. Next Steps (see ROADMAP.md)
