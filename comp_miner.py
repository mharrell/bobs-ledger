#!/usr/bin/env python3
"""Propose comps from OUR OWN replay corpus, for tribes the comp source lacks.

Comps have always come from a scraped site (hsreplay). Patch 36.6.1 added the
Aberration tribe and that site still lists **zero** Aberration comps — verified
by re-scraping: 26 comps across the ten original tribes, and it even still lists
two Naga comps that left the pool. So for a new tribe the coach has nothing to
build toward, and until now the only options were to invent one (the
"checklist comp" anti-pattern this project warns about) or to stay silent.

This is the third option: measure. Every Power.log contains the final board of
your own games, so the corpus says which cards actually appear together on
boards that placed well, for any tribe, with the sample size attached.

**It proposes; it never writes `meta/comps.json`.** Output is
`meta/comp_candidates.json` (with `--write`) plus a bounded report, and a
candidate below the evidence floor is reported as `insufficient evidence (n=X,
need Y)` rather than dressed up as a comp. The floor exists because a comp
mined from two games is a coincidence.

Usage:
  python comp_miner.py                       # report (nothing written)
  python comp_miner.py --tribe Aberration
  python comp_miner.py --min-games 8 --write
  python comp_miner.py --json
"""
import argparse
import collections
import glob
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import extract_game as eg  # noqa: E402
import meta  # noqa: E402
import replay_stats as rs  # noqa: E402
from tribes import normalize, parts  # noqa: E402

HS_LOG_GLOB = r"C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_*\Power.log"
CANDIDATES = os.path.join(_HERE, "meta", "comp_candidates.json")
#: A comp mined from fewer games than this is a coincidence, not a pattern.
DEFAULT_MIN_GAMES = 5
#: A card in this share of the tribe's boards is core material.
CORE_SHARE = 0.6


def dominant_tribe(board):
    """The tribe holding a majority of the board's tribed minions, or None.

    The denominator is *tribed cards*, not cards, and not tribe-hits:

    - an untribed minion is not evidence of any tribe;
    - an Amalgam is `All`, which `normalize` maps to None (untribed), and it
      must stay that way here — counting it once per tribe is exactly the bug
      `value._tribe_hits` fixes on the coaching side;
    - a compound card (Demon/Quilboar) counts once for each of its parts, so
      hits can exceed the card count. Pure compound boards therefore tie, and
      a tie resolves to the first tribe seen on the board.
    """
    counts = collections.Counter()
    tribed = 0
    for m in board or []:
        ts = parts(normalize((m or {}).get("tribe")))
        if ts:
            tribed += 1
        for p in ts:
            counts[p] += 1
    if tribed < 3 or not counts:
        return None
    tribe, n = counts.most_common(1)[0]
    return tribe if n * 2 > tribed else None


def scan(log_glob=HS_LOG_GLOB, limit=None):
    """[(tribe, placement, [card ids])] for every game in the corpus."""
    out = []
    paths = sorted(glob.glob(log_glob))
    for path in paths[-limit:] if limit else paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            continue
        for lo, hi in eg.split_game_chunks(lines):
            try:
                feat = rs.game_features(lines[lo:hi])
            except Exception:  # noqa: BLE001 — a malformed game must not stop the scan
                continue
            if not isinstance(feat, dict):
                continue
            tribe = dominant_tribe(feat.get("board"))
            if not tribe:
                continue
            cards = [m.get("card") for m in feat["board"] if m.get("card")]
            out.append((tribe, feat.get("place"), cards))
    return out


def mine(rows, tribe, min_games=DEFAULT_MIN_GAMES):
    """Evidence for one tribe: how many games, and which cards recurred."""
    games = [(p, c) for t, p, c in rows if t == tribe]
    n = len(games)
    per_card = collections.Counter()
    places = collections.defaultdict(list)
    for place, cards in games:
        for cid in set(cards):
            per_card[cid] += 1
            if place:
                places[cid].append(place)
    names = {}
    for row in (meta._raw("minions.json") or []):
        names[row.get("id")] = row.get("name")
    scored = []
    for cid, count in per_card.items():
        pl = places.get(cid) or []
        scored.append({
            "card": cid, "name": names.get(cid, cid), "games": count,
            "share": round(count / n, 2) if n else 0,
            "avg_place": round(sum(pl) / len(pl), 2) if pl else None,
        })
    scored.sort(key=lambda r: (-r["share"], r["avg_place"] or 99))
    core = [r for r in scored if n and r["share"] >= CORE_SHARE][:6]
    addons = [r for r in scored if r not in core][:6]
    return {"tribe": tribe, "games": n, "enough_evidence": n >= min_games,
            "top4": sum(1 for p, _ in games if p and p <= 4),
            "core": core, "addons": addons,
            "note": (None if n >= min_games else
                     f"insufficient evidence (n={n}, need {min_games})")}


def tribes_without_comps(comps):
    defined = {normalize(c.get("tribe")) for c in comps.values()
               if isinstance(c, dict) and c.get("tribe")}
    from tribes import DISPLAY_TRIBES
    return [t for t in DISPLAY_TRIBES if t not in defined]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tribe", default=None,
                    help="mine one tribe (default: every tribe with no comp)")
    ap.add_argument("--min-games", type=int, default=DEFAULT_MIN_GAMES)
    ap.add_argument("--logs", default=HS_LOG_GLOB)
    ap.add_argument("--limit", type=int, default=None,
                    help="scan only the newest N session logs")
    ap.add_argument("--write", action="store_true",
                    help="write meta/comp_candidates.json (never comps.json)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = scan(args.logs, args.limit)
    if not rows:
        print("no games with a dominant tribe found in the corpus")
        return 0
    comps = meta.comps()
    targets = [args.tribe] if args.tribe else tribes_without_comps(comps)
    report = [mine(rows, t, args.min_games) for t in targets]
    report.sort(key=lambda r: -r["games"])

    if args.json:
        print(json.dumps({"games_scanned": len(rows), "candidates": report},
                         indent=1, ensure_ascii=False))
    else:
        by_tribe = collections.Counter(t for t, _p, _c in rows)
        print(f"corpus: {len(rows)} game(s) with a dominant tribe "
              f"| {dict(by_tribe.most_common(4))}")
        print(f"tribes with no comp in comps.json: {targets or '(none)'}")
        for r in report:
            head = (f"  {r['tribe']:12} n={r['games']:2} top4={r['top4']:2}")
            if not r["enough_evidence"]:
                print(f"{head}  {r['note']}")
                if r["core"]:
                    print(f"      would suggest: "
                          f"{[c['name'] for c in r['core']]}")
                continue
            print(f"{head}  CANDIDATE")
            for c in r["core"]:
                print(f"      core  {c['name']:26} {c['games']}/{r['games']} "
                      f"games, avg place {c['avg_place']}")
            for c in r["addons"][:3]:
                print(f"      addon {c['name']:26} {c['games']}/{r['games']}")
    if args.write:
        with open(CANDIDATES, "w", encoding="utf-8") as f:
            json.dump({"games_scanned": len(rows), "min_games": args.min_games,
                       "candidates": report}, f, indent=1, ensure_ascii=False)
            f.write("\n")
        print(f"wrote {os.path.relpath(CANDIDATES, _HERE)} "
              f"(comps.json untouched — promotion is a human call)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
