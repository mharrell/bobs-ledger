#!/usr/bin/env python3
"""Build meta/turn_baseline.json — corpus median board stats by turn.

Walks every local Power.log (our own corpus), replays each game through the
incremental coach, and records at each buy phase: our board's stat total and
the opponent board we just fought (from the same scout machinery live_coach
uses). The medians per turn are the "what does a board at turn N look like"
prior — gate 3 of analysis/LEVELING_MODEL.md.

Usage:
    python build_baseline.py [log ...]   # default: all session logs
"""
import glob
import json
import os
import sys

import live_coach
from extract_game import split_game_chunks

_HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(_HERE, "meta", "turn_baseline.json")
_LOGS = sorted(glob.glob(
    r"C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_*\Power.log"))


def _median(values):
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def walk_game(lines):
    """Yield (turn, our stats, last opponent's stats) at each buy phase."""
    coach = live_coach.LiveCoach()
    prev_turn = 0
    for line in lines:
        coach.feed(line)
        if coach.actions.turn != prev_turn:
            prev_turn = coach.actions.turn
            a = coach.analyze()
            if a is not None and a.get("tier"):
                yield a["turn"], a.get("board_stats"), a.get("last_opp_stats")


def main():
    logs = sys.argv[1:] or _LOGS
    if not logs:
        print("no session logs found")
        return 1
    games = 0
    ours = {}
    theirs = {}
    for path in logs:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for s, e in split_game_chunks(lines):
            games += 1
            for turn, mine, opp in walk_game(lines[s:e]):
                if mine is not None:
                    ours.setdefault(turn, []).append(mine)
                if opp is not None:
                    theirs.setdefault(turn, []).append(opp)
    def bucket(d):
        return {str(t): {"med": _median(v), "n": len(v)}
                for t, v in sorted(d.items())}
    out = {"friendly": bucket(ours), "opp": bucket(theirs), "games": games}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(f"baseline: {games} games -> {os.path.relpath(OUT, _HERE)}")
    for t in sorted(ours):
        print(f"  t{t}: ours {_median(ours[t])} (n={len(ours[t])})"
              f"  opp {_median(theirs.get(t, [0])) if theirs.get(t) else '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())