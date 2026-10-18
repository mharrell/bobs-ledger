#!/usr/bin/env python3
"""Is every cached card PORTRAIT really a portrait?

WHY. `/img/<id>.png` serves `img_cache/<id>.png` as the square art a tile draws
(`thumb()` in coach_ui). A card RENDER — the framed layout WITH the name and the
rules text — is a different picture from the same card, and it is stored per id
forever (art is content-addressed by id and served `max-age=604800`). So a single
wrong write under that name shows the wrong picture on every page that draws the
card, indefinitely, and nothing notices: the file exists, the server returns 200,
and the tile renders a framed card where its neighbours show full-bleed art.

MEASURED 2026-10-17, after the maintainer spotted it in Settle Up: the cached
`BGS_126` (Wildfire Elemental) and `BGS_115` (Sellemental) held card renders while
four control cards in the same row held true portraits.

METHOD. Fetch the canonical portrait — the SAME source `/img/` would use
(`coach_ui.PORTRAIT_URLS`) — and compare a 32x32 grayscale signature. A true
portrait of the same art scores ~0 against it; a card render scores tens.
Calibration on the 2026-10-17 case: 61.6 and 60.6 for the two broken entries,
0.1 and 0.1 for the two controls. 15 is the line between them.

  python3 analysis/audit_card_art.py           # report only, writes the .md
  python3 analysis/audit_card_art.py --fix     # replace the bad entries

Needs Pillow, so run it with a Python that has one (the bundled runtime does; the
project venv does not):

  ~/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/bin/python3 \\
      analysis/audit_card_art.py

The `img_cache/card/` layer is NOT audited: that one is supposed to hold renders.
"""
import argparse
import io
import os
import sys

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
sys.path.insert(0, APP)

from PIL import Image, ImageChops, ImageStat  # noqa: E402


def portrait_url():
    """The portrait source, read from coach_ui.py rather than imported.

    Importing `coach_ui` pulls the whole app graph (`settle_up` -> `outcome_audit`
    -> `live_coach` -> `bans` -> `requests`), which the bundled Python that has
    Pillow does not carry. Reading the one constant keeps a single source of
    truth without dragging the dependency in, and fails loudly if it moves.
    """
    import re
    src = open(os.path.join(APP, "coach_ui.py"), encoding="utf-8").read()
    m = re.search(r'^PORTRAIT_URLS = \("([^"]+)"', src, re.M)
    if not m:
        raise SystemExit("PORTRAIT_URLS not found in coach_ui.py — this audit "
                         "reads that constant, so it has to move with it")
    return m.group(1)


#: The same User-Agent the art fetcher uses; art.hearthstonejson.com is fine
#: either way, but a project UA is what everything else sends.
UA = "hearth-coach-art/1.0"

#: Above this a cached file is not a portrait of the same art. The 2026-10-17
#: calibration put true portraits at ~0.1 and card renders at ~61.
THRESHOLD = 15.0
SIG = (32, 32)


def signature(data):
    return Image.open(io.BytesIO(data)).convert("L").resize(SIG, Image.BILINEAR)


def difference(a, b):
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean)


def fetch(url, cid):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url.format(cid), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true",
                    help="replace an inconsistent entry with the real portrait")
    ap.add_argument("--cache", default=os.path.join(APP, "img_cache"))
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "card_art_audit.md"))
    args = ap.parse_args()

    files = sorted(n for n in os.listdir(args.cache)
                   if n.endswith(".png") and os.path.isfile(os.path.join(args.cache, n)))
    bad, missing, ok = [], [], 0
    SRC = portrait_url()
    print(f"auditing {len(files)} cached portrait(s) against {SRC}", flush=True)

    for n in files:
        cid = n[:-len(".png")]
        path = os.path.join(args.cache, n)
        try:
            upstream = fetch(SRC, cid)
        except Exception as e:                       # 404 or unreachable
            missing.append((cid, type(e).__name__))
            continue
        try:
            d = difference(signature(open(path, "rb").read()), signature(upstream))
        except Exception as e:
            bad.append((cid, -1.0, f"unreadable: {type(e).__name__}"))
            continue
        if d >= THRESHOLD:
            bad.append((cid, d, ""))
            if args.fix:
                img = Image.open(io.BytesIO(upstream)).convert("RGB")
                img.thumbnail((256, 256), Image.LANCZOS)
                tmp = path + ".tmp"
                img.save(tmp, "PNG")
                os.replace(tmp, path)
        else:
            ok += 1

    lines = ["# card art audit — is each cached portrait really a portrait?", "",
             f"source: `{SRC}`  ·  threshold: {THRESHOLD} on a "
             f"{SIG[0]}x{SIG[1]} grayscale signature", "",
             f"- portraits checked: **{len(files)}**",
             f"- consistent: **{ok}**",
             f"- INCONSISTENT (a card render, or unreadable): **{len(bad)}**",
             f"- no portrait upstream (kept as-is): **{len(missing)}**", ""]
    if bad:
        lines += ["## Inconsistent", ""]
        for cid, d, note in bad:
            lines.append(f"- `{cid}`  signature diff {d:.1f}  {note}")
        lines.append("")
    if missing:
        lines += ["## No portrait upstream", "",
                  "Left in place: these ids have nothing at the portrait source, so "
                  "whatever is cached is the only art there is.", ""]
        for cid, why in missing:
            lines.append(f"- `{cid}`  ({why})")
        lines.append("")
    out = "\n".join(lines)
    print(out, flush=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(out + "\n")
    print(f"written: {args.out}", flush=True)


if __name__ == "__main__":
    main()
