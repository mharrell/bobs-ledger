#!/usr/bin/env python3
"""Parse the pasted Lesser Trinkets tier list into meta/trinkets.json.

Input: meta/trinkets_raw.txt (copied from hsreplay.net/battlegrounds/trinkets/).
Each entry is:
  <id>
  <name>
  <description>
  <pick_rate>%
  <avg_placement>
  1st Place: X% ... 8th Place: X%
  4th8th
  [Trinket Guide / UPDATED / JeefHS boilerplate / <guide text>]

Output: meta/trinkets.json — a list of {id, name, description, pick_rate,
avg_placement, placement_distribution, guide}.
"""
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(_HERE, "meta", "trinkets_raw.txt")
OUT = os.path.join(_HERE, "meta", "trinkets.json")

ID_RE = re.compile(r"^BG\d+_MagicItem_\d+$")
PICK_RE = re.compile(r"^(\d+(?:\.\d+)?)%$")
PLACE_RE = re.compile(r"^(\d+\.\d+)$")
DIST_RE = re.compile(r"^(\d+)(?:st|nd|rd|th) Place: ([\d.]+)%$")

# Boilerplate lines in the guide section (not actual guide text).
GUIDE_BOILERPLATE = {
    "UPDATED",
    "Pro player JeefHS's photo",
    "JeefHS",
    "Top BGs Player",
    "Youtube",
    "Twitch",
}


def parse_entry(block):
    tid = block[0].strip()
    name = block[1].strip()
    desc = block[2].strip()
    pick_rate = None
    avg_placement = None
    dist = {}
    guide = None
    for l in block:
        s = l.strip()
        m = PICK_RE.match(s)
        if m and pick_rate is None:
            pick_rate = float(m.group(1))
            continue
        m = PLACE_RE.match(s)
        if m and avg_placement is None:
            avg_placement = float(m.group(1))
            continue
        m = DIST_RE.match(s)
        if m:
            dist[int(m.group(1))] = float(m.group(2))
            continue
        if s == "Trinket Guide":
            guide_lines = [
                x.strip() for x in block[block.index(l) + 1:]
                if x.strip() and x.strip() not in GUIDE_BOILERPLATE
            ]
            if guide_lines:
                guide = " ".join(guide_lines)
    return {
        "id": tid,
        "name": name,
        "description": desc,
        "pick_rate": pick_rate,
        "avg_placement": avg_placement,
        "placement_distribution": dist,
        "guide": guide,
    }


def parse(raw_text):
    lines = [l.rstrip() for l in raw_text.split("\n")]
    starts = [i for i, l in enumerate(lines) if ID_RE.match(l.strip())]
    entries = []
    for k, start in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        entries.append(parse_entry(lines[start:end]))
    return entries


def main():
    with open(RAW, encoding="utf-8") as f:
        raw = f.read()
    entries = parse(raw)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"parsed {len(entries)} trinkets -> {OUT}")
    # sanity: any missing fields?
    missing = [e["id"] for e in entries
               if e["pick_rate"] is None or e["avg_placement"] is None
               or len(e["placement_distribution"]) != 8]
    if missing:
        print("WARN: entries with missing fields:", missing)
    # count entries with guides
    with_guide = sum(1 for e in entries if e["guide"])
    print(f"entries with guide: {with_guide}/{len(entries)}")


if __name__ == "__main__":
    main()
