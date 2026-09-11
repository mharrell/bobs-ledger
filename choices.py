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
from extract_game import MINION_ID
import meta
from tribes import overlaps, parts

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
# Trinket-offer options carry BGxx_MagicItem_NNN ids. MINION_ID can't catch
# them (the [A-Z]+_ id segment is uppercase-only; "MagicItem" is mixed), and
# the SOURCE that offers them usually isn't named "trinket" — the Lesser/Greater
# Trinket buttons are, but their EFFECTS aren't: Trip Vouchers' discover
# (2026-09-08 20:35 log) sourced "Trip Vouchers" and offered four MagicItem
# cards, which the old check classified "unknown" and ranked in original
# option order — "PICK Upstart Embers" (Entities[0]) with no reason.
_MAGIC_ITEM_ID = re.compile(r"^BG\d+_MagicItem_\d+t?$")


def choice_kind(ctype, source, options):
    """Classify a choice: 'hero', 'trinket', 'discover', or 'unknown'."""
    if ctype == "MULLIGAN" or all(_HERO_ID.match(c) for _n, c in options):
        return "hero"
    if source and "trinket" in source.lower():
        return "trinket"
    if options and all(_MAGIC_ITEM_ID.match(c) for _n, c in options):
        return "trinket"
    if options and all(_is_minion_id(c) for _n, c in options):
        return "discover"
    return "unknown"


def _is_minion_id(cid):
    return bool(MINION_ID.match(cid))


def _load_trinket_db():
    """name -> trinket entry (pick_rate, avg_placement, description).

    Matched by NAME — trinket card ids are patch-drifted (the DB carries
    BG36_MagicItem_3022-family ids; live logs use BG30_MagicItem_700-family).
    """
    return {t.get("name"): t for t in meta.trinkets() if t.get("name")}


def _load_hero_db():
    """name -> hero entry (pick_rate, hero_power text)."""
    return {h.get("name"): h for h in meta.heroes() if h.get("name")}


def _locked_heroes():
    """Hero names the player cannot pick (season-pass locked).

    Power.log does NOT expose hero ownership — every offered hero carries the
    same tags — so the player maintains this list once; locked heroes are
    filtered out of the hero ranking (a recommendation you can't act on is
    worse than none). Edit meta/locked_heroes.json to add more.
    """
    path = os.path.join(_HERE, "meta", "locked_heroes.json")
    if not os.path.exists(path):
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {str(n) for n in (data if isinstance(data, list)
                                 else data.get("locked", []))}
    except (OSError, json.JSONDecodeError):
        return set()


def rank_choices(kind, options, board=None, comps=None):
    """Rank a pending choice's options. Returns [(name, card_id, score, why)].

    `options`: [(entity_name, card_id)] from the choice block. `board`/`comps`
    feed the synergy terms (dominant tribe, comp fit). Locked heroes (the
    player's list) are filtered out of hero rankings.
    """
    if kind == "hero":
        locked = _locked_heroes()
        return _rank_heroes([o for o in options if o[0] not in locked])
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
    """Rank trinkets by meta stats + curated board synergy.

    score = pick_rate/10 (0-10, hsreplay's population-weighted preference)
    + (4.5 - avg_placement) — a trinket placing 1.0 adds ~3.5 — plus a flat
    synergy bonus when the CURATED read (trinket_effects.json) says the
    trinket rewards what the board actually is: a matching tribe, or a
    keyword the board's minions carry (deathrattle/battlecry/magnetic/...).
    Falls back to the description substring for unannotated trinkets.
    """
    db = _load_trinket_db()
    ann = meta.trinket_effects()
    board = board or []
    # Flattened canonical parts (compounds split, Amalgams count as every
    # tribe — a board of Amalgams rewards any tribe-synergy trinket, which
    # matches the game: Amalgams ARE each tribe).
    board_parts = [p for m in board for p in parts(m.get("tribe"))]
    dominant = (max(set(board_parts), key=board_parts.count)
                if board_parts else None)
    board_keywords = set()
    for m in board:
        board_keywords.update(k.lower() for k in (m.get("keywords") or []))
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
        # By trinket ID first (names drift across patches); the Compass
        # family shares one id across tribe variants, so also try by name.
        rec = ann.get(cid) or ann.get(_trinket_id_by_name(t)) or {}
        syn = rec.get("synergy") or {}
        fit = False
        if syn and not syn.get("note"):
            if dominant and any(overlaps(dominant, tr)
                                for tr in syn.get("tribes") or []):
                fit = True
            for kw in syn.get("keywords") or []:
                k = kw.lower()
                if k in board_keywords or (k in desc and k in (
                        "deathrattle", "battlecry", "spell", "refresh",
                        "economy", "battlecry", "spellcraft")):
                    fit = True
        elif dominant and dominant.lower() in desc:
            fit = True
        if fit:
            score += 1.5
            why += " · fits your board"
        ranked.append((name, cid, score, why.strip(" ·")))
    ranked.sort(key=lambda x: (-(x[2] or 0), x[0]))
    return ranked


def _trinket_id_by_name(t):
    """The trinket record's id, or None (choices matches by NAME because
    the choice-block ids drift; the curated file is id-keyed)."""
    return (t or {}).get("id")


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