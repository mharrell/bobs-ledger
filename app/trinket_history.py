#!/usr/bin/env python3
"""Refresh trinket population numbers from hsreplay's public JSON API.

`refresh_trinkets.py` records the failure it was built around: the trinket
GUIDE page renders no numbers ("pick_rate" appears zero times in its HTML), so
it carries the old paste's stats joined BY NAME and leaves entries without
history as "no data". The page's frontend actually calls a public endpoint:

    GET /api/v1/battlegrounds/trinkets/
        ?BattlegroundsMMRPercentile=ALL
        &BattlegroundsTimeRange=CURRENT_BATTLEGROUNDS_PATCH

One row per offered trinket:

    trinket_dbf_id, pick_rate, avg_final_placement,
    final_placement_distribution[8], tier, group

`trinket_dbf_id` is joined to a BG card id through hearthstonejson (fetched
fresh: the cached dbf map predates the newest trinkets). This tool then fills
`pick_rate` / `avg_placement` / `placement_distribution` in
`meta/trinkets.json` BY ID.

Nothing is invented: a trinket the API does not list keeps what it had, and
the report says how many that is. Rotated trinkets, tokens and golden ids are
expected in that set. The default only touches rows with NO history; `--all`
deliberately refreshes every matched row.

Usage:
  python trinket_history.py            # dry run: coverage + what would change
  python trinket_history.py --apply    # write meta/trinkets.json
  python trinket_history.py --all      # refresh every matched row
  python trinket_history.py --json     # bounded machine-readable report
"""
import argparse
import json
import os
import re
import sys

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
TRINKETS_PATH = os.path.join(_HERE, "meta", "trinkets.json")

API_URL = "https://hsreplay.net/api/v1/battlegrounds/trinkets/"
PARAMS = {"BattlegroundsMMRPercentile": "ALL",
          "BattlegroundsTimeRange": "CURRENT_BATTLEGROUNDS_PATCH"}
HEARTHSTONEJSON_URL = "https://api.hearthstonejson.com/v1/latest/enUS/cards.json"
#: Plain curl gets 403; the site wants a browser UA (and the referer the page
#: itself sends) on both requests.
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 "
              "Safari/537.36")
REFERER = "https://hsreplay.net/battlegrounds/trinkets/lesser/"


def _headers(referer=REFERER):
    h = {"User-Agent": BROWSER_UA}
    if referer:
        h["Referer"] = referer
    return h


def fetch_rows(session=requests):
    """The API's trinket rows for the current Battlegrounds patch."""
    resp = session.get(API_URL, params=PARAMS, headers=_headers(), timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected trinket API shape: {type(data).__name__}")
    return data


def fetch_dbfid_maps(session=requests):
    """({card_id: dbfId}, {dbfId: card_id}) from a FRESH card dump.

    Not the cached map: it was written before the newest trinkets existed, and
    a missing dbfId would silently read as "no history" for exactly the rows
    this tool exists to fill.
    """
    resp = session.get(HEARTHSTONEJSON_URL, headers=_headers(referer=None),
                       timeout=300)
    resp.raise_for_status()
    by_id, by_dbf = {}, {}
    for card in resp.json():
        cid, dbf = card.get("id"), card.get("dbfId")
        if cid and dbf is not None:
            by_id[cid] = dbf
            by_dbf[dbf] = cid
    return by_id, by_dbf


def distribution(values):
    """[8 percentages] -> {"1": .., "8": ..}, or None when malformed."""
    try:
        nums = [float(v) for v in (values or [])]
    except (TypeError, ValueError):
        return None
    if len(nums) != 8:
        return None
    return {str(i + 1): v for i, v in enumerate(nums)}


def plan(records, rows, dbfid_by_id, refresh_all=False):
    """Return {"updates", "no_row", "matched"} without touching `records`.

    `updates` is [(record, changed_fields)]; a field is only present when the
    new value differs from what the row already carries.
    """
    by_dbf = {r.get("trinket_dbf_id"): r for r in rows if isinstance(r, dict)}
    updates, no_row, matched = [], [], 0
    for rec in records:
        row = by_dbf.get(dbfid_by_id.get(rec.get("id")))
        if not row:
            no_row.append(rec.get("id"))
            continue
        matched += 1
        missing = rec.get("pick_rate") is None or rec.get("avg_placement") is None
        if not (refresh_all or missing):
            continue
        wanted = {"pick_rate": row.get("pick_rate"),
                  "avg_placement": row.get("avg_final_placement")}
        dist = distribution(row.get("final_placement_distribution"))
        if dist is not None:
            wanted["placement_distribution"] = dist
        changed = {k: v for k, v in wanted.items()
                   if v is not None and rec.get(k) != v}
        if changed:
            updates.append((rec, changed))
    return {"updates": updates, "no_row": no_row, "matched": matched}


def apply_updates(updates):
    for rec, changed in updates:
        rec.update(changed)


def load_trinkets(path=TRINKETS_PATH):
    """(document, formatting) with the file's indent/EOL/trailing-newline."""
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8")
    indent = 1
    for line in text.splitlines()[1:]:
        m = re.match(r"^( +)\S", line)
        if m:
            indent = len(m.group(1))
            break
    return json.loads(text), {
        "indent": indent,
        "crlf": b"\r\n" in raw,
        "trailing_newline": raw.endswith(b"\n"),
    }


def save_trinkets(doc, fmt, path=TRINKETS_PATH):
    text = json.dumps(doc, ensure_ascii=False, indent=fmt["indent"])
    if fmt["crlf"]:
        text = text.replace("\n", "\r\n")
    if fmt["trailing_newline"]:
        text += "\r\n" if fmt["crlf"] else "\n"
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write meta/trinkets.json (default: dry run)")
    ap.add_argument("--all", action="store_true",
                    help="refresh every matched row, not only rows with no "
                         "history")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = fetch_rows()
    dbfid_by_id, _ = fetch_dbfid_maps()
    doc, fmt = load_trinkets()
    result = plan(doc, rows, dbfid_by_id, refresh_all=args.all)
    updates = result["updates"]
    report = {
        "api_rows": len(rows),
        "db_rows": len(doc),
        "matched": result["matched"],
        "updated": len(updates),
        "no_api_row": len(result["no_row"]),
        "mode": "all" if args.all else "missing-only",
        "applied": bool(args.apply),
        "first": [{"id": rec.get("id"), "name": rec.get("name"), **ch}
                  for rec, ch in updates[:10]],
    }
    if args.apply and updates:
        apply_updates(updates)
        save_trinkets(doc, fmt)
        report["wrote"] = TRINKETS_PATH

    if args.json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
        return 0

    print(f"hsreplay rows: {report['api_rows']} "
          f"(CURRENT_BATTLEGROUNDS_PATCH, ALL)")
    print(f"trinkets.json: {report['db_rows']} rows; matched by dbfId: "
          f"{report['matched']}; no API row: {report['no_api_row']} "
          f"(rotated/tokens, left alone)")
    print(f"{'updated' if args.apply else 'would update'} "
          f"{report['updated']} row(s) "
          f"[{'all matched' if args.all else 'missing history only'}]")
    for rec, ch in updates[:10]:
        print("  %-24s %-24s pick %s, avg %s" % (
            rec.get("id"), rec.get("name"), ch.get("pick_rate"),
            ch.get("avg_placement")))
    if len(updates) > 10:
        print(f"  ... and {len(updates) - 10} more")
    if args.apply:
        print(f"wrote {TRINKETS_PATH}" if updates
              else "nothing to write — already current")
    else:
        print("dry run — pass --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
