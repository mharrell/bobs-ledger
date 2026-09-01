"""Selection ranker: advise on the picks the coach could only count before.

Every game asks the player to CHOOSE — 1 of 4 heroes at the start, a Lesser
and a Greater Trinket, and mid-game discovers (spells, triples, hero powers).
The coach counted these (`SendChoices` -> trigger_counts) but never ranked
them. This module parses `DebugPrintEntityChoices` blocks and ranks the
options:

- hero     -> meta/heroes.json by NAME (log hero ids aren't in the DB; names
              match 100%) — hsreplay pick_rate, plus the hero power text so
              the player sees what each hero does.
- trinket  -> meta/trinkets.json by NAME (trinket card ids are patch-drifted —
              0/19 id matches in the 2026-09-01 log — but names are stable) —
              hsreplay pick_rate/avg_placement + board synergy.
- discover -> the options are pool minions: rank like shop cards against the
              target comp (value.shop_ranking).
- unknown  -> hero-power shifts, spell discovers: no data; returned unranked.
"""
import json
import os
import re

from value import shop_ranking
from tribes import normalize

_HERE = os.path.dirname(os.path.abspath(__file__))

# GameState.DebugPrintEntityChoices() - id=8 Player=... TaskList=... ChoiceType=GENERAL CountMin=1 CountMax=1
_CHOICE_HEADER = re.compile(
    r"GameState\.DebugPrintEntityChoices\(\) - id=(\d+) Player=(\S+) "
    r".*?ChoiceType=(\w+) CountMin=(\d+) CountMax=(\d+)")
# ... -   Source=[entityName=Lesser Trinket id=388 zone=PLAY ...]
_CHOICE_SOURCE = re.compile(r" -   Source=\[entityName=(.+?) id=")
# ... -   Entities[0]=[entityName=Baller Portrait id=3226 zone=SETASIDE
#       zonePos=0 cardId=BG36_MagicItem_390 player=3]
_CHOICE_OPT = re.compile(
    r" -   Entities\[\d+\]=\[entityName=(.+?) id=\d+ zone=\w+ zonePos=\d+ "
    r"cardId=(\w+) player=(\d+)\]")
# The pick that resolves the choice — m_chosenEntities arrives on its OWN
# line: "GameState.SendChoices() -   m_chosenEntities[0]=[entityName=...]".
_CHOSEN = re.compile(
    r"GameState\.SendChoices\(\) -   m_chosenEntities\[0\]="
    r"\[entityName=(.+?) id=\d+ zone=\w+ zonePos=\d+ cardId=(\w+)")

_HERO_ID = re.compile(r"^(?:TB_BaconShop_HERO_\d+|BG\d+_HERO_\d+)$")


def choice_kind(ctype, source, options):
    """Classify a choice: 'hero', 'trinket', 'discover', or 'unknown'."""
    if ctype == "MULLIGAN" or all(_HERO_ID.match(c) for _n, c in options):
        return "hero"
    if source and "trinket" in source.lower():
        return "trinket"
    if options and all(_is_minion_id(c) for _n, c in options):
        return "discover"
    return "unknown"


def _is_minion_id(cid):
    return bool(re.match(r"^(?:BG\d+_[A-Z]+_\d+|BG\d+_\d+|BGS_\d+|BG_[A-Z]+_\d+)(_G)?$", cid))


def _load_trinket_db():
    """name -> trinket entry (pick_rate, avg_placement, description).

    Matched by NAME — trinket card ids are patch-drifted (the DB carries
    BG36_MagicItem_3022-family ids; live logs use BG30_MagicItem_700-family).
    """
    path = os.path.join(_HERE, "meta", "trinkets.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else list(data.values())
    return {t.get("name"): t for t in items if isinstance(t, dict) and t.get("name")}


def _load_hero_db():
    """name -> hero entry (pick_rate, hero_power text)."""
    path = os.path.join(_HERE, "meta", "heroes.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else list(data.values())
    return {h.get("name"): h for h in items if isinstance(h, dict) and h.get("name")}


def rank_choices(kind, options, board=None, comps=None):
    """Rank a pending choice's options. Returns [(name, card_id, score, why)].

    `options`: [(entity_name, card_id)] from the choice block. `board`/`comps`
    feed the synergy terms (dominant tribe, comp fit).
    """
    if kind == "hero":
        return _rank_heroes(options)
    if kind == "trinket":
        return _rank_trinkets(options, board)
    if kind == "discover":
        return _rank_discover(options, board, comps)
    return [(n, c, None, "") for n, c in options]


def _rank_heroes(options):
    """Rank hero options by hsreplay pick_rate; surface each hero power."""
    db = _load_hero_db()
    ranked = []
    for name, cid in options:
        hero = db.get(name)
        if hero and hero.get("pick_rate") is not None:
            ranked.append((name, cid, hero["pick_rate"] / 10.0,
                           (hero.get("hero_power") or "").strip()))
        else:
            ranked.append((name, cid, None, ""))
    ranked.sort(key=lambda x: (-(x[2] or 0), x[0]))
    return ranked


def _rank_trinkets(options, board):
    """Rank trinkets by meta stats + board synergy from their text.

    score = pick_rate/10 (0-10, hsreplay's population-weighted preference)
    + (4.5 - avg_placement) — a trinket placing 1.0 adds ~3.5 — plus a flat
    synergy bonus when the description mentions the board's dominant tribe.
    """
    db = _load_trinket_db()
    board = board or []
    tribes = [normalize(m.get("tribe")) for m in board if normalize(m.get("tribe"))]
    dominant = max(set(tribes), key=tribes.count) if tribes else None
    ranked = []
    for name, cid in options:
        t = db.get(name)
        why = ""
        if t and t.get("pick_rate") is not None:
            score = t["pick_rate"] / 10.0
            why = f"pick {t['pick_rate']:.0f}%"
            if t.get("avg_placement") is not None:
                score += max(4.5 - t["avg_placement"], 0.0)
                why += f", avg #{t['avg_placement']:.2f}"
        else:
            score = 0.0
        desc = (t.get("description") or "").lower() if t else ""
        if dominant and dominant.lower() in desc:
            score += 1.5
            why += " · fits your board"
        ranked.append((name, cid, score, why.strip(" ·")))
    ranked.sort(key=lambda x: (-(x[2] or 0), x[0]))
    return ranked


def _rank_discover(options, board, comps):
    """Rank minion discovers with the shop ranking (comp-targeted)."""
    cids = [c for _n, c in options]
    ranked = shop_ranking(cids, comps or {}, board_minions=board)
    names = {c: n for n, c in options}
    return [(names.get(cid, cid), cid, score, "comp fit")
            for cid, score in ranked]


def parse_choice_blocks(lines):
    """Batch helper: [(kind, source, options)] from a list of raw log lines.

    Only GameState choice blocks count — PowerTaskList re-prints them and
    would duplicate every option (same double-logging as STEP lines).
    """
    blocks = []
    cur = None
    for line in lines:
        if "PowerTaskList" in line:
            continue
        m = _CHOICE_HEADER.search(line)
        if m:
            cur = {"ctype": m.group(3), "source": None, "options": []}
            blocks.append(cur)
            continue
        if cur is None:
            continue
        ms = _CHOICE_SOURCE.search(line)
        if ms:
            cur["source"] = ms.group(1)
            continue
        mo = _CHOICE_OPT.search(line)
        if mo and all(mo.group(2) != c for _n, c in cur["options"]):
            # the hero-selection screen re-prints the same options; keep one
            cur["options"].append((mo.group(1), mo.group(2)))
    out = []
    for b in blocks:
        out.append((choice_kind(b["ctype"], b["source"], b["options"]),
                    b["source"], b["options"]))
    return out