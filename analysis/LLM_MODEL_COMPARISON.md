# LLM Model Comparison — deepseek-v4-flash vs GLM 5.3 flash

**Status:** proposal / experiment design — not yet run.
**Owner:** Mike Harrell
**Date:** 2026-08-30

## 1. Why this experiment

The coach's advice model is an open decision (see `ROADMAP.md`). It is currently
pinned to `deepseek-v4-flash` (1M-token context, prefix-cache discipline in
`coach_llm.py`). Before committing, we want a controlled comparison against
GLM 5.3 flash on the **actual request types the coach will make**, so the choice
is grounded in real cost / latency / quality numbers rather than a vibe.

The core risk is a **confounded comparison** (the Reddit-screenshot trap): if the
prompts, settings, or system prompt differ between runs, any observed difference
is uninterpretable. This experiment holds everything constant except the model.

## 2. The request types under test

Grounded in the v1 widget set (`analysis/DESIGN_COACHING_UI.md`) and the call
shape in `coach_llm.py`. Every call is a **FIXED_BLOCK** (system prompt + full
static meta reference) followed by a **VARIABLE tail** (live board state +
question). The fixed block is byte-identical across calls — that is what makes the
prefix cacheable.

| Call type | Widget(s) | Tail size | What "correct" means |
|---|---|---|---|
| **Tavern-value** | "Buy this", tavern buy ranking | small | Shop minions ranked by value to the current comp; best buy identified |
| **Board-safety / sell** | Sell ranking | small | Safest-to-sell → most-valuable ordering of the board |
| **Watchlist / selection** | Selection ranker (hero / trinket / discover / dark-gift) | medium | Ranked choices when a pick is active |
| Refresh-vs-level | Refresh-vs-level | small | "you can afford to level" vs "roll here" |
| Comp context | Your comp + rival comps | medium | Correct comp identification + rival read |

The three named in the original plan (tavern-value, board-safety, watchlist) are
the core. Refresh-vs-level and comp-context are optional additions from the v1
set — include them if we want coverage of the full widget set.

## 3. Prompt set

- **15–30 prompts** drawn from real Power.log games (we have raw logs + 19 comps'
  transcripts to source from).
- **Input format identical to production:** the exact
  `build_messages(fixed_block, variable_tail)` shape from `coach_llm.py`. No
  hand-rewriting per model.
- **Fixed block built ONCE per model and reused** across all prompts — this
  mimics real usage and exercises each model's prefix-cache behavior.
- Each prompt is a real board state + a question of one call type. **Tag each
  with its call type** so results can be sliced per type.

## 4. Settings held constant

- `temperature`, `max_tokens`, system prompt: identical across both models.
- **Reasoning effort:** pick one level (low / high / max) and hold it constant.
  Optionally run a second pass at a different effort to see the
  quality-vs-latency tradeoff.
- `stream: False` (same as production).

## 5. Metrics captured per call

| Field | Notes |
|---|---|
| Model | deepseek-v4-flash / glm-5.3-flash |
| Prompt ID | stable id, tagged with call type |
| Call type | tavern-value / board-safety / watchlist / … |
| Prompt tokens | input tokens |
| Cached tokens | prefix-cache hit tokens (if the API reports them) |
| Output tokens | completion tokens |
| Latency | wall-clock, ms |
| Cost | computed from the model's token pricing |
| Quality score | 1–5, hand-assigned per rubric (§8) |

## 6. Computed metrics

- **Cost per correct-quality recommendation** — not just cost per call. A cheap
  call that gives a wrong recommendation is worse than a pricier correct one.
- **p50 / p95 latency** — matters live, turn-to-turn (`live.py` advises each buy
  phase).
- **Token variance across similar prompts** — is one model more consistent in
  output length / shape?
- **Cache-hit rate per model** — see §7; this is the one that can sink the whole
  comparison if ignored.

## 7. The prefix-cache caveat (unique to this tool)

`coach_llm.py`'s entire cost model rests on the 1M-token context + prefix cache:
the **entire static meta** sits in the cached prefix, so per-decision cost
collapses to just the small board-state tail. This comparison **must measure
whether GLM 5.3 flash supports equivalent prefix caching and what its context
window is.** If it cannot hold the full fixed block in a cached prefix, the
"cost per call" comparison is not apples-to-apples — and that is a *finding*, not
a bug. Report cache-hit rate explicitly for both models.

## 8. Quality rubric (define before scoring)

Hand-assigned 1–5 needs a rubric, or it's noise. Define per call type, grounded
in the existing logic (`value.py` sell ranking, comp logic in `bans.py` /
`coach.py`):

- **Tavern-value:** does the top-ranked buy match the value function's pick? Is
  the ranking sensible for the comp?
- **Board-safety / sell:** does the safest-to-sell match `value.py`'s
  recommendation? Is the reasoning sound?
- **Watchlist / selection:** are the ranked choices the right ones, in a
  defensible order?
- **Refresh-vs-level:** is the call correct given gold + tier + board?

Score each response 1–5 against its rubric. Two scorers (or one scorer, blind to
model) to avoid bias.

## 9. Weighting by actual usage

Most calls are **quick tavern-value checks** → latency and cost per call dominate.
End-of-turn board analysis carries more context → quality differences matter more
than the ~2x speed gap. Weight the composite score by the expected call mix (e.g.
70% tavern-value, 20% board-safety, 10% watchlist) so the headline number reflects
real usage, not an equal-weight average.

## 10. Deliverable

A harness (`compare_models.py`) that:

1. builds the fixed block once per model,
2. runs the prompt set through both APIs (OpenAI-compatible endpoints),
3. logs each call to a CSV (the table in §5),
4. prints the computed metrics (§6) and the usage-weighted composite (§9).

## 11. Open questions / decisions needed

- **GLM 5.3 flash API:** endpoint, key, context window, prefix-cache support,
  reasoning-effort parameter name. (DeepSeek side is already wired in
  `coach_llm.py`.)
- **Quality rubric:** confirm the per-call-type rubric before scoring.
- **Sample size:** 15–30 prompts; run each N times (e.g. 3–5) for stable latency
  percentiles, or accept noisy p95 at one run each?
- **Reasoning-effort level:** which to hold constant for the headline run.
