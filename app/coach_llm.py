"""Coach LLM client — GLM 5.3 flash, cache-in-flight discipline.

Pins the coach to `glm-5.3-flash` by default (the DeepSeek v4 flash pin is
retired; the provider table below still knows it so compare_models.py can race
them). Every request is built as a byte-stable FIXED_BLOCK (system prompt +
full static meta reference) followed by a per-decision VARIABLE tail (live
board state + question). GLM's context cache is implicit and prefix-based like
DeepSeek's: the front of the prompt being token-for-token identical across
calls is what converts most input tokens to the cheaper cached rate (~5x on
GLM's paid tiers). Output is never cached — keep max_tokens tight.

The fixed block holds the ENTIRE static meta (all comps + cards), so the
per-decision cost collapses to just the small board-state tail. Do NOT
interleave live state into the fixed block, and do NOT regenerate the system
prompt per call — either busts the whole prefix.

Keys: reads `GLM_API_KEY` (or `DEEPSEEK_API_KEY` when provider="deepseek").
Override the pin per-process with `COACH_LLM_PROVIDER` / `COACH_LLM_MODEL` /
`COACH_LLM_BASE_URL`. Uses `requests` (already in the venv) against the
OpenAI-compatible endpoint — no SDK install needed.
"""
import json
import os

import requests

import meta

# ---------------------------------------------------------------------------
# Provider table. coach_llm pins to GLM; compare_models.py passes
# provider="deepseek" for the other side of the race. All fields are
# overridable via env (see _provider_config).
# ---------------------------------------------------------------------------

PROVIDERS = {
    "glm": {
        "model": "glm-5.3-flash",
        "base_url": "https://api.zhipuai.com/chat/completions",
        "key_env": "GLM_API_KEY",
    },
    "deepseek": {
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com/chat/completions",
        "key_env": "DEEPSEEK_API_KEY",
    },
}

DEFAULT_PROVIDER = "glm"


def _provider_config(provider=None):
    """Resolve provider -> (model, base_url, key_env), with env overrides.

    Env contract: COACH_LLM_PROVIDER / COACH_LLM_MODEL / COACH_LLM_BASE_URL
    apply globally; GLM_MODEL / GLM_BASE_URL are honored for the glm provider
    (the vars compare_models.py documented) and must stay byte-stable within a
    session — changing them mid-run silently busts every cached prefix.
    """
    name = provider or os.environ.get("COACH_LLM_PROVIDER") or DEFAULT_PROVIDER
    if name not in PROVIDERS:
        raise RuntimeError(f"unknown LLM provider: {name!r}")
    cfg = dict(PROVIDERS[name])
    if name == "glm":
        if os.environ.get("GLM_MODEL"):
            cfg["model"] = os.environ["GLM_MODEL"]
        if os.environ.get("GLM_BASE_URL"):
            cfg["base_url"] = os.environ["GLM_BASE_URL"]
    if os.environ.get("COACH_LLM_MODEL"):
        cfg["model"] = os.environ["COACH_LLM_MODEL"]
    if os.environ.get("COACH_LLM_BASE_URL"):
        cfg["base_url"] = os.environ["COACH_LLM_BASE_URL"]
    return cfg


# ---------------------------------------------------------------------------
# FIXED_BLOCK — byte-stable across every call. Never edit per-request.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are the Hearthstone Battlegrounds coach. You reason over the player's "
    "live board state plus a curated meta reference, and give dynamic, "
    "board-specific, explainable advice. Be concrete: name the cards, the "
    "level, and the buy/sell/roll decision. If the board is ambiguous, say so "
    "and give the highest-probability line."
)


_FIXED_BLOCK = None  # assembled once — the prefix must never change mid-session


def build_fixed_block():
    """Assemble the static meta reference once, deterministically.

    Ordering is frozen (comps by slug, cards by id) so the serialized bytes are
    identical across calls — that is what makes the prefix cacheable. Returns a
    single string to append after the system prompt. Cached module-level:
    rebuilding identical bytes per call wasted work and invited drift.
    """
    global _FIXED_BLOCK
    if _FIXED_BLOCK is not None:
        return _FIXED_BLOCK
    comps = meta.comps()
    cards = meta.cards()

    lines = ["# Curated meta reference (static)"]
    lines.append("## Comps")
    for slug in sorted(comps):
        c = comps[slug]
        lines.append(
            f"- {c['name']} [{c.get('meta_tier', '?')}/{c.get('tribe', '?')}]: "
            f"{c.get('summary', '')}"
        )
    lines.append("## Cards")
    for cid in sorted(cards):
        c = cards[cid]
        lines.append(
            f"- {c['name']} ({cid}): tier {c.get('tier', '?')} "
            f"{c.get('tribe', '')} {c.get('atk', '?')}/{c.get('health', '?')}"
        )
    _FIXED_BLOCK = "\n".join(lines)
    return _FIXED_BLOCK


def build_messages(fixed_block, variable_tail):
    """System + user message. `fixed_block` is stable; `variable_tail` is last.

    The variable tail is appended at the very end so the entire fixed prefix
    (system prompt + meta reference) is byte-identical across calls.
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": fixed_block + "\n\n" + variable_tail},
    ]


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

def _headers(cfg):
    key = os.environ.get(cfg["key_env"])
    if not key:
        raise RuntimeError(f"{cfg['key_env']} is not set in the environment")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def chat(messages, temperature=0.7, max_tokens=1024, provider=None,
         extra_payload=None):
    """Send one raw chat request. Returns text + usage (cache hit/miss).

    Callers doing repeated same-prefix work should go through complete()
    instead; chat() is for one-off shaped calls (e.g. patch-notes extraction)
    that build their own message list.

    Usage parsing is defensive and normalized to cache_hit/cache_miss: GLM
    reports OpenAI-style prompt_tokens_details.cached_tokens, DeepSeek reports
    prompt_cache_hit_tokens / prompt_cache_miss_tokens. Verify the hit rate
    from these fields after any prompt change — don't assume the cache.
    """
    cfg = _provider_config(provider)
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if extra_payload:
        payload.update(extra_payload)
    resp = requests.post(cfg["base_url"], headers=_headers(cfg), json=payload,
                         timeout=60)
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    hit = usage.get("prompt_cache_hit_tokens")
    if hit is None:
        hit = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    hit = hit or 0
    miss = usage.get("prompt_cache_miss_tokens")
    if miss is None:
        miss = max(int(usage.get("prompt_tokens", 0)) - hit, 0)
    return {
        "text": data["choices"][0]["message"]["content"],
        "usage": usage,
        "cache_hit_tokens": hit,
        "cache_miss_tokens": miss,
    }


def complete(variable_tail, fixed_block=None, temperature=0.7, max_tokens=1024,
             provider=None, extra_payload=None):
    """Send one coaching request (FIXED_BLOCK + variable tail). Returns text
    + usage (cache hit/miss).

    `fixed_block` defaults to the full static meta reference (built once and
    reused across calls so it stays byte-stable). Pass a prebuilt block to
    avoid rebuilding it every decision.
    """
    if fixed_block is None:
        fixed_block = build_fixed_block()
    return chat(build_messages(fixed_block, variable_tail),
                temperature=temperature, max_tokens=max_tokens,
                provider=provider, extra_payload=extra_payload)


# ---------------------------------------------------------------------------
# CLI smoke test: python coach_llm.py "board state here"
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    tail = sys.argv[1] if len(sys.argv) > 1 else "Tier 4, 8 gold, board: 2x Naga."
    fb = build_fixed_block()
    out = complete(tail, fixed_block=fb)
    print(out["text"])
    print("\n--- usage ---")
    print(json.dumps(out["usage"], indent=2))