#!/usr/bin/env python3
"""Extend meta/minions.json with BG minion ids seen in recent session logs.

The minion pool is a hand-pasted snapshot (parse_minions.py); after a patch
or for older reprints, real board/shop minions can be missing from it — and
the value function silently scores unknown cards as worthless (shop_ranking
skips them outright). This heals the drift: any BG minion id observed in a
local Power.log but absent from the pool is added from the hearthstonejson
card DB (.cards_full.json) with tier=techLevel (the tavern tier — which IS
the buy price; card `cost` is the mana cost and is NOT the buy price).

Usage:
  python extend_pool.py            # scan newest session logs, print additions
  python extend_pool.py --apply    # write them into meta/minions.json
"""
import glob
import json
import os
import re
import sys

from board_state import MINION_ONLY
from tribes import normalize

_HERE = os.path.dirname(os.path.abspath(__file__))
POOL = os.path.join(_HERE, "meta", "minions.json")
CARDS = os.path.join(_HERE, ".cards_full.json")
LOG_GLOB = r"C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_*\Power.log"


def minion_ids_in_logs(limit=5):
    """Distinct BG minion card ids from the most recent session logs."""
    logs = sorted(glob.glob(LOG_GLOB), key=os.path.getmtime, reverse=True)[:limit]
    ids = set()
    for path in logs:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                for m in re.finditer(r"cardId=(\w+)", line):
                    cid = m.group(1)
                    if MINION_ONLY.match(cid):
                        # Golden variants never get looked up (board_state
                        # strips _G before the pool query) — skip them.
                        ids.add(cid[:-2] if cid.endswith("_G") else cid)
    return ids


def cards_full():
    """id -> card dict from the hearthstonejson cache."""
    with open(CARDS, encoding="utf-8") as f:
        return {c.get("id"): c for c in json.load(f)}


def main():
    do_apply = "--apply" in sys.argv[1:]
    with open(POOL, encoding="utf-8") as f:
        pool = json.load(f)
    known = {m.get("id") for m in pool}
    seen = minion_ids_in_logs()
    missing = sorted(seen - known)
    # Heal tier drift too: pool minions added before techLevel was filled in
    # carry tier=null, which breaks buy-price affordability (tier IS the price).
    healed = 0
    for m in pool:
        if m.get("tier") is None:
            card = cards_full().get(m.get("id"))
            if card and card.get("techLevel") is not None:
                m["tier"] = card["techLevel"]
                m["auto_added"] = "from session logs (extend_pool.py)"
                healed += 1
    if healed:
        print(f"tier healed for {healed} minion(s) from .cards_full.json")
    if not missing:
        if do_apply and healed:
            with open(POOL, "w", encoding="utf-8") as f:
                json.dump(pool, f, indent=2, ensure_ascii=False)
                f.write("\n")
            print(f"Applied tier healing -> {POOL}")
        else:
            print("pool is complete for recent logs — nothing to add")
        return 0
    cards = cards_full()
    additions = []
    for cid in missing:
        card = cards.get(cid)
        if not card or card.get("type") != "MINION":
            continue  # enchantment/token shape we don't track
        races = card.get("races") or ([card["race"]] if card.get("race") else [])
        additions.append({
            "tier": card.get("techLevel"),
            "id": cid,
            "name": card.get("name"),
            "cost": card.get("cost"),
            "tribe": normalize(races[0]) if races else None,
            "attack": card.get("attack"),
            "health": card.get("health"),
            "mechanics": card.get("mechanics", []),
            "text": re.sub(r"<[^>]+>", "", card.get("text") or "").strip(),
            "auto_added": "from session logs (extend_pool.py)",
        })
    for a in additions:
        print(f"  + {a['id']}  {a['name']}  (t{a['tier']} {a['tribe']})")
    if do_apply:
        pool.extend(additions)
        with open(POOL, "w", encoding="utf-8") as f:
            json.dump(pool, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Applied: {len(additions)} added"
              + (f", {healed} tiers healed" if healed else "")
              + f" -> {POOL}")
    else:
        print(f"Dry run: {len(additions)} minion(s) would be added"
              + (f", {healed} tiers healed" if healed else "")
              + " (--apply to write).")
    return 0


if __name__ == "__main__":
    sys.exit(main())