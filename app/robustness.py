#!/usr/bin/env python3
"""Robustness of the two numbers the plan now rests on.

TWO QUESTIONS, BOTH ABOUT OVER-CONFIDENCE

1. `fight_model.py` reported AUC 0.78 for the stat ratio on 48 rows across 5
   games. Five games is a small number of clusters, and a single lucky game can
   carry a ranking. A bootstrap over GAMES (not rows) says how much of that
   0.78 is stable. Resampling rows would be the wrong move: rows inside a game
   share a hero, an opponent pool and a run of luck, so a row bootstrap
   reports a precision the data cannot support.

2. The shipped rule uses fixed ratio thresholds — 1.3 for "favored", 0.8 for
   "close". If the ratio ranks fights at 0.78 AUC and the rule that consumes it
   scores 57%, the thresholds may simply be in the wrong place. Two reference
   points make that decidable:

     * the BEST achievable single-threshold rule on this data (a threshold
       sweep), which is the fair upper bound for the shipped design
     * the MAJORITY-CLASS constant, which is what any rule must beat

   If a swept threshold beats the constant comfortably, the shipped 1.3/0.8 are
   the problem. If even the best threshold cannot, then no amount of
   threshold-tuning fixes it and the probability output is the only honest
   option.

Usage:
  python robustness.py
"""
import glob
import os
import random
import statistics as st
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import HS_LOG_GLOB
from extract_game import split_game_chunks
import fight_model
import fight_table


def dataset():
    rows = []
    for p in sorted(glob.glob(HS_LOG_GLOB), key=os.path.getmtime):
        if time.time() - os.path.getmtime(p) < 1800:
            continue
        lines = open(p, encoding="utf-8", errors="replace").readlines()
        sess = os.path.basename(os.path.dirname(p))
        for gi, (s, e) in enumerate(split_game_chunks(lines), 1):
            rows += fight_table.rows_for(lines[s:e], sess, gi)
    usable = []
    for r in rows:
        x = fight_model.features_of(r)
        if x is None or r.get("lost") is None:
            continue
        usable.append((r, x))
    return usable


def main():
    random.seed(20261005)
    usable = dataset()
    games = sorted({(r["session"], r["game"]) for r, _ in usable})
    by_game = {g: [(r, x) for r, x in usable
                   if (r["session"], r["game"]) == g] for g in games}
    print(f"== robustness of the ratio's AUC ==")
    print(f"   {len(usable)} rows over {len(games)} games")

    # ---- bootstrap over GAMES ---------------------------------------------
    # 200 resamples, not 2000: each one refits a leave-one-game-out model, and
    # the point of the exercise is the WIDTH of the interval, which 200
    # estimates adequately.
    aucs = []
    for _ in range(200):
        sample = []
        for _g in games:
            pick = random.choice(games)          # resample games, not rows
            sample += by_game[pick]
        if not sample:
            continue
        pairs = []
        for held in games:
            train = [([x[0]], 1.0 if r["lost"] else 0.0)
                     for r, x in sample if (r["session"], r["game"]) != held]
            test = [(r, x) for r, x in sample
                    if (r["session"], r["game"]) == held]
            if not train or not test:
                continue
            w = fight_model.fit(train, epochs=200, lr=0.5, l2=0.05)
            for r, x in test:
                pairs.append((fight_model.predict(w, [x[0]]), bool(r["lost"])))
        a = fight_model._auc(pairs)
        if a == a:                                # skip NaN
            aucs.append(a)
    if aucs:
        aucs.sort()
        lo = aucs[int(0.025 * len(aucs))]
        hi = aucs[int(0.975 * len(aucs)) - 1]
        print(f"\n   game-bootstrap AUC over {len(aucs)} resamples:")
        print(f"     median {st.median(aucs):.2f}   95% interval "
              f"[{lo:.2f}, {hi:.2f}]")
        print(f"     fraction of resamples above 0.50: "
              f"{sum(1 for a in aucs if a > 0.5) / len(aucs):.0%}")
        if lo <= 0.5:
            print("     -> the interval CROSSES 0.50: with 5 games the ratio's "
                  "signal is\n        not established beyond doubt, however "
                  "good the point estimate looks.")

    # ---- the threshold sweep ---------------------------------------------
    print("\n== is the shipped rule mis-tuned, or is the design wrong? ==")
    pts = [(r["our_stats"], r["their_stats"], bool(r["lost"]))
           for r, _x in usable
           if r.get("our_stats") and r.get("their_stats")]
    if not pts:
        return 1
    print(f"   {len(pts)} rows with both sides of the ratio")
    base = sum(1 for _a, _b, y in pts if not y) / len(pts)
    print(f"   constant (never lost): {base:.0%} accuracy")

    # sweep a single threshold: below it predict 'lost'
    best = None
    for i in range(40, 200):
        thr = i / 100.0
        right = sum(1 for a, b, y in pts
                    if ((a / max(b, 1)) < thr) == y)
        acc = right / len(pts)
        if best is None or acc > best[1]:
            best = (thr, acc)
    print(f"   best single threshold on this data: ratio < {best[0]:.2f} "
          f"-> {best[1]:.0%}")
    # the shipped pair, scored the same way
    for a_thr, b_thr, name in ((1.3, 0.8, "shipped 1.3/0.8 (behind < 0.8)"),):
        right = sum(1 for a, b, y in pts
                    if ((a / max(b, 1)) < b_thr) == y)
        print(f"   {name:34} {(right / len(pts)):5.0%} "
              f"(as a single threshold at <{b_thr})")
    print(f"\n   -> the BEST a threshold can do is {best[1]:.0%} against a "
          f"constant of {base:.0%}.")

    # ---- what the ratio orders vs what the thresholds discard -------------
    # The sweep is thresholded; the model is not. The gap between the best
    # threshold and the ratio's AUC is the information the BINNING costs.
    pairs = []
    for held in games:
        train = [([x[0]], 1.0 if r["lost"] else 0.0)
                 for r, x in usable if (r["session"], r["game"]) != held]
        test = [(r, x) for r, x in usable if (r["session"], r["game"]) == held]
        if not train or not test:
            continue
        w = fight_model.fit(train, epochs=400, lr=0.5, l2=0.05)
        for r, x in test:
            pairs.append((fight_model.predict(w, [x[0]]), bool(r["lost"])))
    auc = fight_model._auc(pairs)
    print(f"\n   the untresholded ratio orders fights at AUC {auc:.2f}")
    print(f"   the best THRESHOLD on it reaches {best[1]:.0%} accuracy "
          f"(constant {base:.0%})")
    print("   -> thresholding a well-ordered signal can still lose to a "
          "constant; the\n      information is in the ordering, which a "
          "verdict throws away.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
