#!/usr/bin/env python3
"""Replay-regression harness: expected coach advice at (session, game, turn).

The validation layer of analysis/engine_coaching.md, in the validate_growth.py
spirit: for each case, reconstruct the exact state the live coach saw
(replay_review's machinery — the same incremental path as live.py: state from
game start, fire on the settled phase-start shop), run analyze(), and diff it
against the expectations table.

Cases at birth come from the 2026-09-15 session review (the four-game log
that motivated the engine-coaching plans):

  - game 4 t11/t13 (Shudderwock, 1st): the Sous Chef Sticker recipe must be
    ACTIVE and Tavern Tempest — the build key the old coach never surfaced —
    must rank in the shop's top 5.
  - game 1 t8/t9 (Tras'tath, 6th): NO recipe may activate for a hero with
    none (the anti-false-activation guard). t9 also documents the "LEVEL —
    you're strong" push Plan 3 will flip: flipping THIS case is the visible
    sign, never a silent one.
  - game 2 t6/t7 (Voone, 7th): the coach's LEVEL advice was CORRECT (the
    player under-leveled) — must not regress.

A missing session log SKIPS (logs rotate off the client) — a gone log is not
a regression. Exit 0 = all run cases pass; 1 = any failure.

Usage:
  python validate_advice.py              # all cases
  python validate_advice.py game4        # substring filter on case names
"""
import glob
import os
import re
import sys

from config import HS_LOG_GLOB
from extract_game import split_game_chunks
from replay_review import _phases, _advise_point, _resolve_at
from value import _load_bg_names

CASES = [
    {
        # The Tempest buys happened MID-PHASE (they appeared on rolls, not
        # the phase-start shop), so the honest assertion point is the
        # settled shop at the moment of each actual purchase: 09:06:44
        # (t11, first buy) and 09:12:22 (t13). The recipe must be live and
        # Tavern Tempest — the build key the old coach never surfaced —
        # must headline the same shop the player bought from.
        "name": "game4-t11-buy-moment-tempest-surfaced",
        "session": "Hearthstone_2026_01_01", "game": 4,
        "at": "09:06:44",
        "recipes": ["shudderwock-sous-chef-battlecries"],
        "shop_surfaced": "Tavern Tempest",
        # Surfaced, not headlined: at THIS moment a big plain body still
        # outranks the boosted Tempest (the boost is deliberately sized
        # under a comp core so it can't displace dominant cards). By the
        # 09:12:22 buy it headlines outright.
    },
    {
        "name": "game4-t13-buy-moment-tempest-headlined",
        "session": "Hearthstone_2026_01_01", "game": 4,
        "at": "09:12:22",
        "recipes": ["shudderwock-sous-chef-battlecries"],
        "shop_surfaced": "Tavern Tempest",
        "buy_this": "Tavern Tempest",
    },
    {
        "name": "game4-t12-recipe-active-weak-reach-mention",
        "session": "Hearthstone_2026_01_01", "game": 4, "turn": 12,
        "recipes": ["shudderwock-sous-chef-battlecries"],
        # Plan 2 Layer A: the tier-blocked hunt for the named piece stays
        # BLOCKED (random generation is a weak mention, never a gate) but
        # names the live generator instead of a bare "needs tier 6".
        "top_contains": "needs tier 6; Tavern Tempest can still drop it",
    },
    {
        # Plan 2 Layer B positive: Unbound Tempest live on board, idle gold
        # past the tempo window, a fuel conversion in the shop — the plan
        # names the conversion instead of leaving gold unspent.
        "name": "game4-t20-feed-the-engine",
        "session": "Hearthstone_2026_01_01", "game": 4, "turn": 20,
        "recipes": ["shudderwock-sous-chef-battlecries"],
        "top_contains": "feed the engine",
    },
    {
        # Plan 3 validation: the engine (Unbound on board from t14) + a
        # clean health sheet beats "you're strong — LEVEL": the roll-lead
        # fires with the dual output - the roll line AND the level as an
        # explicit next-priority with its exit condition. t13 stays LEVEL
        # (the engine piece only hit the board mid-phase); t17 stays LEVEL
        # (took 10 damage - stabilize first); t15 and t19 roll-lead.
        "name": "game4-t15-roll-for-fuel-leads",
        "session": "Hearthstone_2026_01_01", "game": 4, "turn": 15,
        "recipes": ["shudderwock-sous-chef-battlecries"],
        "top_contains": "consider rerolling for elemental bodies",
        "top_contains2": "next priority: LEVEL to tier 6",
    },
    {
        "name": "game4-t19-roll-for-fuel-leads",
        "session": "Hearthstone_2026_01_01", "game": 4, "turn": 19,
        "recipes": ["shudderwock-sous-chef-battlecries"],
        "top_contains": "consider rerolling for",
        "top_contains2": "next priority: LEVEL to tier 6",
    },
    {
        "name": "game1-t8-no-false-recipe-no-fuel-line",
        "session": "Hearthstone_2026_01_01", "game": 1, "turn": 8,
        "recipes": [],
        # Plan 2 Layer B negative: no fuel engine on board -> the
        # feed-the-engine line must not exist.
        "top_not_contains": "feed the engine",
    },
    {
        # Documents the "you're strong — convert it into a tier" push.
        # Plan 3 re-anchored strength to the lobby pace, but THIS phase's
        # board read is itself corrupted: the parse carries a PLAY-zone
        # Nomi at ~1010 ATK (tavern-scaling leak into the warband read,
        # the extract noise family) that inflates board_stats to ~1115 vs
        # a real ~105 - so "you're strong" fires against ANY anchor. The
        # case stays pinned to the current render as the visible gauge:
        # when the board-contamination fix lands, THIS case flips to
        # "buy stats" (flip_why: behind the lobby pace) and that edit is
        # the fix's acceptance test.
        "name": "game1-t9-no-false-recipe_level-push-documented",
        "session": "Hearthstone_2026_01_01", "game": 1, "turn": 9,
        "recipes": [],
        "top_contains": "LEVEL to tier 5",
    },
    {
        # Voone t6/t7: the LEVEL advice was right (the player under-leveled
        # into 7th) — a regression guard for every later plan.
        "name": "game2-t6-level-stands",
        "session": "Hearthstone_2026_01_01", "game": 2, "turn": 6,
        "recipes": [],
        "top_startswith": "LEVEL",
    },
    {
        "name": "game2-t7-level-stands",
        "session": "Hearthstone_2026_01_01", "game": 2, "turn": 7,
        "recipes": [],
        "top_startswith": "LEVEL",
    },
    # The Morchie over-hunt guard (Plan 2 Layer A's rule: reachability must
    # not resurrect hunt-every-turn). The 2026-09-11 game hunted the tier-3
    # Gem Rat for 11 straight phases; since the feasibility gates, the plan
    # says "no hunt" and buys on-tier pieces instead — and Layer A's new
    # TIER-gate exception (discover/token reach) must NOT reopen it.
    {
        "name": "morchie-t9-over-hunt-stays-blocked",
        "session": "Hearthstone_2026_01_01", "game": 2, "turn": 9,
        "recipes": [],
        "top_contains": "no hunt",
        "top_not_contains": "hunting",
    },
]


def _session_path(session):
    for p in glob.glob(HS_LOG_GLOB):
        if os.path.basename(os.path.dirname(p)) == session:
            return p
    return None


def _shop_names(a, names, n=5):
    out = []
    for e in (a.get("shop_rank") or [])[:n]:
        cid = e.get("card") if isinstance(e, dict) else e[0]
        out.append(names.get(cid, cid))
    return out


def _analyze_at(chunk, target):
    """Coach analysis at an exact log line (a mid-phase shop moment).

    _advise_at's long settle exists to skip PAST roll generations to the
    next stable shop; here the target IS the settled moment (picked from
    the player's actual purchase). Feed start -> target, analyze — no
    scan, so the offer set is exactly what the player decided on.
    """
    import live_coach
    coach = live_coach.LiveCoach()
    for j in range(target):
        coach.feed(chunk[j])
    return coach.analyze()


def _run_case(case, chunk, names):
    """[(ok, description)] for one case's expectations."""
    if case.get("at"):
        target = _resolve_at(chunk, case["at"], 0)
        if target is None:
            return [(False, f"at {case['at']}: no matching log line")]
        a = _analyze_at(chunk, target)
    else:
        phases = _phases(chunk)
        t = case["turn"]
        if t > len(phases):
            return [(False, f"turn {t} > {len(phases)} buy phases in log")]
        lo, hi = phases[t - 1]
        a, _, _saw_shop = _advise_point(chunk, lo, hi)
    if a is None:
        return [(False, "coach not ready at this moment")]
    got = {r.get("id") for r in (a.get("engine_recipes") or [])}
    want = set(case.get("recipes") or [])
    out = []
    # Both directions: a required recipe missing AND an unrequested one
    # firing (the false-activation guard) are failures.
    for rid in sorted(want - got):
        out.append((False, f"recipe {rid} NOT active"))
    for rid in sorted(got - want):
        out.append((False, f"recipe {rid} fired unexpectedly"))
    if want <= got:
        out.append((True, f"recipes active: {sorted(got) or 'none'}"))
    if case.get("shop_surfaced"):
        surf = case["shop_surfaced"]
        top = _shop_names(a, names)
        ok = any(surf in n for n in top)
        out.append((ok, f"'{surf}' {'in' if ok else 'NOT in'} shop top "
                        f"{len(top)}: {top}"))
    if case.get("buy_this"):
        want_name = case["buy_this"]
        buy = a.get("buy_this")
        ok = bool(buy) and want_name in names.get(buy, buy)
        out.append((ok, f"buy_this = {names.get(buy, buy) if buy else None}"
                        f" (want {want_name})"))
    if case.get("top_startswith"):
        tm = a.get("top_move") or ""
        ok = bool(re.match(r"^\d+\. " + re.escape(case["top_startswith"]),
                           tm))
        out.append((ok, f"top_move starts with '{case['top_startswith']}': "
                        f"{tm[:80]}"))
    if case.get("top_contains"):
        tm = a.get("top_move") or ""
        ok = case["top_contains"] in tm
        out.append((ok, f"top_move contains '{case['top_contains']}': "
                        f"{tm[:80]}"))
    if case.get("top_contains2"):
        tm = a.get("top_move") or ""
        ok = case["top_contains2"] in tm
        out.append((ok, f"top_move contains '{case['top_contains2']}': "
                        f"{tm[:80]}"))
    if case.get("top_not_contains"):
        tm = a.get("top_move") or ""
        ok = case["top_not_contains"] not in tm
        out.append((ok, f"top_move must NOT contain "
                        f"'{case['top_not_contains']}': {tm[:80]}"))
    return out


def main():
    argv = sys.argv[1:]
    filt = argv[0] if argv else None
    sessions = {}
    for case in CASES:
        if filt and filt not in case["name"]:
            continue
        sessions.setdefault(case["session"], []).append(case)
    if not sessions:
        print(f"no case matches {filt!r}")
        return 1
    names = _load_bg_names()
    failures = 0
    for session, cases in sessions.items():
        path = _session_path(session)
        if not path:
            for case in cases:
                print(f"SKIP {case['name']} — session log not on disk")
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        chunks = list(split_game_chunks(lines))
        for case in cases:
            print(f"== {case['name']}")
            if case["game"] > len(chunks):
                print(f"   FAIL — game {case['game']} > {len(chunks)} games")
                failures += 1
                continue
            s, e = chunks[case["game"] - 1]
            for ok, desc in _run_case(case, lines[s:e], names):
                print(f"   {'ok  ' if ok else 'FAIL'} {desc}")
                failures += 0 if ok else 1
    print(f"\n{'ALL PASS' if failures == 0 else f'{failures} FAILURES'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
