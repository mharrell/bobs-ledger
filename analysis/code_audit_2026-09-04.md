# Codebase audit — hearth-coach (2026-09-04)

Three-part audit of the ~36 project modules (~8.2k lines): organization/architecture,
coding conventions, and efficiency. Baseline: 171 tests, 170 pass in ~2s (one
import error, see §8).

## Verdict: not spaghetti — healthy skeleton, but accreting fast

The architecture is sound: clean acyclic import DAG (parse → state → reasoning →
loop → UI), a shared `tribes.py` leaf, a real test suite, and docstrings that tie
every heuristic to the game that motivated it. The liabilities are
**accretion-driven, not architecture-driven** — patterns that keep producing
copies of themselves until a couple of shared layers exist. The two hotspots
trending toward spaghetti are `value.py` and `live_coach.py`.

```
extract_game.py (parse base)
  ↑
board_state.py  player_actions.py  bans.py ──> tribes.py (leaf)
  ↑                ↑
  └── live_coach.py ──────────────> meta.py, choices.py
                  └────────────────> value.py ──> simulate_growth.py
                       ↑                ↑
        coach.py, choices.py, coach_ui.py, replay_stats.py, replay_review.py
  live.py ──> live_coach + coach + coach_ui + choices + decision_log  (entry)
```

---

## Findings (ranked)

### 1. `value.top_move` — the worst file in the project

`value.py:573-849`. A **277-line planner+formatter** that:

- does pricing, the entire leveling-gate model (Q0-Q2), pick advice, budget
  walking, sell-for-room, endgame messaging, *and* output formatting;
- **mutates its caller's dict** (`analysis["buy_step_card"]`, `["buy_step_roll"]`
  — value.py:750-751, 787, 821, 835, 848), a hidden side-effect contract the UI
  depends on (coach_ui.py:480-481);
- has its **rendered text re-parsed by the UI as the data protocol**
  (`step.match(/^(\d+)\. (.*)$/)` coach_ui.py:298;
  `(analysis.get("top_move") or "").startswith("1. LEVEL")` coach_ui.py:498).
  Rewording a message can silently break the overlay.

**Fix direction:** extract a structured plan object (list of steps with
kind/card/reason); render strings only at the UI edge.

### 2. The meta-loading layer exists but is bypassed everywhere

`meta.py` was meant to be canonical; instead:

- `os.path.dirname(os.path.abspath(__file__))` hand-rolled in **24 modules**
  (plus inline repeats: player_actions.py:217, 230, 310; replay_review.py:80, 89).
- **35+ raw `json.load(f)` sites.** `minions.json` opened independently in
  value.py:75, value.py:1006, player_actions.py:218 *and* player_actions.py:231
  (two loaders in one file), replay_review.py:81, validate_growth.py:36,
  extend_pool.py:26. `comps.json` in meta.py:15, coach.py:72, live_coach.py:564,
  replay_stats.py:27, coach_llm.py:46.
- Six naming schemes for "read a meta JSON": `_load_card_db` / `_load_spell_db` /
  `_load_bg_names` (value.py), `_load_bg_pool` / `_load_bg_minion_ids`
  (player_actions), `_load_trinket_db` / `_load_hero_db` (choices),
  `load_meta` (patch_notes.py:192).
- **Three different missing-file behaviors** for the same condition:
  import-time hard failure (meta.py:12-16), `os.path.exists` guard returning `{}`
  (value.py:76-79, choices.py:70-75), try/except OSError returning `{}`
  (live_coach.py:97-104). A corrupt meta file fails at different points
  depending on which module reads it first.
- `meta.py`'s own eager import-time loaders are dead code except `hero_power`
  (used by coach.py:84, live_coach.py:22). The list-or-dict tolerance snippet is
  copy-pasted 3 times (value.py:101, choices.py:74, choices.py:85).

**Fix direction:** make `meta.py` the only place that opens `meta/*.json` —
lazy (module-level `functools.lru_cache`), one behavior for missing files.

### 3. Quad-replicated "is this a minion id" regex — copies already disagree

Four divergent definitions:

| Location | Notes |
|---|---|
| `board_state.py:35` (`MINION_ONLY`) | includes `BG\d+_[A-Z]+_\d+` set-code forms |
| `player_actions.py:21` | narrower — **misses the set-code form** |
| `choices.py:60` (`_is_minion_id`) | inline, matches board_state's version |
| `extract_game.py:57` (`MINION`) | yet another pattern with `BG\d+_GS\d+` |

The next set-code addition will make live and batch parse the same log
differently. **Fix direction:** one definition in `extract_game.py` beside
`HERO_CARD`, imported everywhere.

### 4. Copy-paste block in the hottest loop + live/batch duplication pairs

- `live_coach.feed()` contains the shop-reset + `_SHOP_OPT` logic **twice**
  (live_coach.py:326-335 vs 361-370), with a dead `m = _SHOP_OPT.search(line)`
  at line 356 overwritten at 371. Doubles regex work on every line of a
  40-120 MB log; the copies can silently diverge. Looks like a merge artifact.
- Identical twins across modules:
  - `_banned()` — live_coach.py:73-78 and coach.py:100-104.
  - `_median()` — live_coach.py:81-87 and build_baseline.py:27-31.
  - `_game_seed()` — coach.py:33-38 and replay_stats.py:162-168.
  - Trigger-count scenario builder — live_coach.py:196-231 re-implements
    player_actions.py:239-290 (same six keys, acknowledged by the comment at
    live_coach.py:164-165). Same for the spell-cast heuristic
    (live_coach.py:41-43,160-168 vs player_actions.py:60,153-160).
  - Tavern price rule (minion=tier, spell=cost) built in both layers:
    value.py:599-602 and coach_ui.py:459-460.
  - Magic thresholds hardcoded in Python *and* JS: sell floor 15/16
    (`W_SELL_FLOOR = 16` value.py:40, hardcoded `< 15` value.py:807, JS
    `s.score < 15` coach_ui.py:343); dying threshold 12 (value.py:661, JS
    coach_ui.py:250); level-cost fallback `tier+1` (value.py:653, 791, JS
    coach_ui.py:311).
  - Scout fallback chain: value.py:684-688 and coach_ui.py:487-491.
  - `patch_notes.py:34,167` re-implements the DeepSeek call instead of using
    `coach_llm.complete` (compare_models.py:36 does it right).
  - The `_X = None` + `def _load(): global _X` cache dance hand-rolled 4×
    (meta.py:54, decision_log.py:26, player_actions.py:209, live_coach.py:90).

### 5. No shared config module

- The hardcoded `C:\Program Files (x86)\Hearthstone\Logs\...` path appears in
  **10 files**: live.py:32, extend_pool.py:28, build_baseline.py:24, fetch_art.py:32,
  replay_stats.py:188, replay_review.py:104, package_corpus.py:90, upload_corpus.py:85,
  hearth_art_extract.py:70,122, tests/test_integration_real_log.py:15. (Ironic given
  the `hearth-powerlog-locate` skill exists to discover it.)
- Second credential channel: check_patch_notes.py:60-66 reads a key from
  `meta/.patch_config.json` (everything else uses env — coach_llm.py:86,
  compare_models.py:47, upload_corpus.py:64 — no secrets in code, good).

**Fix direction:** one `config.py` with paths and named thresholds (shared
Python-side; JS can get values injected from the analysis payload).

### 6. Hot-path waste (efficiency headline)

- **Uncached meta loaders in value.py**: `_load_card_db` (67-91),
  `_load_spell_db` (94-103), `_load_bg_names` (998-1013), `_load_engines`
  (simulate_growth.py:31-34). One live `analyze()` parses `minions.json` at
  least **6×** and `engines.json` **~7×** (once per spell card via
  `_spell_fuel_bonus` value.py:157). `coach_ui.render_json` re-reads three
  JSON files per second (coach_ui.py:425, 457-459).
- **`_advise_pick` re-ranks before the dedup check** (live.py:200-202, dedup at
  76-79) — full shop-ranking pipeline ~3×/second while a hero/trinket/discover
  pick waits on screen. Reorder: fingerprint-check first, rank once.
- **Unbounded `ensure_meta` retry**: re-runs `extract_game(self.cur_lines)` over
  the ever-growing buffer every 0.3s when the hero parse never lands
  (live.py:191-192 → live_coach.py:539). Add a retry cap.
- `find_active_log()` globs the Logs dir every 0.3s tick (live.py:154) —
  throttle to ~5s.
- `coach_llm.build_fixed_block()` is rebuilt per `complete()` call by default
  (coach_llm.py:102-103). Bytes are identical so the cache still hits, but the
  docstring's "built once and reused" contract isn't enforced — cache it
  module-level now, before the LLM is wired into the live loop (it currently
  isn't called per-decision at all; `coach_llm` is disciplined otherwise:
  byte-stable SYSTEM_PROMPT, deterministic fixed block, cache-hit/miss telemetry).
- Fine as-is (measured, cold path): `board()`/`hand()` full-entity scans in
  `state_fingerprint` (~1ms/tick), `simulate_growth` per engine, 5/5-ban
  rescan, `_catch_up` whole-file read once per session, per-game state resets
  are complete (live_coach.py:274-300), decision-log append is append-only JSONL.

**Fix direction:** `functools.lru_cache` on the four loaders + reorder the
`_advise_pick` dedup are the two highest-leverage cheap fixes in the repo.

### 7. `live_coach.LiveCoach` state sprawl

- **20+ instance attributes** reset in two hand-synced methods (`__init__`
  237-263, `_reset` 274-300) — a new field added to one and not the other is a
  latent cross-game contamination bug.
- Three interleaved state machines in one class (`_LiveActions`, the
  techup/pairing tracker, the scout tracker); `feed()` is 149 lines of
  sequential regex dispatch; `analyze()` is 172 lines building the 25-key
  analysis dict.
- Private-reach imports treat parser internals as a de facto API:
  live_coach.py:24-28 imports `STEP_RE, _GS, ENTITY, MINION_ONLY, CHOICE,
  _load_bg_pool, _load_bg_minion_ids` from player_actions and
  `_CHOICE_HEADER/_CHOICE_OPT/_CHOICE_SOURCE/_CHOSEN` from choices;
  coach_ui.py:27 and coach.py:24-30 import `_load_*` helpers from value/bans
  (including the `_HERE = _HERE  # reuse bans' module dir` oddity at coach.py:30).

**Fix direction:** group per-machine state into sub-objects with their own
reset; make the shared regexes public API on the parser modules.

### 8. Convention drift

- **Three CLI conventions**: argparse (7 modules — sanitize_log, scrape_comps,
  patch_notes, check_meta, check_patch_notes, compare_models, hearth_art_extract;
  bans.py:137-144 is a one-off variant), manual `sys.argv` (board_state,
  player_actions, coach, live), hardcoded flag parsing (`--port=` via
  `a.split("=")[1]` coach_ui.py:560-565; value.py:1116-1128 has a hardcoded demo
  board as `__main__`, no exit code). The two newest, most-used tools (live.py,
  coach_ui.py) are the ones that grew away from argparse.
- **Broad `except Exception` swallows, 8 sites, two styles**: annotated with a
  rationale (decision_log.py:38, 68; live.py:118; hearth_art_extract.py:103,110)
  vs unannotated doing the same kind of work (coach_ui.py:77, fetch_art.py:80,
  parse_bg.py:24, check_patch_notes.py:113). HTTP handling inconsistent even
  within scrape_comps.py (raise_for_status at 95/142/162 vs silent `[]` return
  at 236-237).
- **Zero type hints** — internally consistent but the 25-key analysis dict
  (written by live_coach.analyze 800-846, consumed by value.top_move and
  coach_ui.render_json) is enforced nowhere. `shop_ranking()` takes 9 untyped
  kwargs (value.py:452-454).
- **Print-only logging**: 217 `print()` occurrences, zero `import logging` — no
  levels, no way to quiet the live loop.
- **Test smells**:
  - `tests/test_value.py:94` — `unittest.main()` sits **mid-file**; the five
    classes after it (TestNoEvidenceNoComp:97, TestHandPlan:119,
    TestTopMoveHand:156, TestMultiplierProtect:223, TestCompFilteredBuy:255)
    run under `discover` but are silently skipped when the file is run directly.
  - `tests/test_art_extract.py:9` imports `hearth_art_extract` which imports
    `UnityPy` (not installed in the venv) — hard ImportError instead of
    `@unittest.skipIf`. *This is the one error in today's suite run.*
  - Cross-test import coupling: test_live_updates.py:15 imports `opt_block`
    from `tests.test_shop_parsing`.
  - Untested core logic, biggest first: coach_ui.py (577L), live.py (244L of
    monitor/session logic), coach.py, scrape_comps.py (321L fragile parsing),
    simulate_growth.py (only via validate_growth.py, not the suite), meta.py,
    bans_from_log, extract_game.py (indirect only).
- Minor: duplicate `from tribes import normalize` import (live_coach.py:20, 23);
  `import argparse` inside the `__main__` guard (bans.py:139); lambda-named
  helpers in player_actions.py:319-320.
- What's *good* (keep it): uniform snake_case + `_private` discipline, module
  docstrings with `Usage:` sections, `sys.exit(main())` int-return pattern,
  docstring-as-design-log (dated game citations), uniform unittest structure
  with regression-pinning docstrings, env-based secrets, behavioral (not
  snapshot) tests.

---

## Suggested order of attack

1. **15-minute wins**
   - `functools.lru_cache` the four meta loaders (§6).
   - Delete the duplicated shop-reset block in `feed()` (§4).
   - Reorder `_advise_pick` to dedup-check before ranking (§6).
   - Fix `tests/test_value.py:94` (move the guard to the end).
   - `skipIf`-guard the UnityPy test (§8).
2. **One-day wins**
   - Single lazy meta-loading layer in `meta.py` (§2).
   - One shared minion-id regex in `extract_game.py` (§3).
   - `config.py` for the log path + named thresholds (§5).
3. **Structural, when convenient**
   - Structured plan object out of `top_move`; strings rendered at the UI edge (§1).
   - Group LiveCoach state into per-machine sub-objects with their own reset (§7).
4. **Optional discipline**
   - Type hints starting with a `TypedDict` for the analysis dict (§8).
   - argparse everywhere (§8); `logging` with a level flag instead of print.

## What the audits explicitly cleared

- Import graph: clean DAG, no cycles, no god-module; `tribes.py` and
  `extract_game.py` are correctly placed leaves/foundation.
- Secrets: env-based, none in code.
- Live-loop I/O: incremental byte-offset tailing, 0.3s poll, bounded per-game
  state resets, cache-correct overlay (client skips identical payloads), no
  subprocess-per-tick, art fetch off the analysis path.
- The corpus/telemetry chain (decision_log → sanitize → package → upload) is
  correctly fail-open and redacts BattleTags.