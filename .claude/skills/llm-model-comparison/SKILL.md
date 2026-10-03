---
name: llm-model-comparison
description: Run the controlled LLM model comparison (deepseek-v4-flash vs GLM 5.3 flash) for the Hearthstone coach's advice model. Use when comparing LLM models on cost/latency/quality, running the compare_models.py harness, scoring results, or deciding which model to pin as the coach's advice model.
---

# LLM Model Comparison (coach advice model)

A controlled A/B of candidate LLMs on the coach's **real request types**, so the
advice-model choice is grounded in cost / latency / quality numbers rather than a
vibe. Full design rationale: `analysis/LLM_MODEL_COMPARISON.md`.

## The one rule: hold everything constant except the model

The whole point is to avoid a **confounded comparison** (the Reddit-screenshot
trap). If prompts, settings, or the system prompt differ between runs, any
observed difference is uninterpretable. So:

- Same prompt set, byte-identical input format, for both models.
- Same `temperature`, `max_tokens`, system prompt, and reasoning-effort level.
- Same fixed block (system + full static meta) built once and reused.

## The call shape (why prefix caching matters)

Every call is `coach_llm.py`'s `build_messages(fixed_block, variable_tail)`:

- **FIXED_BLOCK** — system prompt + the entire static meta reference. Byte-stable
  across calls; this is what makes the prefix cacheable.
- **VARIABLE tail** — live board state + the question.

`coach_llm.py`'s cost model rests on the 1M-token context + prefix cache: the whole
meta sits in the cached prefix, so per-decision cost collapses to the small tail.
**If a candidate model can't hold the fixed block in a cached prefix (or has a
smaller window), the cost comparison is not apples-to-apples** — that is a
*finding*, not a bug. Always report cache-hit rate per model.

## Request types under test

Grounded in the v1 widget set (`analysis/DESIGN_COACHING_UI.md`):

| Call type | Widget(s) | Tail size |
|---|---|---|
| `tavern-value` | "Buy this", tavern buy ranking | small |
| `board-safety` | Sell ranking | small |
| `watchlist` | Selection ranker (hero/trinket/discover/dark-gift) | medium |
| `refresh-vs-level` | Refresh-vs-level | small |
| `comp-context` | Your comp + rival comps | medium |

## The harness: `compare_models.py`

Two subcommands:

```
python compare_models.py run [--repeats N] [--prompts prompts.json]
                             [--temperature 0.7] [--max-tokens 1024]
                             [--reasoning-effort high]
python compare_models.py report [--results results.csv]
```

- **`run`** builds the fixed block once per model, runs the prompt set through
  both APIs, and writes `results.csv` with `quality_score` left blank.
- **`report`** reads the scored CSV and prints: cost per correct-quality rec,
  p50/p95 latency, output-token variance, cache-hit rate, and the
  usage-weighted composite.

### Prereqs before a real run

1. **Env keys** — `DEEPSEEK_API_KEY` (already used by `coach_llm.py`) and
   `GLM_API_KEY`. Override GLM's endpoint/model via `GLM_BASE_URL` /
   `GLM_MODEL` if Zhipu's differ from the defaults.
2. **Pricing** — update the `PRICING` dict at the top of `compare_models.py`
   (per-million-token USD: input, cache-hit, output). Placeholders are in there;
   the cost column is meaningless until set.
3. **Prompt set** — ships with 6 seed prompts (2 per core call type) so it runs
   out of the box. For a real comparison, expand to 15–30 real board states from
   Power.log games as `prompts.json` (list of `{id, call_type, tail}`) and pass
   `--prompts`.

### Workflow

1. `python compare_models.py run --repeats 3 --reasoning-effort high`
   (`--repeats N` stabilizes latency percentiles; hold effort constant).
2. Fill `quality_score` (1–5) in `results.csv` by hand, per the rubric below.
3. `python compare_models.py report` and read the metrics.

## Quality rubric (score before you look at the model)

Hand-scored 1–5 is noise without a rubric. Ground "correct" in the existing
logic (`value.py` sell ranking, comp logic in `bans.py`/`coach.py`):

- **tavern-value:** does the top-ranked buy match the value function's pick? Is
  the ranking sensible for the comp?
- **board-safety:** does the safest-to-sell match `value.py`'s recommendation?
  Is the reasoning sound?
- **watchlist:** are the ranked choices the right ones, in a defensible order?
- **refresh-vs-level:** is the call correct given gold + tier + board?

Score blind to model (or have a second scorer) to avoid bias. `report` treats
`quality_score >= 4` as "correct."

## Weighting by usage

Most calls are quick tavern-value checks → latency and cost per call dominate.
End-of-turn board analysis carries more context → quality matters more. The
`CALL_WEIGHTS` dict in `compare_models.py` (default 70/20/10
tavern/board/watchlist) drives the usage-weighted composite — adjust to the real
call mix before trusting the headline number.
