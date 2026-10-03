r"""Own-side pool accounting for card availability (analysis/pool_availability.md).

The Battlegrounds minion pool is SHARED lobby-wide — 18/15/13/11/9/6/5 copies
per tier 1-7. Phase 1 accounts OUR side exactly: copies we currently hold
(board + hand) are not in the pool and can't be offered again until sold.
A golden entity counts as 3 copies for pool purposes (goldens never combine,
but the pool was drained 3 copies to make one). Opponent holdings join in
Phase 2 (card-level scout snapshots keyed by seat).

Honesty limits — these must ride into any label shown to the player:
  - `left()` is "copies beyond your own holdings", NOT lobby availability:
    other seats still hold copies this side of the ledger can't see yet.
  - State-based accounting: an effect-created copy (transform, discover,
    Dark-Gift golden) sits in your holdings though it never drained the
    pool, so `left()` can undercount by that copy. Bought/sold — the exact
    pool events — are captured correctly by construction.
  - Combat deaths are irrelevant by construction (boards reset after
    combat; only buys/sells touch the pool).
"""
from collections import Counter

from meta import pool_sizes, minions

# Patch-independent fallback; meta/pool.json overrides when present.
POOL_FALLBACK = {1: 18, 2: 15, 3: 13, 4: 11, 5: 9, 6: 6, 7: 5}


def base_cid(cid):
    """Strip the golden suffix — the pool counts base cards."""
    return cid[:-2] if isinstance(cid, str) and cid.endswith("_G") else cid


def sizes():
    """{tier: copies} — meta/pool.json first, built-in table as fallback."""
    merged = dict(POOL_FALLBACK)
    merged.update(pool_sizes())
    return merged


_TIER_MAP = None


def _tier_map():
    """card id -> tavern tier (lazy; minions.json only changes on a patch)."""
    global _TIER_MAP
    if _TIER_MAP is None:
        _TIER_MAP = {m.get("id"): m.get("tier") for m in minions()}
    return _TIER_MAP


def tier_of(cid):
    return _tier_map().get(base_cid(cid))


def own_holdings(board, hand=()):
    """Counter of base card id -> copies we hold right now.

    Both lists are live-state minion dicts with "card" and a "golden" flag
    (some paths carry the flag on the id instead — `_G` suffix — so both
    count). The hand is part of the holding: a carried minion is as out of
    the pool as a board one.
    """
    held = Counter()
    for m in list(board or []) + list(hand or []):
        cid = m.get("card")
        if not cid:
            continue
        golden = bool(m.get("golden")) or base_cid(cid) != cid
        held[base_cid(cid)] += 3 if golden else 1
    return held


def left(cid, held, sizes_map=None):
    """Copies of `cid` in the shared pool beyond what we hold — or None when
    the card's tier is unknown (no opinion: unknown ≠ zero)."""
    tier = tier_of(cid)
    if not tier:
        return None
    table = sizes_map if sizes_map is not None else sizes()
    total = table.get(tier)
    if total is None:
        return None
    return max(0, total - held.get(base_cid(cid), 0))


def chip(cid, held, sizes_map=None):
    """The Market-tile availability label, honest by construction.

    "pool dry" / "last pool copy" / "N pool left" — the wording always
    names the POOL, never the lobby: until phase 2 subtracts opponent
    holdings this is a floor on availability, not a lobby total. None when
    we have no opinion (unknown tier)."""
    n = left(cid, held, sizes_map)
    if n is None:
        return None
    if n == 0:
        return "pool dry"
    if n == 1:
        return "last pool copy"
    return f"{n} pool left"
