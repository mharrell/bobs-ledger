#!/usr/bin/env python3
"""Advisory-vs-outcome audit: score what the coach said against what
happened next (the corpus loop, 2026-09-20 test-audit follow-up).

For every buy phase of every local session game:
  - replay the CURRENT coach over the game (one incremental pass — this
    deliberately audits today's rules, unlike decision_log which
    preserves the advice of the code that gave it),
  - record the structured plan (top_move_steps) and the player's actual
    actions that phase (player_actions),
  - record the outcome: effective-HP (health+armor) delta across the
    FOLLOWING combat, snapshotted at buy-phase starts.

Aggregates: adherence per advice class (buy / level-lead / hunt-roll /
pass), and followed-vs-ignored outcome means. THIS IS OBSERVATIONAL:
following advice is correlated with easy spots, so followed-bad and
ignored-good are SUSPECT RULES to review, never proof coaching hurts
or helps (sham-control rule, CLAUDE.md).

Usage:
  python outcome_audit.py [Power.log ...]   # default: all session logs
  python outcome_audit.py --min-followed 4  # suspect-rule sample floor
"""
import glob
import os
import re
import sys
import time
from statistics import mean, median

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import HS_LOG_GLOB
from extract_game import extract_game, _friendly_player, split_game_chunks
from player_actions import parse_actions
from replay_review import _phases, _spell_names
import live_coach

SETTLE = 20  # lines without a new offer set = the shop is fully printed


def _plan_shape(analysis):
    """(lead_class, advised_card) from the structured steps.

    lead_class: buy / level / hunt-roll / pass / pick — what the plan
    asks for FIRST (the advice the player actually reads).
    """
    steps = analysis.get("top_move_steps") or []
    if not steps:
        return "none", None
    first = steps[0]
    kind = first.get("kind") or "none"
    text = first.get("text") or ""
    if kind == "buy":
        return "buy", analysis.get("buy_this") or first.get("card")
    if kind == "level":
        return "level", None
    if kind == "roll":
        return ("hunt-roll" if "hunting" in text else "roll"), None
    if kind == "pick":
        return "pick", first.get("card")
    if text.startswith("pass"):
        return "pass", None
    return kind or "note", None


def audit_game(chunk, game_idx, session):
    """Rows for one game: one per advised buy phase (single feed pass;
    settle inside each phase like replay_review's _advise_point)."""
    game = extract_game(chunk)
    friendly = _friendly_player(game["heroes"], game.get("choice_players"))
    if friendly is None:
        return []
    hero = next((h for h in game["heroes"] if h["player"] == friendly), None)
    phases = _phases(chunk)
    spell_names = _spell_names()
    coach = live_coach.LiveCoach()
    rows = []
    j = 0
    n = len(chunk)
    for pi, (lo, hi) in enumerate(phases):
        while j < lo and j < n:
            coach.feed(chunk[j])
            j += 1
        prev_offers = None
        last_change = j
        a = None
        stop = hi if hi is not None else n
        while j < stop:
            coach.feed(chunk[j])
            offers = tuple(coach.tavern_offers())
            if offers != prev_offers:
                prev_offers = offers
                last_change = j
            elif offers and j - last_change >= SETTLE:
                a = coach.analyze()
                j += 1
                break
            j += 1
        if a is None or not prev_offers:
            continue  # unready coach or a no-shop transition phase
        hi_eff = hi if hi is not None else n
        acts = parse_actions(chunk[lo:hi_eff], friendly=friendly)
        actual = acts[0] if acts else {}
        lead, card = _plan_shape(a)
        buys = actual.get("buys") or []
        steps = a.get("top_move_steps") or []
        picks = ([a.get("buy_this")]
                 + [c for c, _ in (a.get("shop_rank") or [])[:3]])
        picks = [p for p in picks if p]
        followed_buy = bool(lead == "buy" and buys and set(buys) & set(picks))
        planned_level = any(s.get("kind") == "level" for s in steps)
        followed_level = planned_level and bool(actual.get("upgrades"))
        planned_roll = lead in ("hunt-roll", "roll")
        followed_roll = planned_roll and bool(actual.get("refreshes"))
        eff = None
        if a.get("health") is not None:
            eff = a["health"] + (a.get("armor") or 0)
        rows.append({
            "session": session, "game": game_idx, "phase": pi,
            "turn": (a.get("scenario") or {}).get("turns"),
            "hero": (hero or {}).get("hero_name"),
            "placement": (hero or {}).get("place"),
            "tier": a.get("tier"), "gold": a.get("gold"),
            "eff_hp": eff, "hp_delta_next_fight": None,
            "lead": lead, "card": card,
            "card_name": (spell_names.get(card, card) if card else None),
            "followed_buy": followed_buy, "followed_level": followed_level,
            "followed_roll": followed_roll,
            "player_buys": buys, "player_actions": {
                k: actual.get(k) for k in
                ("upgrades", "refreshes", "sells", "freezes")},
        })
    # outcome join: the fight AFTER each advised phase moves eff HP by the
    # delta to the next advised phase (buy-phase armor gains are rare and
    # accepted as v1 noise; the last phase has no following fight)
    for k in range(len(rows) - 1):
        a_eff, b_eff = rows[k]["eff_hp"], rows[k + 1]["eff_hp"]
        if a_eff is not None and b_eff is not None:
            rows[k]["hp_delta_next_fight"] = b_eff - a_eff
    return rows


def _classes(r):
    """Advice classes this row speaks for (a row can carry several)."""
    out = []
    if r["followed_buy"]:
        out.append("buy-followed")
    if r["lead"] == "buy" and not r["followed_buy"]:
        out.append("buy-ignored")
    if r["followed_level"]:
        out.append("level-followed")
    if r["lead"] == "level" and not r["followed_level"]:
        out.append("level-ignored")
    if r["followed_roll"]:
        out.append("hunt-roll-followed")
    if r["lead"] in ("hunt-roll", "roll") and not r["followed_roll"]:
        out.append("hunt-roll-ignored")
    return out


def _summarize(rows, min_followed):
    by = {}
    for r in rows:
        if r["hp_delta_next_fight"] is None:
            continue
        for c in _classes(r):
            by.setdefault(c, []).append(r["hp_delta_next_fight"])
    print("\n== followed vs ignored: eff-HP delta across the NEXT fight ==")
    print("   (negative = bled; observational — see the caveat)\n")
    order = ("buy-followed", "buy-ignored", "level-followed",
             "level-ignored", "hunt-roll-followed", "hunt-roll-ignored")
    for c in order:
        v = by.get(c) or []
        if not v:
            continue
        print(f"  {c:20} n={len(v):3}  mean {mean(v):+6.1f}  "
              f"median {median(v):+6.1f}  min {min(v):+4d}")
    # suspect rules: followed classes whose mean bleeds more than their
    # ignored twin, with a real sample
    print("\n== suspects (followed mean < ignored mean, "
          f"n>={min_followed}) ==")
    found = False
    for base in ("buy", "level", "hunt-roll"):
        f = by.get(f"{base}-followed") or []
        i = by.get(f"{base}-ignored") or []
        if len(f) >= min_followed and i and mean(f) < mean(i):
            found = True
            print(f"  {base}: followed {mean(f):+.1f} (n={len(f)}) vs "
                  f"ignored {mean(i):+.1f} (n={len(i)}) -- review the rule")
    if not found:
        print("  none above the sample floor")
    # the worst followed rows of every suspect class, for the eyeball pass
    worst = sorted((r for r in rows if "level-followed" in _classes(r)
                    and r["hp_delta_next_fight"] is not None),
                   key=lambda r: r["hp_delta_next_fight"])[:8]
    print("\n== worst followed-level phases ==")
    for r in worst:
        print(f"  {r['session'][-8:]} g{r['game']} t{r['turn']} "
              f"tier {r['tier']} at {r['eff_hp']} HP -> "
              f"{r['hp_delta_next_fight']:+d} ({r['hero']}, "
              f"placed {r['placement']})")
    _placement_correlation(rows)


def _placement_correlation(rows):
    """Level-adherence vs placement, per game (direction only until n is
    real — a top-4 weight would need hundreds of games)."""
    games = {}
    for r in rows:
        g = games.setdefault((r["session"], r["game"]),
                             {"place": r["placement"], "leads": 0,
                              "followed": 0, "deltas": []})
        if r["lead"] == "level":
            g["leads"] += 1
            if r["followed_level"]:
                g["followed"] += 1
            if r["hp_delta_next_fight"] is not None:
                g["deltas"].append(r["hp_delta_next_fight"])
    table = [(g["place"], g["followed"], g["leads"],
              mean(g["deltas"]) if g["deltas"] else None)
             for g in games.values()
             if g["leads"] and g["place"] is not None]
    if not table:
        return
    print("\n== level adherence vs placement (per game) ==")
    for place, f, l, d in sorted(table):
        print(f"  placed {place:>2}: followed {f}/{l} level leads"
              + (f", mean {d:+.1f}/fight" if d is not None else ""))


def _dump_json(rows, path):
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print(f"rows written: {path}")


def main():
    argv = [a for a in sys.argv[1:]]
    min_followed = 4
    json_path = None
    archive = None
    if "--min-followed" in argv:
        i = argv.index("--min-followed")
        min_followed = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    if "--json" in argv:
        i = argv.index("--json")
        json_path = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if "--archive" in argv:
        i = argv.index("--archive")
        archive = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    paths = argv or sorted(glob.glob(HS_LOG_GLOB),
                           key=os.path.getmtime, reverse=True)
    now = time.time()
    live_glob = os.path.dirname(HS_LOG_GLOB) if HS_LOG_GLOB else None
    all_rows = []
    for path in paths:
        # the freshness guard exists for the LIVE session dir only (an
        # in-progress Power.log) — explicit paths (archives) always run
        if live_glob and os.path.abspath(path).startswith(
                os.path.abspath(live_glob)) \
                and now - os.path.getmtime(path) < 1800:
            print(f"(skipping live file: {path})")
            continue
        session = os.path.basename(os.path.dirname(path))
        if archive:
            os.makedirs(archive, exist_ok=True)
            dst = os.path.join(archive, f"{session}__Power.log")
            if not os.path.exists(dst):
                import shutil
                shutil.copy2(path, dst)
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        for gi, (s, e) in enumerate(split_game_chunks(lines), 1):
            rows = audit_game(lines[s:e], gi, session)
            all_rows.extend(rows)
            place = rows[0]["placement"] if rows else "?"
            hero = rows[0]["hero"] if rows else "?"
            print(f"{session} game {gi}: {len(rows)} advised phases, "
                  f"hero={hero}, place={place}")
    print(f"\ntotal advised phases: {len(all_rows)} "
          f"across {len({(r['session'], r['game']) for r in all_rows})} games")
    _summarize(all_rows, min_followed)
    if json_path:
        _dump_json(all_rows, json_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
