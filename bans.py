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

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CARD_RACES_CACHE = os.path.join(_HERE, ".card_races.json")
HEARTHSTONEJSON_URL = "https://api.hearthstonejson.com/v1/latest/enUS/cards.json"

ALL_TRIBES = [
    "BEAST", "DEMON", "DRAGON", "ELEMENTAL", "MECHANICAL",
    "MURLOC", "NAGA", "PIRATE", "QUILBOAR", "UNDEAD",
]
CANON = {"MECHANICAL": "Mech"}


def canon(tribe):
    """Raw log tribe name -> canonical display name (MECHANICAL -> Mech)."""
    return CANON.get(tribe, tribe.title())


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
    """Return a list of per-game dicts: {seed, allowed, banned}.

    `allowed`/`banned` are lists of canonical tribe names (e.g. "Mech",
    "Dragon"). Games with no pool minions (non-Battlegrounds) are skipped.
    `lines` may be passed to avoid re-reading the file (the live coach passes the
    current game's lines).
    """
    if card_races is None:
        card_races = _load_card_races(DEFAULT_CARD_RACES_CACHE)

    games = {}  # seed -> set of pure-tribe pool minions
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
            games.setdefault(cur_seed, set())
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
            bt = " ".join(block)
            if "BACON_POOL_MINION" in bt:
                cid = re.search(r"CardID=([A-Z0-9_]+)", bt)
                if cid:
                    races = card_races.get(cid.group(1), [])
                    if len(races) == 1 and races[0] in ALL_TRIBES:
                        games[cur_seed].add(races[0])
            i = j
        else:
            i += 1

    result = []
    for seed, pure_tribes in games.items():
        allowed = sorted(canon(t) for t in pure_tribes)
        banned = sorted(canon(t) for t in ALL_TRIBES if t not in pure_tribes)
        result.append({"seed": seed, "allowed": allowed, "banned": banned})
    return result


def filter_comps_by_available_tribes(comps, card_races, allowed_tribes):
    """Return the comps (slug -> comp) playable given the allowed tribes.

    A comp is playable if **every core card** has at least one tribe in
    `allowed_tribes`, or is neutral / all-tribe. Compound core cards (e.g.
    ELEMENTAL/DEMON) are playable if *either* tribe is allowed. Cards with
    unknown tribes are treated as playable (fail-open) so a comp is never
    wrongly excluded.
    """
    allowed = set(allowed_tribes)
    playable = {}
    for slug, comp in comps.items():
        ok = True
        for cid in comp.get("core", []):
            races = card_races.get(cid)
            if races is None:
                continue  # unknown card — fail open
            if not races or "ALL" in races:
                continue  # neutral or all-tribe — always available
            if not ({canon(r) for r in races} & allowed):
                ok = False
                break
        if ok:
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
