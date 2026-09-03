#!/usr/bin/env python3
"""Pre-fetch card art into img_cache/ for the coaching UI.

Sources the 256x card renders from art.hearthstonejson.com (free, no key).
Coverage is PARTIAL for Battlegrounds: heroes (TB_BaconShop_HERO_*) and
trinkets (BGxx_MagicItem_*) render reliably; only ~35% of pool minions and
~26% of tavern spells do (current-set BG-only cards are missing from the
renderer). The UI falls back to name-only for cache misses, and a fuller
extraction (UnityPy over the local game client) can drop into the same
cache later — img_cache/<cardId>.png is the only contract.

The id set: every id in meta/minions.json + meta/tavern_spells.json, plus
hero and trinket ids observed in recent session logs (those DBs are
name-keyed — log ids are the ground truth).

Usage:
  python fetch_art.py            # download missing art, print a report
  python fetch_art.py --force    # re-download even if cached
"""
import concurrent.futures as cf
import glob
import json
import os
import re
import sys
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(_HERE, "img_cache")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
ART = "https://art.hearthstonejson.com/v1/render/latest/enUS/256x/{}.png"
LOG_GLOB = r"C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_*\Power.log"

# Hero/trinket id families as they appear in logs (heroes.json has NO ids;
# trinket log ids are patch-drifted vs trinkets.json).
HERO_ID = re.compile(r"^(?:TB_BaconShop_HERO_\d+|BG\d+_HERO_\d+)$")
TRINKET_ID = re.compile(r"^BG\d+_MagicItem_\w+$")


def _log_ids(limit=3):
    """Hero + trinket card ids from the most recent session logs."""
    ids = set()
    for path in sorted(glob.glob(LOG_GLOB), key=os.path.getmtime,
                       reverse=True)[:limit]:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    for m in re.finditer(r"cardId=(\w+)", line):
                        cid = m.group(1)
                        if HERO_ID.match(cid) or TRINKET_ID.match(cid):
                            ids.add(cid)
        except OSError:
            continue
    return ids


def _pool_ids():
    ids = set()
    for name in ("minions.json", "tavern_spells.json"):
        path = os.path.join(_HERE, "meta", name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            items = data if isinstance(data, list) else list(data.values())
            ids |= {x.get("id") for x in items if isinstance(x, dict) and x.get("id")}
    return ids


def _fetch(cid, force=False):
    dest = os.path.join(CACHE, f"{cid}.png")
    if os.path.exists(dest) and os.path.getsize(dest) > 0 and not force:
        return "cached"
    try:
        req = urllib.request.Request(ART.format(cid), headers=UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        with open(dest, "wb") as f:
            f.write(data)
        return "fetched"
    except Exception:
        return "missing"  # 404s are expected for current-set BG-only cards


def main():
    force = "--force" in sys.argv[1:]
    os.makedirs(CACHE, exist_ok=True)
    ids = sorted(_pool_ids() | _log_ids())
    print(f"probing {len(ids)} card ids -> {CACHE}")
    with cf.ThreadPoolExecutor(16) as ex:
        results = dict(zip(ids, ex.map(lambda c: _fetch(c, force), ids)))
    got = sum(1 for r in results.values() if r != "missing")
    for label, r in (("fetched", "fetched"), ("cached", "cached")):
        n = sum(1 for v in results.values() if v == r)
        if n:
            print(f"  {label}: {n}")
    print(f"art available for {got}/{len(ids)} ids "
          f"({len(results) - got} missing from the renderer — UI falls "
          f"back to names)")
    return 0


if __name__ == "__main__":
    sys.exit(main())