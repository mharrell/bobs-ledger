#!/usr/bin/env python3
"""Compact review skeleton for a session — and a cache of the full output.

This replaces the most expensive habit in the whole workflow: reading a full
`replay_review` run (20+ buy phases x 3 games, hundreds of lines) in order to
write a review. Four review subagents did that in one session, and each also
rebuilt its own forensic scripts to answer questions `logquery.py` now answers.

What it prints is bounded (<= ~12 lines per game) and contains only the things a
reviewer must see to decide WHERE to look:

  - hero, placement, buy-phase count, and how many card ids in that game the
    meta DB cannot name (a pre-flight: advice that renders as `BG36_318` is not
    reviewable advice);
  - the advice-adherence split — how often the player took the coach's pick,
    passed on it, or the plan's step was never applicable;
  - the phases worth opening, which are the mismatches plus the first and last
    phase of each game.

The full `replay_review` text is written to `.review_cache/<session>_g<N>.txt`
(keyed by log size+mtime, so a re-run costs nothing) — so a reviewer can grep
one phase or hand it to `replay_review --at` instead of re-parsing a 1.1M-line
log.

Usage:
  python review_kit.py [<log>|--latest] [--games 1,3] [--json] [--refresh]
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import extract_game as eg  # noqa: E402
import logquery  # noqa: E402

CACHE = os.path.join(_HERE, ".review_cache")
HEADER = re.compile(r"game (\d+)/(\d+), hero=(.+?), placement (\d+)")
PHASES = re.compile(r"^(\d+) buy phases", re.M)
PHASE = re.compile(r"^t(\d+)\s+tier (\S+)\s+gold (\S+)\s+board (\d+)", re.M)
VERDICT = re.compile(r"^\s+buy match: (.+)$", re.M)


def _cache_path(log, game):
    st = os.stat(log)
    key = f"{int(st.st_size)}_{int(st.st_mtime)}"
    name = os.path.splitext(os.path.basename(os.path.dirname(log)))[0]
    return os.path.join(CACHE, f"{name}_{key}_g{game}.txt")


def _full_output(log, game, refresh=False):
    """The whole replay_review text for one game, cached on disk.

    Written through a FILE, not a pipe: this sandbox refuses pipe creation, and
    the tool that taught us that (git over ssh) failed with a bare
    `couldn't create signal pipe`.
    """
    path = _cache_path(log, game)
    if os.path.exists(path) and not refresh:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(), path
    os.makedirs(CACHE, exist_ok=True)
    with open(path, "w", encoding="utf-8", errors="replace") as fh:
        subprocess.run([sys.executable, "replay_review.py", log, str(game)],
                       stdout=fh, stderr=subprocess.STDOUT, cwd=_HERE)
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read(), path


def _classify(verdict):
    v = verdict.strip().lower()
    if v.startswith("taken"):
        return "taken"
    if v.startswith("passed"):
        return "passed"
    if v.startswith("plan said"):
        return "not_applicable"
    return "other"


def parse_text(text):
    """`replay_review` output -> the facts a reviewer actually needs.

    One parser for both entry points: `review_kit.py` here, and
    `replay_review.py --summary` (which captures its own output and calls
    `summarise_text`). Two parsers would drift.
    """
    header = HEADER.search(text)
    count = PHASES.search(text)
    return {
        "game": int(header.group(1)) if header else None,
        "hero": header.group(3) if header else "?",
        "place": int(header.group(4)) if header else None,
        # `phases` is only the rows that rendered a coach line (a transition
        # turn or an unparsed-hero phase prints none), so it is NOT the buy-phase
        # count — keep both, and label them apart, or the adherence percentage
        # quietly divides by the wrong denominator.
        "phases": [int(m.group(1)) for m in PHASE.finditer(text)],
        "phase_count": int(count.group(1)) if count else None,
        "verdicts": [m.group(1) for m in VERDICT.finditer(text)],
    }


def _adherence(verdicts):
    split = {"taken": 0, "passed": 0, "not_applicable": 0, "other": 0}
    for v in verdicts:
        split[_classify(v)] += 1
    return split


def _compact_line(facts, split, unresolved=None, cache=None):
    rounds = facts.get("phase_count") or len(facts["phases"])
    n = len(facts["verdicts"])
    pct = round(100.0 * split["taken"] / n) if n else None
    out = [f"g{facts['game']} {str(facts['hero'])[:20]:20} "
           f"place={facts['place']} phases={rounds} "
           f"taken={split['taken']}/{n} ({pct}%) "
           f"passed={split['passed']} n/a={split['not_applicable']}"]
    mismatch = [t for t, v in zip(facts["phases"], facts["verdicts"])
                if _classify(v) in ("passed", "other")]
    moments = sorted(set(mismatch[:6] + facts["phases"][-1:]))
    out.append(f"   open first: turns {moments or '-'}")
    if unresolved:
        out.append(f"   UNRESOLVED ids (advice renders raw): "
                   f"{', '.join(unresolved[:5])}")
    if cache:
        out.append(f"   full text: {os.path.relpath(cache, _HERE)}")
    return "\n".join(out)


def summarise_text(text):
    """The digest `replay_review --summary` prints: facts, no table."""
    facts = parse_text(text)
    if not facts["phases"] and not facts["verdicts"]:
        # `--at` mode prints a single moment, not a phase table.
        first = next((ln for ln in text.splitlines() if ln.startswith("at ")),
                     "no phases parsed")
        return f"(single moment) {first}"
    return _compact_line(facts, _adherence(facts["verdicts"]))


def summarise_game(log, game, chunk, refresh=False):
    """One game's skeleton row, with the pre-flight and the cache path."""
    text, cache_path = _full_output(log, game, refresh)
    facts = parse_text(text)
    unresolved = [c for c, _ in logquery._unresolved_ids(chunk)]
    return {
        "game": game, "hero": facts["hero"], "place": facts["place"],
        "phases": len(facts["phases"]), "adherence": _adherence(facts["verdicts"]),
        "unresolved": unresolved,
        "moments": _moments(facts),
        "cache": cache_path,
    }


def _moments(facts):
    mismatch = [t for t, v in zip(facts["phases"], facts["verdicts"])
                if _classify(v) in ("passed", "other")]
    return sorted(set(mismatch[:6] + facts["phases"][-1:]))



def show_moments(text, turns):
    """Just the phase blocks for `turns` out of a full cached review.

    The skeleton says "open first: turns [5, 8, 13]" — this is how you open
    them without reading the rest. Found by using the tool: the digest named
    the turns and then left no cheap way to look at only those.
    """
    blocks = {}
    for block in re.split(r"\n(?=t\d+[ (])", text):
        m = re.match(r"t(\d+)", block)
        if m:
            blocks[int(m.group(1))] = block.rstrip()
    return "\n".join(blocks.get(t, f"t{t}: (no such phase in the cached text)")
                     for t in turns)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # cached reviews can carry ⚠/· — a cp1252 console must not kill the run
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log", nargs="?", default=None)
    ap.add_argument("--latest", action="store_true",
                    help="use the newest session log (same as passing no log)")
    ap.add_argument("--games", default=None, help="comma list, e.g. 1,3")
    ap.add_argument("--show", default=None,
                    help="print only these turns from the cache, e.g. --show 5,13")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    path = (args.log if args.log and args.log != "--latest" and not args.latest
            else logquery.newest_log())
    if not path or not os.path.exists(path):
        raise SystemExit("no Power.log found (pass a path)")

    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    chunks = list(eg.split_game_chunks(lines))
    want = ([int(x) for x in args.games.split(",")] if args.games
            else list(range(1, len(chunks) + 1)))

    if args.show:
        turns = [int(x) for x in args.show.split(",")]
        for g in want:
            text, _ = _full_output(path, g, args.refresh)
            print(f"--- game {g} ---")
            print(show_moments(text, turns))
        return 0

    rows = []
    for g in want:
        lo, hi = chunks[g - 1]
        rows.append(summarise_game(path, g, lines[lo:hi], args.refresh))

    if args.json:
        print(json.dumps({"log": os.path.basename(os.path.dirname(path)),
                          "games": rows}, ensure_ascii=False))
        return 0

    print(f"{os.path.basename(os.path.dirname(path))}: {len(rows)} game(s)")
    for r in rows:
        a = r["adherence"]
        pct = (f"{round(100.0 * a['taken'] / r['phases'])}%"
               if r["phases"] else "?")
        print(f"  g{r['game']} {str(r['hero'])[:20]:20} place={r['place']} "
              f"phases={r['phases']} taken={a['taken']}/{r['phases']} ({pct}) "
              f"passed={a['passed']} n/a={a['not_applicable']}")
        if r["unresolved"]:
            print(f"      UNRESOLVED ids (advice will render raw): "
                  f"{', '.join(r['unresolved'][:5])}")
        print(f"      open first: turns {r['moments'] or '-'}")
        print(f"      full text: {os.path.relpath(r['cache'], _HERE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
