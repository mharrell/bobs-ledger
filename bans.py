"""Extract per-game banned/available tribes from a Battlegrounds Power.log.

Each Battlegrounds game allows exactly **5 tribes** and bans the other 5. The
allowed tribes are the **pure single-tribe minions** present in the tavern
minion pool (`BACON_POOL_MINION` entities). Compound-tribe minions (e.g.
MECHANICAL/MURLOC) appear if *any* of their tribes is active, so they can't
reveal bans — only pure-tribe minions can. The 5 tribes with no pure minion in
the pool are banned.

Usage:
  python bans.py <Power.log>            # print per-game allowed/banned tribes
  python bans.py <Power.log> --json      # machine-readable output
"""
import json
import os
import re
import sys

import requests

from tribes import ALL_TRIBES, canon, normalize  # noqa: F401 (re-exported)

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CARD_RACES_CACHE = os.path.join(_HERE, ".card_races.json")
HEARTHSTONEJSON_URL = "https://api.hearthstonejson.com/v1/latest/enUS/cards.json"


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
    """Return a list of per-game dicts: {seed, allowed, banned, races}.

    `allowed`/`banned` are lists of canonical tribe names (e.g. "Mech",
    "Dragon"). Games with no pool minions (non-Battlegrounds) are skipped.
    `races` is the card->races map observed from the log itself: each pool
    minion's FULL_ENTITY block prints its own `tag=CARDRACE` at creation —
    ground truth, unlike the upstream hearthstonejson cache, which lags the
    patch by weeks (new-set ids were missing on 2026-09-09, so detection
    never saw 5 tribes and the comp filter failed OPEN all game: every
    comp listed, banned tribes included). Callers merge `races` over their
    cache so the comp-ban marks work for new cards too. `lines` may be
    passed to avoid re-reading the file (the live coach passes the current
    game's lines).
    """
    if card_races is None:
        card_races = _load_card_races(DEFAULT_CARD_RACES_CACHE)

    games = {}  # seed -> {"pure": set of tribes, "races": {cid: [races]}}
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
            games.setdefault(cur_seed, {"pure": set(), "races": {}})
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
                    games[cur_seed]["pure"].add(races[0])
            i = j
        else:
            i += 1

    result = []
    for seed, info in games.items():
        pure_tribes = info["pure"]
        allowed = sorted(canon(t) for t in pure_tribes)
        banned = sorted(canon(t) for t in ALL_TRIBES if t not in pure_tribes)
        result.append({"seed": seed, "allowed": allowed, "banned": banned,
                       "races": info["races"]})
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
    """
    if not allowed_tribes:
        return dict(comps)
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
    return playable


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
            print(f"seed {g['seed']}: allowed={g['allowed']} banned={g['banned']}")
