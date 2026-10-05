#!/usr/bin/env python3
"""Pre-fetch card PORTRAITS into img_cache/ for the coaching UI.

Sources the square raw art from art.hearthstonejson.com (free, no key) — the
same kind and the same source coach_ui fetches on demand, so a pre-populated
cache and a lazily filled one look identical. The TOOLTIP renders (framed
cards WITH text, 256x388) are the other kind and live in img_cache/card/;
coach_ui fetches those on hover, and they are deliberately not this tool's job
(fetching them for every pool id would triple the download for art nobody has
hovered).

Coverage (probed per id class 2026-10-04): this URL answers for EVERY class
that has art at all — minions, tavern spells, trinkets, tokens, heroes and
golden `_G` ids — because it serves the original art rather than a rendered
card, which is what the old `v1/render/...` path got wrong: that one 404s
every current-patch Battlegrounds card (minions, spells, trinkets, tokens) and
serves returning ids, heroes and golden, so a fresh install drew placeholders
across most of the board. The URLs now come from coach_ui so the two tools
cannot drift apart again.

The UI falls back to name-only for the ids that have no art anywhere
(unreleased machinery, e.g. BG36_MagicItem_417te); a fuller offline extraction
(UnityPy over the local game client, hearth_art_extract.py) drops into the
same cache — img_cache/<cardId>.png is the only contract.

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

from config import HS_LOG_GLOB as LOG_GLOB
from coach_ui import ART_CACHE as CACHE, PORTRAIT_URLS, RENDER_UA

_HERE = os.path.dirname(os.path.abspath(__file__))

# coach_ui holds the UA as a bare string and wraps it per request; this module
# wants the headers dict. Deriving it keeps ONE copy of the value, and the
# shape is asserted by a test — importing the string into the dict slot made
# every request die with "'str' object has no attribute 'items'" (2026-10-04).
UA = {"User-Agent": RENDER_UA}

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


def portrait_urls(cid):
    """The sources to try for cid's portrait, in order (coach_ui's chain)."""
    return [url.format(cid) for url in PORTRAIT_URLS]


def _fetch(cid, force=False):
    dest = os.path.join(CACHE, f"{cid}.png")
    if os.path.exists(dest) and os.path.getsize(dest) > 0 and not force:
        return "cached"
    for url in portrait_urls(cid):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                data = r.read()
        except Exception:
            continue  # try the next source, exactly like coach_ui does
        with open(dest, "wb") as f:
            f.write(data)
        return "fetched"
    return "missing"  # no source has it: unreleased machinery, not a bug


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
    print(f"portrait art for {got}/{len(ids)} ids "
          f"({len(results) - got} have none anywhere — UI falls back to names)")
    return 0


if __name__ == "__main__":
    sys.exit(main())