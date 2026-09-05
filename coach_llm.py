"""Coach LLM client — DeepSeek v4 flash, cache-in-flight discipline.

Pins the coach to `deepseek-v4-flash` (1M-token context). Every request is built
as a byte-stable FIXED_BLOCK (system prompt + full static meta reference)
followed by a per-decision VARIABLE tail (live board state + question). Because
the front of the prompt is token-for-token identical across calls, DeepSeek's
prefix cache serves it at ~50x cheaper input tokens after the first call.

The 1M window is what makes this work: the ENTIRE static meta (all comps + cards)
fits in the cached prefix, so the per-decision cost collapses to just the small
board-state tail. Do NOT interleave live state into the fixed block, and do NOT
regenerate the system prompt per call — either busts the whole prefix.

Reads `DEEPSEEK_API_KEY` from the environment. Uses `requests` (already in the
venv) against DeepSeek's OpenAI-compatible endpoint — no SDK install needed.
"""
import json
import os

import requests

import meta

MODEL = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com/chat/completions"

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

def _headers():
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set in the environment")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def complete(variable_tail, fixed_block=None, temperature=0.7, max_tokens=1024):
    """Send one coaching request. Returns text + usage (cache hit/miss).

    `fixed_block` defaults to the full static meta reference (built once and
    reused across calls so it stays byte-stable). Pass a prebuilt block to
    avoid rebuilding it every decision.
    """
    if fixed_block is None:
        fixed_block = build_fixed_block()
    payload = {
        "model": MODEL,
        "messages": build_messages(fixed_block, variable_tail),
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    resp = requests.post(BASE_URL, headers=_headers(), json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    return {
        "text": data["choices"][0]["message"]["content"],
        "usage": usage,
        "cache_hit_tokens": usage.get("prompt_cache_hit_tokens", 0),
        "cache_miss_tokens": usage.get("prompt_cache_miss_tokens", 0),
    }


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
