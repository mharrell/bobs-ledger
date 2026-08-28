#!/usr/bin/env python3
"""Parse a Power.log into the friendly player's per-turn actions.

Extracts, broken down by turn:
  - buys:     minions that entered the player's hand (from the tavern)
  - sells:    minions removed from the player's board (not combat)
  - triples:  minions combined into a golden (BACON_TRIPLED_BASE_MINION_ID)
  - refreshes: tavern board replacements

Usage:
    python player_actions.py <Power.log> [--games N]
"""
import json
import re
import sys

from extract_game import split_game_chunks, extract_game, _friendly_player

# A real board minion (excludes enchantments, golden _G, trinkets).
MINION_ONLY = re.compile(r"^(?:BG\d+_\d+|BGS_\d+|BG_[A-Z]+_\d+)$")

# [Entity|mainEntity]=[entityName=X id=N zone=Z zonePos=P cardId=C player=P]
# mainEntity= appears in DebugPrintOptions (shop offers / hand display).
ENTITY = re.compile(
    r"(?:Entity|mainEntity)=\[entityName=(\S+) id=(\d+) zone=(\w+) zonePos=(\d+) cardId=(\w+) player=(\d+)"
)
# The real turn counter is NUM_TURNS_IN_PLAY (TURN is a different, unreliable
# counter). In Duos the game re-enters MAIN_READY with alternating values, so we
# take the max of consecutive values as the turn.
TURN = re.compile(r"Entity=GameEntity tag=NUM_TURNS_IN_PLAY value=(\d+)")
TRIPLE = re.compile(r"tag=BACON_TRIPLED_BASE_MINION_ID value=(\d+)")
# STEP marks the game phase. The shop phase (MAIN_ACTION) is where the player
# acts (buy/sell/refresh/upgrade/hero-power); MAIN_COMBAT is automatic.
STEP_RE = re.compile(r"Entity=GameEntity tag=STEP value=(\w+)")
SHOP_STEPS = {"MAIN_ACTION", "MAIN_START", "MAIN_READY", "MAIN_START_TRIGGERS"}
# Player actions are BlockType=PLAY on the relevant button/entity. The
# BlockType=TRIGGER/ATTACK blocks are the game's automatic effects, not actions.
REFRESH = re.compile(r"BLOCK_START BlockType=PLAY Entity=\[entityName=Refresh ")
FREEZE = re.compile(r"BLOCK_START BlockType=PLAY Entity=\[entityName=Freeze ")
UPGRADE = re.compile(r"BLOCK_START BlockType=PLAY Entity=\[entityName=Tavern Tier \d+ ")
# ZONE_POSITION change (rearranging the board).
ZONE_POS = re.compile(r"Entity=\[entityName=(\S+) id=(\d+) zone=PLAY zonePos=(\d+) cardId=(\w+) player=(\d+)")


def parse_actions(chunk, friendly, friendly_hero=None):
    """Return a list of per-turn action dicts for the friendly player.

    `friendly_hero` is the friendly hero's entity name (e.g. "Patchwerk"); when
    given, a BlockType=PLAY on that entity counts as a hero-power use.
    """
    turns = []          # list of {turn, buys, sells, triples, refreshes, ...}
    cur_turn = None
    step = None
    card = {}           # entity id -> card id
    player = {}         # entity id -> player number
    zone = {}           # entity id -> zone
    seen_triples = set()    # (entity, base_id) already counted
    hero_re = re.compile(
        rf"BLOCK_START BlockType=PLAY Entity=\[entityName={friendly_hero} "
    ) if friendly_hero else None

    def new_turn(n):
        return {"turn": n, "buys": [], "sells": [], "triples": [], "refreshes": 0,
                "freezes": 0, "upgrades": 0, "hero_power": 0,
                "plays": [], "rearranges": []}

    for line in chunk:
        m = TURN.search(line)
        if m:
            n = int(m.group(1))
            # New turn only when the counter increases (handles Duos alternation).
            if cur_turn is None or n > cur_turn:
                cur_turn = n
                turns.append(new_turn(n))
            continue

        m = STEP_RE.search(line)
        if m:
            step = m.group(1)
            continue

        m = REFRESH.search(line)
        if m and cur_turn is not None:
            turns[-1]["refreshes"] += 1
            continue

        m = FREEZE.search(line)
        if m and cur_turn is not None:
            turns[-1]["freezes"] += 1
            continue

        m = UPGRADE.search(line)
        if m and cur_turn is not None:
            turns[-1]["upgrades"] += 1
            continue

        if hero_re:
            m = hero_re.search(line)
            if m and cur_turn is not None:
                turns[-1]["hero_power"] += 1
                continue

        m = ENTITY.search(line)
        if m:
            name, eid, z, pos, cid, p = (
                m.group(1), int(m.group(2)), m.group(3),
                m.group(4), m.group(5), int(m.group(6)),
            )
            if not MINION_ONLY.match(cid):
                continue
            old_zone = zone.get(eid)
            old_player = player.get(eid)
            zone[eid] = z
            player[eid] = p
            if cur_turn is None:
                continue

            # PLAY: friendly minion played from hand onto the board.
            if p == friendly and z == "PLAY" and old_zone == "HAND":
                turns[-1]["plays"].append(cid)
            # BUY: minion's controller becomes friendly (bought from the tavern)
            # and it's in HAND.
            elif p == friendly and z == "HAND" and old_player != friendly:
                turns[-1]["buys"].append(cid)
            # SELL: friendly minion leaves PLAY during the shop phase (not combat).
            elif (p == friendly and old_zone == "PLAY"
                  and z in ("SETASIDE", "GRAVEYARD") and step in SHOP_STEPS):
                turns[-1]["sells"].append(cid)
            continue

        m = TRIPLE.search(line)
        if m and cur_turn is not None:
            base = m.group(1)
            if base != "0" and base not in turns[-1]["triples"]:
                turns[-1]["triples"].append(base)

    return turns


def main():
    if len(sys.argv) < 2:
        print("usage: python player_actions.py <Power.log> [--games N]")
        return 1
    log_path = sys.argv[1]
    limit = None
    if "--games" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--games") + 1])

    with open(log_path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    chunks = list(split_game_chunks(lines))
    if limit:
        chunks = chunks[:limit]

    # card id -> name and dbfId -> name, for readable output.
    import os
    card_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cards_full.json")
    id2name, dbf2name = {}, {}
    if os.path.exists(card_db):
        with open(card_db, encoding="utf-8") as f:
            for c in json.load(f):
                if c.get("name"):
                    id2name[c["id"]] = c["name"]
                    if c.get("dbfId"):
                        dbf2name[str(c["dbfId"])] = c["name"]
    nm = lambda cid: id2name.get(cid, cid)
    nmd = lambda d: dbf2name.get(d, d)

    for idx, (start, end) in enumerate(chunks, 1):
        chunk = lines[start:end]
        game = extract_game(chunk)
        friendly = _friendly_player(game["heroes"])
        friendly_hero = next((h.get("name") for h in game["heroes"]
                              if h["player"] == friendly), None)
        print(f"\n=== Game {idx} (friendly player={friendly}, hero={friendly_hero}) ===")
        for t in parse_actions(chunk, friendly, friendly_hero):
            parts = [f"buy={[nm(x) for x in t['buys']]}",
                     f"play={[nm(x) for x in t['plays']]}",
                     f"sell={[nm(x) for x in t['sells']]}",
                     f"triple={[nmd(x) for x in t['triples']]}",
                     f"refresh={t['refreshes']}", f"freeze={t['freezes']}",
                     f"upgrade={t['upgrades']}", f"hero={t['hero_power']}"]
            print(f"  Turn {t['turn']}: " + " ".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
