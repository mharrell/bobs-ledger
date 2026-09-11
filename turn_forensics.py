#!/usr/bin/env python3
"""One-command per-turn forensics for a Battlegrounds game.

The ad-hoc questions a game review keeps asking — how much gold did the
player have at moment X, when was card Y offered (including mid-roll shops),
what was affordable — took half a dozen grep chains per answer against a
100+ MB log (the 2026-09-10 review: the Felfire Conjurer moment needed a
gold timeline, an offer scan, and a coach replay). This tool answers them
in one pass.

Per turn: tier + income, the gold timeline (every spend/refund labeled),
every shop rebuild with a timestamp (comp cores flagged, affordability
noted), the player's actions, and the end-of-turn board.

Usage:
  python turn_forensics.py --latest [--turns 13|13-15|all]
  python turn_forensics.py <Power.log> [game_index] [--turns ...]

Reuses the existing parsers (split_game_chunks, replay_review._phases,
player_actions.parse_actions, live_coach.LiveCoach — whose zone layer keeps
the shop correct mid-phase, value._load_bg_names). Gold = income - USED
(USED resets each buy phase; income = min(tier + 2, 10) — no interest, no
win-streak gold, the player rules).
"""
import glob
import json
import os
import re
import sys

from config import HS_LOG_GLOB
from extract_game import split_game_chunks, extract_game, _friendly_player, \
    MINION_ID
from player_actions import parse_actions
import live_coach
from value import _load_bg_names

TS = re.compile(r"^D (\d+:\d+:\d+)\.")
# GameState lines of offer stability before a shop snapshot commits. Each
# offer arrives as its own write ~30-100 lines apart, so the bar must clear
# the whole build (a settled shop persists for seconds — roll gaps are
# human-paced — while a build takes well under one).
_SETTLE = 300
TECH = re.compile(
    r"TAG_CHANGE Entity=\[[^\]]*?player=(\d+)\] tag=PLAYER_TECH_LEVEL "
    r"value=(\d+)")


def _load_core_ids(here):
    """Card ids (base form) that any comp lists as core or addon."""
    with open(os.path.join(here, "meta", "comps.json"), encoding="utf-8") as f:
        comps = json.load(f)
    ids = set()
    for comp in comps.values():
        ids.update(comp.get("core") or [])
        ids.update(comp.get("addons") or [])
    return ids


def _label(diff, buys_queue, sells_queue):
    """Human label for one gold delta (diff < 0 = spend, > 0 = gain).

    buys_queue / sells_queue hold the turn's buys/sells pre-resolved to
    display names in action order: a -3 delta pops the next buy (minions
    cost a flat 3), a +1 pops the next sell (Drag To Sell refunds 1)."""
    if diff > 0:
        if diff == 1 and sells_queue:
            return f"sell {sells_queue.pop(0)}"
        return f"gain +{diff}"
    want = -diff
    if want == 3 and buys_queue:
        return f"buy {buys_queue.pop(0)}"
    if want == 1:
        return "roll"
    return f"spend {want}"


def _turn_set(spec, n):
    if not spec or spec == "all":
        return set(range(1, n + 1))
    m = re.match(r"^(\d+)-(\d+)$", str(spec))
    if m:
        return set(range(int(m.group(1)), int(m.group(2)) + 1))
    return {int(spec)}


def forensics(chunk, names, cores, turns_filter=None):
    """{turn: [lines]} of distilled forensics for the requested turns."""
    game = extract_game(chunk)
    friendly = _friendly_player(game["heroes"])
    hero = next((h for h in game["heroes"] if h["player"] == friendly), None)
    hero_card = hero["card"] if hero else None
    account = next((n for n, c in game.get("account", {}).items()
                    if c == hero_card), None)
    coach = live_coach.LiveCoach()
    # The friendly player is known from the chunk — set it directly instead
    # of waiting for analyze()'s hero parse, so offer filtering and the
    # snapshot gate work from line one (analyze() is deliberately never
    # called here; this tool is a state walk, not an advice run).
    coach.friendly = friendly

    from replay_review import _phases
    phases = _phases(chunk)
    phase_of_line = {}
    for t, (lo, hi) in enumerate(phases, 1):
        phase_of_line[lo] = ("buy", t)
        if hi is not None:
            phase_of_line[hi] = ("combat", t)
    wanted = _turn_set(turns_filter, len(phases))

    acts = {}
    for t, (lo, hi) in enumerate(phases, 1):
        if t in wanted:
            seg = chunk[lo:hi if hi is not None else len(chunk)]
            lst = parse_actions(seg, friendly, friendly_hero_card=hero_card)
            acts[t] = lst[0] if lst else {}

    def base(cid):
        return cid[:-2] if cid.endswith("_G") else cid

    out = {}
    tier = 0
    turn = None
    income = None
    prev_gold = None
    buys_queue = []
    sells_queue = []
    gold_moves = []
    shops = []
    prev_offers = None
    pending_shop = None   # offers seen, not yet stable for _SETTLE lines
    quiet = 0
    for j, line in enumerate(chunk):
        coach.feed(line)
        if coach.friendly is None and friendly is not None:
            # The chunk's CREATE_GAME runs LiveCoach._reset(), wiping the
            # friendly set above the loop — re-assert it (this tool never
            # calls analyze(), whose hero parse is what normally restores it).
            coach.friendly = friendly
        ev = phase_of_line.get(j)
        if ev:
            phase, t = ev
            if phase == "buy":
                turn = t
                income = None
                prev_gold = None
                gold_moves, shops, prev_offers = [], [], None
                pending_shop = None
                # Only flat-3 minion buys pop the buy queue (spell buys,
                # e.g. Lost Staff of Hamuul at 2g, surface as "spend N");
                # sells pop the sell queue on their +1 refund.
                buys_queue = [names.get(b, b)
                              for b in acts.get(t, {}).get("buys", [])
                              if MINION_ID.match(b)]
                sells_queue = [names.get(s, s)
                               for s in acts.get(t, {}).get("sells", [])]
            else:
                if pending_shop is not None:
                    shops.append(pending_shop)   # flush the phase's last shop
                    pending_shop = None
                if turn in wanted:
                    board = _board_line(coach, friendly)
                    out[turn] = _render(turn, tier, income, acts.get(turn),
                                        gold_moves, shops, board, names,
                                        cores, base)
                turn = None
            continue
        if "GameState." not in line:
            continue
        tm = TECH.search(line)
        # Only the friendly HERO entity's tier counts: hero-pick teardowns
        # write other heroes' PLAYER_TECH_LEVEL=0 tagged player=<ours> mid-game
        # (the 2026-09-10 game wrote George-the-Fallen value=0 as player=1).
        if tm and int(tm.group(1)) == friendly \
                and hero_card and f"cardId={hero_card}" in line:
            tier = int(tm.group(2))
        if turn is None or coach.friendly is None or not account:
            continue
        # Gold straight from the log's purse (RESOURCES + TEMP_RESOURCES
        # - RESOURCES_USED) — board_state's spending-aware model, no
        # per-tier income formula to get wrong.
        gold = coach.gs.gold.get(account)
        if gold is None:
            continue
        if income is None:
            income = coach.gs.gold_max.get(account)
            prev_gold = gold
        if gold != prev_gold:
            ts = TS.match(line)
            gold_moves.append((ts.group(1) if ts else "?",
                               _label(gold - prev_gold, buys_queue,
                                      sells_queue), gold))
            prev_gold = gold
        offers = coach.tavern_offers()
        if offers != prev_offers:
            prev_offers = offers
            pending_shop = None
            if offers:
                ts = TS.match(line)
                pending_shop = (ts.group(1) if ts else "?",
                                list(offers), gold)
            quiet = 0
        elif pending_shop is not None:
            quiet += 1
            if quiet >= _SETTLE:
                # offers stable for _SETTLE GameState lines: a settled shop
                # (each offer ARRIVES as its own write — snapshotting every
                # change spams the growing prefix; only the settled set is
                # the shop the player saw between actions)
                shops.append(pending_shop)
                pending_shop = None
    return out


def _board_line(coach, friendly):
    try:
        board, _opp = coach.gs.final_board(friendly)
    except Exception:
        return None
    if not board:
        return None
    return " ".join(f"{m['card']} {int(m.get('atk') or 0)}/"
                    f"{int(m.get('health') or 0)}" for m in board)


def _render(turn, tier, income, act, gold_moves, shops, board, names, cores,
            base):
    def nm(cid):
        return names.get(base(cid), cid)

    lines = [f"t{turn}  tier {tier}  income {income}"]
    if act:
        bits = []
        if act.get("buys"):
            bits.append(f"buys {len(act['buys'])}")
        if act.get("sells"):
            bits.append(f"sells {len(act['sells'])}")
        if act.get("refreshes"):
            bits.append(f"rolls {act['refreshes']}")
        if act.get("triples"):
            bits.append(f"triples {len(act['triples'])}")
        if bits:
            lines[-1] += "  " + "  ".join(bits)
    if gold_moves:
        moves = "; ".join(f"{ts} {lab} ({g} left)"
                          for ts, lab, g in gold_moves[:12])
        more = f" … +{len(gold_moves) - 12} more" if len(gold_moves) > 12 \
            else ""
        lines.append(f"  gold: {moves}{more}")
    # Settled shops: show them all when few, else first + last + every
    # core-bearing one (the Felfire-moment question this tool exists for).
    shown = []
    picks = set()
    if shops:
        if len(shops) <= 8:
            picks = set(range(len(shops)))
        else:
            picks = {0, len(shops) - 1}
            for i, (_ts, offers, _g) in enumerate(shops):
                if any(base(c) in cores for c in offers):
                    picks.add(i)
    for i in sorted(picks):
        ts, offers, g = shops[i]
        tagged = " ".join(("*" if base(c) in cores else "") + nm(c)
                          for c in offers[:8])
        line = f"  shop@{ts} (gold {g}): {tagged}"
        if any(base(c) in cores for c in offers) and g >= 3:
            line += "  [core affordable]"
        shown.append(line)
    lines.extend(shown)
    if board:
        lines.append(f"  board@turn-end: {board}")
    return lines


def main():
    argv = sys.argv[1:]
    turns = None
    if "--turns" in argv:
        i = argv.index("--turns")
        turns = argv[i + 1]
        del argv[i:i + 2]
    latest = "--latest" in argv
    args = [a for a in argv if not a.startswith("--")]
    if latest or not args:
        logs = sorted(glob.glob(HS_LOG_GLOB), key=os.path.getmtime,
                      reverse=True)
        if not logs:
            print("no session log found")
            return 1
        path = logs[0]
    else:
        path = args[0]
        args = args[1:]
    game_index = int(args[0]) if args else None

    here = os.path.dirname(os.path.abspath(__file__))
    cores = _load_core_ids(here)
    names = _load_bg_names()

    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    chunks = list(split_game_chunks(lines))
    if game_index is None:
        game_index = len(chunks)
    s, e = chunks[game_index - 1]
    game = extract_game(lines[s:e])
    friendly = _friendly_player(game["heroes"])
    hero = next((h for h in game["heroes"] if h["player"] == friendly), None)
    print(f"turn forensics — {os.path.basename(os.path.dirname(path))} "
          f"game {game_index}/{len(chunks)}, "
          f"hero={hero['hero_name'] if hero else '?'}")

    out = forensics(lines[s:e], names, cores, turns)
    for t in sorted(out):
        print()
        for line in out[t]:
            print(line)


if __name__ == "__main__":
    main()
