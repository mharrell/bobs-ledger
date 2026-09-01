"""Canonical tribe vocabulary.

Historically three tribe conventions drifted apart: comps.json carried plural
display names ("Elementals"), minions.json + the Power.log CARDRACE tag carried
raw uppercase ("ELEMENTAL"), and bans.canon() emitted singular titles with a
Mech special case ("Mech"). They never intersected, so every cross-file tribe
comparison silently failed. This module is the single mapping; the canonical
form is the singular display name matching cards.json and the bans output:

  Elemental, Mech, Beast, Demon, Dragon, Murloc, Naga, Pirate, Quilboar, Undead

Use `canon()` for raw log values (ALL_TRIBES members) and `normalize()` for
card/meta entries (single, compound "Demon/Quilboar", "All"/"Neutral" -> None).
"""
CANON = {
    "MECHANICAL": "Mech",
    "ALL": None,       # all-tribe cards are never banned
    "NEUTRAL": None,   # neutral cards are never banned
    # Legacy plural forms from the pre-canonicalization data ("Elementals" etc.).
    "BEASTS": "Beast", "DEMONS": "Demon", "ELEMENTALS": "Elemental",
    "MECHS": "Mech", "MURLOCS": "Murloc", "NAGAS": "Naga", "PIRATES": "Pirate",
}

ALL_TRIBES = [
    "BEAST", "DEMON", "DRAGON", "ELEMENTAL", "MECHANICAL",
    "MURLOC", "NAGA", "PIRATE", "QUILBOAR", "UNDEAD",
]


def canon(tribe):
    """Raw log tribe name -> canonical display name (MECHANICAL -> Mech)."""
    if tribe in CANON:
        return CANON[tribe]
    return tribe.title()


#: Canonical display names, in roster order — for UI text and "banned:" lists.
DISPLAY_TRIBES = [canon(t) for t in ALL_TRIBES]


def normalize(value):
    """A tribe field from any meta file / card DB -> canonical form.

    Handles single tribes ("ELEMENTAL", "Elemental"), compounds separated by
    "/"/" " ("DEMON_QUILBOAR" is never a raw string; "Demon/Dragon" passes
    through with each part canonicalized), and the never-banned markers
    ("All", "Neutral", "ALL", None) which normalize to None.
    """
    if not value:
        return None
    if value in ("All", "ALL", "Neutral", "NEUTRAL"):
        return None
    parts = [p for p in str(value).replace(" ", "/").split("/") if p]
    if len(parts) > 1:
        return "/".join(canon(p.upper()) for p in parts)
    return canon(value.upper())


def is_banned(tribe, allowed):
    """Is `tribe` (any form) excluded by the allowed canonical set?

    Fail open: unknown tribes, or no/empty ban info (`allowed` None or
    empty), are never banned — unknown must not look like "all tribes banned".
    Compound tribes are playable if either part is allowed.
    """
    if not tribe or not allowed:
        return False
    norm = normalize(tribe)
    if norm is None:
        return False
    parts = set(norm.split("/"))
    if not parts <= set(DISPLAY_TRIBES):
        return False  # an unknown tribe can't be judged -> fail open
    return not (parts & set(allowed))