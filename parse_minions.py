#!/usr/bin/env python3
"""Parse the pasted minions list and enrich with full card details.

Input: meta/minions_raw.txt (names grouped by tavern tier, pasted from
hsreplay.net/battlegrounds/minions/). The hsreplay page only gives names; the
full card details (cost, tribe, attack, health, keywords, description) come from
the hearthstonejson card DB (cached at .cards_full.json).

Output: meta/minions.json — a list of {tier, id, name, cost, tribe, tribe_src,
attack, health, mechanics, text}.

Tribe lookups (2026-09-11): the DB must KNOW each minion's tribe, not infer it
from card text (compounds were also silently truncated to races[0], and
Amalgams collapsed to untribed). `--refresh-tribes` backfills the tribe field
in place from sources, most-trusted first:

  1. meta/tribe_overrides.json — hand-curated pins (the Butchering pattern)
  2. the game's own Power.log CARDRACE tags ∪ hearthstonejson
     .card_races.json — unioned (a partial reveal must not erase a known
     race); on a true conflict the log's answer wins, it's patch-proof
  3. the entry's existing tribe (from the paste) — kept, marked unverifiable

Every touched entry records `tribe_src`: "override" | "log" |
"hearthstonejson" | "paste" | None (untribed, or nobody knows — the report
lists those by name so they get curated instead of guessed).

Usage:
  python parse_minions.py                     # rebuild from the raw paste
  python parse_minions.py --refresh-tribes    # audit/backfill tribes (dry run)
  python parse_minions.py --refresh-tribes --apply
  python parse_minions.py --refresh-tribes --refresh-cache   # re-download races
"""
import argparse
import glob
import json
import os
import re

from tribes import normalize, tribes_from_races

_HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(_HERE, "meta", "minions_raw.txt")
OUT = os.path.join(_HERE, "meta", "minions.json")
CARDS = os.path.join(_HERE, ".cards_full.json")
OVERRIDES = os.path.join(_HERE, "meta", "tribe_overrides.json")
OBSERVED_CACHE = os.path.join(_HERE, ".observed_tribes.json")
RACES_CACHE = os.path.join(_HERE, ".card_races.json")
DEFAULT_LOG_DIR = r"C:\Program Files (x86)\Hearthstone\Logs"


def _strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def load_card_map():
    """Return {minion_name: card} for BG minions in the card DB."""
    with open(CARDS, encoding="utf-8") as f:
        cards = json.load(f)
    name_map = {}
    for c in cards:
        if c.get("type") == "MINION" and str(c.get("id", "")).startswith("BG"):
            nm = c.get("name")
            if nm:
                name_map.setdefault(nm, c)
    return name_map


def parse(raw_text, card_map):
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    out = []
    cur_tier = None
    for l in lines:
        m = re.search(r"Tier (\d+)", l)
        if m and ("Tavern Tier" in l or "glowTier" in l):
            cur_tier = int(m.group(1))
            continue
        if cur_tier is None:
            continue
        card = card_map.get(l)
        if card is None:
            print(f"  WARN: no card for '{l}'")
            continue
        races = card.get("races") or ([card["race"]] if card.get("race") else [])
        tribe = tribes_from_races(races)
        out.append({
            "tier": cur_tier,
            "id": card.get("id"),
            "name": card.get("name"),
            "cost": card.get("cost"),
            # Canonical display form via tribes.tribes_from_races: compounds
            # preserved ("Demon/Quilboar"), Amalgams -> "All" (never collapse
            # to None — that means untribed), no race -> None.
            "tribe": tribe,
            "tribe_src": "hearthstonejson" if tribe else None,
            "attack": card.get("attack"),
            "health": card.get("health"),
            "mechanics": card.get("mechanics", []),
            "text": _strip_html(card.get("text")),
        })
    return out


def _scan_file(path):
    """One Power.log -> {card_id: sorted observed CARDRACE values}.

    Entity definition blocks print `tag=CARDRACE value=BEAST` under a
    FULL_ENTITY/SHOW_ENTITY header carrying CardID=... The run-walk mirrors
    bans.bans_from_log (validated by the 5/5 gate): a header starts a run,
    lines containing `tag=` join it (GameState and PowerTaskList blocks
    interleave — a strict per-block tracker would drop most captures), and
    any line with neither ends it. Every reveal counts (shop, board, combat),
    not just pool-minion blocks: this is tribe ground truth for the DB, not
    the ban gate.
    """
    found = {}
    cur_cid = None
    cur_races = set()

    def flush():
        nonlocal cur_races
        if cur_cid and cur_races:
            found.setdefault(cur_cid, set()).update(cur_races)
        cur_races = set()

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "FULL_ENTITY" in line or "SHOW_ENTITY" in line:
                flush()
                m = re.search(r"CardID=([A-Za-z0-9_]+)", line)
                cur_cid = m.group(1) if m else None
            elif "tag=" in line:
                if cur_cid:
                    for r in re.findall(r"tag=CARDRACE value=([A-Za-z]+)", line):
                        cur_races.add(r)
            else:
                flush()  # no header, no tag= — the run is over
                cur_cid = None  # only a header reopens attribution
        flush()
    return {k: sorted(v) for k, v in found.items()}


def scan_observed(log_dir=DEFAULT_LOG_DIR, cache_path=OBSERVED_CACHE,
                  rescan=False):
    """Observed CARDRACE per card id across the machine's Power.logs.

    Incremental: `.observed_tribes.json` caches per-file results keyed by
    (size, mtime), so unchanged logs aren't re-read (they run ~300MB across
    six sessions); the live log's changing signature rescans every run.
    """
    cache = {"files": {}, "races": {}}
    if os.path.exists(cache_path) and not rescan:
        try:
            with open(cache_path, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, ValueError):
            cache = {"files": {}, "races": {}}
    files = cache.setdefault("files", {})
    races = cache.setdefault("races", {})
    scanned = 0
    for path in sorted(glob.glob(
            os.path.join(log_dir, "Hearthstone_*", "Power.log"))):
        try:
            sig = [os.path.getsize(path), os.path.getmtime(path)]
        except OSError:
            continue
        if files.get(path) == sig:
            continue
        races.update(_scan_file(path))
        files[path] = sig
        scanned += 1
    if scanned:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        print(f"  scanned {scanned} Power.log(s) -> {cache_path}")
    return races


def load_overrides(path=OVERRIDES):
    """Hand-curated tribe pins, {card_id: "Mech" | "Demon/Quilboar" | ...}."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def refresh_tribes(minions, observed, card_races, overrides):
    """Resolve each entry's tribe from the lookup sources; return (changed, unknown).

    Resolution per entry, most-trusted first: override > observed races >
    hearthstonejson > kept paste value. Observed + upstream UNION rather than
    log-wins: a shop reveal prints the card's CARDRACE tags, but a card that
    never hit a shop this session shows an incomplete set — Ominous Seer
    revealed only NAGA in six logs while hearthstonejson knows Demon/Naga;
    strict precedence would have DOWNGRADED it. True conflicts (non-empty,
    disjoint sets) keep the log's answer — ground truth beats a lagging
    upstream — and are reported for a human override.
    Returns the entries mutated in place plus the ids no source could resolve
    (no tribe observed anywhere, none inherited) — those need a human read of
    the card, never a guess.
    """
    changed = []
    unknown = []
    for m in minions:
        cid = m.get("id")
        old = m.get("tribe")
        if cid in overrides:
            new, src = overrides[cid], "override"
        else:
            log_r = set(observed.get(cid) or [])
            hs_r = set(card_races.get(cid) or [])
            if log_r and hs_r and not (log_r & hs_r):
                print(f"  WARN {cid} {m.get('name')}: log {sorted(log_r)} vs "
                      f"hearthstonejson {sorted(hs_r)} — keeping the log's")
                races = log_r
            else:
                races = log_r | hs_r
            if races:
                new = tribes_from_races(sorted(races))
                src = "log" if log_r else "hearthstonejson"
            elif old is not None:
                # Paste value, nothing better known — keep it, marked
                # unverifiable (never downgrade an existing better stamp).
                if not m.get("tribe_src"):
                    m["tribe_src"] = "paste"
                continue
            else:
                new, src = None, None
                # Audited and unknown: record that the lookup RAN and no
                # source knows, distinct from a never-audited entry.
                if not m.get("tribe_src"):
                    m["tribe_src"] = None
        if (m.get("tribe"), m.get("tribe_src")) != (new, src):
            m["tribe"], m["tribe_src"] = new, src
        if new != old:
            changed.append((cid, m.get("name"), old, new, src))
        if new is None:
            unknown.append((cid, m.get("name")))
    return changed, unknown


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh-tribes", action="store_true",
                    help="backfill/audit tribe fields in place (dry run "
                         "unless --apply)")
    ap.add_argument("--apply", action="store_true",
                    help="with --refresh-tribes: write meta/minions.json")
    ap.add_argument("--logs", default=DEFAULT_LOG_DIR,
                    help="Hearthstone Logs dir to mine for CARDRACE tags")
    ap.add_argument("--rescan", action="store_true",
                    help="ignore the observed-tribes cache, rescan all logs")
    ap.add_argument("--refresh-cache", action="store_true",
                    help="re-download hearthstonejson races (patch-day)")
    args = ap.parse_args()

    if args.refresh_tribes:
        if args.refresh_cache and os.path.exists(RACES_CACHE):
            os.remove(RACES_CACHE)
        with open(OUT, encoding="utf-8") as f:
            minions = json.load(f)
        observed = scan_observed(args.logs, rescan=args.rescan)
        # bans._load_card_races downloads and caches on first call.
        from bans import _load_card_races
        card_races = _load_card_races(RACES_CACHE)
        overrides = load_overrides()
        changed, unknown = refresh_tribes(minions, observed, card_races,
                                          overrides)
        for cid, name, old, new, src in changed:
            print(f"  {cid} {name}: {old!r} -> {new!r} ({src})")
        print(f"{len(changed)} tribe updates, {len(unknown)} unresolved")
        if unknown:
            print("no source knows these tribes (curate in "
                  "meta/tribe_overrides.json, don't guess):")
            for cid, name in unknown:
                print(f"  {cid} {name}")
        if args.apply:
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(minions, f, indent=2, ensure_ascii=False)
                f.write("\n")
            print(f"wrote {OUT}")
        else:
            print("dry run — pass --apply to write")
        return

    with open(RAW, encoding="utf-8") as f:
        raw = f.read()
    card_map = load_card_map()
    minions = parse(raw, card_map)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(minions, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"enriched {len(minions)} minions -> {OUT}")
    missing = [m["name"] for m in minions if not m["tribe"]]
    print(f"minions with no tribe: {len(missing)}")


if __name__ == "__main__":
    main()
