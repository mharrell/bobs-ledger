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
from tribes import normalize, overlaps, parts

# Pick-time synergy cap (analysis/engine_coaching.md Plan 1): ALL curated
# synergy terms together — board fit, comp direction, hero-power engine —
# add at most this much on the trinket scale (pick_rate 0-10, placement
# ~3.5). Can flip a near-tie, never beat a dominant statistical favorite.
SYN_CAP = 1.5

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


def rank_choices(kind, options, board=None, comps=None, comp=None, hero=None):
    """Rank a pending choice's options: [(name, card_id, score, facts, order)].

    `options`: [(entity_name, card_id)] from the choice block, IN THE ORDER THE
    GAME OFFERED THEM. `board`/`comps` feed the synergy terms (dominant tribe,
    comp fit). `comp`: the SAME evidence-based target the caller displays
    (live_coach's sticky target) — discover scores AND labels key on it, so a
    pick panel can never bless a card of a comp the overlay isn't showing.
    `hero`: the current hero's name — feeds the trinket ranker's capped
    hero-power engine term (an offered trinket that completes a mechanical
    recipe for THIS hero). Locked heroes (the player's list) are filtered out
    of hero rankings.

    **The rows stay SCORE-ORDERED, and that is not presentation.** Row 0 is
    what `value._top_move_text` records as the plan's PICK (and row 1 its
    locked fallback), so this order is the review's and the corpus's record of
    what the model wanted — keep it. `order` is the option's position in the
    list the GAME showed, which is what the overlay renders in: the pick panel
    shows facts per option, in the game's own order, and must not let a sort be
    read as a recommendation (2026-10-07; the shop row's rule since 2026-10-06).
    """
    if kind == "hero":
        locked = _locked_heroes()
        rows = _rank_heroes([o for o in options if o[0] not in locked])
    elif kind == "trinket":
        rows = _rank_trinkets(options, board, comp=comp, hero=hero)
    elif kind == "discover":
        rows = _rank_discover(options, board, comps, comp)
    else:
        rows = [(n, c, None, "") for n, c in options]
    # Stamp each row with the option's position in the list the GAME showed.
    # The rankers above rank; this is the one place that knows the offered
    # order, so every kind gets the slot and a locked hero's removal cannot
    # renumber the options that are left.
    order = {cid: i for i, (_n, cid) in enumerate(options)}
    return [tuple(row[:4]) + (order.get(row[1], 0),) for row in rows]


def _rank_heroes(options):
    """Rank hero options by hsreplay pick_rate; each row carries the POWER TEXT
    and the population statistic behind the score.

    A hero with no population data still shows its POWER TEXT. Dropping it left
    the pick panel with a blank column and nothing to reason about, which is the
    worst case for exactly the heroes that need it most: the 36.6.1 heroes
    (Drest'agath, Kith'ix) have no hsreplay rate yet but are guaranteed in EVERY
    game until 2026-10-06, so the player meets them constantly. An unknown hero
    the DB has never seen keeps the empty row.

    The fact string says what the number IS ("picked in 6% of games") rather
    than printing the 0-10 score it feeds: a bare `2.5` under a hero's name is
    an index nobody can read, and the statistic is the honest part of it.
    """
    db = _load_hero_db()
    ranked = []
    for name, cid in options:
        hero = db.get(name)
        power = (hero.get("hero_power") or "").strip() if hero else ""
        rate = (hero or {}).get("pick_rate")
        score = None if rate is None else rate / 10.0
        facts = " · ".join(x for x in (power, _pick_facts(rate)) if x)
        ranked.append((name, cid, score, facts))
    ranked.sort(key=lambda x: (-(x[2] or 0), x[0]))
    return ranked


def _pick_facts(rate):
    """"picked in 6% of games" — or nothing when the DB has no population."""
    return "" if rate is None else f"picked in {rate:.0f}% of games"


def _placement_facts(t):
    """The trinket's own population numbers, as words: pick rate, average
    placement, and how often it finished top 4.

    `placement_distribution` is a whole distribution (placement -> percent),
    which is the most informative thing the DB holds for a trinket and was
    rendered nowhere — an average placement hides whether a trinket is a
    consistent 4th or a coin-flip between 1st and 8th. Absent or partial
    distributions simply drop the top-4 clause; nothing here is inferred.
    """
    facts = []
    if t.get("pick_rate") is not None:
        facts.append(f"picked in {t['pick_rate']:.0f}% of games")
    if t.get("avg_placement") is not None:
        facts.append(f"avg place {t['avg_placement']:.2f}")
    dist = t.get("placement_distribution") or {}
    top4 = None
    try:
        top4 = sum(float(dist[str(p)]) for p in (1, 2, 3, 4) if str(p) in dist)
    except (TypeError, ValueError):
        top4 = None
    if top4 is not None and dist:
        facts.append(f"top-4 in {top4:.0f}% of its games")
    return " · ".join(facts)


def _rank_trinkets(options, board, comp=None, hero=None):
    """Rank trinkets by meta stats + curated synergy (capped).

    score = pick_rate/10 (0-10, hsreplay's population-weighted preference)
    + (4.5 - avg_placement) — a trinket placing 1.0 adds ~3.5 — plus
    synergy, the SUM of curated fit terms CAPPED at SYN_CAP:

    - board fit: the trinket rewards what the board actually is — a
      matching tribe, or a keyword the board's minions carry
      (deathrattle/battlecry/magnetic/...). Falls back to the description
      substring for unannotated trinkets.
    - comp direction (Plan 1): the trinket rewards the tribe we're
      HEADING toward (the displayed comp target), not just the board we
      have — the pick shapes the next several buys.
    - hero-power engine (Plan 1): the offered trinket completes a
      mechanical engine recipe for THIS hero (e.g. Sous Chef Sticker in a
      Shudderwock game — extra power uses re-fire Battlecries).

    Every term traces to card text; the why-label names each one that fit.
    The cap keeps synergy a tie-breaker: it can flip a near-tie, never
    beat a dominant statistical favorite. Hero pick ranking is untouched.
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
    comp_tribe = (comp or {}).get("tribe")
    ranked = []
    for name, cid in options:
        t = db.get(name)
        # The facts are the STATISTICS this ranks on, spelled out: pick rate,
        # average placement and the top-4 share of its own distribution. The
        # score below stays for the plan's sake (row 0 is the pick the review
        # grades); it is no longer what the panel shows.
        facts = _placement_facts(t) if t else ""
        score = 0.0
        if t and t.get("pick_rate") is not None:
            score = t["pick_rate"] / 10.0
            if t.get("avg_placement") is not None:
                score += max(4.5 - t["avg_placement"], 0.0)
        desc = (t.get("description") or "").lower() if t else ""
        # By trinket ID first (names drift across patches); the Compass
        # family shares one id across tribe variants, so also try by name.
        rec = ann.get(cid) or ann.get(_trinket_id_by_name(t)) or {}
        syn = rec.get("synergy") or {}
        terms = []  # (label, amount) — capped together at SYN_CAP
        if syn and not syn.get("note"):
            if dominant and any(overlaps(dominant, tr)
                                for tr in syn.get("tribes") or []):
                terms.append(("fits your board", 1.5))
            for kw in syn.get("keywords") or []:
                k = kw.lower()
                if k in board_keywords or (k in desc and k in (
                        "deathrattle", "battlecry", "spell", "refresh",
                        "economy", "battlecry", "spellcraft")):
                    terms.append(("fits your board", 1.5))
                    break
        elif dominant and dominant.lower() in desc:
            terms.append(("fits your board", 1.5))
        if comp_tribe and syn and not syn.get("note") and any(
                overlaps(tr, comp_tribe) for tr in syn.get("tribes") or []):
            terms.append(("fits your comp direction", 1.0))
        if hero and t:
            for rid, r in meta.engine_recipes().items():
                if rid.startswith("_") \
                        or r.get("confidence") != "mechanical" \
                        or r.get("hero") != hero:
                    continue
                if t.get("id") in (r.get("trinkets") or []) \
                        or cid in (r.get("trinkets") or []):
                    terms.append(("amps your hero-power engine", 1.5))
                    break
        if terms:
            score += min(sum(a for _l, a in terms), SYN_CAP)
            facts += " · " + " · ".join(l for l, _a in terms)
        ranked.append((name, cid, score, facts.strip(" ·")))
    ranked.sort(key=lambda x: (-(x[2] or 0), x[0]))
    return ranked


def _trinket_id_by_name(t):
    """The trinket record's id, or None (choices matches by NAME because
    the choice-block ids drift; the curated file is id-keyed)."""
    return (t or {}).get("id")


def _rank_discover(options, board, comps, comp=None):
    """Rank minion discovers with the shop ranking (comp-targeted).

    Every per-option fact says what the option IS relative to the displayed
    comp — that is the question a discover raises, and the only one the
    reference DBs can answer without pretending to know the player's plans.

    **"best available" and "best off-comp" are GONE (2026-10-07).** They rode
    on row 0 and said the words the pivot deleted, one layer below the wall:
    `LIVE_VERDICT_KEYS` drops verdict KEYS, and a verdict inside a fact STRING
    survived it. The honest label for an option the displayed comp does not
    want is the one that says nothing about rank — and when there is no
    displayed direction at all, nothing is claimed, because "best available"
    was a claim about a comp nobody had chosen yet.

    The old blanket "comp fit" tagged EVERY option — so Lurking Leviathan (core
    of Beasts - Leviathan) wore it while the overlay showed Beasts - Tasty
    Lobstah committed, and so did an Elemental in a Beast game (2026-09-11).
    Two causes fixed then: the label never inspected anything, and the ranking
    re-derived its own comp from the board instead of using the displayed one
    (the 2026-09-04 one-target rule, missed for the pick panel).
    """
    cids = [c for _n, c in options]
    ranked = shop_ranking(cids, comps or {}, board_minions=board, comp=comp)
    names = {c: n for n, c in options}
    board_ids = {m.get("card") for m in (board or [])}
    core = set((comp or {}).get("core", []))
    addons = set((comp or {}).get("addons", []))
    tribe = normalize((comp or {}).get("tribe")) if comp else None
    comp_name = (comp or {}).get("name")
    # How many of the displayed comp's own core pieces the player already
    # holds: the "does this match what I am building" number, counted off the
    # board rather than asserted. Only meaningful with a displayed comp.
    owned = len(core & board_ids)
    cards = None  # lazy: card id -> tribe, only when a tribe-fit check needs it
    out = []
    for i, (cid, score) in enumerate(ranked):
        base = cid[:-2] if cid.endswith("_G") else cid
        if base in core:
            facts = (f"core of {comp_name} (you have {owned} of its "
                     f"{len(core)})" if comp_name else "core of your comp")
            if base in board_ids:
                facts += " · a second copy triples"
        elif base in addons:
            facts = f"addon of {comp_name}" if comp_name else "comp addon"
        elif comp is None:
            # No displayed direction — say nothing about fit. Claiming a comp
            # here is exactly the hollow label this replaces, and ranking it
            # "best" is the verdict the pivot deleted.
            facts = ""
        else:
            if cards is None:
                cards = meta.cards()
            # Membership lookup, not equality: the DB carries compounds
            # (Demon/Quilboar fits a Demon comp) and Amalgams (fit every).
            card_tribe = (cards.get(base) or {}).get("tribe")
            if tribe and card_tribe and overlaps(card_tribe, tribe):
                facts = f"{card_tribe} — the tribe {comp_name} is built on" \
                    if comp_name else "right tribe"
            else:
                facts = "not a piece of the comp you are on"
        out.append((names.get(cid, cid), cid, score, facts))
    return out


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