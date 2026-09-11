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

Membership questions ("is this minion a Demon?") go through `matches()` /
`overlaps()` / `parts()` — never `normalize(x) == normalize(y)`: equality
drops compound tribes ("Demon/Quilboar" vs comp "Demon") and collapses
Amalgams (`normalize("All")` -> None reads as untribed).
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

#: The meta-DB value for a minion that counts as EVERY tribe (Amalgam-class:
#: Gatekeeper Amalgam, Motley Phalanx). Deliberately distinct from None, which
#: means *untribed* — collapse Amalgams to None and every tribe-fit term
#: (W_TRIBE, comp damping, Butchering Undead targeting) misreads them.
ALL_MARKER = "All"


def tribes_from_races(races):
    """Raw race list (log CARDRACE tags or hearthstonejson 'races') -> the
    canonical meta `tribe` field.

    ["DEMON", "QUILBOAR"] -> "Demon/Quilboar" (compounds preserved — the old
    `normalize(races[0])` silently dropped every tribe after the first);
    ["ALL"] -> "All"; [] / None -> None (genuinely untribed).
    """
    races = [r for r in (races or []) if r and r != "NEUTRAL"]
    if not races:
        return None
    if "ALL" in races:
        return ALL_MARKER
    return normalize("/".join(races))


def parts(tribe):
    """Canonical tribe parts of a meta/log tribe field.

    "All" -> every display tribe (Amalgam counts as each of them);
    "Demon/Quilboar" -> ["Demon", "Quilboar"]; "Elemental" -> ["Elemental"];
    None / neutral / unknown -> [] (an untribed card matches nothing).
    """
    if tribe == ALL_MARKER:
        return list(DISPLAY_TRIBES)
    norm = normalize(tribe)
    return norm.split("/") if norm else []


def matches(card_tribe, want):
    """Membership lookup: does a card's tribe field include tribe `want`?

    `want` may be any canonical form ("UNDEAD", "Undead", "Demon/Quilboar" —
    any part of a compound want counts). All-tribe cards match everything
    (even an unknown tribe name); untribed cards match nothing.
    """
    want_parts = parts(want)
    return bool(want_parts) and bool(set(parts(card_tribe)) & set(want_parts))


def overlaps(a, b):
    """Do two tribe fields share any tribe?

    The general fit test (minion vs comp, board vs spell target): "All"
    overlaps any tribed field, compounds overlap on any shared part, and an
    untribed field overlaps nothing.
    """
    return bool(set(parts(a)) & set(parts(b)))


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