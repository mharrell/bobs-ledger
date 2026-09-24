"""Extract per-game banned/available tribes from a Battlegrounds Power.log.

Each Battlegrounds game allows exactly **5 tribes** and bans the other 5. The
allowed tribes are the **pure single-tribe minions** present in the tavern
minion pool (`BACON_POOL_MINION` entities). Compound-tribe minions (e.g.
MECHANICAL/MURLOC) appear if *any* of their tribes is active, so they can't
reveal bans — only pure-tribe minions can. The tribes with no pure minion in
the pool are banned, within the universe of tribes the patch still offers:
a tribe that is OUT OF PLAY entirely (rotated — Naga since 36.6.1) is not
banned, it is reported separately as `out_of_pool` (see `out_of_pool_tribes`).

Usage:
  python bans.py <Power.log>            # print per-game allowed/banned tribes
  python bans.py <Power.log> --json      # machine-readable output
"""
import json
import os
import re
import sys

import requests

from tribes import (ALL_TRIBES, DISPLAY_TRIBES,  # noqa: F401 (re-exported)
                    canon, normalize)

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CARD_RACES_CACHE = os.path.join(_HERE, ".card_races.json")
HEARTHSTONEJSON_URL = "https://api.hearthstonejson.com/v1/latest/enUS/cards.json"

# Distinct pure-tribe pool minions a tribe needs before it counts as
# allowed. Card effects summon banned-tribe pool minions mid-game (a spell
# made the Demon BG34_500 enter an opponent's board on 2026-09-10), and
# those singletons pushed the seen-tribe count past 5 — the live 5/5 gate
# then failed open and the comps panel listed banned comps all game. Real
# allowed tribes show 10+ distinct pure minions in the first minutes;
# observed leaks max out at 2 (see bans_from_log docstring).
MIN_PURE_POOL_CARDS = 3


def out_of_pool_tribes():
    """Canonical tribes that are OUT OF PLAY entirely (rotated by a patch).

    A tribe is now in one of three states, and "banned" is only the second:

      1. in play          — detected as a pure pool tribe this game;
      2. banned this game — inside the game's universe, just not detected;
      3. out of play      — not in the pool at all any more: Naga left the
                            minion pool in 36.6.1 (2026-09-22), and no shop can
                            offer it in ANY lobby.

    State 3 is a PATCH-level fact, not a per-game one, so it cannot come out of
    the log — `meta/out_of_play.json` (via `playable.OutOfPlay`) owns it. The
    ban universe is ALL_TRIBES minus this set: without it every 36.6.1 game
    reported Naga as "banned this game" (the ban universe silently grew to 11
    when Aberration was added) and the overlay read "Naga: banned" for a tribe
    that no longer exists in the pool.

    Fail OPEN: an unavailable/unreadable registry, or one that lists no tribes,
    returns an empty set — the universe is then all of ALL_TRIBES and nothing
    is silently marked out of play. `HEARTH_OUT_OF_PLAY=0` (historical replay
    review) switches it off the same way, so an old log is judged under the
    roster it was actually played with.
    """
    try:
        import playable as playable_mod
    except ImportError:  # pragma: no cover — playable ships with the coach
        return set()
    try:
        oop = playable_mod.enforcement()
        if oop is None:
            return set()
        return {canon(t) for t in oop.tribes_out()} & set(DISPLAY_TRIBES)
    except Exception:  # noqa: BLE001 — a broken registry must fail open, not
        return set()   # kill the live feed (see the fail-open rule above)


def _load_card_races(cache_path):
    """Return {card_id: [races]} from hearthstonejson, cached to disk.

    Races are the raw log names (BEAST, MECHANICAL, ...). Neutral cards have an
    empty list; all-tribe cards have ["ALL"].
    """
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    print(f"  downloading card list from hearthstonejson (cached to {cache_path}) ...")
    resp = requests.get(HEARTHSTONEJSON_URL, timeout=120)
    resp.raise_for_status()
    card_races = {}
    for card in resp.json():
        cid = card.get("id")
        if not cid:
            continue
        races = card.get("races") or ([card["race"]] if card.get("race") else [])
        card_races[cid] = [r for r in races if r and r != "NEUTRAL"]
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(card_races, f)
    return card_races


def bans_from_log(powerlog_path, card_races=None, lines=None):
    """Return a list of per-game dicts:
    {seed, allowed, banned, pending, races, out_of_pool}.

    `allowed`/`banned`/`pending` are lists of canonical tribe names (e.g.
    "Mech", "Dragon"). Games with no pool minions (non-Battlegrounds) are
    skipped. A tribe counts as allowed only with MIN_PURE_POOL_CARDS
    DISTINCT pure pool minions: card effects summon banned-tribe pool
    minions mid-game (2026-09-10: BG34_500 Flaming Enforcer, a Demon
    created by a spell with an opponent, carried IS_BACON_POOL_MINION + a
    single CARDRACE), so counting SEEN tribes made the seen-set reach 6-8
    and the live coach's 5/5 gate failed OPEN all game — every comp
    listed, banned tribes included. Real allowed tribes reveal 10+
    distinct pure minions within the first minutes (every lobby shop
    cycle); effect-generated leaks are 1-2 cards. Validated: with the
    3-card gate, all 9 BG games across the 2026-09-08..10 sessions resolve
    to exactly 5 tribes and every observed leak sits below it.

    Three-state honesty (2026-09-19): the ban list itself is NOT in the
    log (identical CREATE_GAME setup across different-ban games), so
    "banned" is only the confirmed complement once 5 tribes have crossed
    the gate. Before that, sub-gate and unseen tribes are `pending` —
    could still be banned or just unsampled — and `banned` is empty.
    (The 2026-09-19 games' allowed set only completed at minute 12/14,
    so the pending state is the normal early-game reality, not an edge.)
    `races` is the card->races map observed from the log itself: each pool
    minion's FULL_ENTITY block prints its own `tag=CARDRACE` at creation —
    ground truth, unlike the upstream hearthstonejson cache, which lags the
    patch by weeks (new-set ids were missing on 2026-09-09, so detection
    never saw 5 tribes and the comp filter failed OPEN all game: every
    comp listed, banned tribes included). Callers merge `races` over their
    cache so the comp-ban marks work for new cards too. `lines` may be
    passed to avoid re-reading the file (the live coach passes the current
    game's lines).

    Out of play is the THIRD state (2026-09-22, patch 36.6.1): a tribe can be
    (1) detected in play, (2) banned this game — in the universe, not detected,
    or (3) out of play entirely, i.e. absent from the pool in EVERY lobby.
    `banned` must mean only (2), so the ban universe is ALL_TRIBES minus the
    out-of-play tribes the registry knows about (`out_of_pool_tribes()`, i.e.
    Naga since 36.6.1) and `out_of_pool` carries that list back to the caller,
    which can then say "Naga: rotated out" instead of "Naga: banned". The
    registry — not the log — owns state (3); a pre-patch log therefore shows
    Naga in `out_of_pool` (the fact is patch-level) while its own detected
    tribes, Naga included, still ride `allowed` (the log is ground truth for
    what that game actually offered). Fail OPEN: no registry/no tribes -> the
    universe is all of ALL_TRIBES and `out_of_pool` is empty.
    """
    if card_races is None:
        card_races = _load_card_races(DEFAULT_CARD_RACES_CACHE)

    # seed -> {"pure": tribe -> distinct card ids, "races": {cid: [races]}}
    games = {}
    cur_seed = None
    if lines is None:
        with open(powerlog_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        m = re.search(r"GAME_SEED value=(\d+)", line)
        if m:
            cur_seed = m.group(1)
            games.setdefault(cur_seed, {"pure": {}, "races": {}})
        if cur_seed and ("SHOW_ENTITY" in line or "FULL_ENTITY" in line):
            block = []
            j = i
            while j < n and (
                "tag=" in lines[j]
                or "SHOW_ENTITY" in lines[j]
                or "FULL_ENTITY" in lines[j]
            ):
                block.append(lines[j])
                j += 1
            # The block may glue several back-to-back entity definitions
            # into one run (the pool reveal prints them without separators)
            # — segment it per entity header so each CardID gets its own
            # races instead of the first card swallowing the rest.
            segments = []  # (card_id, block text)
            cur_cid = None
            cur_text = []
            for bl in block:
                if "FULL_ENTITY" in bl or "SHOW_ENTITY" in bl:
                    if cur_cid is not None:
                        segments.append((cur_cid, "\n".join(cur_text)))
                    m2 = re.search(r"CardID=([A-Z0-9_]+)", bl)
                    cur_cid = m2.group(1) if m2 else None
                    cur_text = [bl]
                else:
                    cur_text.append(bl)
            if cur_cid is not None:
                segments.append((cur_cid, "\n".join(cur_text)))
            for cid_str, bt in segments:
                if "BACON_POOL_MINION" not in bt or cid_str is None:
                    continue
                # The log's own CARDRACE tags first (patch-proof); a cache
                # lookup only for blocks without one (numeric values from
                # older log formats, or a race the block omits).
                race_vals = [r for r in re.findall(
                    r"tag=CARDRACE value=([A-Z]+)", bt) if r in ALL_TRIBES]
                races = race_vals
                if not races:
                    races = card_races.get(cid_str, [])
                if races:
                    games[cur_seed]["races"][cid_str] = races
                if len(races) == 1 and races[0] in ALL_TRIBES:
                    games[cur_seed]["pure"].setdefault(
                        races[0], set()).add(cid_str)
            i = j
        else:
            i += 1

    result = []
    # The ban universe: every tribe the pool could still offer. Out-of-play
    # tribes are not in it (see the docstring) — they are reported separately,
    # never as "banned this game".
    out_of_pool = sorted(out_of_pool_tribes())
    universe = [t for t in ALL_TRIBES if canon(t) not in set(out_of_pool)]
    for seed, info in games.items():
        pure_tribes = {t for t, cids in info["pure"].items()
                       if len(cids) >= MIN_PURE_POOL_CARDS}
        allowed = sorted(canon(t) for t in pure_tribes)
        others = sorted(canon(t) for t in universe if t not in pure_tribes)
        if len(allowed) >= 5:
            banned, pending = others, []
        else:
            # Not yet a confirmed 5/5: nothing is called banned (the log
            # carries no ban list — see docstring); the rest is pending.
            banned, pending = [], others
        result.append({"seed": seed, "allowed": allowed, "banned": banned,
                       "pending": pending, "races": info["races"],
                       "out_of_pool": out_of_pool})
    return result


def filter_comps_by_available_tribes(comps, card_races, allowed_tribes):
    """Return the comps (slug -> comp) playable given the allowed tribes.

    A comp survives when its core still has a working MAJORITY after the
    ban: hsreplay cores are "the combo pieces", and hybrid comps carry
    cross-tribe and/or pieces (nagas-groundbreaker lists the Dragon
    Sky-hatch Runaway alongside the Nagas Groundbreaker + Seafloor
    Recruiter) — the 2026-09-05 game had Groundbreaker + Seafloor
    Recruiter on board with Naga ALLOWED, but the old all-or-nothing rule
    dropped the comp because Sky-hatch (Dragon) was banned, and the coach
    went comp-blind over a naga board. A comp is dropped only when more
    than half its core is banned-tribe (the comp as written can't be
    built); survivors carry `_blocked_core` (the banned core ids) so the
    shopping list can mark them banned-this-game instead of buyable.

    Core cards with unknown tribes are treated as playable (fail-open) so
    a comp is never wrongly excluded; compound races (e.g.
    ELEMENTAL/DEMON) are playable if *either* tribe is allowed.
    `allowed_tribes` None or empty = no ban info — fail OPEN and keep
    every comp (an unknown ban must not look like "all tribes banned").
    NOTE the designed counter-point: the LIVE coach's detection window is
    deliberately fail CLOSED (advisory list = confirmed-tribe comps only
    until the 5/5 set lands — see live_coach._refresh_bans). These two
    are a pair: the replay/panel layer must never read no-info as
    all-banned, the live advisory must never read no-info as all-clear.
    Don't unify them.
    """
    if not allowed_tribes:
        # No ban info: fail OPEN on the per-game ban — but out-of-play is a
        # PATCH-level fact, not a per-game one, so it still applies.
        return _drop_out_of_play(dict(comps))
    allowed = set(allowed_tribes)
    playable = {}
    for slug, comp in comps.items():
        # The comp's own TRIBE is the first gate (2026-09-07, live report:
        # the coach pivoted to Nagas with Naga banned — nagas-end-of-turn
        # has only ONE naga-tribe core card, so the core-majority rule
        # alone passed it). A comp whose tribe is banned is unplayable no
        # matter how its core divides; the core rule below then only
        # governs hybrid comps whose tribe IS allowed.
        tribe = comp.get("tribe")
        if tribe and canon(tribe) not in allowed:
            continue
        blocked = []
        for cid in comp.get("core", []):
            races = card_races.get(cid)
            if races is None:
                continue  # unknown card — fail open
            if not races or "ALL" in races:
                continue  # neutral or all-tribe — always available
            if not ({canon(r) for r in races} & allowed):
                blocked.append(cid)
        core = comp.get("core", [])
        if len(blocked) * 2 >= len(core) and core:
            continue  # most of the core is unbuyable — comp as written is dead
        if blocked:
            comp = dict(comp, _blocked_core=blocked)  # copy: meta dicts are shared
        playable[slug] = comp
    return _drop_out_of_play(playable)


def _drop_out_of_play(comps_in):
    """Remove comps that are out of play entirely (rotated/removed by a patch).

    The ban filter above answers "is this comp legal in THIS game"; out-of-play
    answers "does this comp still exist at all". Both are reasons the coach must
    not build toward it — on 2026-09-22 (36.6.1) Naga left the pool, and without
    this the coach would keep offering Naga comps in every lobby.

    Delegates to `playable.OutOfPlay.filter_comps` (which owns the compound
    rule: a comp is out only when every core piece is out, and an untribed or
    unknown card fails open). Honours `HEARTH_OUT_OF_PLAY=0`, so a historical
    replay review is judged under the rules it was played with.

    The imported module is aliased deliberately: this function's argument used to
    be called `playable`, and `import playable` rebound it to the module, so
    `filter_comps` received a module and died on `.items()` — caught by
    test_tribes / test_live_updates the moment it landed.
    """
    try:
        import playable as playable_mod
    except ImportError:  # pragma: no cover — playable ships with the coach
        return comps_in
    oop = playable_mod.enforcement()
    if oop is None:
        return comps_in
    kept, _dropped = oop.filter_comps(comps_in)
    return kept


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("powerlog", help="path to a Power.log")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--cards-cache", default=DEFAULT_CARD_RACES_CACHE)
    args = ap.parse_args()

    card_races = _load_card_races(args.cards_cache)
    games = bans_from_log(args.powerlog, card_races)
    if args.json:
        print(json.dumps(games, indent=2))
    else:
        for g in games:
            extra = (f" pending={g['pending']}" if g["pending"] else "")
            oop = (f" out_of_pool={g['out_of_pool']}"
                   if g["out_of_pool"] else "")
            print(f"seed {g['seed']}: allowed={g['allowed']} "
                  f"banned={g['banned']}{oop}{extra}")
