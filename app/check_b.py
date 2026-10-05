"""Check B: does an opponent's measured growth rate predict their next sighting?

The tracker proposal (§4 of analysis/REPLAY_LEARNING.md) rests on being able to
say "they were X at turn 7, so expect Y now". With 2-3 sightings per seat that
is a claim about EXTRAPOLATION, and the probe that measured the spread already
suggested it would be weak (spread 9.2 > median gain 7.0). This asks the
question directly and, importantly, against a fair baseline.

The prior is pessimistic, so the framing matters: a straight-line fit is one
candidate, not the standard. Competing answers to "what will their next board
be?" are:

  * LAST SEEN      — assume no change at all (the naive but strong baseline:
                     a board often does not change much between sightings)
  * LOBBY MEDIAN   — the median of every seat's latest stat total, i.e. ignore
                     this opponent entirely
  * RATE x dt      — the tracker: their own two most recent sightings, linearly
                     extrapolated to the target turn
  * MEAN RATE      — their own rate, but pooled with every other seat's rate
                     (a shrinkage check: is the per-seat rate carrying
                     information the pooled rate does not?)

MAE is reported per candidate; a projection earns its place only by beating
LAST SEEN, since that costs nothing to compute.

Usage:
  python check_b.py            # all archived logs
"""
import glob
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import HS_LOG_GLOB
from extract_game import split_game_chunks, extract_game, _friendly_player
import live_coach
import lobby


class HistoryScout(lobby.LobbyScout):
    """Keeps every resolved observation per seat instead of only the latest.

    `seats` overwrites, so the trajectory has to be captured as it is resolved.
    This is the same shape Step 1 of the tracker would persist.
    """

    def __init__(self):
        super().__init__()
        self.history = {}          # seat -> [(turn, stats, n)]

    def resolve_completed(self, cur_turn, pairing, friendly):
        # read the stats for the rounds about to be consumed
        pending = {}
        for t, rec in list(self._rounds.items()):
            if t in self._resolved or t >= cur_turn:
                continue
            board, _g, _h, stats, counts = self._opp_board(rec, friendly)
            if board is None or sum(board.values()) > 7:
                continue          # blended records carry no trustworthy total
            opp = next((c for c in stats if c != friendly), None)
            if opp is not None and stats.get(opp):
                pending[t] = (stats[opp], counts.get(opp))
        updated = super().resolve_completed(cur_turn, pairing, friendly)
        for t, seat in (pairing or {}).items():
            if t in pending and seat in updated:
                s, n = pending[t]
                self.history.setdefault(seat, []).append((t, s, n))
        return updated


def trajectories():
    """{game: {seat: [(turn, stats, n)]}} over the archived logs."""
    out = {}
    live_coach._GAME_DEFAULTS["_scout"] = HistoryScout
    for p in sorted(glob.glob(HS_LOG_GLOB)):
        lines = open(p, encoding="utf-8", errors="replace").readlines()
        sess = os.path.basename(os.path.dirname(p))
        for gi, (a, b) in enumerate(split_game_chunks(lines), 1):
            chunk = lines[a:b]
            g = extract_game(chunk)
            friendly = _friendly_player(g["heroes"], g.get("choice_players"))
            if friendly is None:
                continue
            coach = live_coach.LiveCoach()
            for i, line in enumerate(chunk):
                coach.feed(line)
                if i % 200 == 0:
                    coach.analyze()
            hist = {s: sorted(set(v)) for s, v in coach._scout.history.items()
                    if len(v) >= 2}
            if hist:
                out[(sess, gi)] = hist
    return out


def main():
    trajs = trajectories()
    n_seats = sum(len(h) for h in trajs.values())
    lens = [len(v) for h in trajs.values() for v in h.values()]
    print(f"== Check B: can a seat's own growth rate predict its next sighting? "
          f"==\n")
    print(f"games with a multi-sighting seat: {len(trajs)}")
    print(f"seats with 2+ sightings: {n_seats}")
    print(f"sightings per seat: {sorted(lens)}")
    print(f"seats with 3+ (a rate AND a target): {sum(1 for x in lens if x >= 3)}")

    # ---- the backtest: fit on the first two sightings, predict the third ----
    errs = {"last_seen": [], "lobby_median": [], "rate": [], "mean_rate": []}
    all_rates = []
    for h in trajs.values():
        for seat, obs in h.items():
            for i in range(2, len(obs)):
                t1, s1, _ = obs[i - 2]
                t2, s2, _ = obs[i - 1]
                t3, s3, _ = obs[i]
                dt = t2 - t1
                if dt <= 0 or t3 <= t2:
                    continue
                rate = (s2 - s1) / dt
                all_rates.append(rate)
                horizon = t3 - t2
                errs["last_seen"].append(abs(s2 - s3))
                errs["rate"].append(abs(s2 + rate * horizon - s3))
                # the lobby at the target turn: every seat's latest value at
                # or before t3, from THIS game only
                vals = [v for o in h.values() for (t, v, _n) in o if t <= t3]
                if vals:
                    errs["lobby_median"].append(
                        abs(st.median(vals) - s3))

    pooled = st.mean(all_rates) if all_rates else 0.0
    print(f"\npooled mean rate: {pooled:+.1f} stats/turn "
          f"(from {len(all_rates)} fitted rates)")

    # mean-rate candidate needs a second pass with the pooled value known
    for h in trajs.values():
        for seat, obs in h.items():
            for i in range(2, len(obs)):
                t1, s1, _ = obs[i - 2]
                t2, s2, _ = obs[i - 1]
                t3, s3, _ = obs[i]
                if t2 - t1 <= 0 or t3 <= t2:
                    continue
                errs["mean_rate"].append(
                    abs(s2 + pooled * (t3 - t2) - s3))

    print(f"\n{'candidate':16} {'n':>4} {'MAE':>8} {'median AE':>10}")
    for k in ("last_seen", "lobby_median", "mean_rate", "rate"):
        e = errs[k]
        if e:
            print(f"{k:16} {len(e):4} {st.mean(e):8.1f} {st.median(e):10.1f}")
    n_rate = len(errs["rate"])
    if n_rate < 10:
        # Say this loudly. The numbers above read like a finding and are not:
        # a rate needs THREE sightings (two to fit, one to test), the archived
        # games supply two such seats, and a blended sighting is unusable —
        # which leaves one. Reporting an MAE off n=2 as a conclusion would be
        # exactly the "one game is an anecdote however loud" failure this
        # project keeps catching.
        print(f"\n   UNDERPOWERED — n={n_rate}. The candidates above are "
              f"ILLUSTRATIVE, not a result:\n   a rule needs three sightings per "
              f"seat and only "
              f"{sum(1 for x in lens if x >= 3)} seat(s) here have them.")
    elif errs["rate"] and errs["last_seen"]:
        gain = st.mean(errs["last_seen"]) - st.mean(errs["rate"])
        print(f"\nthe rate projection is {gain:+.1f} MAE vs no-change "
              f"({'BETTER' if gain > 0 else 'WORSE'})")

    # ---- the question the data CAN answer --------------------------------
    # The predictor is unusable: 3 sightings per seat is required (two to fit a
    # rate, one to test it) and the archived games supply TWO seats that
    # qualify — one of which is blended and unusable. So the backtest above has
    # n=2 and says nothing. What the data does support is the maintainer's
    # actual intuition — "it's turn 10 and they're on Unbound Tempest, so
    # they've probably been growing" — which asks whether a seat's stat total
    # is predicted by the TURN at all, with 25 observations rather than 2.
    print("\n== is a seat's stat total predicted by the turn? ==")
    pts = [(t, s) for h in trajs.values() for obs in h.values()
           for (t, s, _n) in obs]
    print(f"   {len(pts)} sightings across {len(all_rates) + len(pts)} pairs")
    if len(pts) > 3:
        ts = [t for t, _ in pts]
        ss = [s for _, s in pts]
        mt, ms = st.mean(ts), st.mean(ss)
        denom = sum((t - mt) ** 2 for t in ts)
        slope = (sum((t - mt) * (s - ms) for t, s in pts) / denom
                 if denom else 0.0)
        # how much of the variance does the turn explain?
        pred = [ms + slope * (t - mt) for t in ts]
        sse = sum((s - p) ** 2 for s, p in zip(ss, pred))
        sst = sum((s - ms) ** 2 for s in ss)
        r2 = 1 - sse / sst if sst else 0.0
        print(f"   slope {slope:+.1f} stats per turn; R^2 = {r2:.2f} "
              f"(so the turn explains {100 * r2:.0f}% of the spread)")
        resid = st.pstdev([s - p for s, p in zip(ss, pred)])
        print(f"   residual spread: {resid:.0f} stats — a point projection "
              f"from the turn alone\n   would be wrong by roughly that much, "
              f"against boards whose totals run "
              f"{min(ss)}-{max(ss)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
