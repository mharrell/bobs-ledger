#!/usr/bin/env python3
"""Validate the meta/ JSON files and the tribe vocabulary.

Guards against the class of silent data bugs that once made every tribe
comparison in the coach dead (comps.json said "Elementals" while minions.json
said "ELEMENTAL" — nothing intersected, so the value function's comp-context
terms and the banned-tribe penalty all misfired, unnoticed).

Checks (exit 1 on any ERROR):
- Every `tribe` field in comps.json / cards.json / minions.json is canonical
  (see tribes.py) or a compound of canonical parts.
- The comp-tribe vocabulary and the minion-tribe vocabulary actually
  intersect — the check that would have caught the split-vocabulary bug.
Warnings (printed, nonfatal):
- comps missing `tribe` or `core`;
- core/addon card ids not found in cards.json or minions.json;
- duplicate names within any meta JSON (e.g. dark gifts share names across
  tiers).

Usage: python check_meta.py            # validate meta/
       python check_meta.py --quiet    # errors only
"""
import argparse
import json
import os
import sys
from collections import Counter

from tribes import DISPLAY_TRIBES, normalize

_HERE = os.path.dirname(os.path.abspath(__file__))
META = os.path.join(_HERE, "meta")


def _load(name):
    path = os.path.join(META, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _main_reconfigure_streams():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _tribe_vocabulary(entries, path, errors, warnings):
    """Every tribe value must canonicalize to canonical-or-compound; warn on
    unknown-compound shapes and return the set of canonical tribe atoms."""
    vocab = set()
    for item in entries:
        t = item.get("tribe") if isinstance(item, dict) else None
        if t is None:
            continue
        norm = normalize(t)
        if norm != t and t not in ("All", "Neutral"):
            # normalize() must be idempotent on canonical data — a value that
            # changes under it is off-vocabulary (the historical bug).
            errors.append(f"{path}: non-canonical tribe {t!r} (should be "
                          f"{norm!r})" if norm else
                          f"{path}: tribe {t!r} normalizes away (All/Neutral)")
            continue
        if not t:
            continue
        if norm is None:
            warnings.append(f"{path}: tribe {t!r} is All/Neutral in a tribe "
                            f"field — use null instead")
            continue
        for part in norm.split("/"):
            if part not in DISPLAY_TRIBES:
                errors.append(f"{path}: tribe {t!r} is not canonical "
                              f"({part!r} not in " f"{DISPLAY_TRIBES})")
            else:
                vocab.add(part)
    return vocab


def main():
    _main_reconfigure_streams()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quiet", action="store_true", help="print errors only")
    args = ap.parse_args()

    errors, warnings = [], []
    comps = _load("comps.json") or {}
    cards = _load("cards.json") or {}
    minions = _load("minions.json") or []

    # --- Tribe vocabulary: one canonical language across all three files ----
    comp_tribes = _tribe_vocabulary(list(comps.values()), "comps.json",
                                    errors, warnings)
    minion_tribes = _tribe_vocabulary(minions, "minions.json",
                                      errors, warnings)
    card_tribes = _tribe_vocabulary(list(cards.values()), "cards.json",
                                    errors, warnings)
    # The intersection check: comp tribes must exist in the minion pool
    # vocabulary (comp cards come from the tavern pool).
    dead = {t for t in comp_tribes} - minion_tribes
    if comp_tribes and not (comp_tribes & minion_tribes):
        errors.append(
            "comp tribes and minion tribes do not intersect at all — the "
            f"split-vocabulary bug (comp={sorted(comp_tribes)} "
            f"vs minion={sorted(minion_tribes)})")
    elif dead:
        warnings.append(
            f"comp tribes absent from the minion pool vocabulary: "
            f"{sorted(dead)} (all-tribe/compound comps excluded)")

    # --- comps schema -------------------------------------------------------
    comp_ids = set()
    for slug, comp in comps.items():
        if not comp.get("tribe"):
            warnings.append(f"comps.json: {slug} has no tribe field")
        if not comp.get("core"):
            warnings.append(f"comps.json: {slug} has no core cards")
        comp_ids.update(c for c in comp.get("core", []))
        comp_ids.update(c for c in comp.get("addons", []))
    minion_ids = {m.get("id") for m in minions}
    card_ids = set(cards)
    unknown = comp_ids - minion_ids - card_ids
    if unknown:
        warnings.append(f"comps.json: {len(unknown)} core/addon card ids not "
                        f"in minions.json/cards.json: {sorted(unknown)[:8]}...")

    # --- duplicate names (patch_notes.py indexes by name: duplicates are ---
    # --- silently aliased) --------------------------------------------------
    for name, filename in (("dark_gifts.json", "dark_gifts"),
                           ("heroes.json", "heroes"),
                           ("trinkets.json", "trinkets"),
                           ("tavern_spells.json", "tavern_spells")):
        data = _load(name)
        if not data:
            continue
        items = data if isinstance(data, list) else [
            v for v in data.values() if isinstance(v, dict)]
        counts = Counter(
            (i.get("name") or "").lower() for i in items if isinstance(i, dict))
        dupes = sorted(n for n, c in counts.items() if c > 1)
        if dupes:
            warnings.append(f"{name}: duplicate names {dupes} (patch_notes.py "
                            f"name index aliases these — resolve by tier)")

    if not args.quiet:
        for w in sorted(set(warnings)):
            print(f"WARN: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"meta OK: {len(comps)} comps, {len(cards)} cards, {len(minions)} "
          f"minions; comp tribes {sorted(comp_tribes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())