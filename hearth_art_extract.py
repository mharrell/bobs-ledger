#!/usr/bin/env python3
"""Extract card art from the local Hearthstone client into img_cache/.

HearthstoneJSON's render service lags the current patch: returning minions
(old ids) and most heroes render, but brand-new minions, the newest heroes,
and ALL trinkets (BGxx_MagicItem_NNN) 404 upstream — and hearthstone.wiki.gg
is Cloudflare-blocked. The game's own assets carry 100% of the art:

  carddef-*.unity3d    CardDef objects: card id (GameObject name) ->
                       portrait art asset name (m_PortraitTexturePath,
                       e.g. "BG-048_M.tif:<guid>")
  cardtexture-*.unity3d  Texture2D objects named by that art asset

This builds the id -> asset map from the carddefs, then exports each wanted
id's texture into img_cache/<id>.png. Renders fetched from HearthstoneJSON
(coach_ui's on-demand fetch) are left alone — those carry the framed card
layout; the client textures are the raw art portrait. Note HS is Unity
6000.3.11f1 but the bundles carry no embedded version, so a fallback version
is required.

Usage:
  python hearth_art_extract.py                # extract everything wanted
  python hearth_art_extract.py --ids BG36_204 BG30_MagicItem_434
  python hearth_art_extract.py --list         # scan + report, no writes
"""
import argparse
import glob
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from config import HS_DATA_DIR, HS_LOG_GLOB  # noqa: E402

CACHE = os.path.join(_HERE, "img_cache")

# Card ids in the defs: BG36_204, BG30_MagicItem_434, BG26_HERO_104, BGS_012,
# BG_LOE_077. Golden defs may share the base id (the UI strips _G anyway).
ID_RE = re.compile(r"^(?:BG\d+_[A-Za-z0-9_]+|BGS_\d+|BG_[A-Z]+_\d+)$")

# UnityPy is imported lazily (_unitypy) rather than at module level: it's an
# optional dep, and the eager import made `import hearth_art_extract` — and the
# test suite's test_art_extract — hard-fail when it isn't installed.
def _unitypy():
    import UnityPy
    UnityPy.config.FALLBACK_UNITY_VERSION = "6000.3.11f1"
    return UnityPy


def _meta_ids():
    """Every card id the UI could display, from the meta DBs."""
    wanted = set()

    def _load(name, key="id"):
        try:
            with open(os.path.join(_HERE, "meta", name), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        return [item.get(key) for item in data if isinstance(item, dict)]

    for key in ("id", "card_id"):
        wanted.update(i for i in _load("minions.json", key) if i)
        wanted.update(i for i in _load("tavern_spells.json", key) if i)
        wanted.update(i for i in _load("trinkets.json", key) if i)
    # heroes.json has no id field (names only) — hero ids come from the logs.
    return wanted


def _log_ids():
    """Card ids seen in any Hearthstone session log (heroes/trinkets included)."""
    wanted = set()
    for log in glob.glob(HS_LOG_GLOB):
        try:
            with open(log, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        for m in re.finditer(r"cardId=((?:BG|BGS|EBG|BG_)[A-Za-z0-9_]+)", text):
            wanted.add(m.group(1))
    return wanted


def _art_map():
    """card id -> portrait art GUID, from all carddef bundles.

    m_PortraitTexturePath is "<asset>.tif:<guid>" and the cardtexture bundle
    containers are keyed by that GUID — the asset NAME family differs between
    content generations (legacy "BG-048_M" vs current "BG30-063_HP"), so the
    GUID is the stable address.
    """
    mapping = {}
    bundles = sorted(glob.glob(os.path.join(HS_DATA_DIR, "carddef*.unity3d")))
    for path in bundles:
        try:
            env = _unitypy().load(path)
        except Exception as e:  # noqa: BLE001
            print(f"  (skip {os.path.basename(path)}: {e})")
            continue
        go_names = {}
        for obj in env.objects:
            if obj.type.name == "GameObject":
                try:
                    go_names[obj.path_id] = obj.read().m_Name
                except Exception:  # noqa: BLE001
                    pass
        for obj in env.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            try:
                tree = obj.read_typetree()
            except Exception:  # noqa: BLE001
                continue
            go = (tree.get("m_GameObject") or {}).get("m_PathID")
            cid = go_names.get(go, "")
            if not ID_RE.match(cid) or cid in mapping:
                continue
            pt = tree.get("m_PortraitTexturePath") or ""
            if pt and ":" in pt:
                mapping[cid] = pt.split(":")[-1]
    return mapping


def extract(only_ids=None, write=True):
    os.makedirs(CACHE, exist_ok=True)
    wanted = _meta_ids() | _log_ids()
    if only_ids:
        wanted = set(only_ids)
    missing = {cid for cid in wanted
               if not os.path.exists(os.path.join(CACHE, f"{cid}.png"))}
    print(f"wanted {len(wanted)}, missing {len(missing)}")

    art = _art_map()
    print(f"carddef mapping: {len(art)} ids")
    # Golden ids resolve to their base id's art (the UI strips _G).
    for gid in [c for c in missing if c.endswith("_G")]:
        missing.discard(gid)
        missing.add(gid[:-2])
    need = {cid: art[cid] for cid in missing if cid in art}
    unmapped = [cid for cid in missing if cid not in art]
    print(f"need {len(need)} textures; {len(unmapped)} ids have no carddef")

    # Any bundle can hold the textures (content families differ), so scan the
    # whole set once; each needed GUID is looked up in the bundle container.
    bundles = sorted(glob.glob(os.path.join(HS_DATA_DIR, "*.unity3d")))
    print(f"scanning {len(bundles)} bundles for {len(need)} GUIDs...")
    found = 0
    for path in bundles:
        if not need:
            break
        try:
            env = _unitypy().load(path)
        except Exception as e:  # noqa: BLE001
            print(f"  (skip {os.path.basename(path)}: {e})")
            continue
        container = env.container
        if not container:
            continue
        for guid in [g for g in need.values() if g in container]:
            cid = next(c for c, g in need.items() if g == guid)
            try:
                data = container[guid].read()
                img = data.image
            except Exception as e:  # noqa: BLE001
                print(f"  (decode failed for {cid}: {e})")
                continue
            if write:
                try:
                    # The UI shows 64px thumbs with 256px hover zoom — full
                    # 512px client textures quadruple the repo for nothing.
                    if max(img.size) > 256:
                        img = img.resize((256, 256))
                    img.save(os.path.join(CACHE, f"{cid}.png"))
                except Exception as e:  # noqa: BLE001
                    print(f"  (export failed for {cid}: {e})")
                    continue
            del need[cid]
            found += 1
            if found % 50 == 0:
                print(f"  {found} extracted so far...")
    print(f"done: {found} new art files")
    still = [cid for cid in missing
             if not os.path.exists(os.path.join(CACHE, f"{cid}.png"))]
    print(f"still missing: {len(still)}")
    for cid in sorted(still)[:20]:
        why = "no carddef" if cid not in art else f"no texture ({art[cid]})"
        print(f"    {cid} ({why})")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", help="extract only these card ids")
    ap.add_argument("--list", action="store_true",
                    help="scan and report without writing")
    args = ap.parse_args()
    sys.exit(extract(only_ids=args.ids or None, write=not args.list))