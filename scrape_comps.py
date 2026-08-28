#!/usr/bin/env python3
"""Scrape hsreplay.net Battlegrounds comp pages into meta/comps.json.

Implements the recipe from the hsreplay-transcripts memory note, corrected
against the live site (2026-08):

- The comp list lives in the index page's
  `<script type="application/json" id="react_context">`; each record has
  `comp_slug` and a numeric `comp_id`.
- The individual comp page URL uses the **numeric id**, not the slug:
  `https://hsreplay.net/battlegrounds/comps/<id>/` (the slug URL 404s).
- The individual page's record uses `comp_`-prefixed keys: `comp_name`,
  `comp_tier` (1=S/2=A/3=B), `comp_difficulty` (1/2/3), `comp_core_cards` /
  `comp_addon_cards` (dbfIds), `comp_how_to_play`, `comp_when_to_commit`,
  `comp_common_enablers`, `comp_summary`, `comp_representative_card`.
- `comp_when_to_commit` / `comp_common_enablers` use `[[Card Name||dbfId]]`
  wiki-links; these are stripped to plain card names.
- dbfIds map to BG ids (e.g. "BG36_352") via api.hearthstonejson.com.
- Video links are NOT in the HTML; they come from
  `GET /api/v1/youtube/affiliates/links/?prefix=battlegrounds/comps/<id>/`
  (needs a browser User-Agent + `Referer` header).

The page provides `summary` and `representative_card`; only `tribe` and `guide`
are hand-added. This script merges into meta/comps.json and preserves those
hand-added fields, so re-scraping on a patch won't clobber them.

Usage:
  python scrape_comps.py <comp_id_or_slug> [more...] [--youtube] [--cards-cache FILE]
  python scrape_comps.py --top N [--prune] [--youtube] [--cards-cache FILE]

  comp_id_or_slug  a numeric comp id (e.g. 20) or a slug (e.g.
                   "nagas-groundbreaker"); slugs are resolved via the index.
  --top N          instead of explicit ids, scrape the top N *visible* comps
                   (hidden/archived comps are filtered out), ranked by tier
                   then tier_rank.
  --prune          (with --top) remove comps from comps.json that are no longer
                   in the current top-N visible set. Off by default.
  --youtube        also fetch the YouTube affiliate links for each comp
  --cards-cache    where to cache the hearthstonejson card list (default
                   .cards_cache.json next to this script)
"""
import argparse
import json
import os
import re
import sys

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
COMPS_PATH = os.path.join(_HERE, "meta", "comps.json")
DEFAULT_CARDS_CACHE = os.path.join(_HERE, ".cards_cache.json")

# Plain curl gets 403; a browser UA is required.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
COMPS_INDEX_URL = "https://hsreplay.net/battlegrounds/comps/"
COMP_PAGE_URL = "https://hsreplay.net/battlegrounds/comps/{id}/"
YOUTUBE_LINKS_URL = (
    "https://hsreplay.net/api/v1/youtube/affiliates/links/"
    "?prefix=battlegrounds/comps/{id}/"
)
HEARTHSTONEJSON_URL = "https://api.hearthstonejson.com/v1/latest/enUS/cards.json"

# Comp-page tier/difficulty are 1/2/3; the meta DB uses S/A/B and Easy/Med/Hard.
TIER_MAP = {1: "S", 2: "A", 3: "B"}
DIFFICULTY_MAP = {1: "Easy", 2: "Medium", 3: "Hard"}

# Hand-added fields the page does NOT provide — preserved across re-scrapes.
HAND_ADDED_FIELDS = ("tribe", "guide")

# [[Card Name||dbfId]] wiki-link used in when_to_commit / common_enablers.
WIKILINK_RE = re.compile(r"\[\[([^|\]]+)\|\|(\d+)\]\]")


def _headers(referer=None):
    h = {"User-Agent": BROWSER_UA}
    if referer:
        h["Referer"] = referer
    return h


def _react_context(resp):
    """Extract and parse the react_context JSON from a page response."""
    m = re.search(
        r'<script type="application/json" id="react_context">(.*?)</script>',
        resp.text,
        re.DOTALL,
    )
    if not m:
        raise RuntimeError(f"no react_context found on {resp.url}")
    return json.loads(m.group(1))


def _find_comp_record(data):
    """Recursively find the dict that holds a comp record.

    The react_context blob nests comp records at an unknown depth; search for a
    dict that carries `comp_core_cards` (the record's signature key).
    """
    if isinstance(data, dict):
        if "comp_core_cards" in data:
            return data
        for v in data.values():
            found = _find_comp_record(v)
            if found is not None:
                return found
    elif isinstance(data, list):
        for v in data:
            found = _find_comp_record(v)
            if found is not None:
                return found
    return None


def _all_comp_records(data):
    """Yield every comp record dict in the blob (for the index page)."""
    if isinstance(data, dict):
        if "comp_core_cards" in data:
            yield data
        for v in data.values():
            yield from _all_comp_records(v)
    elif isinstance(data, list):
        for v in data:
            yield from _all_comp_records(v)


def resolve_comp_id(comp_id_or_slug):
    """Return the numeric comp id for a slug (or pass through a numeric id)."""
    if str(comp_id_or_slug).isdigit():
        return int(comp_id_or_slug)
    resp = requests.get(COMPS_INDEX_URL, headers=_headers(), timeout=60)
    resp.raise_for_status()
    data = _react_context(resp)
    for rec in _all_comp_records(data):
        if rec.get("comp_slug") == comp_id_or_slug:
            return rec["comp_id"]
    raise RuntimeError(f"slug '{comp_id_or_slug}' not found on the comps index")


def visible_top_comps(n):
    """Return [(comp_id, comp_slug)] for the top n *visible* comps.

    Hidden/archived comps (comp_hidden=True) are filtered out — they're stale
    and not shown on the tier list. The rest are ranked by tier then tier_rank.
    """
    resp = requests.get(COMPS_INDEX_URL, headers=_headers(), timeout=60)
    resp.raise_for_status()
    data = _react_context(resp)
    visible = [c for c in _all_comp_records(data) if not c.get("comp_hidden")]
    visible.sort(key=lambda c: (c.get("comp_tier", 9), c.get("comp_tier_rank", 999)))
    return [(c["comp_id"], c["comp_slug"]) for c in visible[:n]]


def fetch_comp_page(comp_id):
    """Return the parsed react_context JSON for a comp page."""
    url = COMP_PAGE_URL.format(id=comp_id)
    resp = requests.get(url, headers=_headers(), timeout=60)
    resp.raise_for_status()
    return _react_context(resp)


def load_dbfid_map(cache_path):
    """Return {dbfId: bg_id} from hearthstonejson, cached to disk."""
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    print(f"  downloading card list from hearthstonejson (cached to {cache_path}) ...")
    resp = requests.get(HEARTHSTONEJSON_URL, headers=_headers(), timeout=120)
    resp.raise_for_status()
    dbfid_map = {}
    for card in resp.json():
        dbfid = card.get("dbfId")
        cid = card.get("id")
        if dbfid is not None and cid:
            dbfid_map[str(dbfid)] = cid
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(dbfid_map, f)
    return dbfid_map


def map_cards(dbfids, dbfid_map):
    """Map a list of dbfIds to BG ids, dropping any that don't resolve."""
    out = []
    for d in dbfids or []:
        cid = dbfid_map.get(str(d))
        if cid:
            out.append(cid)
        else:
            print(f"  WARN: dbfId {d} did not resolve to a BG id")
    return out


def strip_wikilinks(text):
    """Turn '[[A||1]] plus [[B||2]]' into 'A plus B'."""
    if not text:
        return ""
    return WIKILINK_RE.sub(r"\1", text)


def enablers_to_text(enablers):
    """Normalize comp_common_enablers (list of wiki-links) to newline text."""
    if isinstance(enablers, list):
        names = [WIKILINK_RE.sub(r"\1", str(e)) for e in enablers]
        return "\n".join(n for n in names if n)
    return strip_wikilinks(str(enablers))


def build_comp(record, dbfid_map):
    """Turn a raw comp record (comp_* keys) into the meta schema dict."""
    rep = record.get("comp_representative_card")
    return {
        "name": record.get("comp_name", ""),
        "difficulty": DIFFICULTY_MAP.get(record.get("comp_difficulty"), "?"),
        "meta_tier": TIER_MAP.get(record.get("comp_tier"), "?"),
        "core": map_cards(record.get("comp_core_cards"), dbfid_map),
        "how_to_play": record.get("comp_how_to_play", ""),
        "addons": map_cards(record.get("comp_addon_cards"), dbfid_map),
        "summary": record.get("comp_summary", ""),
        "when_to_commit": strip_wikilinks(record.get("comp_when_to_commit", "")),
        "common_enablers": enablers_to_text(record.get("comp_common_enablers", "")),
        "representative_card": dbfid_map.get(str(rep), "") if rep else "",
    }


def fetch_youtube_links(comp_id):
    """Return the YouTube affiliate links for a comp (or [] if none)."""
    url = YOUTUBE_LINKS_URL.format(id=comp_id)
    resp = requests.get(
        url, headers=_headers(referer=COMP_PAGE_URL.format(id=comp_id)), timeout=60
    )
    if resp.status_code != 200:
        return []
    data = resp.json()
    return data if isinstance(data, list) else data.get("results", [])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("comp_ids", nargs="*", help="comp ids or slugs to scrape")
    ap.add_argument("--top", type=int, help="scrape the top N visible comps instead")
    ap.add_argument("--prune", action="store_true",
                    help="(with --top) drop comps no longer in the top-N visible set")
    ap.add_argument("--youtube", action="store_true", help="fetch YouTube links too")
    ap.add_argument("--cards-cache", default=DEFAULT_CARDS_CACHE)
    args = ap.parse_args()

    if args.top is None and not args.comp_ids:
        ap.error("provide comp ids/slugs or --top N")

    with open(COMPS_PATH, encoding="utf-8") as f:
        comps = json.load(f)

    dbfid_map = load_dbfid_map(args.cards_cache)

    # Work list: [(comp_id, key)]. With --top, key is the index slug; the
    # keep-set for --prune is the full top-N visible set (so a failed scrape
    # never prunes a comp that's still in the ranking).
    keep_slugs = None
    if args.top is not None:
        top_visible = visible_top_comps(args.top)
        work = top_visible
        keep_slugs = {slug for _, slug in top_visible}
    else:
        work = [(resolve_comp_id(cid), cid) for cid in args.comp_ids]

    for comp_id, key in work:
        print(f"== {key} ==")
        try:
            data = fetch_comp_page(comp_id)
        except Exception as e:  # noqa: BLE001 - report and continue
            print(f"  ERROR: {e}")
            continue
        record = _find_comp_record(data)
        if record is None:
            print("  ERROR: could not locate comp record in react_context")
            continue
        comp = build_comp(record, dbfid_map)

        # Preserve hand-added fields from any existing entry.
        existing = comps.get(key, {})
        for field in HAND_ADDED_FIELDS:
            if field in existing:
                comp[field] = existing[field]

        if args.youtube:
            links = fetch_youtube_links(comp_id)
            if links:
                comp["youtube"] = [
                    {
                        "video_id": l.get("video_id"),
                        "channel": l.get("channel_title"),
                        "title": l.get("title"),
                        "views": l.get("view_count"),
                        "upvotes": l.get("upvote_count"),
                    }
                    for l in links
                ]

        comps[key] = comp
        print(f"  {comp['name']} [{comp['meta_tier']}/{comp['difficulty']}] "
              f"core={len(comp['core'])} addons={len(comp['addons'])}")

    if args.prune and keep_slugs is not None:
        for key in list(comps):
            if key not in keep_slugs:
                del comps[key]
                print(f"  pruned {key}")

    with open(COMPS_PATH, "w", encoding="utf-8") as f:
        json.dump(comps, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\nWrote {len(comps)} comps to {COMPS_PATH}")


if __name__ == "__main__":
    sys.exit(main())
