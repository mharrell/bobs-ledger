#!/usr/bin/env python3
"""Audit the meta DB against a patch's change list.

`check_meta.py` validates the meta DB's own internal consistency. This checks it
against the PATCH: the transcription of the official change list in
`analysis/patch_<version>_changes.md` names every new / changed / removed /
returning card, and a DB update driven by one tribe can quietly skip the rest.
That is not hypothetical — the 36.6.1 update was steered by the new Aberration
tribe, and this tool is what confirmed the OTHER lists were covered (all 7
changed minions, all 25 returning, all 3 spells, both heroes) while exposing the
one real hole (the returning tavern spell `Seafood Stew`, which has no card id in
any local log and had to be sourced from the hearthstonejsons cache).

The transcription format is the house one: markdown tables whose first column is
a number and second is a bold card name, plus plain `- Name` bullets. Anything
the parser cannot see is PRINTED rather than silently ignored, because a coverage
tool that hides its blind spots is worse than no tool.

Usage:
  python check_patch_db.py                                   # the newest doc
  python check_patch_db.py analysis/patch_3661_changes.md
  python check_patch_db.py --json
"""
import argparse
import glob
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
ANALYSIS = os.path.join(_HERE, "analysis")

#: section start -> the heading that ENDS it. Section titles come from the house
#: transcription format; a patch doc that renames them must update this table,
#: and the tool reports a section it could not find instead of passing silently.
SECTIONS = [
    ("new_minions", "## 4. New minions", "## 5."),
    ("changed_minions", "### 5.2", "## 6."),
    ("removed_minions", "## 6. Removed minions", "## 7."),
    ("returning_minions", "## 7. Returning minions", "## 8."),
    ("new_spells", "### 8.1", "### 8.2"),
    ("removed_spells", "### 8.2", "### 8.3"),
    ("returning_spells", "### 8.3", "## 9."),
    ("new_heroes", "### 3.1", "### 3.2"),
]


def _load(name):
    path = os.path.join(_HERE, "meta", name)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _by_name(rows, key="name"):
    return {r.get(key): r for r in rows if isinstance(r, dict) and r.get(key)}


def _section(doc, start, end):
    i = doc.find(start)
    if i < 0:
        return None
    j = doc.find(end, i + 1)
    return doc[i:j if j > 0 else len(doc)]


def table_names(text):
    """Names from the two table shapes the house transcription uses.

    Shape A — a card per row, name in the first (optionally numbered) column:
        | 4 | **Joyous** | 1 | 2/3 | ... |
        | **Sludge Corrosion** | 1 | Give your minions +1/+1. ... |
    Shape B — TWO cards per row, names unbolded in columns 2 and 4 (how the long
    removed/returning lists are packed to keep the table short):
        | 1 | Ancestral Automaton | 19 | Moat Custodian |

    Shape B has to be handled separately, not with a "take the bold cell" rule:
    those names are plain text, and every other cell in the row is prose.
    """
    out = []
    shape_b = re.compile(r"^\|\s*\d+\s*\|\s*([^|*]+?)\s*\|\s*\d+\s*\|\s*([^|*]+?)\s*\|")
    # A trailing row of the pair-packed table can carry a single name.
    shape_b1 = re.compile(r"^\|\s*\d+\s*\|\s*([^|*]+?)\s*\|\s*\|\s*\|")
    shape_a = re.compile(r"^\|\s*(?:\d+\s*\|\s*)?\*\*(.+?)\*\*\s*\|")
    for line in text.splitlines():
        b = shape_b.match(line)
        if b:
            out.extend(g.strip() for g in b.groups())
            continue
        b1 = shape_b1.match(line)
        if b1:
            out.append(b1.group(1).strip())
            continue
        a = shape_a.match(line)
        if a:
            out.append(a.group(1).strip())
    return out


def _heading_claim(text):
    """The count a section heading claims, e.g. '## 6. Removed minions (35 ...)'.

    Used as a self-check: if the parser sees fewer names than the heading says
    exist, the tool says so instead of quietly auditing a shorter list. That
    is how the 35th removed minion was caught (the pair-packed table's odd
    trailing row was not being read).
    """
    m = re.search(r"\((\d+)\b", text or "")
    return int(m.group(1)) if m else None


def bullet_names(text):
    """Names from `- Name` / `* **Name**` bullets."""
    out = []
    for m in re.finditer(r"^\s*[-*]\s+(?:\*\*)?([^*\n]+?)(?:\*\*)?\s*$",
                         text, re.M):
        name = m.group(1).strip()
        if name and not name.endswith(":"):
            out.append(name)
    return out


def _accepted_gaps():
    """Patch-named cards the DB genuinely cannot carry, each with its reason.

    Read from meta/patch_gaps.json. A gap on this list is reported as ACCEPTED
    (and does not fail the run); a gap that is NOT on it fails, so the gate keeps
    working for the next patch instead of being permanently red.
    """
    try:
        with open(os.path.join(_HERE, "meta", "patch_gaps.json"),
                  encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return {}
    return {e.get("name"): e for e in doc.get("expected_missing") or []}


def audit(doc_path=None):
    """Return {"sections", "problems", "accepted", "unparsed", "doc"}."""
    if doc_path is None:
        docs = sorted(glob.glob(os.path.join(ANALYSIS, "patch_*_changes.md")))
        if not docs:
            return {"problems": ["no analysis/patch_*_changes.md found"],
                    "sections": {}, "unparsed": [], "accepted": []}
        doc_path = docs[-1]
    with open(doc_path, encoding="utf-8") as f:
        doc = f.read()

    minions = _by_name(_load("minions.json"))
    spells = _by_name(_load("tavern_spells.json"))
    heroes = _by_name(_load("heroes.json"))
    try:
        with open(os.path.join(_HERE, "meta", "out_of_play.json"),
                  encoding="utf-8") as f:
            oop = json.load(f)
    except (OSError, ValueError):
        oop = {"cards": {}}
    oop_names = {e.get("name") for e in (oop.get("cards") or {}).values()}
    accepted_map = _accepted_gaps()

    problems, unparsed, found = [], [], {}
    for key, start, end in SECTIONS:
        text = _section(doc, start, end)
        if text is None:
            unparsed.append(f"section not found: {start!r} (format changed?)")
            continue
        names = table_names(text) or bullet_names(text)
        if not names:
            unparsed.append(f"no names parsed from {start!r}")
        claimed = _heading_claim(text)
        if claimed and len(names) < claimed:
            unparsed.append(
                f"{start!r}: the heading claims {claimed} but only "
                f"{len(names)} were parsed — the audit below covers a SHORTER "
                f"list than the change list does")
        found[key] = names

    accepted = []

    def check(key, pool, label, where):
        for name in found.get(key, []):
            if name in pool:
                continue
            if name in accepted_map:
                accepted.append((name, accepted_map[name]))
            else:
                problems.append(f"{label} {name!r} listed in {key} but "
                                f"{where}")

    check("new_minions", minions, "new minion", "absent from minions.json")
    check("changed_minions", minions, "changed minion",
          "absent from minions.json")
    check("returning_minions", minions, "returning minion",
          "absent from minions.json")
    check("removed_minions", oop_names, "removed minion",
          "absent from meta/out_of_play.json")
    check("new_spells", spells, "new spell", "absent from tavern_spells.json")
    check("returning_spells", spells, "returning spell",
          "absent from tavern_spells.json")
    check("new_heroes", heroes, "new hero", "absent from heroes.json")
    # Removed spells are expected to STILL be in the DB (it is the card record);
    # they belong in the registry, so check that side instead.
    for name in found.get("removed_spells", []):
        if name not in oop_names and name not in accepted_map:
            problems.append(f"removed spell {name!r} is not in "
                            f"meta/out_of_play.json")

    return {"doc": doc_path, "sections": found, "problems": problems,
            "accepted": accepted, "unparsed": unparsed}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("doc", nargs="?", default=None,
                    help="path to a patch change-list transcription")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    result = audit(args.doc)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if result["problems"] else 0

    print(f"patch coverage audit: {os.path.basename(result.get('doc') or '?')}")
    for key, names in result["sections"].items():
        print(f"  {key:20} {len(names):3} listed")
    if result["unparsed"]:
        print("\n  the parser could not see:")
        for u in result["unparsed"]:
            print(f"    ? {u}")
    if result.get("accepted"):
        print(f"\n  {len(result['accepted'])} accepted gap(s) "
              f"(recorded in meta/patch_gaps.json):")
        for name, entry in result["accepted"]:
            print(f"    - {name}: {entry.get('reason')}")
            if entry.get("evidence"):
                print(f"        evidence: {entry['evidence'][:160]}")
    if result["problems"]:
        print(f"\n  {len(result['problems'])} GAP(S):")
        for p in result["problems"]:
            print(f"    ! {p}")
        return 1
    print("\n  every name the change list labels is reflected in the DB "
          "(new/changed/returning present; removed in the registry)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
