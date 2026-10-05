#!/usr/bin/env python3
"""Is the DAMAGE we take on a loss predictable?

WHY THIS IS THE MISSING HALF

The reshaped target the maintainer asked for is not "will I lose" but "how bad
will it be" — P(win) / P(tie) / P(loss) with the damage spread across it, since
"at least not full damage" is the band that decides whether a risky turn is
survivable. `fight_model.py` answered P(loss). This asks whether the DAMAGE on
those losses can be called too.

GROUND TRUTH, AND A REAL FORMULA TO TEST AGAINST

Battlegrounds loss damage is their tavern tier plus their surviving minions,
capped per round by `BACON_COMBAT_DAMAGE_CAP` (the escalating 2/5/10/15 the
coach already tracks as `analysis.damage_cap`). That is a stated mechanic, so it
can be checked against the log rather than guessed at — and the opponent's
surviving minions are recoverable, because the combat window stages their board
and the teardown shows what lived.

The two obvious errors in modelling it are both worth measuring:

  * assuming the cap is always reached (the pessimistic read — "any loss costs
    the cap")
  * assuming the cap is never reached (the optimistic read)

Whatever sits between those two is the honest spread, and it is what makes
P(damage < cap) answerable at all.

Usage:
  python damage_model.py
"""
import argparse
import glob
import os
import statistics as st
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import HS_LOG_GLOB
from extract_game import split_game_chunks
import fight_table


def rows():
    out = []
    for p in sorted(glob.glob(HS_LOG_GLOB), key=os.path.getmtime):
        if time.time() - os.path.getmtime(p) < 1800:
            continue
        lines = open(p, encoding="utf-8", errors="replace").readlines()
        sess = os.path.basename(os.path.dirname(p))
        for gi, (s, e) in enumerate(split_game_chunks(lines), 1):
            out += fight_table.rows_for(lines[s:e], sess, gi)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    rs = rows()
    losses = [r for r in rs if (r.get("damage") or 0) > 0]
    wins = [r for r in rs if r["lost"] is False]
    print("== the damage on a lost fight ==")
    print(f"   {len(rs)} advisories; {len(losses)} with damage > 0; "
          f"{len(wins)} fights not lost")

    if not losses:
        print("no losses in the sample")
        return 1
    dmg = [r["damage"] for r in losses]
    caps = [r.get("damage_cap") for r in losses if r.get("damage_cap")]
    print(f"\n   damage taken: {sorted(dmg)}")
    print(f"   mean {st.mean(dmg):.1f}  median {st.median(dmg):.1f}  "
          f"min {min(dmg)}  max {max(dmg)}")

    # ---- the two straw men -------------------------------------------------
    if caps:
        at_cap = sum(1 for r in losses
                     if r.get("damage_cap") and r["damage"] >= r["damage_cap"])
        print(f"\n   cap reached on {at_cap} of {len(losses)} losses "
              f"({100 * at_cap / len(losses):.0f}%)")
        print(f"   -> 'a loss always costs the cap' would be wrong "
              f"{100 * (1 - at_cap / len(losses)):.0f}% of the time")
        below = [r["damage"] for r in losses
                 if r.get("damage_cap") and r["damage"] < r["damage_cap"]]
        if below:
            print(f"   -> when below the cap, damage was "
                  f"{sorted(below)} (mean {st.mean(below):.1f})")
        capped = [r["damage"] for r in losses
                  if r.get("damage_cap") and r["damage"] >= r["damage_cap"]]
        if capped:
            print(f"   -> when at the cap: {sorted(capped)}")

    # ---- is it predicted by the ATTACKER's board? --------------------------
    # A bigger surviving board hits harder; the damage formula is
    # their tier + their survivors, so their pre-fight board SIZE should
    # correlate with the damage even though the fight's outcome does not.
    print("\n   their pre-fight board vs the damage we took:")
    pairs = [(len(r["their_board"] or []), r["damage"]) for r in losses]
    pairs = [(n, d) for n, d in pairs if n]
    if len(pairs) > 3:
        ns = sorted({n for n, _ in pairs})
        for n in ns:
            ds = [d for m, d in pairs if m == n]
            print(f"     {n} minions staged: n={len(ds):2}  damage "
                  f"{sorted(ds)}")
        # a crude rank correlation, stdlib only
        ranks_x = _ranks([n for n, _ in pairs])
        ranks_y = _ranks([d for _, d in pairs])
        rho = _pearson(ranks_x, ranks_y)
        print(f"\n     Spearman rho (staged minions vs damage): {rho:+.2f}")
        print("     (their staged count is the pre-fight board, which is the "
              "number a\n     real formula would use — survivors are only "
              "knowable after the fight)")

    # ---- the band the maintainer actually asked for -----------------------
    if caps:
        print("\n   P(damage < cap | lost) — the 'not full damage' band:")
        less = sum(1 for r in losses
                   if r.get("damage_cap") and r["damage"] < r["damage_cap"])
        tot = sum(1 for r in losses if r.get("damage_cap"))
        if tot:
            print(f"     {less}/{tot} = {100 * less / tot:.0f}% of losses "
                  f"stay under the cap")
    if args.json:
        import json
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(losses, f)
        print(f"\nwritten: {args.json}")
    return 0


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def _pearson(a, b):
    if len(a) < 2:
        return 0.0
    ma, mb = st.mean(a), st.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0


if __name__ == "__main__":
    sys.exit(main())
