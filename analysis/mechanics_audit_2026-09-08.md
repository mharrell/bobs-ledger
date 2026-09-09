# Mechanics audit — 2026-09-08

Scope: "what mechanics are still missing or misinterpreted by the coach?"
Three surveys (code mechanics coverage, a 22-file test-contradiction audit,
the docs' already-known gaps), merged with player-confirmed rules and a
real-log ground-truth pass. Fix work landed in worktree branch
`worktree-keen-sparking-alpaca` (commits: tier+1 removal/golden/trinkets,
CHANGE_ENTITY + gold spells, test_simulate_growth.py, spell card-text pass).

## Player rules confirmed this session (don't re-flag these as gaps)

1. **Golden shop minions cost the flat 3 gold** (they're spell/trinket-made,
   rare, still pay the triple reward when played) — pricing was already
   correct; the real gap was VALUATION (fixed: W_SHOP_GOLDEN 25.0).
2. **No interest on saved gold.** The purse-only gold model is correct.
3. **No winning-streak gold.** Extra gold comes only from specific spells
   that pay on a tie/win (see below).
4. **Best practice is to literally read the text of each card and each
   spell** — curated per-card encodes beat runtime regex heuristics
   (the Butchering fix is the proven pattern; the spell pass below is the
   first full application).

## Fixed this session

| Finding | Fix |
|---|---|
| Batch-path `tier+1` level-price fallback (dead in prod, enshrined by 2 tests + the overlay JS) | Removed everywhere; unpriced level = no level step; fixtures pass explicit `level_cost` |
| `test_make_room_never_sells_a_held_card` was a no-op (duplicate `hand_plan` key) — the held-card guard was pinned by nothing | Fixture repaired; asserts `Hold Sewer Lord` and no sell step |
| `test_hunt_names_specific_cores_first` was vacuous (mutation applied to a dead copy) | Feeds the mutated analysis + populated comps; the shared-utility exclusion actually runs |
| **Golden shop offers were dropped entirely** (`_G` id not in card_db) and unpriced | Resolved to base card, 3x stacked body + 25.0 triple reward, flat-3 price, raw id kept; ordering golden > missing core > dupe |
| **Held trinkets invisible after the pick** (`trinkets=` never passed; W_TRINKET + Copper Coil were dead code) | `board_state.held_trinkets()` + CHANGE_ENTITY parsing (see ground truth) + wired into `analyze()`'s sell/shop calls and the sim scenario |
| Tie/win gold spells (Overconfidence) and every `Gain N Gold` economy spell scored 0 | Gold = liquid tempo (2/gold; max-gold income 4/gold); then superseded by the curated layer |
| 5 stale docstrings/comments enshrining the two superseded pricing models | Rewritten; tier-5 discriminator fixture added (tier-3 fixture couldn't catch tier-pricing regressions) |
| Vacuous/weak tests: one-sided damp assertion, `and []` trap, 20-pt fudge, dead `_account` setup, spell-id-as-discover fixture, test_check_meta rewriting the committed meta | All fixed (tempdir copy, exact assertions) |
| `simulate_growth.py` had ONE test | `tests/test_simulate_growth.py`: 16 hand-computed tests (compounding shop-eat, cumulative fallbacks, multipliers, goldens, magnetize chaining, trinket gate, tribe scaling) |

## Ground truth from the 2026-09-08 session logs

- **Held trinkets**: the `Lesser/Greater Trinket` placeholder entities
  (`BG30_Trinket_1st/2nd`, always controller 7) become the chosen
  `BGxx_MagicItem_NNN` via **CHANGE_ENTITY** — which board_state did not
  parse at all. Now parsed (card id swap, stale stats dropped, fresh tag
  lines retargeted). Verified end-to-end on two real logs. Notes: the
  friendly player NUMBER VARIES per game (7 in the 13:33 session, 2 in the
  09:52 one); trinkets can be REPLACED mid-game (entity 363 swapped twice —
  last id wins); opponents' trinkets are also visible (players 5/6) —
  future opponent-trinket intel.
- **Dark gifts**: recoverable — the granted gift appears as an entity whose
  entityName IS the gift name on a generic `BG36_MidGameEffect_*` effect
  entity, attached to its host minion via `tag=1234 value=<host eid>`;
  REMOVEDFROMGAME when consumed. Not yet wired into any ranker (see open).
- **Overconfidence** ("win → 3 gold, tie → 1") parsed to zero — the exact
  class the player flagged. Now in the curated layer (8 pts).

## The card-text pass — phase 1 done (tavern spells)

- `meta/spell_effects.json`: all 71 spells annotated; every id verified
  against `tavern_spells.json` (no missing, no orphans;
  `test_all_spells_annotated` is the guard).
- `value._spell_effect` consumes the curated read deterministically;
  regex stays as fallback. Score changes: Perfect Vision 40 (invisible
  before), Eyes of the Earth Mother 8, Overconfidence 8, tavern-buff
  spells credit future buys.

## Remaining phases of the card-text pass (open)

3. **Shop-ranking minions + engines.json chains** verified against card
   text (the Butchering precedent; the undead engine's self-declared
   under-counts: Eternal Knight recursion, ~casts/turn error).
4. **Dark gifts (43) + heroes (115)** — the unranked universes; the
   ground-truth recovery path above is the prerequisite.

## Phase 2 done — trinkets (2026-09-08, same session)

- `meta/trinket_effects.json`: all 117 trinkets (108 unique ids; the
  Colorful Compass family shares one id across 10 tribe variants; its DB
  text is glitched to "Get a random 92" — read as a random tribe minion)
  annotated with `base_value` (intrinsic power read) and `synergy`
  (precise tribe/keyword fit). Coverage verified; `test_all_trinkets_annotated`
  is the guard.
- `value.minion_value`'s trinket term now matches curated
  tribes/keywords (mechanics + card text) instead of the description
  substring; description strings keep the substring read as fallback.
- `choices._rank_trinkets`: the "fits your board" bonus is curated-synergy
  driven (board tribes + minion keywords, e.g. Dragon Skull fits a
  BATTLECRY board without mentioning any tribe); population anchor
  (pick_rate/avg_placement) unchanged.
- `live_coach.analyze` passes merged trinket records (description +
  curated synergy) into the sell/shop rankings.
- Opponent trinkets are visible too (players share nothing; trinkets are
  per-player) — future scout-box intel.

## Dark-gift ranker + opponent trinket intel (landed, same session)

- `board_state` now captures the bracket `entityName` (where generated-card
  identity lives when the CardID is generic) and the tag=1234 host link;
  `dark_gift_effects()` is the raw recovery layer.
- Ground truth refined on the full log: Dark Discovery grants ~3 gifts per
  press (three markers, sequential hosts); the same gift recurs on new
  minions (Replication-class); player attribution is fuzzy mid-combat
  (marker vs host controller disagree — the shared-spectator problem), so
  the friendly filter requires BOTH tags to agree; display dedups by name.
- `live_coach.analyze` emits `dark_gifts` (name + description —
  dark_gifts.json is read by decision code for the first time) and
  `opp_trinkets`; the overlay shows them as footlines.
- Opponent trinket intel reads `[]` in games where opponents haven't
  picked yet (the 13:33 log ends before their picks); the 09:52 log has
  players 5/6 carrying trinkets — intel appears when they exist.

## Longer-standing gaps (already documented, unchanged)

- Gate-5 combat forecast is a stat ratio (no positioning/keywords/
  deathrattles; opponent keywords untracked) — LEVELING_MODEL.md.
- Simulator underestimates growth 1.6–2x (untuned parameters) — ROADMAP.
- W-weights never systematically tuned; refresh-EV unmodeled.
- LLM advice layer unwired; sham-control evaluation not run.
- Opponent buys/sells structurally unrecoverable (log structure).
- Log-rotation can lose a game tail (A. F. Kay incident).
- `dark_gifts.json` is write-only data (no decision code reads it).
- Dark-gift/discover picks still fall through to "unranked" (choices.py).

## Test-suite state

294 → 300 tests, all green at each commit. Suite had been green all along
while hiding two broken tests and the stale tier+1 model — the lesson:
green ≠ correct; the contradiction audit was the real detector.