#!/usr/bin/env python3
"""Aggregate outcome data across a corpus of Power.logs (no LLM).

A deterministic replay-analysis pipeline: for each game, extract the friendly
hero, placement, implied comp, and final board; then aggregate into outcome
tables (comp win-rate, hero win-rate, card value). This is the foundation for
tuning the simulator and weighting comps by actual success — and it costs zero
LLM tokens per game.

Usage:
    python replay_stats.py <Power.log> [more logs...] [--json]
"""
import glob
import json
import os
import sys
from collections import defaultdict

from extract_game import split_game_chunks, extract_game, _friendly_player
from board_state import GameState
from value import _load_bg_names

_HERE = os.path.dirname(os.path.abspath(__file__))


def _load_comps():
    with open(os.path.join(_HERE, "meta", "comps.json"), encoding="utf-8") as f:
        return json.load(f)


def _detect_comp(board, comps):
    """The comp with the most core cards on the board (distinguishes same-tribe
    comps, unlike a tribe-overlap fit)."""
    board_cards = {m["card"] for m in board}
    best, best_score = None, 0
    for slug, comp in comps.items():
        score = len(set(comp.get("core", [])) & board_cards)
        if score > best_score:
            best_score, best = score, comp
    return best


def game_features(chunk):
    """Deterministic per-game features: hero, placement, implied comp, board, tier."""
    game = extract_game(chunk)
    friendly = _friendly_player(game["heroes"])
    if friendly is None:
        return None
    hero = next((h for h in game["heroes"] if h["player"] == friendly), None)
    if hero is None:
        return None
    gs = GameState()
    for line in chunk:
        gs.feed(line)
    board, _ = gs.final_board(friendly)
    comp = _detect_comp(board, _load_comps())
    return {
        "hero": hero.get("hero_name"),
        "place": hero.get("place"),
        "comp": comp["name"] if comp else None,
        "tier": gs.hero_meta.get(hero["card"], {}).get("tier"),
        "board": board,
    }


def aggregate(games):
    """Build outcome tables from per-game features."""
    comps = defaultdict(lambda: {"games": 0, "places": [], "wins": 0, "top4": 0})
    heroes = defaultdict(lambda: {"games": 0, "places": []})
    cards = defaultdict(lambda: {"games": 0, "places": []})
    for g in games:
        if g is None or g["place"] is None:
            continue
        p = g["place"]
        if g["comp"]:
            c = comps[g["comp"]]
            c["games"] += 1
            c["places"].append(p)
            c["wins"] += 1 if p == 1 else 0
            c["top4"] += 1 if p <= 4 else 0
        h = heroes[g["hero"] or "?"]
        h["games"] += 1
        h["places"].append(p)
        for m in g["board"]:
            k = cards[m["card"]]
            k["games"] += 1
            k["places"].append(p)
    return comps, heroes, cards


def _avg(places):
    return sum(places) / len(places) if places else None


def summarize(comps, heroes, cards, names):
    lines = []
    lines.append("=== Comp win-rate (by avg placement) ===")
    rows = []
    for name, c in comps.items():
        if c["games"] < 1:
            continue
        rows.append((name, c["games"], _avg(c["places"]), c["wins"], c["top4"]))
    for name, games, avg, wins, top4 in sorted(rows, key=lambda r: (r[2] or 99)):
        lines.append(f"  {name:28s} n={games:2d} avg={avg:.2f} wins={wins} top4={top4}")

    lines.append("\n=== Hero win-rate ===")
    for name, h in sorted(heroes.items(), key=lambda kv: (_avg(kv[1]["places"]) or 99)):
        if h["games"] >= 1:
            lines.append(f"  {name:24s} n={h['games']:2d} avg={_avg(h['places']):.2f}")

    lines.append("\n=== Card value (avg placement of boards it's on) ===")
    rows = []
    for cid, c in cards.items():
        if c["games"] < 2:
            continue
        rows.append((names.get(cid, cid), c["games"], _avg(c["places"])))
    for name, games, avg in sorted(rows, key=lambda r: (r[2] or 99))[:20]:
        lines.append(f"  {name:28s} n={games:2d} avg={avg:.2f}")
    return "\n".join(lines)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    if not args:
        # default: the whole local corpus
        args = sorted(glob.glob(r"C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_*\Power.log"))
    names = _load_bg_names()
    games = []
    for path in args:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for start, end in split_game_chunks(lines):
            games.append(game_features(lines[start:end]))
    comps, heroes, cards = aggregate(games)
    if as_json:
        out = {
            "comps": {k: {**v, "avg_place": _avg(v["places"])} for k, v in comps.items()},
            "heroes": {k: {**v, "avg_place": _avg(v["places"])} for k, v in heroes.items()},
            "cards": {k: {**v, "avg_place": _avg(v["places"])} for k, v in cards.items()},
        }
        print(json.dumps(out, indent=2))
    else:
        print(f"Analyzed {len(games)} games across {len(args)} log(s).\n")
        print(summarize(comps, heroes, cards, names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
