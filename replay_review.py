#!/usr/bin/env python3
"""Replay review: what the coach recommended vs what the player actually did.

For every buy phase of a game, reconstruct the exact state the live coach saw
(same incremental code path as live.py: state from game start, arm on the
turn's first MAIN_ACTION, fire on shop parse), capture top_move + sell/shop
ranking, then print the player's actual actions for that phase. The output is
the raw material for honing: where advice was followed, where the player
overrode it, and what the coach was blind to.

Usage:
  python replay_review.py <Power.log> [game_index]
  python replay_review.py --latest
"""
import glob
import os
import re
import sys

from extract_game import split_game_chunks, extract_game, _friendly_player
from player_actions import parse_actions
from value import _load_bg_names

GS = "GameState."


def _phases(chunk):
    """[(start, end)] per buy phase (GameState MAIN_ACTION -> next MAIN_END)."""
    bounds, start = [], None
    for i, line in enumerate(chunk):
        if GS not in line:
            continue
        if "tag=STEP value=MAIN_ACTION" in line:
            if start is None:
                start = i
        elif "tag=STEP value=MAIN_END" in line and start is not None:
            bounds.append((start, i))
            start = None
    if start is not None:
        bounds.append((start, None))
    return bounds


def _advise_point(lines, phase_lo, phase_hi):
    """Feed from game start; return (analysis, stop_index) at the exact moment
    live.py advises (shop parsed after MAIN_ACTION)."""
    import live_coach
    coach = live_coach.LiveCoach()
    stop = len(lines)
    for j in range(0, phase_hi if phase_hi is not None else len(lines)):
        line = lines[j]
        armed = False
        if j >= phase_lo and "tag=STEP value=MAIN_ACTION" in line:
            armed = True
        coach.feed(line)
        if armed and coach.shop_cards:
            stop = j + 1
            break
    return coach.analyze(), stop


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    latest = "--latest" in sys.argv[1:]
    if latest or not args:
        logs = sorted(glob.glob(
            r"C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_*\Power.log"),
            key=os.path.getmtime, reverse=True)
        if not logs:
            print("no session log found")
            return 1
        path, gi = logs[0], len(list(split_game_chunks([])))
    else:
        path = args[0]
    game_index = int(args[1]) if len(args) > (1 if args else 0) else None

    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    chunks = list(split_game_chunks(lines))
    if game_index is None:  # default: last game
        game_index = len(chunks)
    s, e = chunks[game_index - 1]
    chunk = lines[s:e]

    game = extract_game(chunk)
    friendly = _friendly_player(game["heroes"])
    hero = next((h for h in game["heroes"] if h["player"] == friendly), None)
    names = _load_bg_names()
    print(f"replay review — {os.path.basename(os.path.dirname(path))} "
          f"game {game_index}/{len(chunks)}, hero={hero['hero_name'] if hero else '?'}")

    phases = _phases(chunk)
    print(f"{len(phases)} buy phases\n")
    for t, (lo, hi) in enumerate(phases, 1):
        hi_eff = hi if hi is not None else None
        a, _ = _advise_point(chunk, lo, hi_eff)
        acts_list = parse_actions(chunk[lo: hi_eff if hi_eff is not None else len(chunk)],
                                  friendly=friendly)
        actual = acts_list[0] if acts_list else {}
        if a is None:
            print(f"t{t}: (coach not ready — hero/seed not parsed yet)")
            print(f"     actual: {_actual(actual, names)}")
            continue
        rec = a.get("top_move") or "-"
        sold = actual.get("sells") or []
        buys = [names.get(c, c) for c in (actual.get("buys") or [])]
        board_n = len(a.get("board") or [])
        print(f"t{t}  tier {a.get('tier')}  gold {a.get('gold')}  board {board_n}")
        print(f"     coach: {rec}")
        print(f"     actual: {_actual(actual, names)}")
        # Was the headline buy taken?
        buy_rec = a.get('buy_this')
        if buy_rec:
            got = "TAKEN" if any(names.get(c, c) == names.get(buy_rec, buy_rec)
                                 for c in (actual.get("buys") or [])) else "passed"
            print(f"     buy match: {got}")
    return 0


def _actual(t, names):
    if not t:
        return "(pass / no actions)"
    bits = []
    if t.get("buys"):
        bits.append("buy " + ", ".join(names.get(c, c) for c in t["buys"]))
    if t.get("sells"):
        bits.append("sell " + ", ".join(names.get(c, c) for c in t["sells"]))
    if t.get("upgrades"):
        bits.append("LEVEL " + "x" * t["upgrades"])
    if t.get("refreshes"):
        bits.append("roll x" + str(t["refreshes"]))
    if t.get("freezes"):
        bits.append("freeze")
    if t.get("hero_power"):
        bits.append("hero power x" + str(t["hero_power"]))
    if t.get("plays"):
        bits.append("play " + ", ".join(names.get(c, c) for c in t["plays"][:3]))
    return "; ".join(bits) if bits else "(pass / no actions)"


if __name__ == "__main__":
    sys.exit(main())