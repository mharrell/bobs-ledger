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
# entityName is non-greedy so multi-word names (e.g. "Tusked Camper") parse.
ENTITY = re.compile(
    r"(?:Entity|mainEntity)=\[entityName=(.+?) id=(\d+) zone=(\w+) zonePos=(\d+) cardId=(\w+) player=(\d+)"
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
# Each block is logged twice (GameState + PowerTaskList), so require GameState.
_GS = r"GameState\.DebugPrintPower\(\) - BLOCK_START "
REFRESH = re.compile(_GS + r"BlockType=PLAY Entity=\[entityName=Refresh ")
FREEZE = re.compile(_GS + r"BlockType=PLAY Entity=\[entityName=Freeze ")
UPGRADE = re.compile(_GS + r"BlockType=PLAY Entity=\[entityName=Tavern Tier \d+ ")
# Rearranging a minion = a MOVE_MINION block.
MOVE_MINION = re.compile(_GS + r"BlockType=MOVE_MINION ")
# Dark Discovery (dark gift) = a PLAY block on the Dark Discovery button.
DARK = re.compile(_GS + r"BlockType=PLAY Entity=\[entityName=Dark Discovery ")
# A discover/trinket pick = SendChoices() with the chosen entity.
CHOICE = re.compile(
    r"SendChoices\(\) -   m_chosenEntities\[0\]=\[entityName=(.+?) id=\d+ zone=\w+ zonePos=\d+ cardId=(\w+)"
)
# A buy = a PLAY block on the "Drag To Buy" button, whose Target is the minion.
BUY = re.compile(
    _GS + r"BlockType=PLAY Entity=\[entityName=Drag To Buy .*?Target=\[entityName=(.+?) id=\d+ zone=\w+ zonePos=\d+ cardId=(\w+)"
)


def parse_actions(chunk, friendly, friendly_hero_card=None):
    """Return a list of per-turn action dicts for the friendly player.

    `friendly_hero_card` is the friendly hero's card id (e.g. "BG22_HERO_000");
    the hero power is the same id with a "p" suffix (e.g. "BG22_HERO_000p_Alt"),
    so a BlockType=PLAY on that card counts as a hero-power use.
    """
    turns = []          # list of {turn, buys, sells, triples, refreshes, ...}
    cur_turn = None
    step = None
    in_buying_phase = False
    started = False     # skip the first MAIN_ACTION (setup/mulligan phase)
    played = set()      # entity ids the player played onto the board (HAND->PLAY)
    card = {}           # entity id -> card id
    player = {}         # entity id -> player number
    zone = {}           # entity id -> zone
    seen_triples = set()    # (entity, base_id) already counted
    hero_re = re.compile(
        rf"GameState\.DebugPrintPower\(\) - BLOCK_START BlockType=PLAY Entity=\[entityName=[^]]+ cardId={friendly_hero_card}p"
    ) if friendly_hero_card else None

    def new_turn(n):
        return {"turn": n, "buys": [], "sells": [], "triples": [], "refreshes": 0,
                "freezes": 0, "upgrades": 0, "hero_power": 0,
                "plays": [], "rearranges": 0, "dark_gifts": 0, "choices": []}

    for line in chunk:
        m = STEP_RE.search(line)
        if m:
            step = m.group(1)
            # A buying phase (MAIN_ACTION) = one turn. MAIN_ACTION re-enters
            # within a buying phase (after refreshes), so only count the first
            # MAIN_ACTION after a combat (or the very first one).
            if step == "MAIN_ACTION" and not in_buying_phase:
                if not started:
                    started = True  # skip the setup/mulligan phase
                else:
                    cur_turn = (cur_turn or 0) + 1
                    turns.append(new_turn(cur_turn))
                in_buying_phase = True
            elif step == "MAIN_END":  # combat phase ends the buying phase
                in_buying_phase = False
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
            # Only count the buy-phase use (the combat-phase trigger is automatic).
            if m and cur_turn is not None and step == "MAIN_ACTION":
                turns[-1]["hero_power"] += 1
                continue

        m = MOVE_MINION.search(line)
        if m and cur_turn is not None:
            turns[-1]["rearranges"] += 1
            continue

        m = DARK.search(line)
        if m and cur_turn is not None:
            turns[-1]["dark_gifts"] += 1
            continue

        m = CHOICE.search(line)
        if m and cur_turn is not None:
            turns[-1]["choices"].append(m.group(2))  # card id chosen
            continue

        m = BUY.search(line)
        if m and cur_turn is not None:
            turns[-1]["buys"].append(m.group(2))  # card id bought
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
                played.add(eid)
                turns[-1]["plays"].append(cid)
            # SELL: a played minion leaves the board during the shop phase. Only
            # counts minions the player actually played (in `played`) so effect
            # removals (e.g. Lock & Load removing a tavern minion) aren't sold.
            elif (p == friendly and eid in played and old_zone == "PLAY"
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
        friendly_hero_card = next((h.get("card") for h in game["heroes"]
                                   if h["player"] == friendly), None)
        friendly_hero_name = next((h.get("hero_name") for h in game["heroes"]
                                   if h["player"] == friendly), None)
        print(f"\n=== Game {idx} (friendly player={friendly}, hero={friendly_hero_name}) ===")
        for t in parse_actions(chunk, friendly, friendly_hero_card):
            parts = [f"buy={[nm(x) for x in t['buys']]}",
                     f"play={[nm(x) for x in t['plays']]}",
                     f"sell={[nm(x) for x in t['sells']]}",
                     f"triple={[nmd(x) for x in t['triples']]}",
                     f"refresh={t['refreshes']}", f"freeze={t['freezes']}",
                     f"upgrade={t['upgrades']}", f"hero={t['hero_power']}",
                     f"rearrange={t['rearranges']}", f"dark={t['dark_gifts']}",
                     f"choice={[nm(x) for x in t['choices']]}"]
            print(f"  Turn {t['turn']}: " + " ".join(parts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
