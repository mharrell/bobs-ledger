#!/usr/bin/env python3
"""The fight table: every combat as a labelled training example.

WHAT THIS IS FOR

The coach forecasts each buy phase from a SCALAR stat ratio
(`combat_forecast`, value.py:3298) — board_stats over the opponent's total,
thresholded at 1.3 ("favored") and 0.8 ("close"). Those two thresholds have
never been measured against outcomes, and the ratio itself cannot see what
fights actually turn on: a divine shield absorbs a hit, a venomous minion
removes one, attack order decides who trades first. So the point of this table
is to put a NUMBER on what the current approach achieves before anything
replaces it. That number is the baseline a simulator must beat; without it,
"the new thing is better" is an opinion.

ONE ROW PER BUY PHASE — not per snapshot. A buy phase produces dozens of
advisories, so sampling them all would inflate n by roughly 10x and every
p-value with it. The advice is read once per phase, at the settled shop, the
same way `replay_review` does it.

Row fields:

  turn, tier, gold, health    the state at the advisory
  our_stats, their_stats      the two sides of the ratio it used
  their_board, our_board      structured (card, atk, hp, golden, keywords)
  forecast                    the verdict string it published
  lost, damage                the outcome

THE OUTCOME IS DERIVED INDEPENDENTLY, which is the point. `lost` comes from the
friendly hero's PREDAMAGE writes: the code's own rule is "the winner takes 0"
(ties take 0 too), so a positive predamage is an unambiguous LOSS
(`live_coach._predamage_turns`). Grading against `outcome_audit` would not do:
it compares coach-recorded HP at phase N to coach-recorded HP at phase N+1, so
one parser sits on both sides and a health bug moves both together.

KNOWN LIMIT OF THE LABEL: a win and a tie are NOT distinguishable from the
predamage flag alone — neither wins nor ties cost health. Measured over 67
fights, `PREDAMAGE > 0` is exactly (damage taken) UNION (tie): 18 had both, 4
had predamage with no health change, and ZERO had damage without predamage. So
`lost` is defined as DAMAGE TAKEN (from the health writes), and ties are
flagged separately rather than counted as losses.

Usage:
  python fight_table.py                    # every archived session log
  python fight_table.py --json out.json
  python fight_table.py PATH [PATH ...]
"""
import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import HS_LOG_GLOB
from extract_game import split_game_chunks, extract_game, _friendly_player
import live_coach

#: Lines without a new offer set = the options block is fully printed, so this
#: is the settled shop the live loop advises on (replay_review SETTLE).
SETTLE = 20


def _their_board(coach, turn, friendly):
    """The opponent's staged board for the fight that follows buy phase `turn`.

    Mirrors `_resolve_boards`' selection rule — the snapshot with the most
    opponent presence, since combat reveals their board progressively and
    deaths empty it, so the fullest view is the honest estimate — but keeps the
    STRUCTURE instead of summing it away. Snapshots are 6-tuples since the
    projection widening: (player, card, atk, health, golden, keywords).

    Prefers combat-phase snapshots (the real fight boards); buy-phase snapshots
    are shop plays and the previous fight's teardown remnants, and are only
    used when a turn staged nothing in combat.
    """
    allsnaps = coach._snap_by_turn.get(turn, [])
    snaps = [s for s in allsnaps if s.get("phase") == "combat"] or allsnaps
    best, best_total = [], -1
    for snap in snaps:
        opp = [m for m in snap.get("minions", [])
               if m[0] not in (friendly, None) and len(m) > 3]
        total = sum(m[2] + m[3] for m in opp)
        if total > best_total:
            best, best_total = opp, total
    return [{"card": m[1], "atk": m[2], "health": m[3],
             "golden": m[4], "keywords": list(m[5])} for m in best]


def _board(minions):
    """The coach's own board dicts as the same structure as `their_board`."""
    return [{"card": m.get("card"), "atk": m.get("atk") or 0,
             "health": m.get("health") or 0,
             "golden": bool(m.get("golden")),
             "keywords": list(m.get("keywords") or [])}
            for m in (minions or [])]


def fight_outcomes(chunk, hero_id):
    """{turn: {"lost": bool, "damage": int|None}} read from the LOG alone.

    Independent of the coach on purpose. The coach publishes per-turn damage
    (`analysis.damage_last`) computed from ITS OWN health series, and its
    `_predamage_turns` bucket is stamped when the stat log drains — which
    happens later for turns that arrive before the hero parses
    (`_stat_pending`), so the bucket index does not line up with a row's `turn`.
    Joining on those gave a table where 11 of 24 "losses" showed no damage and
    2 "wins" showed damage, i.e. the label and the damage described different
    fights.

    Here a turn is counted the same way the rows are: one per
    `tag=STEP value=MAIN_ACTION`. The window from that turn's `MAIN_END` to the
    next `MAIN_ACTION` is its combat. Damage taken is the change in
    (DAMAGE accumulated - ARMOR) across that window, which is true HP moving:
    the hero's HEALTH tag is the BASE and is never rewritten this season, so
    HEALTH alone says nothing (the 2026-09-08 Guff session read 30 all game
    while sitting at 19).
    """
    import re
    ent = (r"(?:Entity=%s\b|Entity=\[[^\]]*id=%s\b)" % (hero_id, hero_id))
    wr = re.compile(ent + r"[^\n]*?tag=(HEALTH|DAMAGE|ARMOR|PREDAMAGE) "
                          r"value=(-?\d+)")
    turn = 0
    in_buy = False
    dmg = armor = 0
    at_buy, at_end, lost = {}, {}, set()
    for line in chunk:
        if "GameState." in line:
            if "tag=STEP value=MAIN_ACTION" in line:
                if turn:
                    at_end[turn] = (dmg, armor)
                turn += 1
                in_buy = True
                at_buy[turn] = (dmg, armor)
            elif "tag=STEP value=MAIN_END" in line and in_buy:
                in_buy = False
        m = wr.search(line)
        if m:
            tag, v = m.group(1), int(m.group(2))
            if tag == "DAMAGE":
                dmg = v
            elif tag == "ARMOR":
                armor = v
            elif tag == "PREDAMAGE" and v > 0 and not in_buy:
                lost.add(turn)
    out = {}
    for t, (d0, a0) in at_buy.items():
        d1, a1 = at_end.get(t, (d0, a0))
        dmg = (d1 - a1) - (d0 - a0)
        # `lost` is DAMAGE TAKEN, which is the unambiguous reading. Measured
        # over 67 fights in the 5 archived games, PREDAMAGE>0 is exactly
        # (damage > 0) UNION (tie): 18 fights had both, 4 had predamage with
        # no health change at all, and ZERO had damage without predamage. So
        # predamage alone cannot tell a loss from a tie, and the damage
        # arithmetic can — which is why this reads the health writes rather
        # than the predamage flag.
        out[t] = {"lost": dmg > 0, "damage": dmg,
                  "tie": dmg == 0 and t in lost}
    return out


def rows_for(chunk, session, game_idx):
    """One row per advised buy phase, with the following fight's outcome."""
    game = extract_game(chunk)
    friendly = _friendly_player(game["heroes"], game.get("choice_players"))
    if friendly is None:
        return []
    hero = next((h for h in game["heroes"] if h["player"] == friendly), None)
    coach = live_coach.LiveCoach()
    rows = []
    turn = 0
    armed = False
    saw_offers = False
    prev_offers = None
    last_change = 0
    for i, line in enumerate(chunk):
        # analyze() on a cadence, like the live loop. This is not optional:
        # `friendly` is set only by analyze() -> _ensure_meta(), and
        # _scout.open_round is gated on it, so a whole-log feed with no
        # analyze() measures nothing at all (0 seats, 0 rounds — measured).
        if "GameState." in line and "tag=STEP value=MAIN_ACTION" in line:
            turn += 1
            armed = True
            saw_offers = False   # a new phase: do not fire before its shop
            prev_offers = None
            coach.analyze()
        coach.feed(line)
        if i % 200 == 0:
            coach.analyze()
        if not armed:
            continue
        offers = tuple(coach.tavern_offers())
        if not offers:
            continue             # options block not printed yet
        if offers != prev_offers:
            saw_offers = True
            prev_offers = offers
            last_change = i
            continue
        if not saw_offers or i - last_change < SETTLE:
            continue
        # the settled shop: this is where the live coach's advice would show
        a = coach.analyze()
        armed = False           # one row per buy phase
        if not a or not a.get("board_stats"):
            continue
        # PREDICTION ONLY. The fight this advice is about has not happened
        # yet, so the boards and the outcome are joined after the whole game
        # has been fed — reading them here would attach the PREVIOUS fight
        # (its snapshots are what exist at this moment), which silently
        # mislabels every row.
        rows.append({
            "session": session, "game": game_idx,
            "hero": (hero or {}).get("hero_name"),
            "placement": (hero or {}).get("place"),
            "turn": a.get("turn"), "tier": a.get("tier"),
            "gold": a.get("gold"),
            # `health` is ALREADY effective HP (HEALTH - DAMAGE; the code
            # subtracts the DAMAGE tag itself, live_coach.py:1393), so it is
            # true HP and not the base 30 the raw tag carries.
            "health": a.get("health"),
            "armor": a.get("armor"),
            # The per-round ceiling on ONE lost fight (BACON_COMBAT_DAMAGE_CAP,
            # escalating 2/5/10/15). Kept because P(damage < cap) is one of the
            # three bands the reshaped target has to report.
            "damage_cap": a.get("damage_cap"),
            "our_stats": a.get("board_stats"),
            # the anchor the forecast actually used, in its own preference
            # order (value.combat_forecast: fresh preview, then lobby, then
            # the corpus baseline)
            "their_stats": (a.get("opp_stats") or a.get("lobby_opp")
                            or a.get("baseline_opp")),
            "opp_age": a.get("opp_age"),
            "fresh": a.get("opp_stats") is not None,
            "forecast": a.get("forecast"),
            "our_board": _board(a.get("board")),
            "their_board": [],
            # what the plan asked for, so a later pass can score the advice
            "top_move_steps": a.get("top_move_steps") or [],
            "buy_this": a.get("buy_this"),
            "shop_rank": [list(e) if isinstance(e, (list, tuple)) else e
                          for e in (a.get("shop_rank") or [])],
            "lost": None, "damage": None, "tie": None,
        })
    # ---- the outcome join, after the whole game is fed ---------------------
    # Outcomes come from the LOG (`fight_outcomes`), not from the coach's
    # buckets, and they are joined on the row's own `turn`: the advisory at
    # buy phase k is about the fight fought during turn k.
    hero_id = (next((h.get("id") for h in game["heroes"]
                     if h["player"] == friendly), None))
    outcomes = fight_outcomes(chunk, hero_id) if hero_id else {}
    for r in rows:
        t = r.get("turn")
        r["their_board"] = _their_board(coach, t, friendly) if t else []
        o = outcomes.get(t)
        if o:
            r["lost"] = o["lost"]
            r["damage"] = o["damage"]
            r["tie"] = o["tie"]
    return rows


#: The verdicts `value.combat_forecast` can emit, in its own order.
VERDICTS = ("favored", "ahead on paper", "close fight", "behind")


def verdict_of(forecast):
    """The verdict class a forecast string encodes, or None.

    Parsed from the STRING rather than re-derived from the ratio, because the
    question here is what the player actually saw. Re-deriving would grade a
    reconstruction instead of the shipped advice — the same mistake
    `replay_review` documents for the opponent pairing.
    """
    if not forecast:
        return None
    for v in VERDICTS:
        if forecast.startswith(v):
            return v
    return None


def baseline_report(rows):
    """Check A: what does the current stat-ratio rule actually achieve?

    Established BEFORE anything replaces it. Without this number, "the new
    thing is better" is an opinion, and a simulator cannot be judged at all.

    Two things are reported, and they are different questions:

      * ACCURACY of the verdict against `lost` — how often the label the
        player read matched what happened. `favored`/"ahead on paper" predict
        NOT-lost; `behind` predicts lost; `close fight` predicts nothing in
        particular, so it is counted separately rather than scored as either.
      * CALIBRATION per class — the loss rate within each verdict. This is the
        number that shows whether the thresholds mean anything: if "favored"
        and "close fight" lose at similar rates, the ratio is not separating
        the cases it claims to separate.
    """
    scored = [r for r in rows if r.get("lost") is not None]
    print(f"\n== Check A: the current stat-ratio rule, measured ==")
    print(f"   {len(scored)} advisories with an outcome label, "
          f"{len({(r['session'], r['game']) for r in scored})} game(s)")
    print("   `lost` = the friendly hero's effective HP (hp+armor) DROPPED "
          "across that turn's\n   combat window, read from the log. A TIE "
          "takes no damage and is NOT a loss —\n   it is counted separately, "
          "not folded in.")
    ties = sum(1 for r in scored if r.get("tie"))
    if ties:
        print(f"   ({ties} ties in the sample, excluded from `lost`.)")
    by = {}
    for r in scored:
        by.setdefault(verdict_of(r.get("forecast")), []).append(r)
    print(f"\n   {'verdict':16} {'n':>4} {'lost':>5} {'loss rate':>10} "
          f"{'fresh anchor':>13}")
    for v in list(VERDICTS) + [None]:
        rs = by.get(v) or []
        if not rs:
            continue
        nlost = sum(1 for r in rs if r["lost"])
        fresh = sum(1 for r in rs if r.get("fresh"))
        name = v if v else "(no forecast)"
        print(f"   {name:16} {len(rs):4} {nlost:5} "
              f"{100 * nlost / len(rs):9.0f}% {fresh:13}")
    # scored accuracy, on the classes that make a claim
    claims = [(r, verdict_of(r.get("forecast"))) for r in scored]
    claims = [(r, v) for r, v in claims if v in ("favored", "ahead on paper",
                                                "behind")]
    if claims:
        right = sum(1 for r, v in claims
                    if (v == "behind") == bool(r["lost"]))
        print(f"\n   directional accuracy on the {len(claims)} advisories that "
              f"made a claim: {100 * right / len(claims):.0f}%")
        base = sum(1 for r in scored if not r["lost"]) / len(scored)
        print(f"   (always guessing 'not lost' scores "
              f"{100 * base:.0f}% — anything below that is worse than a "
              f"constant)")
    # does the fresh/stale split matter?
    print("\n   by anchor quality:")
    for label, sel in (("fresh preview", lambda r: r.get("fresh")),
                       ("stale/lobby/baseline", lambda r: not r.get("fresh"))):
        rs = [r for r in scored if sel(r)]
        if rs:
            print(f"     {label:22} n={len(rs):3} "
                  f"lost {100 * sum(1 for r in rs if r['lost']) / len(rs):.0f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", help="Power.log files")
    ap.add_argument("--json", help="write the rows here")
    ap.add_argument("--live", action="store_true",
                    help="include the newest log even if it is still being "
                         "written")
    args = ap.parse_args()
    paths = args.paths or sorted(glob.glob(HS_LOG_GLOB),
                                 key=os.path.getmtime)
    all_rows = []
    for p in paths:
        # An in-progress session is a half-written game: its last phase has no
        # following fight, and Hearthstone rotates logs, so a row from it is
        # not re-derivable later. Skipped unless asked for (outcome_audit's
        # freshness guard, same reason).
        if not args.live and not args.paths and \
                time.time() - os.path.getmtime(p) < 1800:
            print(f"(skipping live file: {os.path.basename(p)})")
            continue
        lines = open(p, encoding="utf-8", errors="replace").readlines()
        sess = os.path.basename(os.path.dirname(p))
        for gi, (s, e) in enumerate(split_game_chunks(lines), 1):
            rows = rows_for(lines[s:e], sess, gi)
            all_rows += rows
            if rows:
                print(f"{sess} g{gi}: {len(rows)} advisories  "
                      f"hero={rows[0]['hero']} place={rows[0]['placement']}")
    print(f"\n{len(all_rows)} advisory rows across "
          f"{len({(r['session'], r['game']) for r in all_rows})} game(s)")
    if all_rows:
        baseline_report(all_rows)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(all_rows, f)
        print(f"written: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
