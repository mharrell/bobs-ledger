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
from value import sell_recommendation, _load_card_db, _load_bg_names, _load_spell_db
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
    """Render a readable situation analysis from the analyze() dict.

    Compact labeled sections so the whole situation reads at a glance:
    hero line, top move, the target comp's shopping list (which cards belong
    to it, which you already have), shop ranking with comp tags, board,
    triggers, banned tribes, sell ranking.
    """
    names = _load_bg_names()
    b = analysis["board"]
    ln = []
    ln.append(f"{analysis['hero'] or '?'}  ·  tier {analysis['tier'] or '?'}  ·  "
              f"gold {analysis['gold'] if analysis['gold'] is not None else '?'}  ·  "
              f"board {len(b)}/7")
    if analysis.get("top_move"):
        ln.append(f">> {analysis['top_move']}")
    choice = analysis.get("choice")
    if choice and choice.get("ranked"):
        ln.append("")
        ln.append(f"PICK ({choice['kind']}):")
        for n, c, s, why in choice["ranked"]:
            mark = " <-- " if (n, c, s, why) == choice["ranked"][0] else "  "
            ln.append(f"  {mark}{n}" + (f"  [{s:.1f} {why}]" if s is not None and why else ""))

    # Target comp — the shopping list (cards that belong to the comp, and
    # which pieces are already on the board).
    tc = analysis.get("target_cards")
    if tc and (tc.get("core") or tc.get("addons")):
        state = analysis.get("target_state") or "pivot"
        ln.append("")
        ln.append(f"TARGET COMP: {tc['name']} ({state})")
        for label, key in (("core  ", "core"), ("addons", "addons")):
            cards = tc.get(key) or []
            if cards:
                cards_s = " · ".join(
                    f"{c['name']}{' [have]' if c['owned'] else ''}" for c in cards)
                ln.append(f"  {label}: {cards_s}")

    # Shop ranking, tagged by comp membership (core/addon/spell).
    shop = analysis.get("shop_rank") or []
    if shop:
        core = {c["card"] for c in (tc or {}).get("core", [])} if tc else set()
        addons = {c["card"] for c in (tc or {}).get("addons", [])} if tc else set()
        spells = set(_load_spell_db())
        ln.append("")
        ln.append("SHOP (best first):")
        for c, v in shop:
            tag = ""
            if c in core:
                tag = " CORE"
            elif c in addons:
                tag = " addon"
            elif c in spells:
                tag = " spell"
            ln.append(f"  {names.get(c, c)} ({v:.0f}){tag}")

    ln.append("")
    ln.append(f"BOARD ({len(b)}/7): " + (" · ".join(
        f"{names.get(m['card'], m['card'])} {m['atk']}/{m['health']}"
        + (f" {normalize(m.get('tribe'))}" if m.get('tribe') else "")
        + (" (golden)" if m.get("golden") else "")
        for m in b) or "empty"))
    sc = analysis.get("scenario") or {}
    active = {k: v for k, v in sc.items() if v and not k.endswith("_total")}
    if active:
        ln.append("TRIGGERS: " + ", ".join(f"{k}={v}" for k, v in active.items()))
    if analysis.get("banned"):
        ln.append("BANNED: " + ", ".join(analysis["banned"]))
    if analysis.get("sell_rank"):
        ln.append("SELL (safe -> keep): " + " · ".join(
            f"{names.get(c, c)} ({v:.0f})" for c, v in analysis["sell_rank"][:3]))
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
