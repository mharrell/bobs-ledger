#!/usr/bin/env python3
"""Parse the pasted minions list and enrich with full card details.

Input: meta/minions_raw.txt (names grouped by tavern tier, pasted from
hsreplay.net/battlegrounds/minions/). The hsreplay page only gives names; the
full card details (cost, tribe, attack, health, keywords, description) come from
the hearthstonejson card DB (cached at .cards_full.json).

Output: meta/minions.json — a list of {tier, id, name, cost, tribe, attack,
health, mechanics, text}.
"""
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(_HERE, "meta", "minions_raw.txt")
OUT = os.path.join(_HERE, "meta", "minions.json")
CARDS = os.path.join(_HERE, ".cards_full.json")


def _strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def load_card_map():
    """Return {minion_name: card} for BG minions in the card DB."""
    with open(CARDS, encoding="utf-8") as f:
        cards = json.load(f)
    name_map = {}
    for c in cards:
        if c.get("type") == "MINION" and str(c.get("id", "")).startswith("BG"):
            nm = c.get("name")
            if nm:
                name_map.setdefault(nm, c)
    return name_map


def parse(raw_text, card_map):
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    out = []
    cur_tier = None
    for l in lines:
        m = re.search(r"Tier (\d+)", l)
        if m and ("Tavern Tier" in l or "glowTier" in l):
            cur_tier = int(m.group(1))
            continue
        if cur_tier is None:
            continue
        card = card_map.get(l)
        if card is None:
            print(f"  WARN: no card for '{l}'")
            continue
        races = card.get("races") or ([card["race"]] if card.get("race") else [])
        out.append({
            "tier": cur_tier,
            "id": card.get("id"),
            "name": card.get("name"),
            "cost": card.get("cost"),
            "tribe": races[0] if races else None,
            "attack": card.get("attack"),
            "health": card.get("health"),
            "mechanics": card.get("mechanics", []),
            "text": _strip_html(card.get("text")),
        })
    return out


def main():
    with open(RAW, encoding="utf-8") as f:
        raw = f.read()
    card_map = load_card_map()
    minions = parse(raw, card_map)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(minions, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"enriched {len(minions)} minions -> {OUT}")
    missing = [m["name"] for m in minions if not m["tribe"]]
    print(f"minions with no tribe: {len(missing)}")


if __name__ == "__main__":
    main()
