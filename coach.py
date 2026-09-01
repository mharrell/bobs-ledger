#!/usr/bin/env python3
"""Coach loop: turn a Power.log game into a board-specific situation analysis.

Ties together the Phase 2-4 pieces:
  - board_state.py   -> the friendly board + hero tier/gold.
  - bans.py          -> the 5 allowed / 5 banned tribes for the game.
  - comps.json       -> the comps, filtered to those playable under the ban.
  - value.py         -> which board minion is safest to sell.

The output is a structured situation analysis that the (future) advice model
would turn into coaching text. This is the "reasoning layer" the coach reasons
over (board + meta) before speaking.

Usage:
    python coach.py <Power.log> [game_index]
"""
import json
import os
import re
import sys

from board_state import GameState
from extract_game import split_game_chunks, extract_game, _friendly_player
from bans import bans_from_log, filter_comps_by_available_tribes, _load_card_races, _HERE
from player_actions import parse_actions, trigger_counts
from value import sell_recommendation, _load_card_db
import meta
from tribes import DISPLAY_TRIBES, normalize

_HERE = _HERE  # reuse bans' module dir


def _game_seed(chunk):
    for line in chunk:
        m = re.search(r"GAME_SEED value=(\d+)", line)
        if m:
            return m.group(1)
    return None


def analyze(path, game_index=1):
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    chunks = list(split_game_chunks(lines))
    if game_index < 1 or game_index > len(chunks):
        raise ValueError(f"game index {game_index} out of range (1..{len(chunks)})")
    start, end = chunks[game_index - 1]
    chunk = lines[start:end]

    game = extract_game(chunk)
    friendly = _friendly_player(game["heroes"])
    friendly_hero = next((h for h in game["heroes"] if h["player"] == friendly), None)
    friendly_account = next((n for n, c in game["account"].items()
                             if c == friendly_hero["card"]), None)

    gs = GameState()
    for line in chunk:
        gs.feed(line)
    friendly_board, opponent_board = gs.final_board(friendly)
    tier = gs.hero_meta.get(friendly_hero["card"], {}).get("tier")
    gold = gs.gold.get(friendly_account) if friendly_account else None

    # Family ban -> allowed tribes + playable comps. No seed match (or no pool
    # minions parsed yet) = no ban info: fail OPEN (None), never "all banned".
    card_races = _load_card_races(os.path.join(_HERE, ".card_races.json"))
    seed = _game_seed(chunk)
    allowed = None
    for g in bans_from_log(path, card_races):
        if g["seed"] == seed:
            allowed = g["allowed"]
            break
    with open(os.path.join(_HERE, "meta", "comps.json"), encoding="utf-8") as f:
        comps = json.load(f)
    playable = filter_comps_by_available_tribes(comps, card_races, allowed)

    # Real per-turn trigger counts (spells cast, elementals/mechs/nagas played)
    # from the player's actions, so the growth simulator uses actual rates
    # instead of hardcoded defaults.
    actions = parse_actions(chunk, friendly, friendly_hero["card"] if friendly_hero else None)
    scenario = trigger_counts(actions)

    # Sell recommendation (hero power text feeds the W_HERO synergy term when
    # the hero is in meta/heroes.json).
    hero_power = meta.hero_power(friendly_hero["hero_name"]) if friendly_hero else None
    ranked = sell_recommendation(friendly_board, playable, allowed,
                                 scenario=scenario, hero_power=hero_power)

    return {
        "hero": friendly_hero["hero_name"] if friendly_hero else "?",
        "tier": tier,
        "gold": gold,
        "board": friendly_board,
        "banned": _banned(allowed),
        "playable_comps": playable,
        "sell_rank": ranked,
        "scenario": scenario,
    }


def _banned(allowed):
    # Unknown ban info (None) shows as no banned tribes, never "all banned".
    if not allowed:
        return []
    return [t for t in DISPLAY_TRIBES if t not in set(allowed)]


def describe(analysis):
    """Render a readable situation analysis from the analyze() dict."""
    ln = []
    b = analysis["board"]
    ln.append(f"Hero: {analysis['hero'] or '?'}  Tier: {analysis['tier'] or '?'}  "
              f"Gold: {analysis['gold'] or '?'}")
    ln.append(f"Board ({len(b)} minions):")
    id2name = {cid: info.get("name") for cid, info in _load_card_db().items()
               if info.get("name")}
    for m in b:
        nm = id2name.get(m["card"], m["card"])
        ln.append(f"  {nm}  {m['atk']}/{m['health']}  {normalize(m.get('tribe')) or ''}")
    ln.append(f"Banned tribes: {', '.join(analysis['banned']) or 'none'}")
    ln.append(f"Playable comps: {', '.join(sorted(analysis['playable_comps'])) or 'none'}")
    if analysis.get("top_move"):
        ln.append(f"Top move: {analysis['top_move']}")
    sc = analysis.get("scenario") or {}
    active = {k: v for k, v in sc.items() if v}
    if active:
        ln.append("Per-turn triggers: " + ", ".join(f"{k}={v}" for k, v in active.items()))
    ln.append("Safest to sell -> most valuable:")
    for c, v in analysis["sell_rank"]:
        nm = id2name.get(c, c)
        ln.append(f"  {nm} ({v:.0f})")
    return "\n".join(ln)


def main():
    if len(sys.argv) < 2:
        print("usage: python coach.py <Power.log> [game_index]")
        return 1
    path = sys.argv[1]
    gi = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    analysis = analyze(path, gi)
    print(describe(analysis))
    return 0


if __name__ == "__main__":
    sys.exit(main())
