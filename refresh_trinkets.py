#!/usr/bin/env python3
"""Refresh meta/trinkets.json and re-key meta/trinket_effects.json to log ids.

The 2026-09-16 Reno game exposed the failure: BOTH the player's trinkets
(Flaming Portrait BG35_MagicItem_156, Minion Bait BG30_MagicItem_973) were
absent from the DB, so the Greater pick was ranked on raw hsreplay stats
alone and recommended Timeworn Candelabra over the engine-perfect Portrait.

Root cause: the manual paste (meta/trinkets_raw.txt, parse_trinkets.py)
captured hsreplay's OLD 4-digit id space (BG30_MagicItem_3016) while the
log speaks 3-digit ids (BG30_MagicItem_301) — the whole Sous-Chef drift
family. Every id lookup missed; only the name fallback kept the DB alive.

This tool rebuilds the DB with LOG ids:
  - universe: old entries  +  every trinket id ever OFFERED in a local
    session's pick menus (DebugPrintEntityChoices) — the play-history
    superset, not hsreplay's all-seasons archive (418 ids; importing all
    of it would demand curating retired trinkets the coach can never see).
  - name/description: hearthstonejson cards.json (the hsreplay pages render
    them client-side; raw HTML carries none). Markup stripped to the old
    paste's plain-text shape.
  - guide + Lesser/Greater type: hsreplay's trinkets pages (react_context).
  - pick_rate / avg_placement / placement_distribution: rendered client-
    side, so headless-scraped entries carry the old DB's stats joined BY
    NAME; entries without history rank honestly as "no data" (choices.py
    guards pick_rate None).
  - trinket_effects.json is re-keyed old-id -> log-id through the name
    join; the card-text curation gate (test_all_trinkets_annotated) must
    stay bidirectional, so newly covered trinkets need hand-curated
    entries — the tool reports them, it does not invent them.

Usage:
    python refresh_trinkets.py [--hsjson-cache PATH] [--guides-cache PATH]

Idempotent: run after patches to pick up new offerings.
"""
import argparse
import glob
import json
import os
import re
import sys

import requests

from scrape_comps import HEARTHSTONEJSON_URL, _headers, _react_context

_HERE = os.path.dirname(os.path.abspath(__file__))
TRINKETS_PATH = os.path.join(_HERE, "meta", "trinkets.json")
EFFECTS_PATH = os.path.join(_HERE, "meta", "trinket_effects.json")
TRINKETS_PAGE = "https://hsreplay.net/battlegrounds/trinkets/{page}/"
MAGICITEM = re.compile(r"^(?:BG\d+)_MagicItem_\w+$")
CHOICE_OPT = re.compile(
    r"DebugPrintEntityChoices.*?cardId=(BG\d+_MagicItem_\w+)")


def _clean_text(text):
    """hsjson card text -> the old paste's plain-text shape."""
    text = re.sub(r"\[x\]\s*", "", text or "")
    text = re.sub(r"</?[bi]>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _offered_ids():
    """Every trinket id any local session ever put in a pick menu."""
    ids = set()
    for path in glob.glob(os.path.join(
            r"C:\Program Files (x86)\Hearthstone\Logs",
            "Hearthstone_*", "Power.log")):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = CHOICE_OPT.search(line)
                    if m:
                        ids.add(m.group(1))
        except OSError:
            continue
    return ids


def _hsreplay_guides(cache_path):
    """{id: {guide, type, tribes}} from both trinkets pages."""
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    out = {}
    for page in ("lesser", "greater"):
        url = TRINKETS_PAGE.format(page=page)
        resp = requests.get(url, headers=_headers(url), timeout=60)
        resp.raise_for_status()
        for rec in _react_context(resp):
            out.setdefault(rec["trinket_id"], {
                "guide": rec.get("trinket_guide") or None,
                "type": rec.get("trinket_type"),
                "tribes": rec.get("trinket_guide_favorable_tribes") or [],
            })
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


def _hsjson_cards(cache_path):
    """{id: (name, clean description)} for every MagicItem card."""
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    print("  downloading hearthstonejson cards.json ...")
    resp = requests.get(HEARTHSTONEJSON_URL, headers=_headers(), timeout=300)
    resp.raise_for_status()
    out = {}
    for card in resp.json():
        cid = card.get("id") or ""
        if not MAGICITEM.match(cid):
            continue
        name = card.get("name")
        if not name:
            continue  # unrevealed placeholders
        out[cid] = [name, _clean_text(card.get("text"))]
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hsjson-cache", default=os.path.join(
        _HERE, "meta", ".trinkets_hsjson_cache.json"))
    ap.add_argument("--guides-cache", default=os.path.join(
        _HERE, "meta", ".trinkets_guides_cache.json"))
    ap.add_argument("--dry-run", action="store_true",
                    help="report without writing")
    args = ap.parse_args()

    with open(TRINKETS_PATH, encoding="utf-8") as f:
        old_db = json.load(f)
    old_by_name = {r["name"]: r for r in old_db if r.get("name")}
    old_by_id = {r["id"]: r for r in old_db if r.get("id")}

    guides = _hsreplay_guides(args.guides_cache)
    cards = _hsjson_cards(args.hsjson_cache)
    offered = _offered_ids()
    print(f"old entries: {len(old_db)} | hsreplay guides: {len(guides)}"
          f" | offered in local logs: {len(offered)}")

    # name -> log ids (a name can hold several ids: Colorful Compass
    # tribe variants 426/426t share text and stats).
    name_to_ids = {}
    for cid in set(offered) | set(guides):
        card = cards.get(cid)
        if card:
            name_to_ids.setdefault(card[0], set()).add(cid)

    new_db = []
    rekey = {}    # old id -> {new log ids} (for the effects re-key)
    covered_names = set()
    for old in old_db:
        nm = old.get("name")
        ids = sorted(name_to_ids.get(nm, ()))
        entry = dict(old)
        if ids:
            covered_names.add(nm)
            entry["id"] = ids[0]
            rekey[old["id"]] = set(ids)
        entry["guide"] = old.get("guide") or next(
            (g["guide"] for i in ids if (g := guides.get(i)))
            , None)
        new_db.append(entry)

    added = []
    for cid in sorted(set(offered) - {e["id"] for e in new_db}):
        card = cards.get(cid)
        if not card:
            print(f"  !! offered id {cid} has no hearthstonejson card — skipped")
            continue
        name, desc = card
        prior = old_by_name.get(name) or {}
        g = guides.get(cid) or {}
        new_db.append({
            "id": cid,
            "name": name,
            "description": desc,
            "pick_rate": prior.get("pick_rate"),
            "avg_placement": prior.get("avg_placement"),
            "placement_distribution": prior.get("placement_distribution"),
            "guide": g.get("guide"),
            "type": g.get("type"),
        })
        added.append((cid, name))
    new_db.sort(key=lambda e: e.get("id") or "")

    # Re-key the curated effects through the name join. The fan-out only
    # targets ids that made it INTO the new DB — sibling variants that were
    # never offered must not become orphan annotations.
    db_ids = {e["id"] for e in new_db if e.get("id")}
    with open(EFFECTS_PATH, encoding="utf-8") as f:
        effects = json.load(f)
    new_effects = {}
    moved = unresolved = 0
    for key, val in effects.items():
        if key.startswith("_"):
            new_effects[key] = val
            continue
        ids = rekey.get(key)
        if ids is None:
            nm = (old_by_id.get(key) or {}).get("name")
            ids = set(name_to_ids.get(nm, ())) if nm else set()
        ids = ids & db_ids if ids else ids
        if ids:
            for i in sorted(ids):
                new_effects.setdefault(i, val)
            moved += 1
        else:
            new_effects[key] = val
            unresolved += 1

    annotated = {k for k in new_effects if not k.startswith("_")}
    need = [e["id"] for e in new_db
            if e.get("id") and e["id"] not in annotated]
    print(f"trinkets.json: {len(old_db)} -> {len(new_db)} entries "
          f"({len(added)} added)")
    for cid, name in added:
        print(f"   + {cid} {name}")
    print(f"trinket_effects.json: {moved} re-keyed, {unresolved} unresolved")
    print(f"NEED CURATION ({len(need)}):")
    for cid in need:
        print(f"   * {cid} {(cards.get(cid) or ('?',''))[0]}")
    if args.dry_run:
        print("dry run — nothing written")
        return 0
    with open(TRINKETS_PATH, "w", encoding="utf-8") as f:
        json.dump(new_db, f, ensure_ascii=False, indent=1)
    with open(EFFECTS_PATH, "w", encoding="utf-8") as f:
        json.dump(new_effects, f, ensure_ascii=False, indent=1)
    print("written:", TRINKETS_PATH)
    print("written:", EFFECTS_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
