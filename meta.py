"""Load the curated card/comp meta and match a board against known comps.

The card DB is built up by hand (see meta/cards.json and meta/comps.json) from
curated meta sources (tier lists, comp guides). Card ids are the internal
Battlegrounds ids (BGxx_NNN, BGS_NNN, BG_XXX_NNN) that board_state.py emits.
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_HERE, "meta", "cards.json"), encoding="utf-8") as f:
    CARDS = json.load(f)

with open(os.path.join(_HERE, "meta", "comps.json"), encoding="utf-8") as f:
    COMPS = json.load(f)


def card(cid):
    """Card metadata for a card id, or None if unknown."""
    return CARDS.get(cid)


def card_name(cid):
    """Human-readable name for a card id (falls back to the id)."""
    c = CARDS.get(cid)
    return c["name"] if c else cid


def match_comps(board_ids):
    """Rank known comps by how many of their core/addon cards are on the board.

    Returns a list of dicts, best match first:
      {slug, name, core_hits, addon_hits, score}
    score = 2 * core_hits + addon_hits (core cards weigh more).
    """
    board = set(board_ids)
    results = []
    for slug, comp in COMPS.items():
        core_hits = [cid for cid in comp["core"] if cid in board]
        addon_hits = [cid for cid in comp.get("addons", []) if cid in board]
        if core_hits or addon_hits:
            results.append({
                "slug": slug,
                "name": comp["name"],
                "core_hits": core_hits,
                "addon_hits": addon_hits,
                "score": 2 * len(core_hits) + len(addon_hits),
            })
    results.sort(key=lambda r: -r["score"])
    return results


_HEROES = None


def hero_power(hero_name):
    """Hero-power text for a hero name, or None.

    Best-effort: exact (case-insensitive) name match against meta/heroes.json.
    Skin display names that don't match exactly return None.
    """
    global _HEROES
    if _HEROES is None:
        path = os.path.join(_HERE, "meta", "heroes.json")
        _HEROES = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for h in json.load(f):
                    if h.get("name"):
                        _HEROES[h["name"].lower()] = h.get("hero_power")
    if not hero_name:
        return None
    return _HEROES.get(hero_name.lower())
