# Bob's Ledger — Design

**Built:** a Battlegrounds board reader and (in progress) a post-game review. It
reads the game's own `Power.log`, reconstructs the board, and shows what is true
about it. What produces those numbers is a **deterministic value function plus a
growth simulator over a curated meta database** — no model is called during play,
no API key is needed, and nothing about the game leaves the machine.

**Why this document mentions LLMs at all.** The project began as an
exploration of where a language model *would* help in a game coach, and that
thinking is preserved below (sections 4, 7 and the strategy notes) because it
explains why the engine is shaped the way it is. Two things came of it, and
neither is the runtime: `coach_llm.py` + `patch_notes.py` extract Blizzard's
patch notes into the meta DB (maintainer tooling, absent from a release), and
`compare_models.py` was a model-comparison harness. The **live path calls
no model**, and any section here that reads as a plan is history, not a
roadmap item.

**Status:** Live overlay running (Phase 5 V1 overlay; see ROADMAP.md), now
shipping state only — see §0.

---

## 0. Posture: what ships live, what ships after the fact (2026-10-06)

**The live path ships STATE. The verdict ships after the fact, in the review.**
Full reasoning, the corrections to the claim that triggered it, and the phase
plan are in `PIVOT.md` (maintainer-only, and never published).

The split, precisely:

| Live (the overlay)                                                            | After the fact (the review)                        |
| ----------------------------------------------------------------------------- | -------------------------------------------------- |
| Board stats vs the next opponent and vs the lobby; fragility band; scout strip  | The model's line for the phase, step by step        |
| Each board minion's value number and its composition role                       | The card it would have bought, and why              |
| The tavern's offers in the game's own order, with price, pool count and role    | The pick it would have taken                        |
| Comp pieces owned/missing; commit-readiness meters; lobby pressure              | What the player actually did, and what it cost      |
| Hero/trinket/discover options with their own scores — no winner named           | Adherence and outcome, per advice class             |

**The mechanism is one choke point.** `coach_ui.render_json()` is the only place
the page's view is built, and it drops every key in `LIVE_VERDICT_KEYS`. The
analysis keeps all of them: `decision_log.record()` writes it, and
`replay_review` / `outcome_audit` / `fight_table` read it back. So the engine is
untouched — `value.top_move` still computes the numbered plan on every buy
phase — and only its destination changed. `test_live_view.py` asserts all three
halves (dropped from the page, kept in the analysis, read by no page code), and
`test_readme_claims.py` asserts the README's claims about the machine *and* that
the capability is absent from `app/`.

**Two things this posture does NOT claim.** It is not a claim of safety: EULA
1.C prohibits software that "facilitates the gameplay" and grants an advantage,
and a statistics overlay grants that advantage too — the clause does not mention
verdicts. And it is not a claim that the model was wrong to have opinions: the
plan is the part of this project worth keeping, and the review is where it can
be measured against outcomes instead of asserted at a player mid-turn.

**Not yet built:** the review itself (PIVOT.md Phase 2). Until it exists, the
plan is recorded locally and readable through the maintainer tools; the player
sees the state overlay. Do not describe the review as shipping until it does.

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
`meta/comps.json` holds **24 comps, 4 of them Aberration**
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
| `comps.json` | 24 comps (tier, difficulty, core/addon cards, how-to-play, when-to-commit) |
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
  old when last checked); rescrape when the meta moves. `scrape_comps.py
  --changes` is how to ask whether it moved: it prints the source's OWN change
  metadata (`comp_tier_last_updated`, `comp_previous_tier`,
  `comp_tier_recently_updated`) newest-first, beside our stored tier — so the
  question is answerable without trusting the copy whose staleness is in doubt.
  `--diff` shows card and text edits but can only compare against that copy.
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

## 7. (Research record) Vision models reading card art — not used by the coach

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

- Working dir: this repository (the code is at the root).
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

### What players send, and how it is bounded

Collection is consented, small, and built from a whitelist rather than a
filter:

- **Consent is asked once**, on the welcome card, remembered in
  `.share_consent.json`, and reversible from that card, `share.py on|off`, or
  `--no-share` for a single session. Undecided sends nothing, and the card's
  privacy sentence is generated from the state so it cannot drift from what
  the code does.
- **What is sent is a distillation**, not the log: `session_report.py` turns
  154 advisories from a 7.5 MB decision log into 15.6 KB. The bulk it drops
  (`game_comps` at 38 KB per record, `playable_comps` at 15 KB) is the comp
  tree, which is not what checks advice against outcomes.
- **The report cannot carry a person.** `SPEC` names every field allowed, and
  `verify()` re-walks the finished report against the same spec, so a new
  analysis field cannot travel by accident. `analysis.opp_comp.name` is the
  opponent's handle and is excluded by construction — not by a regex.
- **Transport:** `POST /session` is unauthenticated by design (a secret inside
  a downloadable client is not a secret) with a 512 KB cap, a shape check and
  a coarse personal-data net; reading is keyed (`GET /sessions`), and
  `fetch_sessions.py` pulls reports into `sessions_in/` (or summarises them
  with `--stats`).
- **Open ingest, accepted deliberately (2026-10-03).** Fabrication is possible,
  so the corpus is indicative rather than evidential — a trade the maintainer
  took knowingly, not by omission. The escalation path if volume or abuse ever
  justifies it, in the order it would be used: the per-location throttle is
  already live (20/60s), a stored report can never be overwritten, implausible
  content is refused, `?days=all` purges the store in one command, and beyond
  that handed-out keys would buy attribution at the cost of friction.
- **Retention: 30 days**, swept daily at 04:00. It is also the only answer an
  anonymous design can give to "delete mine": there is nothing to look a
  report up by, which is the same property that protects the players sending
  them.
- **Capacity is the reason for the tier.** At ~16 KB a report the free KV tier
  holds tens of thousands, against roughly 750 of the 1.3 MB full-log bundles.
  Full logs stay opt-in through `package_corpus.py`.
- **Throttled per location, not globally.** `POST /session` is limited by a
  Worker rate limiting binding (20/60s, keyed on the caller's address used only
  as a counter key), checked before the body is read. It is per Cloudflare
  location, so one source flooding from one place is stopped; a distributed
  attacker gets N x the allowance. That is the honest bound: a global cap needs
  a custom domain plus a zone WAF rule, or a KV counter that costs a write per
  upload.

### Distribution & first run

**The launcher offers to turn on Hearthstone's file logging** (2026-10-03),
because that step is the one nearly every new player misses and the difference
between advice and an empty card forever. `setup_logging.py` makes the edit,
under three rules that came out of looking at a real file: it creates
`log.config` only when there is none; when one exists it sets ONLY `LogLevel=1`
and `FilePrinting=true` inside the existing `[Power]` section, leaving the
other five sections (`[Achievements]`, `[Arena]`, `[FullScreenFX]`,
`[LoadingScreen]`, one more) byte-identical; and it copies the original to
`log.config.bobs-ledger-backup` before the first change. It refuses while the
game is running, since the game reads that file at startup.

That is a deliberate exception to "the coach only reads": it edits one file it
does not own, which is why it asks first, says what it changed, keeps the
original, and never touches anything else on disk. The README's promise was
rewritten to say exactly that rather than leave the old one standing.

`publish_release.py` builds the zip (code + `meta/` + user docs; never
`analysis/`, `telemetry/`, `CLAUDE.md`, the caches, local data, or any
`.lnk`), stamps `VERSION` and `.update_state.json`, and PUTs it plus a
manifest to the collector's KV namespace. Users are pointed at ONE place:
`GET /release/latest.zip` (a 302 to the current zip, no GitHub account
needed). A GitHub release is still cut for every version — the version, the
note and the asset live on that page — but the README does not offer it as a
second way to do the same thing (2026-10-03). `GET /release/latest.json`
is the updater's manifest, not a user instruction.

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

### Updates are atomic (2026-10-03)

An update used to rewrite the install file by file, straight over the running
copy. Killed part way through — a crash, a power cut, a second coach window
holding a file open — it left a tree that was part old and part new, with no
way back but downloading the zip again. A truncated module is an install that
cannot start, and the player has no way to tell which half they have.

`apply_zip` is now three phases:

1. **Stage.** Unpack the release into `.staging/new`. Nothing outside
   `.staging` is written, so the failure-prone half — a corrupt archive, a full
   disk, a killed process — cannot cost the player their coach.
2. **Verify.** Every staged entry is present at the size the zip states. A
   short write is exactly what a kill leaves behind, and it is caught here,
   before anything has moved.
3. **Commit.** Each file is *moved* into place — one atomic replace per file,
   never a rewrite in place — with whatever it replaces set aside in
   `.staging/old` first. A failure mid-commit rolls back: the set-aside copies
   go back and the files this release added are removed, because new code
   beside old code is the mixed state all of this exists to prevent.

The phase is recorded as a marker *inside* the staging directory, so a later
start can finish whichever direction was interrupted. `APPLYING` means a commit
was in flight and the install may be half-updated, so it is rolled back;
`APPLIED` means the commit finished **and verified**, so there is nothing to
undo and recovery only tidies up. That distinction is the whole safety
property: rolling a good update back would throw it away.

Recovery deliberately runs in two places. Both launchers do a crude,
dependency-free restore from `.staging/old` *before* the program check, because
a killed commit can leave `app/live.py` missing and a launcher that responds by
telling the player to re-extract the zip they already extracted is useless.
`update.recover()` — also reachable as `update.py --recover` — then finishes
the job precisely once Python is up, including removing the files the new
version added. Player data is untouched by construction: `PROTECTED` paths are
skipped at stage time, so nothing in the commit can reach them.

Rejected alternatives, recorded because they look attractive: renaming `app/`
to `app.old` wholesale (instant swap, but the player's data lives *inside*
`app/`, so it would have to be re-attached within the same window — more moving
parts around the data to shrink a code-only window), and keeping the previous
code on disk to switch to on failure (two copies of the coach, and a "which one
am I running?" question at every start).

### macOS: groundwork only (2026-10-03)

The runtime needed nothing Windows-specific — no ctypes, no Tk, no window
manipulation, and the overlay is a localhost page in a browser — so the port
is a short list rather than a rewrite. What was platform-bound:

- `config.default_home` (client root; macOS keeps the game in `/Applications`)
  and the log lookup. Windows writes `Logs/Hearthstone_<date>/Power.log`; the
  community reference documents a flat `Logs/Power.log` on macOS, and which
  one the client actually uses is **unverified**, so both patterns are asked
  for.
- `setup_logging.config_dir`: `~/Library/Preferences/Blizzard/Hearthstone`,
  not `AppData`. The old code read `LOCALAPPDATA`, which is unset on a Mac, so
  it would have resolved to `~/Blizzard/Hearthstone` — a folder the game never
  reads — and created a log.config there.
- The running-game probe. `tasklist` does not exist on macOS and the old
  `except: return False` answered "not running", i.e. it would have edited
  `log.config` underneath a live game, the one thing that module promises not
  to do. macOS asks `pgrep -x Hearthstone`, falling back to `ps`.
- `Start Bob's Ledger.command`, the launcher twin.

Packaging: the zip is built on Windows, where a file has no Unix mode, so the
launcher entries are stamped `0o755` with `create_system=3` — otherwise macOS
unarchives a `.command` nobody can double-click — and `apply_zip` re-applies
the bit after extracting, because `zipfile` does not restore permissions.
`privacy_scan.TEXT_SUFFIXES` now covers `.cmd`, `.command` and `.bat`: the
launchers were the most-copied files in the project and the least scanned.

**Unverified, deliberately recorded:** no Mac has ever run any of this, and no
shell on the packaging machine has even parsed the `.command`. The unit tests
inject the platform, which covers the logic and the exact command lines — not
macOS. Nothing should be announced as Mac support until a Mac completes an
install and a game.

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
