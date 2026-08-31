#!/usr/bin/env python3
"""Validate the growth simulator against a real game (breakoutBot discipline).

Replays a Power.log and compares the simulator's predicted growth to the actual
stat growth the board gained. The per-turn timing is noisy (the Utility Drone's
end-of-turn effect fires at the start of the next turn, and board composition
changes as minions are bought/sold), so this uses an aggregate comparison:

  - Actual total growth = final board stats - base stats of those minions.
  - Simulated growth = run the simulator with the game's total trigger count on
    the board snapshot that had the most engine pieces (the engine's peak).

The ratio tells us whether the simulator is in the right ballpark (within ~2-3x
is a sane heuristic; the model is not exact).

Usage:
    python validate_growth.py <Power.log> [game_index]
"""
import json
import os
import re
import sys

from board_state import GameState
from extract_game import split_game_chunks, extract_game, _friendly_player
from player_actions import parse_actions, trigger_counts
from simulate_growth import _load_engines, simulate_growth
from value import _best_engine, _load_bg_names

_HERE = os.path.dirname(os.path.abspath(__file__))
STEP_RE = re.compile(r"Entity=GameEntity tag=STEP value=(\w+)")


def _base_stats():
    """card id -> (atk, health) from the BG minion pool."""
    with open(os.path.join(_HERE, "meta", "minions.json"), encoding="utf-8") as f:
        return {m.get("id"): (m.get("attack") or 0, m.get("health") or 0)
                for m in json.load(f)}


def _total_stats(board):
    return sum((m.get("atk") or 0) + (m.get("health") or 0) for m in board)


def _engine_pieces(board, names):
    """How many of the board's minions are engine chain-source cards."""
    engines = _load_engines()
    pieces = set()
    for eng in engines.values():
        if isinstance(eng, dict) and "chain" in eng:
            for step in eng["chain"]:
                for m in board:
                    if step["source"].lower() in (names.get(m["card"]) or "").lower():
                        pieces.add(m["card"])
    return len(pieces)


def validate_game(path, game_index=1):
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    chunks = list(split_game_chunks(lines))
    if game_index < 1 or game_index > len(chunks):
        raise ValueError(f"game index {game_index} out of range (1..{len(chunks)})")
    start, end = chunks[game_index - 1]
    chunk = lines[start:end]

    game = extract_game(chunk)
    friendly = _friendly_player(game["heroes"])
    hero = next((h.get("card") for h in game["heroes"] if h["player"] == friendly), None)

    # Replay the log, snapshotting the friendly board at each buy phase.
    gs = GameState()
    turn_boards = []
    for line in chunk:
        m = STEP_RE.search(line)
        if m and m.group(1) == "MAIN_ACTION":
            turn_boards.append(gs.board(friendly)[0])
        gs.feed(line)

    # Final board + base stats -> actual total growth.
    final_board, _ = gs.final_board(friendly)
    base = _base_stats()
    actual = sum((m.get("atk") or 0) - base.get(m["card"], (0, 0))[0]
                 + (m.get("health") or 0) - base.get(m["card"], (0, 0))[1]
                 for m in final_board)

    # Trigger counts across the game (cumulative totals, per-trigger-type).
    actions = parse_actions(chunk, friendly, hero)
    tc = trigger_counts(actions)

    # The engine's peak board: the snapshot with the most engine pieces.
    names = _load_bg_names()
    peak = max(turn_boards, key=lambda b: _engine_pieces(b, names)) if turn_boards else []
    engine = _best_engine(peak, names)

    print(f"Hero: {hero}  turns: {len(actions)}  final board: {len(final_board)} minions")
    print(f"Final board:")
    for m in final_board:
        nm = names.get(m["card"], m["card"])
        print(f"  {nm}  {m['atk']}/{m['health']}")
    print(f"\nActual total growth (final - base): {actual}")

    if not engine:
        print("No modeled engine found on the peak board -> cannot simulate.")
        return 0
    # Use the engine's real cumulative trigger count (e.g. play_elemental, not
    # cast_spell), which compounding engines consume.
    key = engine["trigger"]
    count = tc.get(key + "_total", tc.get(key, 0))
    print(f"Engine: {engine['name']}  (peak board: {len(peak)} minions, "
          f"{_engine_pieces(peak, names)} engine pieces)  trigger={key} x{count}")

    enriched = [dict(m, name=names.get(m["card"], "")) for m in peak]
    r = simulate_growth(enriched, {key: count, key + "_total": count}, engine)
    sim = r["gain"]["atk"] + r["gain"]["hp"]
    print(f"Simulated growth (total spells on peak board): {sim}")
    if actual:
        print(f"Ratio (sim/actual): {sim / actual:.2f}x")
    return 0


def main():
    if len(sys.argv) < 2:
        print("usage: python validate_growth.py <Power.log> [game_index]")
        return 1
    path = sys.argv[1]
    gi = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    return validate_game(path, gi)


if __name__ == "__main__":
    sys.exit(main())
