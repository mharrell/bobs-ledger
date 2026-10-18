#!/usr/bin/env python3
"""Build meta/tokens.json — the SUMMONED minions the pool deliberately lacks.

WHY THIS FILE EXISTS. A token is a real minion that appears on a board or in a
hand without ever being in the tavern, so `extend_pool.py` filters it out of
`meta/minions.json` on purpose: the pool is what the model may DRAFT, and a token
in it would be offered as a buy. But the rest of the program still has to know
what a token is. Without a record, the review prints the raw id — "BGS_115t" in a
SELLS row — and the cast counter calls it a spell.

MEASURED 2026-10-17: the player sold Sellemental's token and the Sell row said
`BGS_115t`; the same turn reported five casts, one of which was that token. An
earlier hand-added row (BGFYM_002t, Aberrant Tentacle) records the same complaint
from 2026-09-24 — done by hand then, because there was nowhere to put it.

So: `meta/tokens.json` is a table of its own, never merged into the pool, read by
the NAME resolver and by the "is this a minion?" test.

A token's id shape is a trailing `t` (Half-Shell `BG19_010t`, Beetle `BG28_603t`,
Sellemental's `BGS_115t`); the golden spelling is `_Gt` and is skipped, because
board_state strips `_G` before any lookup.

Usage:
  python parse_tokens.py /path/to/cards.json           # print what would change
  python parse_tokens.py /path/to/cards.json --apply   # write meta/tokens.json

`cards.json` is hearthstonejson's full dump (every card, tokens included):
  https://api.hearthstonejson.com/v1/latest/enUS/cards.json
It is NOT kept in the repo — only the ~90 rows derived from it are.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "meta", "tokens.json")

#: The id shape that means "summoned/created", not "draftable". Deliberately the
#: same rule `extend_pool.py` uses to keep tokens OUT of the pool.
def is_token_id(cid):
    return cid.endswith("t") and not cid.endswith("_Gt")


def is_bg(cid):
    return cid.startswith(("BG", "TB_Bacon"))


def build(cards, pool, spells):
    from tribes import tribes_from_races
    rows = []
    for c in cards:
        cid = c.get("id") or ""
        if not cid or not is_bg(cid) or c.get("type") != "MINION":
            continue
        if not is_token_id(cid):
            continue
        if cid in pool or cid in spells:
            continue                      # already named by another table
        # Not minions at all, only token-shaped: a hero power's summoned copy
        # (`BG31_HERO_801pt`), and a trinket's (`BG30_MagicItem_442t`) — the
        # second belongs to meta/trinkets.json, which already covers its family.
        if "_HERO_" in cid or "MagicItem" in cid:
            continue
        rows.append({
            "id": cid,
            "name": c.get("name"),
            # techLevel IS the tavern tier (and the buy price); card `cost` is
            # the mana cost, which is not what the shop charges.
            "tier": c.get("techLevel"),
            "cost": c.get("cost") or 0,
            "tribe": tribes_from_races(c.get("races")) or c.get("race"),
            "attack": c.get("attack"),
            "health": c.get("health"),
            "mechanics": sorted(m for m in (c.get("mechanics") or []) if m),
            "text": c.get("text"),
            "auto_added": "parse_tokens.py (hearthstonejson full dump): a "
                          "summoned minion, kept out of meta/minions.json "
                          "because the pool is what may be drafted",
        })
    rows.sort(key=lambda r: (r["name"] or "", r["id"]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cards", help="hearthstonejson cards.json (full dump)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    cards = json.load(open(args.cards, encoding="utf-8"))
    pool = {m["id"] for m in json.load(open(os.path.join(HERE, "meta", "minions.json"),
                                            encoding="utf-8"))}
    spells = {s["id"] for s in json.load(open(os.path.join(HERE, "meta",
                                                           "tavern_spells.json"),
                                              encoding="utf-8"))}
    rows = build(cards, pool, spells)
    print(f"{len(rows)} token(s)")
    for r in rows[:10]:
        print(f"  {r['id']:16} {r['name']}")
    if not args.apply:
        print("(dry run — pass --apply to write)")
        return
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    print(f"written: {OUT}")


if __name__ == "__main__":
    sys.exit(main())
