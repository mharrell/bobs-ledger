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
import json
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
    live.py advises (shop parsed after MAIN_ACTION).

    The live monitor fires at the end of a ~1s poll batch, by which time the
    options block has fully arrived. Feeding line-by-line and firing on the
    first tavern offer instead ranks a PARTIAL shop (one offer) — advice that
    was never actually shown live (the t9/t15 one-card rankings were this
    artifact). Fire once the offer set has been stable for a stretch, like the
    settled state the live loop actually advises on.
    """
    import live_coach
    coach = live_coach.LiveCoach()
    stop = len(lines)
    armed = False
    prev_offers = None
    last_change = 0
    SETTLE = 20  # lines without new offers = the options block is complete
    for j in range(0, phase_hi if phase_hi is not None else len(lines)):
        line = lines[j]
        if j >= phase_lo and "tag=STEP value=MAIN_ACTION" in line:
            armed = True
        coach.feed(line)
        if armed:
            offers = tuple(coach.tavern_offers())
            if offers != prev_offers:
                prev_offers = offers
                last_change = j
            elif offers and j - last_change >= SETTLE:
                stop = j + 1
                break
    return coach.analyze(), stop


def _known_minion_ids():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "meta", "minions.json"), encoding="utf-8") as f:
        return {m.get("id") for m in json.load(f)}


def _spell_names():
    """id -> name for tavern spells (shop advice ranks spells too since
    spell-buy advice; spell purchases are reported as such, not as 'passed')."""
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "meta", "tavern_spells.json"), encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else list(data.values())
        return {s.get("id"): s.get("name") for s in items
                if isinstance(s, dict) and s.get("id")}
    except OSError:
        return {}


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
    place = (hero or {}).get("place")
    print(f"replay review — {os.path.basename(os.path.dirname(path))} "
          f"game {game_index}/{len(chunks)}, hero={hero['hero_name'] if hero else '?'}"
          + (f", placement {place}" if place else ""))

    phases = _phases(chunk)
    spell_names = _spell_names()
    minion_ids = _known_minion_ids()
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
        buys = [names.get(c, c) for c in (actual.get("buys") or [])]
        board_n = len(a.get("board") or [])
        print(f"t{t}  tier {a.get('tier')}  gold {a.get('gold')}  board {board_n}")
        print(f"     coach: {rec}")
        print(f"     actual: {_actual(actual, names)}")
        # Was a coach pick taken? Compare card IDS (names can be missing from
        # the pool; ids are the parse-level truth). Headline buy plus the next
        # two ranked offers count.
        buys_raw = actual.get("buys") or []
        spell_buys = [c for c in buys_raw if c not in minion_ids]
        picks = [a.get("buy_this")] + [c for c, _ in (a.get("shop_rank") or [])[:3]]
        picks = [p for p in picks if p]
        if picks:
            if buys_raw and set(buys_raw) & set(picks):
                hit = next(c for c in buys_raw if c in picks)
                print(f"     buy match: TAKEN ({names.get(hit, hit)})")
            elif buys_raw and all(c in spell_names for c in buys_raw):
                print("     buy match: spells only "
                      f"({', '.join(spell_names.get(c, c) for c in buys_raw)}) "
                      f"— not among the coach's ranked picks this phase")
            else:
                print(f"     buy match: passed "
                      f"(coach pick: {names.get(picks[0], picks[0])})")
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