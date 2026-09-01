#!/usr/bin/env python3
"""Compare deepseek-v4-flash vs GLM 5.3 flash on the coach's real call types.

Design: see analysis/LLM_MODEL_COMPARISON.md. Every call is the production
FIXED_BLOCK (system + full static meta) + a VARIABLE tail (board state +
question), built once per model and reused — so prefix-cache behavior is
exercised realistically.

Usage:
    python compare_models.py run [--repeats N] [--prompts prompts.json]
    python compare_models.py report [--results results.csv]

`run`    executes the prompt set through both models and writes results.csv
         (identity + metrics) and score_sheet.csv (responses only, shuffled,
         NO model column — score it blind).
`report` joins the blind sheet to results.csv by row_id and prints the
         metrics: cost per correct-quality, p50/p95 latency, token variance,
         cache-hit rate, usage-weighted composite, and a paired sign test.

Env:
    DEEPSEEK_API_KEY   (already used by coach_llm.py)
    GLM_API_KEY        (Zhipu / GLM key)
    GLM_BASE_URL       default https://api.zhipuai.com/chat/completions
    GLM_MODEL          default glm-5.3-flash
"""
import argparse
import csv
import json
import os
import statistics
import sys
import time

import requests

from coach_llm import build_fixed_block, build_messages, complete as deepseek_complete

# ---------------------------------------------------------------------------
# GLM client (OpenAI-compatible). DeepSeek side is already wired in coach_llm.
# ---------------------------------------------------------------------------

GLM_BASE_URL = os.environ.get("GLM_BASE_URL", "https://api.zhipuai.com/chat/completions")
GLM_MODEL = os.environ.get("GLM_MODEL", "glm-5.3-flash")


def _glm_headers():
    key = os.environ.get("GLM_API_KEY")
    if not key:
        raise RuntimeError("GLM_API_KEY is not set in the environment")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def glm_complete(variable_tail, fixed_block, temperature=0.7, max_tokens=1024,
                 reasoning_effort=None):
    """One GLM call, mirroring coach_llm.complete(). Returns text + usage."""
    payload = {
        "model": GLM_MODEL,
        "messages": build_messages(fixed_block, variable_tail),
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    resp = requests.post(GLM_BASE_URL, headers=_glm_headers(), json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return {
        "text": data["choices"][0]["message"]["content"],
        "usage": data.get("usage", {}),
    }


# ---------------------------------------------------------------------------
# Usage / cost
# ---------------------------------------------------------------------------

# Per-million-token USD. PLACEHOLDERS — update to the real prices before
# trusting the cost column. Cache-hit price is the discounted prefix-cache rate.
PRICING = {
    "deepseek-v4-flash": {"input": 0.07, "cache_hit": 0.014, "output": 0.28},
    "glm-5.3-flash":     {"input": 0.10, "cache_hit": 0.05,  "output": 0.40},
}


def parse_usage(usage):
    """Return (prompt_tokens, cached_tokens, output_tokens) defensively.

    DeepSeek reports prompt_cache_hit_tokens / prompt_cache_miss_tokens; GLM may
    use OpenAI-style prompt_tokens_details.cached_tokens. Handle both.
    """
    prompt = usage.get("prompt_tokens", 0)
    output = usage.get("completion_tokens", 0)
    cached = usage.get("prompt_cache_hit_tokens")
    if cached is None:
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    return prompt, cached or 0, output


def cost_for(model, prompt_tokens, cached_tokens, output_tokens):
    p = PRICING.get(model)
    if not p:
        return 0.0
    miss = max(prompt_tokens - cached_tokens, 0)
    return (miss * p["input"] + cached_tokens * p["cache_hit"]
            + output_tokens * p["output"]) / 1_000_000


# ---------------------------------------------------------------------------
# Prompt set
# ---------------------------------------------------------------------------

# Fallback seed so the harness runs out of the box. Replace/expand with 15-30
# real board states from Power.log games (see the proposal, section 3).
DEFAULT_PROMPTS = [
    {"id": "tv-01", "call_type": "tavern-value",
     "tail": "Tier 4, 8 gold. Board: 2x Naga (2/4, 3/5), 1x Murloc (2/2). "
             "Shop: Naga (4/5), Murloc (3/3), Beast (2/4), Elemental (3/2). "
             "Which shop minion should I buy, and why?"},
    {"id": "tv-02", "call_type": "tavern-value",
     "tail": "Tier 3, 6 gold. Board: 3x Mech (2/3, 3/2, 1/4). "
             "Shop: Mech (4/4), Mech (2/2), Demon (3/3), Tavern spell. "
             "Rank the shop by value to my mech comp."},
    {"id": "bs-01", "call_type": "board-safety",
     "tail": "Tier 5, 10 gold. Board: 5 minions — Naga (5/6), Naga (3/4), "
             "Murloc (2/2), Beast (4/4), Elemental (1/1). "
             "Which minion is safest to sell this turn?"},
    {"id": "bs-02", "call_type": "board-safety",
     "tail": "Tier 4, 7 gold. Board: 4 minions — Mech (4/4), Mech (3/3), "
             "Mech (2/2), Demon (5/5). I need to make room. "
             "What should I sell, and what's the order?"},
    {"id": "wl-01", "call_type": "watchlist",
     "tail": "A trinket choice is active. Options: (A) +1/+1 to all minions "
             "each turn, (B) your first minion each turn is free, "
             "(C) +2 attack to all minions. My comp is Naga stat-scaling. "
             "Rank these trinkets for me."},
    {"id": "wl-02", "call_type": "watchlist",
     "tail": "A discover choice is active. Options: (A) Naga 4/5, "
             "(B) Murloc 3/3, (C) Elemental 2/4. My comp is Murloc. "
             "Rank these for my comp."},
]


def load_prompts(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_PROMPTS


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def run(prompts_path, repeats, temperature, max_tokens, reasoning_effort):
    import random
    prompts = load_prompts(prompts_path)
    print(f"Running {len(prompts)} prompts x {repeats} repeat(s) x 2 models "
          f"(temp={temperature}, max_tokens={max_tokens}, "
          f"effort={reasoning_effort or 'default'})")

    # Build the fixed block ONCE per model and reuse — exercises prefix cache.
    deepseek_fb = build_fixed_block()
    glm_fb = build_fixed_block()

    def call(model, tail):
        if model == "deepseek-v4-flash":
            return deepseek_complete(tail, fixed_block=deepseek_fb,
                                    temperature=temperature, max_tokens=max_tokens)
        return glm_complete(tail, fixed_block=glm_fb, temperature=temperature,
                            max_tokens=max_tokens, reasoning_effort=reasoning_effort)

    rows, sheet = [], []
    rid = 0
    for p in prompts:
        for rep in range(repeats):
            for model in ("deepseek-v4-flash", "glm-5.3-flash"):
                rid += 1
                row_id = f"r{rid:03d}"
                response = ""
                row = {"row_id": row_id, "model": model, "rep": rep,
                       "prompt_id": p["id"], "call_type": p["call_type"]}
                t0 = time.perf_counter()
                try:
                    out = call(model, p["tail"])
                    latency_ms = (time.perf_counter() - t0) * 1000
                    pt, ct, ot = parse_usage(out["usage"])
                    row.update({
                        "prompt_tokens": pt, "cached_tokens": ct,
                        "output_tokens": ot, "latency_ms": round(latency_ms, 1),
                        "cost": round(cost_for(model, pt, ct, ot), 6),
                        "error": "",
                    })
                    response = out["text"]
                except Exception as e:  # noqa: BLE001 - record, don't kill the run
                    row.update({"prompt_tokens": "", "cached_tokens": "",
                                "output_tokens": "", "latency_ms": "",
                                "cost": "", "error": str(e)})
                    response = ""
                rows.append(row)
                # The blind sheet: response text WITHOUT the model column, in
                # random order, so quality scoring can't be biased by identity.
                sheet.append({"row_id": row_id, "prompt_id": p["id"],
                              "call_type": p["call_type"], "response": response,
                              "quality_score": ""})
                print(f"  {model:16s} {p['id']:6s} "
                      f"{'OK' if not row['error'] else 'ERR: ' + row['error']}")

    with open("results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "row_id", "model", "rep", "prompt_id", "call_type",
            "prompt_tokens", "cached_tokens", "output_tokens", "latency_ms",
            "cost", "error"])
        w.writeheader()
        w.writerows(rows)
    random.shuffle(sheet)
    with open("score_sheet.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["row_id", "prompt_id", "call_type",
                                          "response", "quality_score"])
        w.writeheader()
        w.writerows(sheet)
    print(f"\nWrote {len(rows)} rows to results.csv (identity + metrics, model "
          f"names included) and score_sheet.csv (blind: responses only, "
          f"shuffled). Score quality_score 1-5 in score_sheet.csv WITHOUT "
          f"opening results.csv, then run `report`.")


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

# Usage weighting by call type (proposal section 9). Adjust to the real mix.
CALL_WEIGHTS = {"tavern-value": 0.7, "board-safety": 0.2, "watchlist": 0.1}
CORRECT_AT = 4  # quality_score >= this counts as "correct"


def _pct(xs, q):
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _sign_test_p(diffs):
    """Two-sided sign-test p-value for paired score differences (deepseek minus
    GLM): 2 * P(X >= max(k, n-k)) under binomial(n, 0.5), capped at 1."""
    import math
    nonzero = [d for d in diffs if d != 0]
    n = len(nonzero)
    if n == 0:
        return None
    k = sum(1 for d in nonzero if d > 0)
    extreme = max(k, n - k)
    tail = sum(math.comb(n, i) for i in range(extreme, n + 1)) / 2 ** n
    return min(2 * tail, 1.0)


def report(results_path, sheet_path="score_sheet.csv"):
    with open(results_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # Scores live in the blind sheet (the scorer never saw model identities);
    # join by row_id here.
    if not os.path.exists(sheet_path):
        print(f"ERROR: {sheet_path} not found — fill quality_score (1-5) in it "
              f"first, then re-run report.")
        return 1
    with open(sheet_path, encoding="utf-8") as f:
        sheet = list(csv.DictReader(f))
    scores = {r["row_id"]: r for r in sheet}
    unscored = [r for r in sheet if not (r.get("quality_score") or "").strip()]
    for r in rows:
        r["quality_score"] = (scores.get(r["row_id"], {}).get("quality_score")
                              or "").strip()
    if unscored:
        print(f"WARNING: {len(unscored)} row(s) in {sheet_path} unscored — "
              f"metrics cover scored rows only.\n")

    models = ["deepseek-v4-flash", "glm-5.3-flash"]
    print(f"\n=== LLM comparison report ({len(rows)} rows) ===\n")
    print(f"Pricing assumed (per-M tokens, USD): {json.dumps(PRICING)}")
    print(f"Correct = quality_score >= {CORRECT_AT}; "
          f"call weights = {json.dumps(CALL_WEIGHTS)}\n")

    for model in models:
        m = [r for r in rows if r["model"] == model]
        ok = [r for r in m if not r.get("error")]
        errs = [r for r in m if r.get("error")]
        scored = [r for r in ok if r.get("quality_score", "").strip() != ""]

        print(f"--- {model} ---")
        if errs:
            print(f"  ERRORS ({len(errs)}): {errs[0]['error']}")
        if not ok:
            print("  no successful calls")
            continue

        lat = [float(r["latency_ms"]) for r in ok if r.get("latency_ms")]
        out_tok = [int(r["output_tokens"]) for r in ok if r.get("output_tokens")]
        cache_rate = [int(r["cached_tokens"]) / int(r["prompt_tokens"])
                      for r in ok if r.get("prompt_tokens") and r.get("cached_tokens")]
        cost = [float(r["cost"]) for r in ok if r.get("cost")]

        print(f"  calls: {len(ok)} ok / {len(m)} total")
        if lat:
            print(f"  latency p50={_pct(lat, .5):.0f}ms  p95={_pct(lat, .95):.0f}ms")
        if out_tok:
            print(f"  output tokens: mean={statistics.mean(out_tok):.0f} "
                  f"stdev={statistics.stdev(out_tok):.0f} "
                  f"(variance across prompts)")
        if cache_rate:
            print(f"  cache-hit rate: {statistics.mean(cache_rate)*100:.1f}%")
        if cost:
            print(f"  total cost: ${sum(cost):.4f}")

        if scored:
            qs = [int(r["quality_score"]) for r in scored]
            correct = [r for r in scored if int(r["quality_score"]) >= CORRECT_AT]
            total_cost = sum(float(r["cost"]) for r in scored if r.get("cost"))
            print(f"  quality: mean={statistics.mean(qs):.2f} "
                  f"correct={len(correct)}/{len(scored)}")
            if total_cost and correct:
                print(f"  cost per correct-quality rec: "
                      f"${total_cost / len(correct):.4f}")

            # Usage-weighted composite quality.
            wsum = sum(CALL_WEIGHTS.get(r["call_type"], 0) for r in scored)
            if wsum:
                wq = sum(CALL_WEIGHTS.get(r["call_type"], 0) * int(r["quality_score"])
                         for r in scored) / wsum
                print(f"  usage-weighted quality: {wq:.2f}")
        else:
            print("  (no quality_score yet — fill results.csv and re-run report)")
        print()

    print("Note: if one model shows 0% cache-hit or errors on the fixed block, "
          "that is the prefix-cache finding from proposal section 7 - "
          "the cost comparison is then not apples-to-apples.")

    # Paired quality comparison (per prompt_id+rep, both models scored).
    by_pair = {}
    for r in rows:
        if r.get("error") or not r.get("quality_score", "").strip():
            continue
        by_pair.setdefault((r["prompt_id"], r["rep"]), {})[r["model"]] = \
            int(r["quality_score"])
    diffs = [pair["deepseek-v4-flash"] - pair["glm-5.3-flash"]
             for pair in by_pair.values()
             if len(pair) == 2]
    if diffs:
        p = _sign_test_p(diffs)
        print(f"\nPaired quality: {len(diffs)} pairs, "
              f"deepseek wins {sum(1 for d in diffs if d > 0)}, "
              f"GLM wins {sum(1 for d in diffs if d < 0)}, "
              f"ties {sum(1 for d in diffs if d == 0)}; "
              f"sign-test p={p if p is None else round(p, 3)} "
              f"(n is tiny unless repeats were run — not decision-grade below "
              f"~10 pairs).")


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Compare coach LLM models")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="execute the prompt set and write results.csv")
    r.add_argument("--repeats", type=int, default=1,
                   help="run each prompt N times for stable latency (default 1)")
    r.add_argument("--prompts", default=None, help="path to prompts.json")
    r.add_argument("--temperature", type=float, default=0.7)
    r.add_argument("--max-tokens", type=int, default=1024)
    r.add_argument("--reasoning-effort", default=None,
                   help="low/high/max — hold constant across both models")

    s = sub.add_parser("report", help="print metrics from a scored score_sheet.csv")
    s.add_argument("--results", default="results.csv")
    s.add_argument("--sheet", default="score_sheet.csv")

    args = ap.parse_args()
    if args.cmd == "run":
        run(args.prompts, args.repeats, args.temperature, args.max_tokens,
            args.reasoning_effort)
    else:
        sys.exit(report(args.results, args.sheet))
    return 0


if __name__ == "__main__":
    sys.exit(main())
