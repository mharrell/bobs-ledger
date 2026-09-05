r"""Lazy, cached accessors for the curated meta DB — the ONE place that opens
meta/*.json.

Before consolidation every module hand-rolled its own loader (35+ raw
json.load sites, six naming schemes, three different missing-file behaviors —
analysis/code_audit_2026-09-04.md §2). Rules here:

  - lazy: nothing touches disk until an accessor is called (the old eager
    import-time CARDS/COMPS load made `import meta` fail for tools whose
    checkout lacked the DBs);
  - cached: the DBs only change on a patch (patch_notes.py --apply,
    extend_pool.py --apply) — standalone processes, so a within-process stale
    cache is not a real scenario;
  - forgiving: a missing or corrupt file yields an empty collection (with a
    one-line warning), never a crash — a corrupt comp DB must not kill the
    live loop;
  - shared: accessors return the cached object. Callers must not mutate it
    (value functions and the UI only read; filter_* builds new dicts).

Accessors:
    minions()  -> list of minion records (meta/minions.json)
    spells()   -> list of tavern-spell records (meta/tavern_spells.json)
    comps()    -> dict slug -> comp record (meta/comps.json)
    cards()    -> dict card id -> card record (meta/cards.json)
    trinkets() / heroes() -> list of records
    items(name) -> list form of any meta file (a dict-of-records is tolerated)
"""
import functools
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


@functools.lru_cache(maxsize=None)
def _raw(name):
    path = os.path.join(_HERE, "meta", name)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f"meta: {name} unreadable ({e}) — continuing without it",
              file=sys.stderr)
        return None


def _items(name):
    data = _raw(name)
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        return [d for d in data.values() if isinstance(d, dict)]
    return []


def minions():
    return _items("minions.json")


def spells():
    return _items("tavern_spells.json")


def comps():
    return _raw("comps.json") or {}


def cards():
    return _raw("cards.json") or {}


def trinkets():
    return _items("trinkets.json")


def heroes():
    return _items("heroes.json")


def items(name):
    """Records of any meta file as a list (dict-of-records tolerated)."""
    return _items(name)


def hero_power(hero_name):
    """Hero-power text for a hero name, or None.

    Best-effort: exact (case-insensitive) name match against meta/heroes.json.
    Skin display names that don't match exactly return None.
    """
    if not hero_name:
        return None
    for h in heroes():
        if (h.get("name") or "").lower() == hero_name.lower():
            return h.get("hero_power")
    return None