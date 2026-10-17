#!/usr/bin/env python3
"""Rebuild each saved replay from its own log and diff it against the file.

The audit `REVIEWING_REPLAYS.md` describes, for the Settle Up side: the saved
replay is a CLAIM, and the log it names is the evidence. This rebuilds every
saved game with the current code and reports, per turn, what the file says
against what today's parse produces.

Run from anywhere:

    python3 analysis/audit_replays.py [--limit N] [--json PATH]

Deliberately NOT part of the test suite: it needs the player's logs and saved
games, so it is a maintainer tool like `live_replay.py`.
"""
import argparse
import glob
import json
import os
import sys

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
sys.path.insert(0, APP)

import settle_up     # noqa: E402
import turn_review   # noqa: E402

LOGS = "/Applications/Hearthstone/Logs"

#: What a turn row is compared on. `steps` counts, because a step's board is what
#: the Step-through renders and an empty one is the failure this audit exists for.
TURN_FIELDS = ("winner", "damage_taken", "battle_end", "theirs_survivors",
               "combat_peak", "combat_start", "buy_end", "steps", "notes",
               "lag", "gold", "tier", "eff")


def _len(v):
    return len(v) if isinstance(v, (list, dict)) else v


def _row(turn):
    return {f: (_len(turn.get(f)) if f in ("battle_end", "theirs_survivors",
                                          "combat_peak", "combat_start",
                                          "buy_end", "steps", "notes")
                else turn.get(f))
            for f in TURN_FIELDS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--json", metavar="PATH", default=None)
    ap.add_argument("--dir", default=os.path.join(APP, "saved_replays"))
    args = ap.parse_args()

    saved = sorted(glob.glob(os.path.join(args.dir, "*.json")))
    if args.limit:
        saved = saved[-args.limit:]
    report, skipped = [], []

    for path in saved:
        d = json.load(open(path, encoding="utf-8"))
        sess, game = d.get("session"), d.get("game")
        log = os.path.join(LOGS, sess or "", "Power.log")
        name = os.path.basename(path)
        if not sess or not os.path.exists(log):
            skipped.append({"file": name, "why": "source log is gone"})
            continue
        print(f"\n=== {name}  ({sess} game {game})", flush=True)
        try:
            # `settle_up.build` is what WROTE the file. `turn_review.timeline`
            # is one layer inside it and has no `placement`, which the first
            # version compared against and reported as a mismatch on all eleven.
            rep = settle_up.build(log, game_index=int(game))
        except SystemExit as e:                 # no such game index
            skipped.append({"file": name, "why": str(e)})
            print(f"    SKIP: {e}", flush=True)
            continue

        old = ((d.get("rep") or {}).get("timeline") or {}).get("turns") or []
        new = ((rep.get("timeline") or {}).get("turns")) or []
        entry = {"file": name, "session": sess, "game": game,
                 "saved_turns": len(old), "rebuilt_turns": len(new),
                 "saved_hero": d.get("hero"), "rebuilt_hero": rep.get("hero"),
                 "saved_place": d.get("placement"),
                 "rebuilt_place": rep.get("placement"),
                 "saved_cap": (d.get("rep") or {}).get("ends_at_cap"),
                 "rebuilt_cap": rep.get("ends_at_cap"),
                 "rebuilt_place": rep.get("placement"),
                 "diffs": []}
        by_turn = {t.get("turn"): t for t in new}
        for t in old:
            n = by_turn.get(t.get("turn"))
            if n is None:
                entry["diffs"].append({"turn": t.get("turn"), "why": "gone"})
                continue
            a, b = _row(t), _row(n)
            for f in TURN_FIELDS:
                if a[f] != b[f]:
                    entry["diffs"].append({"turn": t.get("turn"), "field": f,
                                           "saved": a[f], "rebuilt": b[f]})
        report.append(entry)
        print(f"    turns saved={len(old)} rebuilt={len(new)}"
              f"  diffs={len(entry['diffs'])}", flush=True)

    lines = ["# replay audit — saved file vs a rebuild from its own log", ""]
    for e in report:
        lines.append(f"## {e['file']}")
        lines.append(f"- {e['session']} game {e['game']}")
        lines.append(f"- hero saved={e['saved_hero']!r} rebuilt={e['rebuilt_hero']!r}")
        lines.append(f"- place saved={e['saved_place']!r} rebuilt={e['rebuilt_place']!r}")
        lines.append(f"- turns saved={e['saved_turns']} rebuilt={e['rebuilt_turns']}")
        lines.append(f"- field mismatches: {len(e['diffs'])}")
        for x in e["diffs"][:24]:
            lines.append(f"    - turn {x.get('turn')} {x.get('field', x.get('why'))}:"
                         f" saved={x.get('saved')!r} rebuilt={x.get('rebuilt')!r}")
        if len(e["diffs"]) > 24:
            lines.append(f"    - … {len(e['diffs']) - 24} more")
        lines.append("")
    lines.append(f"skipped (no source log): {len(skipped)}")
    for s in skipped:
        lines.append(f"- {s['file']}: {s['why']}")
    out = "\n".join(lines)
    print("\n" + out)
    dest = args.json or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "replay_audit.md")
    if dest.endswith(".md"):
        open(dest, "w", encoding="utf-8").write(out + "\n")
        print(f"\nwritten: {dest}")


if __name__ == "__main__":
    main()
