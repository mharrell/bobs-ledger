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

from config import HS_LOG_GLOB
from extract_game import split_game_chunks, extract_game, _friendly_player
from board_state import GameState
from value import _load_bg_names, _best_engine

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
    engine = _best_engine(board, _load_bg_names())
    board_stats = sum((m.get("atk") or 0) + (m.get("health") or 0) for m in board)
    return {
        "hero": hero.get("hero_name"),
        "place": hero.get("place"),
        "comp": comp["name"] if comp else None,
        "engine": engine["name"] if engine else None,
        "board_stats": board_stats,
        "tier": gs.hero_meta.get(hero["card"], {}).get("tier"),
        "board": board,
    }


def aggregate(games):
    """Build outcome tables from per-game features."""
    comps = defaultdict(lambda: {"games": 0, "places": [], "wins": 0, "top4": 0})
    engines = defaultdict(lambda: {"games": 0, "places": [], "stats": []})
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
        if g["engine"]:
            e = engines[g["engine"]]
            e["games"] += 1
            e["places"].append(p)
            e["stats"].append(g["board_stats"])
        h = heroes[g["hero"] or "?"]
        h["games"] += 1
        h["places"].append(p)
        for m in g["board"]:
            k = cards[m["card"]]
            k["games"] += 1
            k["places"].append(p)
    return comps, engines, heroes, cards


def _avg(places):
    return sum(places) / len(places) if places else None


def _shrunk(avg, n, shrink_k=3):
    """Sample-shrunk placement strength (4.5 - avg_place) * n/(n+k) — the same
    statistic the value function consumes. Half weight at n=3, ~0 at n=1."""
    if avg is None:
        return 0.0
    return (4.5 - avg) * n / (n + shrink_k)


LOW_SAMPLE = 3  # below this, a row is descriptive, not a signal


def summarize(comps, engines, heroes, cards, names):
    lines = []
    lines.append("=== Comp placement (observational — placement is confounded) ===")
    lines.append(f"  [low] = n<{LOW_SAMPLE}: descriptive only, NOT a signal. "
                 f"str = shrunk placement strength (4.5-avg, n/(n+3)).")
    rows = []
    for name, c in comps.items():
        if c["games"] < 1:
            continue
        rows.append((name, c["games"], _avg(c["places"]), c["wins"], c["top4"],
                     _shrunk(_avg(c["places"]), c["games"])))
    for name, games, avg, wins, top4, strg in sorted(rows, key=lambda r: (-r[5])):
        low = " [low]" if games < LOW_SAMPLE else ""
        lines.append(f"  {name:28s} n={games:2d} avg={avg:.2f} wins={wins} "
                     f"top4={top4} str={strg:+.2f}{low}")

    lines.append("\n=== Engine placement (same caveats) ===")
    rows = []
    for name, e in engines.items():
        if e["games"] < 1:
            continue
        rows.append((name, e["games"], _avg(e["places"]), _avg(e["stats"]),
                     _shrunk(_avg(e["places"]), e["games"])))
    for name, games, avg, stats, strg in sorted(rows, key=lambda r: (-r[4])):
        low = " [low]" if games < LOW_SAMPLE else ""
        lines.append(f"  {name:28s} n={games:2d} avg={avg:.2f} "
                     f"board_stats={stats:.0f} str={strg:+.2f}{low}")

    lines.append("\n=== Hero placement ===")
    for name, h in sorted(heroes.items(), key=lambda kv: (_avg(kv[1]["places"]) or 99)):
        if h["games"] >= 1:
            low = " [low]" if h["games"] < LOW_SAMPLE else ""
            lines.append(f"  {name:24s} n={h['games']:2d} avg={_avg(h['places']):.2f}{low}")

    lines.append("\n=== Card placement (boards it ended on — CONFOUNDED: no")
    lines.append("      tenure/role weighting; treat as a lookup, not a signal) ===")
    rows = []
    for cid, c in cards.items():
        if c["games"] < LOW_SAMPLE:
            continue
        rows.append((names.get(cid, cid), c["games"], _avg(c["places"])))
    for name, games, avg in sorted(rows, key=lambda r: (r[2] or 99))[:20]:
        lines.append(f"  {name:28s} n={games:2d} avg={avg:.2f}")
    return "\n".join(lines)


def _game_seed(lines):
    import re
    for line in lines:
        m = re.search(r"GAME_SEED value=(\d+)", line)
        if m:
            return m.group(1)
    return None


def main():
    argv = sys.argv[1:]
    args = []
    save_path = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--save":
            save_path = argv[i + 1]
            i += 2
            continue
        if not a.startswith("--"):
            args.append(a)
        i += 1
    as_json = "--json" in argv
    if not args:
        # default: the whole local corpus
        args = sorted(glob.glob(HS_LOG_GLOB))
    names = _load_bg_names()
    games = []
    seen_seeds = set()
    dupes = 0
    for path in args:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for start, end in split_game_chunks(lines):
            # The same game appears in rotated logs (Power.log + Power_old.log);
            # GAME_SEED dedups so a game is only counted once.
            seed = _game_seed(lines[start:end])
            if seed is not None:
                if seed in seen_seeds:
                    dupes += 1
                    continue
                seen_seeds.add(seed)
            games.append(game_features(lines[start:end]))
    if dupes:
        print(f"(skipped {dupes} duplicate game(s) already seen in another log)")
    comps, engines, heroes, cards = aggregate(games)
    out = {
        "comps": {k: {**v, "avg_place": _avg(v["places"])} for k, v in comps.items()},
        "engines": {k: {**v, "avg_place": _avg(v["places"]), "avg_stats": _avg(v["stats"])}
                    for k, v in engines.items()},
        "heroes": {k: {**v, "avg_place": _avg(v["places"])} for k, v in heroes.items()},
        "cards": {k: {**v, "avg_place": _avg(v["places"])} for k, v in cards.items()},
    }
    if save_path:
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"Saved corpus stats to {save_path} ({len(games)} games).")
    if as_json:
        print(json.dumps(out, indent=2))
    else:
        print(f"Analyzed {len(games)} games across {len(args)} log(s).\n")
        print(summarize(comps, engines, heroes, cards, names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
