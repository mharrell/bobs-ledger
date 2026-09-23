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
import datetime
import glob
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import extract_game as eg  # noqa: E402
import meta  # noqa: E402
import replay_stats as rs  # noqa: E402
from tribes import normalize, parts  # noqa: E402

HS_LOG_GLOB = r"C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_*\Power.log"
CANDIDATES = os.path.join(_HERE, "meta", "comp_candidates.json")
COMPS_PATH = os.path.join(_HERE, "meta", "comps.json")
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
    """Tribes with no PUBLISHED comp — a provisional one does not close this.

    The distinction is the point: "no comp published" and "no comp at all" lead
    to different advice (stay honest about the gap vs coach the mined package),
    and the two are told apart by the `provisional` marker, not by presence.
    """
    defined = {normalize(c.get("tribe")) for c in comps.values()
               if isinstance(c, dict) and c.get("tribe")
               and not c.get("provisional")}
    from tribes import DISPLAY_TRIBES
    return [t for t in DISPLAY_TRIBES if t not in defined]


# ---------------------------------------------------------------------------
# Promotion: an own-corpus proposal into comps.json, marked provisional
# ---------------------------------------------------------------------------

#: The floor for a PROVISIONAL comp. Below DEFAULT_MIN_GAMES on purpose: for a
#: tribe the published source does not cover at all, "4 of our games agree on
#: these two cores" is more useful than silence — as long as the entry says so.
PROVISIONAL_FLOOR = 3
PROVISIONAL_SOURCE = "own replay corpus (comp_miner.py)"


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def provisional_entry(mined, name=None, min_games=PROVISIONAL_FLOOR,
                      summary=None):
    """A comps.json entry proposed from our own boards, marked provisional.

    Same shape as a scraped entry plus the fields the pipeline and the UI read,
    and `meta_tier`/`difficulty` left null ON PURPOSE: nobody published this
    comp, so there is no tier to quote, and a fabricated "A" would let it sort
    among real comps and win pick ranking it never earned.
    """
    tribe = mined["tribe"]
    label = name or f"{tribe} - Mined Core"
    return {
        "name": label,
        "tribe": tribe,
        "meta_tier": None,
        "difficulty": None,
        "core": [c["card"] for c in mined["core"]],
        "addons": [c["card"] for c in mined["addons"]],
        "provisional": True,
        "source": PROVISIONAL_SOURCE,
        "summary": summary or (
            f"Mined from {mined['games']} of our own {tribe}-dominant games "
            f"({mined['top4']} top-4). Core = cards on {int(CORE_SHARE * 100)}% "
            f"or more of those final boards."),
        "when_to_commit": (
            "When the board is majority "
            f"{tribe} and two or more of the core cards are held or bought."),
        "evidence": {
            "games": mined["games"],
            "top4": mined["top4"],
            "floor": min_games,
            "built": datetime.date.today().isoformat(),
            "core": mined["core"],
            "addons": mined["addons"],
        },
    }


def promote(rows, comps, tribe, name=None, min_games=PROVISIONAL_FLOOR,
            summary=None):
    """(slug, entry, action, reason) for promoting one tribe's proposal.

    Refuses in the two cases that would corrupt the DB: a PUBLISHED comp for
    that tribe (the scraped source owns the tribe, our mining does not
    outrank it) and an existing entry under the same slug that is not
    provisional. Re-running is safe: our own provisional entry is rebuilt with
    fresh evidence and the human-chosen name preserved.
    """
    mined = mine(rows, tribe, min_games)
    published = [k for k, c in comps.items()
                 if isinstance(c, dict) and not c.get("provisional")
                 and normalize(c.get("tribe")) == normalize(tribe)]
    if published:
        return None, None, "skipped", (f"a published comp already covers "
                                       f"{tribe} ({', '.join(sorted(published)[:2])})")
    if not mined["enough_evidence"]:
        return None, None, "skipped", mined["note"]
    # Resolve the target slug. An explicit --name wins; otherwise reuse the
    # tribe's existing provisional entry, so a re-run WITHOUT --name updates
    # that row instead of adding a second one under the bare tribe slug.
    prior = [k for k, c in comps.items()
             if isinstance(c, dict) and c.get("provisional")
             and normalize(c.get("tribe")) == normalize(tribe)]
    if name:
        slug = _slug(name)
    elif prior:
        slug = sorted(prior)[0]
    else:
        slug = _slug(tribe)
    existing = comps.get(slug)
    if existing is not None and not existing.get("provisional"):
        return None, None, "skipped", (f"{slug} exists and is not provisional "
                                       f"— refusing to overwrite")
    if existing and existing.get("name") and not name:
        name = existing["name"]            # keep the human's label
    entry = provisional_entry(mined, name=name, min_games=min_games,
                              summary=summary)
    return slug, entry, ("updated" if existing else "created"), None


def shadowed_provisional(comps):
    """Provisional slugs a published comp now covers — for the report only.

    The published source catching up is the intended end of a provisional
    entry, but deleting it here would silently drop the evidence trail and
    could remove a comp the player has been using mid-session, so this reports
    and lets a human decide.
    """
    published_tribes = {normalize(c.get("tribe")) for c in comps.values()
                        if isinstance(c, dict) and not c.get("provisional")}
    return [k for k, c in comps.items()
            if isinstance(c, dict) and c.get("provisional")
            and normalize(c.get("tribe")) in published_tribes]


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
    ap.add_argument("--promote", action="store_true",
                    help="write a PROVISIONAL comp into meta/comps.json "
                         "(default --min-games 3; never touches a published "
                         "comp, never invents a meta tier)")
    ap.add_argument("--name", default=None,
                    help="display name for the promoted comp")
    ap.add_argument("--summary", default=None,
                    help="one-line summary for the promoted comp")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --promote: report, write nothing")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = scan(args.logs, args.limit)
    if not rows:
        print("no games with a dominant tribe found in the corpus")
        return 0

    if args.promote:
        floor = args.min_games if args.min_games != DEFAULT_MIN_GAMES \
            else PROVISIONAL_FLOOR
        targets = [args.tribe] if args.tribe else tribes_without_comps(
            meta.comps())
        comps = dict(meta.comps())
        changed = []
        for tribe in targets:
            slug, entry, action, reason = promote(
                rows, comps, tribe, name=args.name if len(targets) == 1 else None,
                min_games=floor, summary=args.summary)
            if entry is None:
                print(f"  {tribe:12} {action}: {reason}")
                continue
            comps[slug] = entry
            changed.append(slug)
            ev = entry["evidence"]
            print(f"  {tribe:12} {action} {slug} — core="
                  f"{[c['name'] for c in ev['core']]} "
                  f"(n={ev['games']}, top4={ev['top4']}, floor={ev['floor']})")
        for slug in shadowed_provisional(comps):
            print(f"  ! {slug} is now shadowed by a published comp — review")
        if not changed:
            print("nothing promoted")
            return 0
        if args.dry_run:
            print(f"(dry run — {len(changed)} provisional comp(s) not written)")
            return 0
        with open(COMPS_PATH, "w", encoding="utf-8") as f:
            json.dump(comps, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"wrote {len(changed)} provisional comp(s) to "
              f"{os.path.relpath(COMPS_PATH, _HERE)} "
              f"(published entries untouched)")
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
