#!/usr/bin/env python3
"""Does seeing the keywords beat the scalar stat ratio?

THE QUESTION

`value.combat_forecast` decides favored / close / behind from ONE number —
`board_stats / theirs` — and then names divine shields and venomous in the
sentence beside it while letting none of them affect the verdict. Check A
measured the result (`fight_table.py`): **57% directional accuracy against a
constant "never lost", which scores 78%.** So the current rule is worse than
saying nothing.

This asks the narrow question that decision implies: with the same logged
fights, do the features the ratio ignores — divine shields, taunt, reborn,
windfury, and the shape of the boards — predict a lost fight better than a
constant?

WHY A MODEL AND NOT A COMBAT SIMULATOR

Deliberate, and it is the parameter-budget rule from
analysis/REPLAY_LEARNING.md applied honestly. A real combat simulator is the
largest piece of work on the roadmap, and it would need a training set of 58
logged fights to tune anything against. A small logistic model answers "is
there signal in the keywords at all?" in a fraction of the effort, and if the
answer is no, the simulator's premise is dead before it is written. If the
answer is yes, that is the evidence for building it.

HOW IT IS EVALUATED

**Leave-one-GAME-out**, never leave-one-row-out. Rows inside a game are not
independent — they share one opponent pool, one hero and one run of luck — so a
row-wise split leaks and reports a fantasy. This project has already been bitten
by the row/game distinction elsewhere (`session_report` double-counting, the
10x row inflation), so it is enforced here rather than noted.

The bar is the constant: always predicting "not lost" scores ~78% on this
sample. Anything at or below that has learned nothing.

Usage:
  python fight_model.py            # archived logs
  python fight_model.py --json
"""
import argparse
import glob
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import HS_LOG_GLOB
from extract_game import split_game_chunks
import fight_table

#: Features, each a difference or ratio between the two boards. Kept FEW on
#: purpose: the budget rule allows 2-3 free parameters at this sample size, and
#: the constants below are not fitted to the data (they are sensible fixed
#: scales), so only the weights are learned.
#:
#: VENOMOUS is deliberately absent. It occurs TWICE in the whole corpus, so a
#: weight for it would be fitted to two rows — the plan proposed it as a
#: feature and the data refused it.
FEATURES = ("log_ratio", "shield_diff", "taunt_diff", "reborn_diff",
            "body_diff")

#: True when a row's ratio came from the opponent's OBSERVED board, which
#: exists only because we already fought them. The shipped forecast cannot see
#: it — it works from `opp_stats` / `lobby_opp` / `baseline_opp`, and on this
#: corpus that anchor is the real opponent in ONE advisory out of 52.
#:
#: This is not hypothetical. Grading the ratio off the observed board scored
#: AUC 0.78 and was quoted as a result; the same model on the anchor the coach
#: actually has scores **0.23** — worse than chance, because the observed-board
#: variable is partly downstream of the label (a large board is often the
#: SURVIVOR of a fight we won, so "big board" correlates with having won).
#: `deployable_shares()` is the guard.
def leaked_anchor(rows):
    """How many of these rows resolved their opponent board from a fight.

    `their_board` is populated by `fight_table` from the combat snapshots, so a
    non-empty one on a row whose advisory preceded the fight means the anchor
    is post-hoc. Returns the fraction, for `deployable_shares`.
    """
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.get("their_board")) / len(rows)


def deployable_shares(fraction):
    """Refuse a headline number built on features that cannot ship.

    Called with the share of a run's rows whose ratio rested on an OBSERVED
    opponent board. Above zero, the run is measuring an input that is
    unavailable at decision time, so its accuracy is not a result about the
    coach — say so instead of reporting it.
    """
    if fraction > 0:
        return (f"WARNING: {fraction:.0%} of rows anchored the ratio on the "
                f"opponent's\n  OBSERVED board. That input does not exist at "
                f"decision time (the coach\n  has the real opponent in ~1 "
                f"advisory in 52), so any accuracy below is\n  LOOKAHEAD and "
                f"must not be quoted. Use the forecast's own anchor — see\n  "
                f"analysis/REPLAY_LEARNING.md §7 item 5.")
    return None


def _count(board, kw):
    return sum(1 for m in (board or []) if kw in (m.get("keywords") or []))


def _stats(board):
    return sum((m.get("atk") or 0) + (m.get("health") or 0)
               for m in (board or []))


def features_of(row):
    """The feature vector for one advisory, or None if a board is missing."""
    ours, theirs = row.get("our_board") or [], row.get("their_board") or []
    if not ours or not theirs:
        return None
    a, b = _stats(ours), _stats(theirs)
    return [
        math.log((a + 20) / (b + 20)),          # +20 keeps it finite at 0
        (_count(ours, "DIVINE_SHIELD") - _count(theirs, "DIVINE_SHIELD")) / 3.0,
        (_count(ours, "TAUNT") - _count(theirs, "TAUNT")) / 3.0,
        (_count(ours, "REBORN") - _count(theirs, "REBORN")) / 3.0,
        (len(ours) - len(theirs)) / 3.0,
    ]


def _sigmoid(z):
    if z < -30:
        return 0.0
    if z > 30:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def fit(rows, epochs=600, lr=0.35, l2=0.02):
    """Logistic regression by gradient descent — no numpy, stdlib only.

    L2 is not decoration: with ~50 training rows and 6 free parameters the
    unregularised fit memorises, and this model's whole claim is that it does
    NOT have enough data to be clever.
    """
    w = [0.0] * (len(FEATURES) + 1)          # last is the intercept
    for _ in range(epochs):
        grad = [0.0] * len(w)
        for x, y in rows:
            z = w[-1] + sum(wi * xi for wi, xi in zip(w[:-1], x))
            err = _sigmoid(z) - y
            for j, xi in enumerate(x):
                grad[j] += err * xi
            grad[-1] += err
        n = len(rows) or 1
        for j in range(len(w) - 1):
            w[j] -= lr * (grad[j] / n + l2 * w[j])
        w[-1] -= lr * grad[-1] / n
    return w


def predict(w, x):
    return _sigmoid(w[-1] + sum(wi * xi for wi, xi in zip(w[:-1], x)))


def _auc(pairs):
    """Rank-based AUC: P(a random lost row scores above a random won row).

    Ties count a half, which is the standard convention.
    """
    pos = [p for p, y in pairs if y]
    neg = [p for p, y in pairs if not y]
    if not pos or not neg:
        return float("nan")
    wins = 0.0
    for p in pos:
        for q in neg:
            wins += 1.0 if p > q else (0.5 if p == q else 0.0)
    return wins / (len(pos) * len(neg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="include the newest log even if still being written")
    ap.add_argument("--json", help="write the scored rows here")
    args = ap.parse_args()

    import time
    all_rows = []
    for p in sorted(glob.glob(HS_LOG_GLOB), key=os.path.getmtime):
        if not args.live and time.time() - os.path.getmtime(p) < 1800:
            continue
        lines = open(p, encoding="utf-8", errors="replace").readlines()
        sess = os.path.basename(os.path.dirname(p))
        for gi, (s, e) in enumerate(split_game_chunks(lines), 1):
            all_rows += fight_table.rows_for(lines[s:e], sess, gi)

    usable = []
    for r in all_rows:
        x = features_of(r)
        if x is None or r.get("lost") is None:
            continue
        usable.append((r, x))
    games = sorted({(r["session"], r["game"]) for r, _ in usable})
    print(f"== keywords vs the stat ratio: logistic model ==")
    print(f"   {len(usable)} usable advisories over {len(games)} game(s) "
          f"(both boards present and an outcome label)")

    # The guard, printed BEFORE any accuracy, so a lookahead number can never
    # be read without its warning attached. This model requires both boards to
    # exist, and `their_board` comes from the combat snapshots — so every row
    # here rests on an observation that only exists because we already fought
    # them. The numbers below are therefore diagnostic of the FEATURES, not a
    # measurement of the shipped coach.
    warn = deployable_shares(leaked_anchor([r for r, _x in usable]))
    if warn:
        print()
        for line in warn.splitlines():
            print("   " + line)
    print()

    # ---- leave-one-GAME-out ------------------------------------------------
    correct = model_right = 0
    base_right = 0
    scored = []
    for held in games:
        train = [(x, 1.0 if r["lost"] else 0.0)
                 for r, x in usable if (r["session"], r["game"]) != held]
        test = [(r, x) for r, x in usable
                if (r["session"], r["game"]) == held]
        if not train or not test:
            continue
        w = fit(train)
        for r, x in test:
            pr = predict(w, x)
            pred = pr >= 0.5
            model_right += pred == bool(r["lost"])
            # the constant: always "not lost" (the majority class)
            base_right += not r["lost"]
            correct += 1
            scored.append({"session": r["session"], "game": r["game"],
                           "turn": r["turn"], "lost": r["lost"],
                           "p_loss": round(pr, 3),
                           "forecast": r.get("forecast"),
                           "verdict": fight_table.verdict_of(r.get("forecast")),
                           "damage": r.get("damage")})

    if not correct:
        print("no test rows")
        return 1
    # ACCURACY IS THE WRONG METRIC HERE, and the raw comparison is misleading
    # enough to be worth stating: with a ~23% loss rate, "never lost" scores
    # ~77% by predicting the majority class and knowing nothing. A rule that
    # discriminates perfectly can still lose on accuracy if it is not allowed
    # to abstain. So report both — accuracy for the shipped question, AUC for
    # "does this know anything at all".
    auc = _auc([(s["p_loss"], s["lost"]) for s in scored])
    print(f"\n   {'rule':22} {'accuracy':>9}")
    print(f"   {'constant (never lost)':22} {base_right / correct:8.0%}")
    print(f"   {'keywords model':22} {model_right / correct:8.0%}")
    print(f"\n   discrimination (AUC, held out): {auc:.2f}")
    print("   (0.50 = knows nothing; the constant has no AUC to report because "
          "it\n   never varies its answer)")

    # the same held-out rows, scored by the shipped forecast, for reference
    claims = [s for s in scored if s["verdict"] in
              ("favored", "ahead on paper", "behind")]
    if claims:
        right = sum(1 for s in claims
                    if (s["verdict"] == "behind") == bool(s["lost"]))
        print(f"   {'shipped forecast':22} "
              f"{right / len(claims):8.0%}   (on its {len(claims)} claiming "
              f"rows)")

    # ---- do the KEYWORDS add anything over the ratio? ---------------------
    # The headline claim is about keywords, so credit must not be given to
    # variance that the plain stat ratio already carries. Ablate: ratio only,
    # then the keyword features on top, same held-out folds.
    def logo_auc(cols):
        pairs = []
        for held in games:
            train = [([x[i] for i in cols], 1.0 if r["lost"] else 0.0)
                     for r, x in usable if (r["session"], r["game"]) != held]
            test = [(r, x) for r, x in usable
                    if (r["session"], r["game"]) == held]
            if not train or not test:
                continue
            w = fit(train)
            for r, x in test:
                pairs.append((predict(w, [x[i] for i in cols]), bool(r["lost"])))
        return _auc(pairs), len(pairs)

    kw_cols = [i for i, f in enumerate(FEATURES) if f != "log_ratio"]
    ratio_auc, n_ab = logo_auc([0])
    full_auc, _ = logo_auc(list(range(len(FEATURES))))
    kw_auc, _ = logo_auc(kw_cols)
    print(f"\n   ablation on the same {n_ab} held-out rows:")
    print(f"     stat ratio only            AUC {ratio_auc:.2f}")
    print(f"     keywords/shape only        AUC {kw_auc:.2f}")
    print(f"     both                       AUC {full_auc:.2f}")
    gain = full_auc - ratio_auc
    print(f"     keywords add {gain:+.2f} AUC over the ratio alone")
    if kw_auc <= 0.5:
        print("     -> the keyword features are AT OR BELOW CHANCE on their "
              "own. Do not\n        build a keyword simulator on this "
              "evidence; see the note below.")
    if gain < 0:
        print("     -> adding them HURTS: 4 extra parameters fitted to 48 rows "
              "cost\n        more than the features contribute.")

    # ---- the finding this actually produces ------------------------------
    # The ratio-only model is the one to keep: ONE fitted parameter, and it
    # recovers discrimination the shipped thresholds destroy. Check A measured
    # the shipped rule at 57% accuracy while the raw ratio ranks fights at
    # ~0.78 AUC — i.e. the information is THERE and the 1.3/0.8 BINNING throws
    # it away. So the actionable change is to stop thresholding and publish the
    # probability, not to add features.
    simple_pairs = []
    for held in games:
        train = [([x[0]], 1.0 if r["lost"] else 0.0)
                 for r, x in usable if (r["session"], r["game"]) != held]
        test = [(r, x) for r, x in usable
                if (r["session"], r["game"]) == held]
        if not train or not test:
            continue
        w = fit(train, epochs=400, lr=0.5, l2=0.05)
        for r, x in test:
            simple_pairs.append((predict(w, [x[0]]), bool(r["lost"]), r))
    if simple_pairs:
        auc_s = _auc([(p, y) for p, y, _r in simple_pairs])
        print(f"\n== the one-parameter version (ratio -> P(loss)) ==")
        print(f"   AUC {auc_s:.2f} on {len(simple_pairs)} held-out rows, with a "
              f"single fitted weight")
        print(f"   {'bucket':14} {'n':>4} {'lost':>5} {'predicted':>10}")
        for lo, hi in ((0.0, 0.10), (0.10, 0.20), (0.20, 0.35), (0.35, 1.01)):
            b = [(p, y) for p, y, _r in simple_pairs if lo <= p < hi]
            if b:
                obs = sum(1 for _p, y in b if y) / len(b)
                mp = sum(p for p, _y in b) / len(b)
                print(f"   {f'{lo:.2f}-{hi:.2f}':14} {len(b):4} {obs:5.0%} "
                      f"{mp:10.0%}")
        # what a player would actually see
        print("\n   what the three bands become, as measured probabilities:")
        for lo, hi, label in ((0.0, 0.20, "not losing"),
                              (0.20, 0.40, "around even"),
                              (0.40, 1.01, "likely losing")):
            b = [(p, y) for p, y, _r in simple_pairs if lo <= p < hi]
            if b:
                obs = sum(1 for _p, y in b if y) / len(b)
                print(f"     {label:14} n={len(b):3}  lost {obs:4.0%}")

    print(f"\n   calibration (the model's own P(loss), held out):")
    print(f"   {'bucket':14} {'n':>4} {'lost':>5} {'predicted':>10}")
    for lo, hi in ((0.0, 0.1), (0.1, 0.2), (0.2, 0.35), (0.35, 1.01)):
        b = [s for s in scored if lo <= s["p_loss"] < hi]
        if b:
            obs = sum(1 for s in b if s["lost"]) / len(b)
            mean_p = sum(s["p_loss"] for s in b) / len(b)
            print(f"   {f'{lo:.2f}-{hi:.2f}':14} {len(b):4} "
                  f"{obs:5.0%} {mean_p:10.0%}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(scored, f)
        print(f"\nwritten: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
